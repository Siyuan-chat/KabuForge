"""Multiple local decisions sharing the same strategy, planner and journal."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from .application import ApplicationService
from .config import _read_json_snapshot,ConfigError
from .execution import AccountState,Position,Quote,Instrument,OrderPlan,ExecutionError
from .local_io import (context_from_file,account_from_file,research_marks,result_document,write_new)
from .models import StrategyState
from .simulation import FakeBroker
from .store import Store,StoreError

def _account(view):
    return AccountState(view["account_id"],view["revision"],view["equity"],view["available_cash"],
        tuple(Position(code,p["quantity"],p["average_cost"]) for code,p in view["positions"].items()))

def schedule(sessions,rebalance):
    """Use the explicitly supplied trading calendar; never infer missing sessions."""
    frequency=rebalance["frequency"]
    if frequency=="daily": return sessions
    chosen={}
    for session in sessions:
        day=datetime.fromisoformat(session["decision_at"]).astimezone(ZoneInfo("Asia/Tokyo")).date()
        if frequency=="weekly":
            if "weekday" in rebalance and day.weekday()!=rebalance["weekday"]: continue
            key=day.isocalendar()[:2]
        else:
            if "day_of_month" in rebalance and day.day!=rebalance["day_of_month"]: continue
            key=(day.year,day.month)
        chosen[key]=session
    return list(chosen.values())

def run_history(run_path,timeline_path,*,output_dir,cancel_check=None):
    path=Path(run_path).resolve(); service=ApplicationService(); resolved=service.validate(path)
    if resolved.run["mode"] not in {"backtest","paper","fake"}:
        raise ExecutionError("historical simulation cannot run broker mode")
    timeline,timeline_hash=_read_json_snapshot(Path(timeline_path))
    if set(timeline)!={"format","sessions"} or timeline["format"] not in {"execution.timeline.v1", "execution.daily_bars.v2"}:
        raise ConfigError("explicit execution timeline required")
    daily_bars = timeline["format"] == "execution.daily_bars.v2"
    sessions=timeline["sessions"]
    if not isinstance(sessions,list) or not sessions: raise ConfigError("timeline must contain sessions")
    previous=None; days=set()
    for session in sessions:
        if cancel_check is not None and cancel_check(): raise InterruptedError("local job canceled")
        required = {"decision_at","now","quotes","instruments"}
        if daily_bars: required.add("execution_quotes")
        if set(session)!=required: raise ConfigError("invalid session fields")
        at=datetime.fromisoformat(session["decision_at"]); now=datetime.fromisoformat(session["now"])
        if at.tzinfo is None or now.tzinfo is None or now<at or (previous is not None and at<=previous):
            raise ConfigError("sessions must have ascending aware decision clocks")
        previous=at
        day=at.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()
        if day in days: raise ConfigError("timeline supports one session per Tokyo trading day")
        days.add(day)
        if not resolved.run["clock"]["start"]<=day<=resolved.run["clock"]["end"]:
            raise ConfigError("timeline session outside run clock")
    selected={s["decision_at"] for s in schedule(sessions,resolved.strategy["rebalance"])}
    account=account_from_file(path.parent/resolved.run["account_ref"],expected_hash=resolved.account_hash)
    root=Path(output_dir).resolve(); root.mkdir(parents=True,exist_ok=False)
    store=Store(root/"journal.sqlite")
    store.register_batch("initial",OrderPlan((),{},Decimal(0),account.available_cash),account,
        decision_identity="initial:"+resolved.account_hash,strategy_hash=resolved.strategy_hash)
    state=StrategyState(); decisions=[]; nav=[]
    initial_equity=account.equity; peak=initial_equity
    for i,session in enumerate(sessions):
        if cancel_check is not None and cancel_check(): raise InterruptedError("local job canceled")
        now=datetime.fromisoformat(session["now"])
        context=context_from_file(path.parent/resolved.run["data_snapshot"],expected_hash=resolved.data_snapshot_hash,decision_at=session["decision_at"])
        marks=research_marks(context)
        account=_account(store.account_view(account.account_id))
        store.mark_account(account.account_id,account.revision,{p.code:marks[p.code] for p in account.positions},f"pre:{i}",datetime.fromisoformat(session["decision_at"]))
        account=_account(store.account_view(account.account_id))
        quotes_list=[Quote(**{**q,"asof":datetime.fromisoformat(q["asof"])}) for q in session["quotes"]]
        instruments_list=[Instrument(**{**item,"expires_at":datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None}) for item in session["instruments"]]
        quotes={q.code:q for q in quotes_list}; instruments={item.code:item for item in instruments_list}
        execution_quotes = quotes
        if daily_bars:
            execution_list = [Quote(**{**q,"asof":datetime.fromisoformat(q["asof"])}) for q in session["execution_quotes"]]
            execution_quotes = {q.code:q for q in execution_list}
            if len(execution_quotes) != len(execution_list): raise ConfigError("duplicate execution symbol")
            if any(q.asof != now for q in execution_list): raise ConfigError("execution quote clock mismatch")
        if len(quotes)!=len(quotes_list) or len(instruments)!=len(instruments_list): raise ConfigError("duplicate session symbol")
        if session["decision_at"] in selected:
            result=service.plan(resolved,context=context,account=account,research_marks=marks,
                quotes=quotes,instruments=instruments,now=now,state=state)
            store.register_batch(f"decision:{i}",result.plan,account,raw_target=result.risk.raw,allowed_target=result.risk.allowed,
                decision_identity=result.decision_identity,strategy_hash=result.strategy_hash,
                evidence={"result":result_document(result),"file_hashes":dict(resolved.file_hashes),"execution_timeline_hash":timeline_hash})
            broker=FakeBroker(account)
            for intent in result.plan.intents:
                store.begin_submission(intent.intent_id)
                store.record_event(broker.submit(intent,now=now))
                quote = execution_quotes.get(intent.code)
                fee = intent.estimated_fee
                if daily_bars and quote is not None:
                    from .planner import FeeModel
                    price = quote.ask if intent.side == "buy" else quote.bid
                    fee = FeeModel(**dict(resolved.run["fees"])).estimate(price * intent.quantity)
                    if intent.side == "buy" and price * intent.quantity + fee > broker.account().available_cash:
                        quote = None  # Gap cannot resize a pre-sized order after the fact.
                if quote is None:
                    store.record_event(broker.cancel(intent.intent_id, now=now))
                else:
                    match=broker.match(intent.intent_id,quote,now=now,fee=fee)
                    if match is not None: store.record_event(*match)
            state=result.decision.state
            decisions.append(result_document(result))
        view=store.account_view(account.account_id)
        post_marks=dict(marks)
        for code,quote in execution_quotes.items():
            if quote.asof<=now and (now-quote.asof).total_seconds()<=60:
                post_marks[code]=(quote.bid+quote.ask)/2
        store.mark_account(account.account_id,view["revision"],{code:post_marks[code] for code in view["positions"]},f"post:{i}",now)
        view=store.account_view(account.account_id); equity=Decimal(view["equity"])
        peak=max(peak,equity)
        nav.append({"at":now.isoformat(),"equity":str(equity),"nav":str(equity/initial_equity),
            "drawdown":str(equity/peak-1),"cash":view["available_cash"],"revision":view["revision"]})
    document={"model":"daily_bar_open_with_previous_close_sizing_v2" if daily_bars else "fictional_fixed_quote_matching_v1","mode":resolved.run["mode"],
        "strategy_hash":resolved.strategy_hash,"data_snapshot_hash":resolved.data_snapshot_hash,
        "execution_timeline_hash":timeline_hash,"file_hashes":dict(resolved.file_hashes),
        "decisions":decisions,"nav":nav,"final_state":state.to_json(),
        "journal":store.export_view(),"external_submission":False}
    write_new(root/"report.json",document)
    return document
