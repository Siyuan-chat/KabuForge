"""Verified, report-only price/signal/fill diagnostics for price research runs.

This module derives display series from a run's frozen research_inputs.json and
the immutable price-research report. It never recalculates NAV or changes an
order, and it does not assign historical data-availability timestamps.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any


_COPY = {
    "zh_CN": {
        "unavailable": "价格与执行诊断不可用：缺少可核验的冻结行情、订单或成交证据。",
        "pit": "历史行情可见性未认证；仅供 RESEARCH-ONLY 研究展示。",
        "close": "研究价格（收盘）", "fast": "快线 SMA", "slow": "慢线 SMA",
        "signal": "前收盘信号 / 定量日", "fill": "实际开盘成交", "skip": "跳过订单（非成交）",
    },
    "ja_JP": {
        "unavailable": "価格・執行診断は利用できません。検証可能な凍結データ、注文または約定根拠がありません。",
        "pit": "過去のデータ可視性は未認証です。RESEARCH-ONLY の研究表示です。",
        "close": "研究価格（終値）", "fast": "短期 SMA", "slow": "長期 SMA",
        "signal": "前日終値シグナル / 数量決定日", "fill": "実際の始値約定", "skip": "スキップ注文（約定ではない）",
    },
    "en_US": {
        "unavailable": "Price and execution diagnostics are unavailable: verified frozen bars, orders or fills are missing.",
        "pit": "Historical visibility is unverified; this is RESEARCH-ONLY research output.",
        "close": "Research price (close)", "fast": "Fast SMA", "slow": "Slow SMA",
        "signal": "Prior-close signal / sizing date", "fill": "Actual open fill", "skip": "Skipped order (not a fill)",
    },
}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _strict_json(raw: bytes, description: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value in {description}: {value}")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {description}") from exc


def _unavailable(language: str, reason_code: str, *, input_hash=None, order_hash=None) -> dict:
    locale = language if language in _COPY else "en_US"
    return {
        "schema": "kabuforge.price_execution_diagnostics.v1",
        "status": "unavailable", "reason_code": reason_code,
        "message": _COPY[locale]["unavailable"], "pit_guarantee": False,
        "readiness": "RESEARCH-ONLY", "explanation": _COPY[locale]["pit"],
        "input_hash": input_hash, "order_schedule_hash": order_hash,
        "series": [], "events": [], "labels": dict(_COPY[locale]),
    }


def _finite_positive(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"invalid {name}")
    return number


def build_price_execution_diagnostics(run_dir: str | Path, report: dict, *, language="zh_CN") -> dict:
    """Build localized chart payloads from a verified research run directory.

    ``run_dir`` must contain the exact ``research_inputs.json`` written by
    ``run_price_research``. A changed input snapshot or order schedule is an
    integrity error, rather than a partially trusted visualization.
    """
    locale = language if language in _COPY else "en_US"
    if not isinstance(report, dict):
        return _unavailable(locale, "report_missing")
    if report.get("model") != "daily_bar_next_open_research_v1":
        return _unavailable(locale, "unsupported_report_model")

    root = Path(run_dir).resolve(strict=True)
    snapshot = root / "research_inputs.json"
    try:
        raw = snapshot.read_bytes()
    except OSError:
        return _unavailable(locale, "frozen_input_missing")
    actual_input_hash = hashlib.sha256(raw).hexdigest()
    expected_input_hash = report.get("input_hash")
    if not isinstance(expected_input_hash, str) or actual_input_hash != expected_input_hash:
        raise ValueError("frozen research input hash does not match report input_hash")
    inputs = _strict_json(raw, "frozen research inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("bars"), list) or not isinstance(inputs.get("recipe"), dict):
        return _unavailable(locale, "frozen_input_schema_invalid", input_hash=actual_input_hash)
    bars = inputs["bars"]
    recipe = inputs["recipe"]
    if report.get("recipe") != recipe:
        raise ValueError("frozen recipe does not match report recipe")

    schedule = report.get("order_schedule")
    if not isinstance(schedule, list) or not isinstance(report.get("order_schedule_hash"), str):
        return _unavailable(locale, "order_schedule_missing", input_hash=actual_input_hash)
    actual_order_hash = _canonical_hash(schedule)
    if actual_order_hash != report["order_schedule_hash"]:
        raise ValueError("order schedule hash does not match report order_schedule_hash")

    by_code: dict[str, dict[str, dict]] = {}
    for row in bars:
        if not isinstance(row, dict):
            return _unavailable(locale, "bar_row_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)
        code = str(row.get("code", "")).strip()
        day = str(row.get("date", ""))
        if not code:
            return _unavailable(locale, "bar_code_missing", input_hash=actual_input_hash, order_hash=actual_order_hash)
        try:
            date.fromisoformat(day)
            _finite_positive(row.get("close"), "close")
            _finite_positive(row.get("open"), "open")
        except (ValueError, TypeError):
            return _unavailable(locale, "bar_price_or_date_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)
        if day in by_code.setdefault(code, {}):
            return _unavailable(locale, "duplicate_bar", input_hash=actual_input_hash, order_hash=actual_order_hash)
        by_code[code][day] = row
    if not by_code:
        return _unavailable(locale, "bars_missing", input_hash=actual_input_hash, order_hash=actual_order_hash)

    # The research engine requires a common calendar; enforce it for charts too.
    calendars = [set(rows) for rows in by_code.values()]
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        return _unavailable(locale, "incomplete_common_calendar", input_hash=actual_input_hash, order_hash=actual_order_hash)

    actual_fills = report.get("trades")
    skipped_orders = report.get("skipped_orders")
    if not isinstance(actual_fills, list) or not isinstance(skipped_orders, list):
        return _unavailable(locale, "fill_or_skip_evidence_missing", input_hash=actual_input_hash, order_hash=actual_order_hash)
    allowed_dates = calendars[0]
    known_codes = set(by_code)

    def valid_event(row, *, fill=False, skipped=False):
        if not isinstance(row, dict):
            return False
        event_day = str(row.get("date") if fill else row.get("execution_date", row.get("date", "")))
        signal_day = str(row.get("signal_date", ""))
        code = str(row.get("code", ""))
        side = row.get("side")
        try:
            date.fromisoformat(event_day)
            date.fromisoformat(signal_day)
            _finite_positive(row.get("quantity"), "quantity")
            if fill:
                _finite_positive(row.get("price"), "fill price")
            elif skipped:
                _finite_positive(row.get("open_price"), "skipped open price")
        except (ValueError, TypeError):
            return False
        return event_day in allowed_dates and signal_day in allowed_dates and code in known_codes and side in {"buy", "sell"}

    if any(not valid_event(row) for row in schedule):
        return _unavailable(locale, "order_event_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)
    if any(not valid_event(row, fill=True) for row in actual_fills):
        return _unavailable(locale, "fill_event_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)
    if any(not valid_event(row, skipped=True) for row in skipped_orders):
        return _unavailable(locale, "skipped_event_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)

    template = recipe.get("signal_template", "price_momentum")
    parameters = report.get("strategy_parameters") or {}
    fast = slow = None
    if template == "sma_crossover":
        fast = parameters.get("fast_period", recipe.get("fast_period"))
        slow = parameters.get("slow_period", recipe.get("slow_period"))
        if type(fast) is not int or type(slow) is not int or fast < 2 or slow <= fast:
            return _unavailable(locale, "sma_parameters_invalid", input_hash=actual_input_hash, order_hash=actual_order_hash)
    elif template != "price_momentum":
        return _unavailable(locale, "signal_template_unsupported", input_hash=actual_input_hash, order_hash=actual_order_hash)

    events = []
    for source, event_rows in (("scheduled", schedule), ("fill", actual_fills), ("skipped", skipped_orders)):
        for row in event_rows:
            event_day = str(row.get("date") if source == "fill" else row.get("execution_date", row.get("date", "")))
            events.append({
                "kind": source, "code": str(row["code"]), "side": row["side"],
                "signal_date": str(row["signal_date"]), "execution_date": event_day,
                "quantity": float(row["quantity"]),
                "price": float(row["price"]) if source == "fill" else (
                    float(row["open_price"]) if source == "skipped" else None),
                "reason": str(row.get("reason", "")) if source == "skipped" else None,
            })
    events.sort(key=lambda item: (item["execution_date"], item["code"], {"scheduled": 0, "fill": 1, "skipped": 2}[item["kind"]]))

    series = []
    for code in sorted(by_code):
        code_rows = by_code[code]
        days = sorted(code_rows)
        closes = [_finite_positive(code_rows[day].get("selected_price", code_rows[day]["close"]), "research price") for day in days]
        fast_values: list[float | None] = []
        slow_values: list[float | None] = []
        if fast is not None:
            for index in range(len(days)):
                fast_values.append(sum(closes[index-fast+1:index+1]) / fast if index + 1 >= fast else None)
                slow_values.append(sum(closes[index-slow+1:index+1]) / slow if index + 1 >= slow else None)
        scheduled = [event for event in events if event["kind"] == "scheduled" and event["code"] == code]
        fills = [event for event in events if event["kind"] == "fill" and event["code"] == code]
        skips = [event for event in events if event["kind"] == "skipped" and event["code"] == code]
        series.append({
            "code": code, "dates": days,
            "research_close": closes,
            "raw_close": [_finite_positive(code_rows[day]["close"], "raw close") for day in days],
            "raw_open": [_finite_positive(code_rows[day]["open"], "raw open") for day in days],
            "price_basis": str(code_rows[days[0]].get("selected_price_basis", "raw")),
            "fast_sma": fast_values, "slow_sma": slow_values,
            "scheduled_orders": scheduled, "actual_fills": fills, "skipped_orders": skips,
        })

    return {
        "schema": "kabuforge.price_execution_diagnostics.v1",
        "status": "available", "reason_code": None,
        "message": "", "pit_guarantee": False, "readiness": "RESEARCH-ONLY",
        "explanation": _COPY[locale]["pit"], "input_hash": actual_input_hash,
        "order_schedule_hash": actual_order_hash,
        "strategy_hash": report.get("strategy_hash"), "strategy_template": template,
        "signal_parameters": {"fast_period": fast, "slow_period": slow} if fast is not None else {},
        "labels": dict(_COPY[locale]), "series": series, "events": events,
        "event_counts": {"scheduled": len(schedule), "fills": len(actual_fills), "skipped": len(skipped_orders)},
    }
