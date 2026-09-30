"""Descriptive software diagnostics, not strategy research readiness ratings."""
import pandas as pd

def decision_diagnostics(result):
    factors={}
    for name,factor in result.factors.items():
        frame=factor.minimal
        count=len(frame); valid=int(frame.factor_value.notna().sum())
        ends=pd.to_datetime(frame.data_end_date,errors="coerce")
        signals=pd.to_datetime(frame.signal_date,errors="coerce")
        rebalance=pd.to_datetime(frame.rebalance_date,errors="coerce")
        ages=(rebalance-ends).dt.total_seconds()/86400
        factors[name]={"rows":count,"valid":valid,"missing":count-valid,
            "coverage":valid/count if count else None,
            "unknown_data_end":int(ends.isna().sum()),
            "max_data_age_days":float(ages.max()) if ages.notna().any() else None,
            "data_after_signal_rows":int((ends>signals).fillna(False).sum())}
    raw=result.risk.raw; allowed=result.risk.allowed
    return {"factors":factors,"dropped_codes":list(result.decision.dropped_codes),
        "raw_gross":str(raw.gross) if raw is not None else None,
        "allowed_gross":str(allowed.gross) if allowed is not None else None,
        "allowed_net":str(allowed.net) if allowed is not None else None,
        "risk_reasons":list(result.risk.reasons),"intent_count":len(result.plan.intents),
        "planned_turnover":str(result.plan.estimated_turnover),"skipped":dict(result.plan.skipped)}
