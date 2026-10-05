"""Explicitly assumption-based daily-bar research, separate from strict PIT execution.

No available_at timestamps are invented. Input bars and recipe are snapshotted.
Only a complete common calendar with unchanged split factors is accepted.
"""
from __future__ import annotations
import math, json, hashlib
from pathlib import Path

def _canonical_fingerprint(value):
    """Hash canonical JSON without importing the broker/legacy service graph."""
    encoded=json.dumps(value,sort_keys=True,ensure_ascii=False,
                       separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def research_bars(rows, recipe):
    count=int(recipe["count"]); lookback=int(recipe["lookback"])
    cash=float(recipe["cash"]); initial=cash; fee=float(recipe["fee"])/100
    frequency=recipe["frequency"]
    if count<1 or lookback<2 or not math.isfinite(cash) or cash<=0 or not math.isfinite(fee) or not 0<=fee<=.05 or frequency not in {"daily","weekly","monthly"}: raise ValueError("Invalid research settings")
    by_code={}; price_bases=set()
    for row in rows:
        code=str(row["code"]); day=str(row["date"])
        from datetime import date
        date.fromisoformat(day)
        if day in by_code.setdefault(code,{}): raise ValueError("Duplicate bar: "+code+" "+day)
        for field in ("open","close"):
            value=float(row[field]) if row.get(field) is not None else float("nan")
            if not math.isfinite(value) or value<=0: raise ValueError("Missing or invalid "+field+": "+code+" "+day)
        if row.get("selected_price") is not None:
            selected_price=float(row["selected_price"])
            if not math.isfinite(selected_price) or selected_price<=0:
                raise ValueError("Missing or invalid selected research price: "+code+" "+day)
            price_bases.add(str(row.get("selected_price_basis","raw")))
        by_code[code][day]=row
    if len(price_bases)>1 or any(basis not in {"raw","adjusted"} for basis in price_bases):
        raise ValueError("Mixed or unsupported selected research price bases")
    selected_basis=next(iter(price_bases),"raw")
    if not by_code or count>len(by_code): raise ValueError("Not enough stocks for the selected holding count")
    dates=sorted(set.union(*(set(v) for v in by_code.values())))
    signal_template=recipe.get("signal_template","price_momentum")
    if signal_template not in {"price_momentum","sma_crossover"}:
        raise ValueError("Unsupported market signal template")
    if signal_template=="price_momentum" and len(dates)<lookback+2:
        raise ValueError("Not enough sessions for lookback and next-open execution")
    for code,items in by_code.items():
        if set(items)!=set(dates): raise ValueError("Incomplete common calendar: "+code)
        if any(r.get("adjustment_factor") is None for r in items.values()):
            raise ValueError("Adjustment-factor evidence missing: "+code)
        factors={float(r["adjustment_factor"]) for r in items.values()}
        if factors!={1.0}: raise ValueError("Split-adjusted periods require a corporate-action model: "+code)
    if signal_template=="sma_crossover":
        fast=int(recipe.get("fast_period",10)); slow=int(recipe.get("slow_period",30))
        if fast<2 or slow<=fast: raise ValueError("MA crossover requires 2 <= fast_period < slow_period")
        if len(dates)<slow+2: raise ValueError("Not enough sessions for MA warmup and next-open execution")
        provider=recipe.get("signal_provider","native")
        if provider not in {"native","talib"}: raise ValueError("Signal provider must be native or talib")
        result=_research_sma_crossover(by_code,dates,recipe,initial,fee,fast,slow,provider)
        _annotate_price_basis(result,selected_basis)
        return result
    positions={code:0.0 for code in by_code}; previous_period=None; nav=[]; trades=[]; peak=initial
    order_schedule=[]; skipped=[]; account_path=[]; daily_turnover=[]; cumulative_fees=0.0
    for i,day in enumerate(dates):
        from datetime import date
        at=date.fromisoformat(day)
        period=day if frequency=="daily" else at.isocalendar()[:2] if frequency=="weekly" else day[:7]
        if i>=lookback+1 and period!=previous_period:
            # Decisions use data strictly before today's open.
            scored=sorted(by_code,key=lambda code:(-float(by_code[code][dates[i-1]].get("selected_price",by_code[code][dates[i-1]]["close"]))/float(by_code[code][dates[i-1-lookback]].get("selected_price",by_code[code][dates[i-1-lookback]]["close"])),code))[:count]
            opens={code:float(data[day]["open"]) for code,data in by_code.items()}
            known_prices={c:float(by_code[c][dates[i-1]]["close"]) for c in by_code}
            equity=cash+sum(positions[c]*known_prices[c] for c in positions)
            # Conservative reserve covers both sides of a full rebalance.
            investable=equity/(1+2*fee)
            target={c:investable/count/known_prices[c] if c in scored else 0.0 for c in positions}
            sizing_date=dates[i-1]
            prior_close_equity=(initial if i==0 else cash+sum(
                positions[c]*float(by_code[c][dates[i-1]]['close']) for c in positions))
            gross_notional=0.0
            for code in sorted(positions,key=lambda c:target[c]-positions[c]):
                delta=target[code]-positions[code]
                if abs(delta)<1e-10: continue
                notional=delta*opens[code]; cost=abs(notional)*fee
                order={"signal_date":sizing_date,"execution_date":day,"code":code,
                       "side":"buy" if delta>0 else "sell","quantity":abs(delta),
                       "sizing_price":known_prices[code],"sizing_equity":prior_close_equity}
                order_schedule.append(order)
                if delta>0 and notional+cost>cash+1e-8:
                    # Actual opening gaps may invalidate the cash reservation;
                    # skip the pre-sized order, never resize with future prices.
                    skipped.append({**order,"open_price":opens[code],"cash_available":cash,
                                    "cash_required":notional+cost,
                                    "cash_shortfall":notional+cost-cash,
                                    "reason":"opening gap exceeds prior-close cash budget"})
                    continue
                cash-=notional+cost; positions[code]=target[code]
                trades.append({"date":day,"code":code,"side":"buy" if delta>0 else "sell","quantity":abs(delta),"price":opens[code],"fee":cost,"signal_date":dates[i-1]})
                gross_notional+=abs(notional)
            if cash < -1e-6: raise ValueError("Research cash invariant failed")
            previous_period=period
        else:
            prior_close_equity=(initial if i==0 else cash+sum(
                positions[c]*float(by_code[c][dates[i-1]]['close']) for c in positions))
            gross_notional=0.0
        equity=cash+sum(positions[c]*float(by_code[c][day]["close"]) for c in positions)
        peak=max(peak,equity); nav.append({"at":day,"nav":equity/initial,"drawdown":equity/peak-1,"cash":cash})
        day_fees=sum(float(trade["fee"]) for trade in trades if trade["date"]==day)
        cumulative_fees+=day_fees
        account_positions=[]
        for code,quantity in sorted(positions.items()):
            mark=float(by_code[code][day]["close"]); market_value=quantity*mark
            if quantity>1e-10:
                account_positions.append({"code":code,"quantity":quantity,"mark_price":mark,
                    "market_value":market_value,"weight":market_value/equity if equity else None})
        account_path.append({"at":day,"cash":cash,"equity":equity,"position_universe":sorted(positions),
            "cash_weight":cash/equity if equity else None,"positions":account_positions,
            "fees":day_fees,"cumulative_fees":cumulative_fees})
        daily_turnover.append({"at":day,"gross_executed_notional":gross_notional,
            "denominator_prior_close_equity":prior_close_equity,
            "gross_traded_turnover":gross_notional/prior_close_equity if prior_close_equity>0 else None,
            "basis":"total buy plus sell executed fill notional / prior-close marked equity; both sides included"})
    result={"model":"daily_bar_next_open_research_v1","pit_guarantee":False,"mode":"research",
            "readiness":"RESEARCH-ONLY",
            "assumptions":["prior-close signal and sizing / next-open execution; unaffordable buys skipped","current downloaded data vintage; historical visibility unverified",
                           "continuous shares; no board lots, slippage, market impact or dividends","complete common calendar; split events rejected",
                           "gross traded turnover is total buy plus sell executed notional divided by prior-close marked equity; skipped orders have no turnover"],
            "nav":nav,"account_path":account_path,"order_schedule":order_schedule,"skipped_orders":skipped,
            "daily_turnover":daily_turnover,"trades":trades,"fees":sum(t["fee"] for t in trades),"recipe":recipe,
            "initial_equity":initial,"initial_at":nav[0]["at"],"initial_nav":1.0,
            "nav_base_includes_initial":True,"nav_frequency":"daily",
            "decisions":[],"submitted":False}
    _annotate_price_basis(result,selected_basis)
    return result


def _annotate_price_basis(report,basis):
    report["signal_price_basis"]=basis
    report["execution_price_basis"]="raw source open/close OHLC"
    report["price_basis_semantics"]={
        "signals":"selected_price (adjustment_close when adjusted; close when raw)",
        "execution":"original raw open; selected_price never substitutes execution OHLC",
        "valuation":"original raw close; price-only mark, no dividend cash model",
        "pit_guarantee":False,
    }
    if basis=="adjusted":
        report["assumptions"].append("Adjusted close is used for signal calculations only; fills use original raw opens and NAV marks use raw closes. Price-only NAV excludes dividend cash flows; adjustment history and PIT are unverified.")


def _research_sma_crossover(by_code,dates,recipe,initial,fee,fast,slow,provider):
    """Replay a frozen D-1 crossover schedule at next-session opens.

    Every buy quantity is determined from the previous close and prior-close
    cash before any opening price is observed. Opening gaps can skip an order,
    but cannot change its quantity or budget.
    """
    import numpy as np
    import hashlib
    from importlib import metadata

    closes={code:np.asarray([float(by_code[code][day].get("selected_price",by_code[code][day]["close"])) for day in dates],dtype=np.float64)
            for code in by_code}
    if provider=="talib":
        import talib
        fast_values={code:np.asarray(talib.SMA(values,timeperiod=fast),dtype=np.float64) for code,values in closes.items()}
        slow_values={code:np.asarray(talib.SMA(values,timeperiod=slow),dtype=np.float64) for code,values in closes.items()}
        engine={"name":"TA-Lib","version":metadata.version("TA-Lib")}
    else:
        fast_values={}; slow_values={}
        for code,values in closes.items():
            fast_column=np.full(len(values),np.nan,dtype=np.float64)
            slow_column=np.full(len(values),np.nan,dtype=np.float64)
            for index in range(slow-1,len(values)):
                fast_column[index]=float(np.mean(values[index-fast+1:index+1]))
                slow_column[index]=float(np.mean(values[index-slow+1:index+1]))
            fast_values[code]=fast_column; slow_values[code]=slow_column
        engine={"name":"Native rolling mean","version":"1"}

    cash=initial; positions={code:0.0 for code in by_code}; nav=[]; trades=[]; skipped=[]
    account_path=[]; order_schedule=[]; daily_turnover=[]; peak=initial; cumulative_fees=0.0
    for index,day in enumerate(dates):
        prior_close_equity=(initial if index==0 else cash+sum(
            positions[code]*float(by_code[code][dates[index-1]]["close"]) for code in positions))
        gross_notional=0.0
        if index>=slow+1:
            signal_index=index-1; prior_index=signal_index-1
            cross_up=[]; cross_down=[]
            for code in sorted(by_code):
                current_fast,current_slow=fast_values[code][signal_index],slow_values[code][signal_index]
                prior_fast,prior_slow=fast_values[code][prior_index],slow_values[code][prior_index]
                if not all(math.isfinite(value) for value in (current_fast,current_slow,prior_fast,prior_slow)):
                    continue
                if prior_fast<=prior_slow and current_fast>current_slow: cross_up.append(code)
                elif prior_fast>=prior_slow and current_fast<current_slow: cross_down.append(code)
            sizing_cash=cash
            buy_budget=sizing_cash/len(cross_up)/(1+fee) if cross_up else 0.0
            decisions=[]
            for code in cross_down:
                quantity=positions[code]
                if quantity>1e-10:
                    decisions.append({"signal_date":dates[signal_index],"execution_date":day,"code":code,"side":"sell",
                                      "quantity":quantity,"sizing_price":float(closes[code][signal_index]),"cash_budget":None})
            for code in cross_up:
                known_price=float(closes[code][signal_index])
                quantity=buy_budget/known_price if known_price>0 else 0.0
                if quantity>1e-10:
                    decisions.append({"signal_date":dates[signal_index],"execution_date":day,"code":code,"side":"buy",
                                      "quantity":quantity,"sizing_price":known_price,"cash_budget":buy_budget})
            order_schedule.extend(decisions)
            for order in decisions:
                code=order["code"]; quantity=float(order["quantity"]); price=float(by_code[code][day]["open"])
                notional=quantity*price; cost=abs(notional)*fee
                if order["side"]=="buy" and notional+cost>cash+1e-8:
                    skipped.append({**order,"open_price":price,"cash_available":cash,
                                    "cash_required":notional+cost,"cash_shortfall":notional+cost-cash,
                                    "reason":"opening gap exceeds prior-close cash budget"})
                    continue
                if order["side"]=="sell":
                    quantity=min(quantity,positions[code]); notional=quantity*price; cost=abs(notional)*fee
                    cash+=notional-cost; positions[code]-=quantity
                else:
                    cash-=notional+cost; positions[code]+=quantity
                trades.append({"date":day,"signal_date":order["signal_date"],"code":code,"side":order["side"],
                               "quantity":quantity,"sizing_price":order["sizing_price"],"price":price,"fee":cost})
                gross_notional+=abs(notional)
            if cash < -1e-6: raise ValueError("Research cash invariant failed")
        equity=cash+sum(positions[code]*float(by_code[code][day]["close"]) for code in positions)
        peak=max(peak,equity)
        nav.append({"at":day,"nav":equity/initial,"drawdown":equity/peak-1,"cash":cash})
        day_fees=sum(float(trade["fee"]) for trade in trades if trade["date"]==day)
        cumulative_fees+=day_fees
        marked_positions=[]
        for code,quantity in sorted(positions.items()):
            mark=float(by_code[code][day]["close"]); market_value=quantity*mark
            if quantity>1e-10:
                marked_positions.append({"code":code,"quantity":quantity,"mark_price":mark,
                    "market_value":market_value,"weight":market_value/equity if equity else None})
        account_path.append({"at":day,"cash":cash,"equity":equity,"position_universe":sorted(positions),"cash_weight":cash/equity if equity else None,
                             "positions":marked_positions,"fees":day_fees,"cumulative_fees":cumulative_fees})
        daily_turnover.append({"at":day,"gross_executed_notional":gross_notional,
            "denominator_prior_close_equity":prior_close_equity,
            "gross_traded_turnover":gross_notional/prior_close_equity if prior_close_equity>0 else None,
            "basis":"total buy plus sell executed fill notional / prior-close marked equity; both sides included"})
    parameters={"fast_period":fast,"slow_period":slow,"provider":provider}
    identity=json.dumps({"template":"sma_crossover","parameters":parameters,"recipe":recipe},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return {"model":"daily_bar_next_open_research_v1","strategy_template":"sma_crossover","strategy_parameters":parameters,
            "strategy_hash":hashlib.sha256(identity).hexdigest(),"engine":engine,"pit_guarantee":False,"mode":"research",
            "readiness":"RESEARCH-ONLY","assumptions":["fast/slow moving-average crossover is signaled using prior-close data; share quantities are fixed at prior close; execution is next-open",
              "opening gaps can skip pre-sized buys; no future-price resizing or redistribution","current downloaded data vintage; historical visibility unverified",
              "continuous shares; no board lots, slippage, market impact or dividends","complete common calendar; split events rejected",
              "gross traded turnover is total buy plus sell executed notional divided by prior-close marked equity; skipped orders have no turnover"],
            "nav":nav,"account_path":account_path,"order_schedule":order_schedule,"skipped_orders":skipped,
            "daily_turnover":daily_turnover,"trades":trades,
            "fees":sum(trade["fee"] for trade in trades),"recipe":recipe,"initial_equity":initial,"initial_at":nav[0]["at"],
            "initial_nav":1.0,"nav_base_includes_initial":True,"nav_frequency":"daily","decisions":[],"submitted":False}



def _load_price_research_input(source_path):
    """Load either the completed download manifest or an explicitly frozen local input."""
    from .data_connection import load_bars
    source=Path(source_path).resolve(strict=True)
    try:
        manifest=json.loads(source.read_text(encoding="utf-8")) if source.suffix.lower()==".json" else None
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise ValueError("market research input manifest cannot be read") from None
    if isinstance(manifest,dict) and manifest.get("kind")=="kabuforge_local_research_bars":
        from .local_cache import _frame_records, load_research_bars
        selection=manifest.get("selection") or {}
        loaded=load_research_bars(source,codes=selection.get("requested_codes",()),
            start_date=selection.get("start_date",""),end_date=selection.get("end_date",""),
            price_basis=selection.get("price_basis",""),
            duplicate_policy=selection.get("duplicate_policy","reject"),
            known_halt_policy=selection.get("known_halt_policy","reject"))
        rows=_frame_records(loaded.bars)
        identity={"kind":loaded.source["kind"],"manifest_sha256":loaded.source["source_sha256"],
            "selected_data_sha256":loaded.selected_data_sha256,
            "selection_identity_sha256":loaded.identity_sha256,
            "pinned_identity_sha256":loaded.source["details"]["pinned_identity_sha256"],
            "pinned_selection":loaded.source["details"]["pinned_selection"],
            "price_basis":loaded.selection["price_basis"],"pit_guarantee":False,
            "source_availability":"history visibility unverified","coverage":loaded.coverage}
        return rows,identity
    rows=load_bars(source)
    identity={"kind":"jquants_manifest","manifest_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
        "price_basis":"raw","pit_guarantee":False,
        "source_availability":"current API view; historical visibility unverified"}
    return rows,identity





def _validate_public_regime_off(recipe, regime_observer):
    if regime_observer is not None:
        # The facade keeps the familiar explicit Off payload, but must never
        # accept a private observer/bridge object or extra bridge fields.
        if (type(regime_observer) is not dict
                or set(regime_observer) != {"mode"}
                or regime_observer.get("mode") != "off"):
            raise ValueError("This public candidate supports only the exact Regime Off configuration")
    if not isinstance(recipe, dict):
        raise ValueError("Research recipe must be an object")
    disabled_values = (None, False, "off", "disabled")
    allowed_recipe_regime_keys = {"regime_mode", "regime", "regime_observer"}
    for key in ("regime_mode", "regime", "regime_observer"):
        value = recipe.get(key)
        if value in disabled_values:
            continue
        if isinstance(value, dict) and value == {"mode": "off"}:
            continue
        raise ValueError("Private or enabled Regime modes are unavailable in this public candidate")
    private_regime_fields = [key for key in recipe
                             if "regime" in str(key).lower()
                             and key not in allowed_recipe_regime_keys]
    if private_regime_fields:
        raise ValueError("Private Regime bridge parameters are unavailable in this public candidate")


def preflight_price_research(manifest_path, recipe, regime_observer=None, *, _rows=None):
    _validate_public_regime_off(recipe, regime_observer)
    source = Path(manifest_path).expanduser().resolve(strict=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    rows, input_source = _load_price_research_input(source) if _rows is None else (_rows, None)
    finance_report = research_bars(rows, recipe)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("research input manifest changed during preflight")
    finance_raw = json.dumps({"bars": rows, "recipe": recipe}, ensure_ascii=False,
                             sort_keys=True, allow_nan=False).encode("utf-8")
    input_hash = hashlib.sha256(finance_raw).hexdigest()
    return {
        "input_hash": input_hash,
        "manifest_path": str(source),
        "manifest_sha256": after,
        "input_source": input_source,
        "finance_model": finance_report.get("model"),
        "regime_observer": {"mode": "off", "availability": "not_configured"},
        "fingerprint": _canonical_fingerprint({"input_hash": input_hash,
            "manifest_sha256": after, "recipe": recipe, "regime_mode": "off"}),
    }


def run_price_research(manifest_path, recipe, output_dir, *, regime_observer=None, expected_preflight=None):
    _validate_public_regime_off(recipe, regime_observer)
    rows, input_source = _load_price_research_input(manifest_path)
    preflight = preflight_price_research(manifest_path, recipe, _rows=rows)
    expected = expected_preflight.get("fingerprint") if isinstance(expected_preflight, dict) else expected_preflight
    if expected is not None and expected != preflight["fingerprint"]:
        raise ValueError("price research inputs changed since UI preflight")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    raw = json.dumps({"bars": rows, "recipe": recipe}, ensure_ascii=False,
                     sort_keys=True, allow_nan=False).encode("utf-8")
    (root / "research_inputs.json").write_bytes(raw)
    report = research_bars(rows, recipe)
    report["input_hash"] = hashlib.sha256(raw).hexdigest()
    report["input_source"] = input_source
    recipe_bytes = json.dumps(recipe, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8")
    report.setdefault("strategy_hash", hashlib.sha256(recipe_bytes).hexdigest())
    report["strategy_template"] = recipe.get("signal_template", "price_momentum")
    if report.get("order_schedule") is not None:
        schedule_raw = json.dumps(report["order_schedule"], sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode("utf-8")
        report["order_schedule_hash"] = hashlib.sha256(schedule_raw).hexdigest()
    if report["input_hash"] != preflight["input_hash"]:
        raise ValueError("price research rows changed after preflight")
    report["workbench_configs"] = {"recipe": recipe}
    report["regime_observer"] = {"mode": "off", "availability": "not_configured",
                                 "timeline": [], "grouped_returns": []}
    report_path = root / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                      allow_nan=False), encoding="utf-8")
    return report_path
