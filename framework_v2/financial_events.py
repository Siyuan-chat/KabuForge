"""Financial disclosure-event normalization with explicit time uncertainty.

This module records issuer disclosure timestamps only.  It does not establish
when an API exposed a record, nor does it establish an as-known data vintage.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

import pandas as pd


JST = "Asia/Tokyo"
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")
_ALIASES = {
    "disclosed_date": "DiscDate",
    "disclosed_time": "DiscTime",
    "disc_no": "DiscNo",
    "code": "Code",
}


class AmbiguousFinancialEventOrderError(ValueError):
    """Raised when same-code events share an exact disclosure timestamp."""


def _value(frame: pd.DataFrame, canonical: str) -> pd.Series:
    if canonical in frame.columns:
        return frame[canonical]
    raw = _ALIASES[canonical]
    if raw in frame.columns:
        return frame[raw]
    return pd.Series(pd.NA, index=frame.index, dtype="object")


def _text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(stamp) else stamp.date().isoformat()


def _time(value: Any) -> str | None:
    text = _text(value)
    if text is None or not _TIME_RE.fullmatch(text):
        return None
    return text if text.count(":") == 2 else f"{text}:00"


def _signature_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_signature_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _signature_value(item) for key, item in sorted(value.items())}
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _content_signature(row: pd.Series) -> str:
    ignored = set(_ALIASES) | set(_ALIASES.values()) | {"source_disclosed_at", "quarantine_reason"}
    payload = {str(column): _signature_value(value) for column, value in row.items() if column not in ignored}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _empty_like(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.iloc[0:0].copy()
    for column in ("disclosed_date", "disclosed_time", "disc_no", "code", "source_disclosed_at"):
        if column not in out:
            out[column] = pd.Series(dtype="object")
    return out


def canonicalize_financial_events(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Return normalized events, quarantined rows, and transparent row counts.

    A natural key is ``(code, disclosed_date, disclosed_time, disc_no)``.
    Equal copies of a natural key are merged; distinct content at that key is
    quarantined.  Missing or invalid disclosure time is never inferred.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    # Original indexes are not event identities and may themselves be duplicated.
    work = frame.copy().reset_index(drop=True)
    stats = {
        "input_rows": len(work), "clean_rows": 0, "quarantined_rows": 0,
        "duplicate_rows_merged": 0, "conflict_rows": 0, "invalid_date_rows": 0,
        "invalid_time_rows": 0, "missing_code_rows": 0, "missing_disc_no_rows": 0,
    }
    if work.empty:
        empty = _empty_like(work)
        quarantine = empty.copy()
        quarantine["quarantine_reason"] = pd.Series(dtype="object")
        return empty, quarantine, stats

    work["disclosed_date"] = _value(work, "disclosed_date").map(_date)
    work["disclosed_time"] = _value(work, "disclosed_time").map(_time)
    work["disc_no"] = _value(work, "disc_no").map(_text)
    work["code"] = _value(work, "code").map(_text)

    reasons: dict[Any, str] = {}
    for index, row in work.iterrows():
        if _text(row["disclosed_date"]) is None:
            reasons[index] = "invalid_or_missing_disclosed_date"
            stats["invalid_date_rows"] += 1
        elif _text(row["disclosed_time"]) is None:
            reasons[index] = "invalid_or_missing_disclosed_time"
            stats["invalid_time_rows"] += 1
        elif _text(row["code"]) is None:
            reasons[index] = "missing_code"
            stats["missing_code_rows"] += 1
        elif _text(row["disc_no"]) is None:
            reasons[index] = "missing_disc_no"
            stats["missing_disc_no_rows"] += 1

    valid = work.loc[[index for index in work.index if index not in reasons]].copy()
    key_columns = ["code", "disclosed_date", "disclosed_time", "disc_no"]
    duplicate_key = valid.duplicated(key_columns, keep=False)
    # Most production rows have a unique natural key: preserve them without a
    # per-row content signature.  Signatures are only needed to classify a
    # repeated key as an exact copy or a conflicting event.
    kept: list[Any] = valid.index[~duplicate_key].tolist()
    for _, group in valid.loc[duplicate_key].groupby(key_columns, dropna=False, sort=False):
        signatures = group.apply(_content_signature, axis=1)
        if signatures.nunique() == 1:
            kept.append(group.index[0])
            stats["duplicate_rows_merged"] += len(group) - 1
        else:
            for index in group.index:
                reasons[index] = "conflicting_duplicate_natural_key"
            stats["conflict_rows"] += len(group)

    clean = valid.loc[kept].copy()
    if not clean.empty:
        clean["source_disclosed_at"] = pd.to_datetime(
            clean["disclosed_date"] + " " + clean["disclosed_time"], errors="raise"
        ).dt.tz_localize(JST)
        clean = clean.sort_values(["source_disclosed_at", "code", "disc_no"], kind="stable").reset_index(drop=True)
    else:
        clean = _empty_like(work)

    quarantine = work.loc[list(reasons)].copy() if reasons else _empty_like(work)
    if not quarantine.empty:
        quarantine["quarantine_reason"] = [reasons[index] for index in quarantine.index]
        quarantine = quarantine.reset_index(drop=True)
    elif "quarantine_reason" not in quarantine:
        quarantine["quarantine_reason"] = pd.Series(dtype="object")
    stats["clean_rows"] = len(clean)
    stats["quarantined_rows"] = len(quarantine)
    return clean, quarantine, stats


def latest_visible_financial_events(frame: pd.DataFrame, decision_at: Any) -> pd.DataFrame:
    """Select each code's latest event visible at an aware decision timestamp.

    Same-code records at the same latest instant are deliberately rejected:
    DiscNo is an identifier, not evidence of a causal ordering.
    """
    if "source_disclosed_at" not in frame.columns or "code" not in frame.columns:
        raise ValueError("frame requires code and source_disclosed_at columns")
    decision = pd.Timestamp(decision_at)
    if pd.isna(decision) or decision.tzinfo is None or decision.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")
    decision = decision.tz_convert(JST)
    work = frame.copy().reset_index(drop=True)
    times = pd.to_datetime(work["source_disclosed_at"], errors="coerce")
    if times.isna().any() or any(value.tzinfo is None or value.utcoffset() is None for value in times):
        raise ValueError("source_disclosed_at must be timezone-aware for every row")
    work["source_disclosed_at"] = times.dt.tz_convert(JST)
    visible = work.loc[work["source_disclosed_at"] <= decision].copy()
    if visible["code"].map(_text).isna().any():
        raise ValueError("code must be present")
    latest_at = visible.groupby("code", dropna=False)["source_disclosed_at"].transform("max")
    candidates = visible.loc[visible["source_disclosed_at"].eq(latest_at)].copy()
    same_time_count = candidates.groupby("code", dropna=False)["code"].transform("size")
    ambiguous = candidates.loc[same_time_count.gt(1)]
    if not ambiguous.empty:
        first = ambiguous.iloc[0]
        count = int(same_time_count.loc[ambiguous.index[0]])
        raise AmbiguousFinancialEventOrderError(
            f"code={first['code']!r} has {count} events at {first['source_disclosed_at'].isoformat()}; ordering is unproven"
        )
    if candidates.empty:
        return visible.iloc[0:0].copy()
    return candidates.sort_values("code", kind="stable").reset_index(drop=True)
