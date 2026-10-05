"""Read an explicitly selected local TOPIX close series for report-only comparison."""
from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path


ADAPTER_VERSION = "topix-local-close-v1"
SUPPORTED_STRATEGY_MODEL = "daily_bar_next_open_research_v1"
BENCHMARK_NAME = "TOPIX"


class TopixBenchmarkError(ValueError):
    """The selected file or strategy report cannot support a TOPIX comparison."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _day(value, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise TopixBenchmarkError(f"{field} must be an ISO calendar date") from None


def _strategy_nav(report: dict) -> dict[date, float]:
    if not isinstance(report, dict) or report.get("model") != SUPPORTED_STRATEGY_MODEL:
        raise TopixBenchmarkError(
            "TOPIX close can be paired only with daily_bar_next_open_research_v1 raw-close NAV; "
            "open-valued or unknown report models are unsupported"
        )
    semantics = report.get("price_basis_semantics")
    if not isinstance(semantics, dict) or semantics.get("valuation") != "original raw close; price-only mark, no dividend cash model":
        raise TopixBenchmarkError("strategy report does not declare raw-close NAV valuation")
    rows = report.get("nav")
    if not isinstance(rows, list) or len(rows) < 3:
        raise TopixBenchmarkError("strategy report needs at least three NAV dates")
    nav = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TopixBenchmarkError("strategy NAV contains a non-object row")
        day = _day(row.get("at", row.get("date")), field="strategy NAV date")
        try:
            value = float(row.get("nav"))
        except (TypeError, ValueError, OverflowError):
            raise TopixBenchmarkError(f"strategy NAV is invalid on {day.isoformat()}") from None
        if not math.isfinite(value) or value <= 0:
            raise TopixBenchmarkError(f"strategy NAV must be finite and positive on {day.isoformat()}")
        if day in nav:
            raise TopixBenchmarkError(f"strategy NAV has a duplicate date: {day.isoformat()}")
        nav[day] = value
    return nav


def attach_local_topix(report: dict, source_path: str | Path) -> dict:
    """Return a report copy with date-exact TOPIX close levels and source evidence.

    This is an after-finance annotation: it does not change strategy NAV, costs,
    plans, fills, or any persisted report or ledger. The selected Parquet file is
    never copied; only TOPIX close levels on dates already present in strategy
    NAV are attached. Every strategy NAV date must be present; missing dates
    reject the comparison rather than being filled or silently dropped.
    """
    strategy_nav = _strategy_nav(report)
    source = Path(source_path).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != ".parquet":
        raise TopixBenchmarkError("select one local Parquet index cache file")

    try:
        original_report_raw = json.dumps(
            report, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False, default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise TopixBenchmarkError("strategy report cannot be hashed as finite JSON") from None

    before = source.stat()
    source_hash_before = _sha256(source)
    try:
        import pandas as pd
        frame = pd.read_parquet(source, columns=["date", "index_code", "close"], engine="pyarrow")
    except Exception as exc:
        raise TopixBenchmarkError(f"selected Parquet file could not be read: {exc}") from exc
    after = source.stat()
    source_hash_after = _sha256(source)
    if (before.st_size, before.st_mtime_ns, source_hash_before) != (
        after.st_size, after.st_mtime_ns, source_hash_after
    ):
        raise TopixBenchmarkError("selected TOPIX file changed while it was being read")
    if not {"date", "index_code", "close"}.issubset(set(frame.columns)):
        raise TopixBenchmarkError("index cache must contain date, index_code and close columns")

    topix = frame.loc[frame["index_code"].astype(str).eq(BENCHMARK_NAME), ["date", "close"]]
    if topix.empty:
        raise TopixBenchmarkError("selected cache contains no exact TOPIX index_code rows")
    source_dates = set()
    levels = {}
    for raw_day, raw_close in topix.itertuples(index=False, name=None):
        day = _day(raw_day, field="TOPIX cache date")
        if day in source_dates:
            raise TopixBenchmarkError(f"TOPIX cache has duplicate dates: {day.isoformat()}")
        source_dates.add(day)
        # Missing or invalid closes outside the user's selected NAV window do
        # not affect this report. An exact-date row with a bad close is rejected.
        if day not in strategy_nav:
            continue
        try:
            close = float(raw_close)
        except (TypeError, ValueError, OverflowError):
            raise TopixBenchmarkError(f"TOPIX close is invalid on {day.isoformat()}") from None
        if not math.isfinite(close) or close <= 0:
            raise TopixBenchmarkError(f"TOPIX close must be finite and positive on {day.isoformat()}")
        levels[day] = close

    missing_days = sorted(set(strategy_nav).difference(levels))
    if missing_days:
        examples = ", ".join(day.isoformat() for day in missing_days[:5])
        raise TopixBenchmarkError(
            f"TOPIX is missing {len(missing_days)} of {len(strategy_nav)} strategy NAV dates; "
            f"comparison requires complete exact-date coverage and applies no forward-fill "
            f"(first missing: {examples})"
        )
    aligned_days = sorted(strategy_nav)
    aligned_rows = [{"at": day.isoformat(), "nav": levels[day]} for day in aligned_days]
    missing_count = len(strategy_nav) - len(aligned_days)
    enriched = copy.deepcopy(report)
    enriched["benchmark_nav"] = {BENCHMARK_NAME: aligned_rows}
    enriched["benchmark_provenance"] = {
        "adapter_version": ADAPTER_VERSION,
        "benchmark": BENCHMARK_NAME,
        "source_kind": "explicit_local_parquet_index_cache",
        "source_file_name": source.name,
        "source_file_sha256": source_hash_after,
        "original_strategy_report_sha256": hashlib.sha256(original_report_raw).hexdigest(),
        "strategy_model": SUPPORTED_STRATEGY_MODEL,
        "strategy_valuation_basis": "original raw close; price-only mark, no dividend cash model",
        "benchmark_type": "price_index",
        "benchmark_value_basis": "TOPIX price-index close; dividends are not included",
        "alignment": "complete exact strategy NAV calendar dates; no missing dates, fill, or bridging",
        "strategy_nav_date_count": len(strategy_nav),
        "aligned_date_count": len(aligned_days),
        "unmatched_strategy_nav_date_count": missing_count,
        "coverage_ratio": len(aligned_days) / len(strategy_nav),
        "first_aligned_date": aligned_days[0].isoformat(),
        "last_aligned_date": aligned_days[-1].isoformat(),
        "source_availability": "historical visibility unverified; selected cache has no available_at field",
        "source_mapping": "local cache columns date/index_code/close; upstream row-level page identity not verified",
        "raw_cache_copied": False,
    }
    return enriched
