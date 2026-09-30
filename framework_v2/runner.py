"""Local simulated execution of one explicitly timestamped decision."""
from datetime import datetime
from pathlib import Path
from .application import ApplicationService
from .local_io import (context_from_file,account_from_file,execution_from_file,
    research_marks,result_document)
from .simulation import FakeBroker
from .store import Store, StoreError

def simulate_once(run_path,execution_path,*,decision_at,now,store_path):
    """Fresh-run simulation only. Existing journals use reconciliation, not rerun.

    The database path must be new, so accidentally choosing an existing paper
    journal cannot mutate it. Fault recovery is available through Store/FakeBroker.
    """
    destination=Path(store_path).resolve()
    if destination.exists(): raise StoreError("simulation requires a new journal path")
    path=Path(run_path).resolve(); service=ApplicationService(); resolved=service.validate(path)
    if resolved.run["mode"] not in {"backtest","paper","fake"}:
        raise StoreError("local simulation does not support broker mode")
    context=context_from_file(path.parent/resolved.run["data_snapshot"],expected_hash=resolved.data_snapshot_hash,decision_at=decision_at)
    account=account_from_file(path.parent/resolved.run["account_ref"],expected_hash=resolved.account_hash)
    quotes,instruments,execution_hash=execution_from_file(execution_path)
    time=datetime.fromisoformat(now)
    result=service.plan(resolved,context=context,account=account,research_marks=research_marks(context),
        quotes=quotes,instruments=instruments,now=time)
    # Exclusive creation protects the existing-ledger boundary against races.
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.open("xb").close()
    store=Store(destination); broker=FakeBroker(account)
    store.register_batch(resolved.run["id"],result.plan,account,
        raw_target=result.risk.raw,allowed_target=result.risk.allowed,
        decision_identity=result.decision_identity,strategy_hash=result.strategy_hash,
        evidence={"result":result_document(result),"file_hashes":dict(resolved.file_hashes),"execution_snapshot_hash":execution_hash})
    for intent in result.plan.intents:
        store.begin_submission(intent.intent_id)
        accepted=broker.submit(intent,now=time)
        store.record_event(accepted)
        matched=broker.match(intent.intent_id,quotes[intent.code],now=time,fee=intent.estimated_fee)
        if matched is not None: store.record_event(*matched)
    document=result_document(result)
    document["execution"]={"type":"fictional_local_matching","execution_snapshot_hash":execution_hash,
        "journal":str(destination),"account":store.account_view(account.account_id),
        "recovery_required":store.recovery_required(),"view":store.export_view(),"external_submission":False}
    return document
