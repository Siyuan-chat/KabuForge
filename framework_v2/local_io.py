"""Explicit JSON snapshot boundary shared by CLI and desktop frontend."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from collections.abc import Mapping
import json
import math
import pandas as pd
from .config import _read_json_snapshot, ConfigError
from .execution import AccountState, Position, Quote, Instrument
from .factors import FactorContext

def plain(value):
    if value is None or isinstance(value,(str,bool,int)): return value
    if isinstance(value,Enum): return value.value
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,(datetime,date,pd.Timestamp)): return value.isoformat()
    if isinstance(value,float): return value if math.isfinite(value) else None
    if value is pd.NA or value is pd.NaT: return None
    if isinstance(value,Mapping): return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [plain(v) for v in value]
    if isinstance(value,pd.DataFrame): return {"columns":list(value.columns),"rows":[[plain(v) for v in row] for row in value.itertuples(index=False,name=None)]}
    if is_dataclass(value): return {f.name:plain(getattr(value,f.name)) for f in fields(value)}
    if hasattr(value,"item"): return plain(value.item())
    raise TypeError("unsupported JSON output: "+type(value).__name__)

def write_new(path, value):
    """Never silently overwrite a user file."""
    with Path(path).open("x",encoding="utf-8") as stream:
        json.dump(plain(value),stream,ensure_ascii=False,indent=2,allow_nan=False)

def checked(path, expected):
    value,digest=_read_json_snapshot(Path(path))
    if digest != expected: raise ConfigError("input changed since preflight: "+str(path))
    return value

def context_from_file(path, *, expected_hash, decision_at):
    value=checked(path,expected_hash)
    from .data_snapshot import snapshot_frames
    datasets=snapshot_frames(path,value)
    return FactorContext(decision_at=decision_at,datasets=datasets,data_snapshot_hash=expected_hash)

def account_from_file(path, *, expected_hash):
    value=checked(path,expected_hash)
    if set(value)!={"account_id","revision","equity","available_cash","positions"}:
        raise ConfigError("unsupported account snapshot fields")
    return AccountState(**{**value,"positions":tuple(Position(**p) for p in value["positions"])})

def execution_from_file(path):
    value,digest=_read_json_snapshot(Path(path))
    if set(value)!={"quotes","instruments"}: raise ConfigError("invalid execution snapshot")
    quotes=[Quote(**{**q,"asof":datetime.fromisoformat(q["asof"])}) for q in value["quotes"]]
    instruments=[Instrument(**{**i,"expires_at":datetime.fromisoformat(i["expires_at"]) if i.get("expires_at") else None}) for i in value["instruments"]]
    if len({q.code for q in quotes})!=len(quotes) or len({i.code for i in instruments})!=len(instruments):
        raise ConfigError("duplicate execution symbol")
    return {q.code:q for q in quotes},{i.code:i for i in instruments},digest

def research_marks(context):
    prices=context.read("prices")
    # Valuation carries the last valid *visible* close over missing sessions.
    # Keep raw factor inputs unchanged, and never fill with a future quote.
    close=pd.to_numeric(prices["close"],errors="coerce")
    prices=prices.loc[close.map(lambda v: math.isfinite(v) and v>0)]
    prices=prices.assign(_date=pd.to_datetime(prices["date"]))
    latest=prices.sort_values("_date").groupby("code",sort=False).tail(1)
    return {str(row.code):Decimal(str(row.close)) for row in latest.itertuples()}

def result_document(result):
    from .diagnostics import decision_diagnostics
    return {"strategy_hash":result.strategy_hash,"decision_identity":result.decision_identity,
        "factors":{k:{"minimal":plain(v.minimal),"detail":plain(v.detail),"summary":plain(v.summary)} for k,v in result.factors.items()},
        "decision":plain(result.decision),"risk":plain(result.risk),"plan":plain(result.plan),
        "diagnostics":plain(decision_diagnostics(result))}
