"""Descriptive factor and visibility checks; never a readiness certification."""
from __future__ import annotations
import pandas as pd
from .local_io import plain


def analyze_frame(frame, *, quantiles=5):
    if type(quantiles) is not int or not 2 <= quantiles <= 20:
        raise ValueError("quantiles must be an integer between 2 and 20")
    if "factor_value" not in frame or "code" not in frame:
        raise ValueError("factor result requires code and factor_value")
    values = pd.to_numeric(frame.factor_value, errors="coerce")
    values = values.where(values.map(lambda x: pd.notna(x) and float('-inf') < x < float('inf')))
    keys = [k for k in ("signal_date", "rebalance_date") if k in frame]
    work = frame.assign(_value=values)
    groups = work.groupby(keys, dropna=False, sort=False) if keys else [(None, work)]
    ranks = []
    for _, group in groups:
        # Average tied ranks preserve ties instead of allocating by row order.
        rank = group._value.rank(method="average", pct=True)
        bucket = (rank * quantiles).apply(lambda x: min(quantiles, max(1, int(__import__('math').ceil(x)))) if pd.notna(x) else None)
        for index in group.index:
            ranks.append({"code":str(group.loc[index, "code"]), **{k:plain(group.loc[index,k]) for k in keys},
                          "rank":plain(rank.loc[index]), "quantile":plain(bucket.loc[index])})
    age = None
    if {"data_end_date", "rebalance_date"} <= set(frame):
        ages = (pd.to_datetime(frame.rebalance_date, utc=True) - pd.to_datetime(frame.data_end_date, utc=True)).dt.total_seconds()/86400
        age = plain(ages.max())
    valid = int(values.notna().sum())
    return {"rows":len(frame), "valid":valid, "missing":len(frame)-valid,
            "coverage":valid/len(frame) if len(frame) else None, "max_data_age_days":age,
            "distribution":plain(values.describe().to_dict()), "cross_sectional_ranks":ranks,
            "quantiles":quantiles, "research_readiness":"NOT_EVALUATED"}


def check_visibility(datasets, decision_at):
    stamp = pd.Timestamp(decision_at)
    if stamp.tzinfo is None: raise ValueError("decision_at requires timezone")
    checks = {}
    for name, frame in datasets.items():
        if "available_at" not in frame:
            checks[name] = {"rows":len(frame), "missing_available_at":len(frame), "future_rows":0, "valid":False}
            continue
        parsed = []
        for value in frame.available_at:
            try:
                item = pd.Timestamp(value)
                parsed.append(item.tz_convert('UTC') if item.tzinfo and not pd.isna(item) else pd.NaT)
            except (ValueError, TypeError): parsed.append(pd.NaT)
        dates = pd.Series(parsed, dtype="datetime64[ns, UTC]")
        missing = int(dates.isna().sum()); future = int((dates > stamp).sum())
        checks[name] = {"rows":len(frame), "missing_available_at":missing, "future_rows":future,
                        "visible_rows":int((dates <= stamp).sum()), "valid":missing == 0}
    # Future rows in a snapshot are permitted only when the PIT context gates them.
    return {"decision_at":stamp.isoformat(), "datasets":checks,
            "availability_valid":all(x['valid'] for x in checks.values()),
            "future_rows_require_gate":sum(x['future_rows'] for x in checks.values()),
            "scope":"timestamp gate only; provenance and historical revisions require independent evidence"}
