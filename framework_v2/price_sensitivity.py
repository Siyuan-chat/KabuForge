"""Pre-registered, report-only fee and execution-delay scenarios.

Baseline and higher-fee cases rerun the frozen price-research recipe against
the exact snapshotted bars. The delay case replays the baseline's frozen
quantities one *observed session* later; it is an execution diagnostic, not a
new signal strategy. Nothing in this module writes to the source run.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "kabuforge.price_sensitivity.v1"
SCENARIOS = (
    {"id": "baseline_fee_0_1pct", "fee_percent": 0.1, "delay_observed_sessions": 0,
     "method": "strategy_rerun"},
    {"id": "higher_fee_0_2pct", "fee_percent": 0.2, "delay_observed_sessions": 0,
     "method": "strategy_rerun"},
    {"id": "one_observed_session_delay", "fee_percent": 0.1, "delay_observed_sessions": 1,
     "method": "fixed_quantity_execution_replay"},
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _read_json(path: Path, label: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda item: (_ for _ in ()).throw(
            ValueError(f"non-finite number in {label}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError(f"invalid {label} root")
    return raw, value


def _same_json(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _report_finance(report: dict) -> dict:
    required = ("nav", "account_path", "order_schedule", "skipped_orders", "trades", "fees")
    missing = [key for key in required if key not in report]
    if missing:
        raise ValueError("baseline report lacks required replay evidence: " + ", ".join(missing))
    return {key: report[key] for key in required}


def _assert_baseline_matches(source: dict, replayed: dict) -> None:
    expected = _report_finance(source)
    actual = _report_finance(replayed)
    for key in expected:
        if not _same_json(expected[key], actual[key]):
            raise ValueError(f"baseline replay does not reproduce source {key}")


def _finite_positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"invalid {name}")
    return number


def _delayed_fixed_quantity_replay(rows: list[dict], source: dict, fee_percent: float) -> dict:
    """Replay frozen baseline order quantities at the next observed open."""
    from datetime import date

    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("bar row is invalid")
        code, day = str(row.get("code", "")), str(row.get("date", ""))
        if not code:
            raise ValueError("bar code is missing")
        date.fromisoformat(day)
        _finite_positive(row.get("open"), "open")
        _finite_positive(row.get("close"), "close")
        if day in grouped.setdefault(code, {}):
            raise ValueError("duplicate bar in frozen snapshot")
        grouped[code][day] = row
    if not grouped:
        raise ValueError("frozen bars are empty")
    dates = sorted(set.union(*(set(items) for items in grouped.values())))
    if any(set(items) != set(dates) for items in grouped.values()):
        raise ValueError("frozen bars do not share a complete observed calendar")
    date_index = {day: index for index, day in enumerate(dates)}
    schedule = source.get("order_schedule")
    if not isinstance(schedule, list):
        raise ValueError("frozen order schedule is missing")
    initial = _finite_positive(source.get("initial_equity", source.get("recipe", {}).get("cash")), "initial equity")
    fee = fee_percent / 100.0
    cash = initial
    positions = {code: 0.0 for code in grouped}
    by_actual_day: dict[str, list[dict]] = {}
    terminal_skips: list[dict] = []
    delayed_plan = []
    for sequence, order in enumerate(schedule):
        if not isinstance(order, dict):
            raise ValueError("invalid frozen order")
        original_day = str(order.get("execution_date", ""))
        if original_day not in date_index:
            raise ValueError("order execution date is absent from frozen calendar")
        code = str(order.get("code", "")); side = str(order.get("side", ""))
        quantity = _finite_positive(order.get("quantity"), "fixed order quantity")
        if code not in grouped or side not in {"buy", "sell"}:
            raise ValueError("frozen order code or side is invalid")
        target_index = date_index[original_day] + 1
        event = {"source_order_index": sequence, "code": code, "side": side,
                 "quantity": quantity, "signal_date": order.get("signal_date"),
                 "original_execution_date": original_day,
                 "execution_date": dates[target_index] if target_index < len(dates) else None}
        delayed_plan.append(event)
        if target_index >= len(dates):
            terminal_skips.append({**event, "status": "skipped", "reason": "no_next_observed_open"})
        else:
            by_actual_day.setdefault(dates[target_index], []).append(event)

    nav = []; account_path = []; trades = []; skips = list(terminal_skips); daily_turnover = []; peak = initial
    cumulative_fees = 0.0; total_fees = 0.0
    for index, day in enumerate(dates):
        prior_equity = initial if index == 0 else cash + sum(
            positions[code] * float(grouped[code][dates[index - 1]]["close"]) for code in positions)
        day_fees = 0.0; notional = 0.0
        for event in by_actual_day.get(day, []):  # preserves source schedule order within each day
            code, side, quantity = event["code"], event["side"], event["quantity"]
            open_price = float(grouped[code][day]["open"])
            signed_quantity = quantity if side == "buy" else -quantity
            gross = quantity * open_price; fee_amount = gross * fee
            if side == "buy" and gross + fee_amount > cash + 1e-8:
                skips.append({**event, "status": "skipped", "open_price": open_price,
                    "cash_available": cash, "cash_required": gross + fee_amount,
                    "reason": "opening cash insufficient for fixed quantity"})
                continue
            if side == "sell" and quantity > positions[code] + 1e-8:
                skips.append({**event, "status": "skipped", "open_price": open_price,
                    "available_quantity": positions[code], "reason": "fixed sell quantity exceeds held position"})
                continue
            if side == "buy":
                cash -= gross + fee_amount; positions[code] += quantity
            else:
                cash += gross - fee_amount; positions[code] -= quantity
                if abs(positions[code]) < 1e-10: positions[code] = 0.0
            if cash < -1e-7:
                raise ValueError("delayed replay cash invariant failed")
            day_fees += fee_amount; total_fees += fee_amount; notional += gross
            trades.append({"date": day, "original_execution_date": event["original_execution_date"],
                "signal_date": event["signal_date"], "code": code, "side": side,
                "quantity": quantity, "price": open_price, "fee": fee_amount})
        equity = cash + sum(positions[code] * float(grouped[code][day]["close"]) for code in positions)
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("delayed replay equity is invalid")
        peak = max(peak, equity)
        cumulative_fees += day_fees
        held = [{"code": code, "quantity": quantity,
                 "mark_price": float(grouped[code][day]["close"]),
                 "market_value": quantity * float(grouped[code][day]["close"]),
                 "weight": quantity * float(grouped[code][day]["close"]) / equity}
                for code, quantity in sorted(positions.items()) if quantity > 1e-10]
        account_path.append({"at": day, "cash": cash, "equity": equity,
            "position_universe": sorted(positions), "cash_weight": cash / equity,
            "positions": held, "fees": day_fees, "cumulative_fees": cumulative_fees})
        nav.append({"at": day, "nav": equity / initial, "drawdown": equity / peak - 1, "cash": cash})
        daily_turnover.append({"at": day, "gross_executed_notional": notional,
            "denominator_prior_close_equity": prior_equity,
            "gross_traded_turnover": notional / prior_equity if prior_equity > 0 else None})
    skips.sort(key=lambda event: (event.get("execution_date") or "9999-99-99", event["source_order_index"]))
    return {"model": source.get("model"), "nav": nav, "account_path": account_path, "trades": trades,
            "skipped_orders": skips, "fees": total_fees, "daily_turnover": daily_turnover,
            "delayed_order_plan": delayed_plan,
            "execution_diagnostic": "Fixed baseline quantities replayed at the next observed session open; no signal or security selection was regenerated."}


def _scenario_summary(report: dict, scenario: dict) -> dict:
    nav = report.get("nav") or []
    account = report.get("account_path") or []
    return {"id": scenario["id"], "status": "COMPLETED", "method": scenario["method"],
        "fee_percent": scenario["fee_percent"], "delay_observed_sessions": scenario["delay_observed_sessions"],
        "start_date": nav[0].get("at") if nav else None, "end_date": nav[-1].get("at") if nav else None,
        "nav_observations": len(nav), "orders": len(report.get("order_schedule", report.get("delayed_order_plan", []))),
        "fills": len(report.get("trades", [])), "skips": len(report.get("skipped_orders", [])),
        "fees": report.get("fees"), "ending_nav": nav[-1].get("nav") if nav else None,
        "ending_cash": account[-1].get("cash") if account else None,
        "ending_equity": account[-1].get("equity") if account else None}


def run_price_sensitivity(run_directory: str | Path, output_directory: str | Path, *,
                          expected_report_sha256: str | None = None) -> Path:
    """Verify and compare fixed cost/delay cases without changing the source run."""
    from .price_research import research_bars

    run_dir = Path(run_directory).resolve(strict=True)
    output_dir = Path(output_directory).resolve()
    if output_dir == run_dir or output_dir.is_relative_to(run_dir):
        raise ValueError("sensitivity output must be outside the immutable source run")
    report_path = run_dir / "report.json"
    input_path = run_dir / "research_inputs.json"
    report_raw, report = _read_json(report_path, "source report")
    input_raw, inputs = _read_json(input_path, "frozen research inputs")
    if not isinstance(report, dict) or report.get("model") != "daily_bar_next_open_research_v1":
        raise ValueError("source report model is unsupported for price sensitivity")
    report_hash = _sha256(report_raw)
    if expected_report_sha256 is not None and expected_report_sha256 != report_hash:
        raise ValueError("source report changed after sensitivity selection")
    input_hash = _sha256(input_raw)
    if report.get("input_hash") != input_hash:
        raise ValueError("frozen input bytes do not match source report")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("bars"), list) or not isinstance(inputs.get("recipe"), dict):
        raise ValueError("frozen input schema is invalid")
    recipe = inputs["recipe"]
    if report.get("recipe") != recipe:
        raise ValueError("source recipe does not match frozen inputs")
    if not math.isclose(float(recipe.get("fee", float("nan"))), 0.1, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("pre-registered sensitivity requires a 0.1% baseline fee")
    if report.get("input_hash") != input_hash:
        raise ValueError("input identity mismatch")
    schedule = report.get("order_schedule")
    if not isinstance(schedule, list) or not isinstance(report.get("order_schedule_hash"), str):
        raise ValueError("source order schedule evidence is missing")
    order_hash = _sha256(_canonical(schedule))
    if order_hash != report["order_schedule_hash"]:
        raise ValueError("source order schedule hash mismatch")

    baseline = research_bars(inputs["bars"], recipe)
    _assert_baseline_matches(report, baseline)
    higher_recipe = {**recipe, "fee": 0.2}
    higher_fee = research_bars(inputs["bars"], higher_recipe)
    delayed = _delayed_fixed_quantity_replay(inputs["bars"], report, 0.1)

    scenarios = []
    for spec, value in zip(SCENARIOS, (baseline, higher_fee, delayed)):
        scenario_recipe = {**recipe, "fee": spec["fee_percent"]}
        schedule_used = value.get("order_schedule", value.get("delayed_order_plan", []))
        item = {"scenario": dict(spec), **_scenario_summary(value, spec),
               "scenario_kind": ("strategy_rerun_with_fee_parameter" if spec["method"] == "strategy_rerun"
                                 else "fixed_baseline_quantity_execution_diagnostic"),
               "fee_basis": "percentage of each actual fill's notional; buy and sell fees are charged independently",
               "quantity_policy": ("recalculated_by_the_same_strategy_and_fee_reserve" if spec["method"] == "strategy_rerun"
                                   else "baseline_order_quantities_are_frozen_without_resizing"),
               "source_recipe": recipe, "scenario_recipe": scenario_recipe,
               "scenario_recipe_sha256": _sha256(_canonical(scenario_recipe)),
               "scenario_order_schedule_sha256": _sha256(_canonical(schedule_used)),
               "financial_path": {key: value.get(key) for key in (
                   "nav", "account_path", "order_schedule", "delayed_order_plan", "trades",
                   "skipped_orders", "fees", "daily_turnover")}}
        if "delayed_order_plan" in value:
            item["delayed_order_plan"] = value["delayed_order_plan"]
            item["execution_diagnostic"] = value["execution_diagnostic"]
        scenarios.append(item)
    result = {"schema": SCHEMA, "status": "COMPLETED", "readiness": "RESEARCH-ONLY",
        "pit_guarantee": False,
        "methodology": "Baseline and 0.2% fee are real strategy reruns on the exact frozen bars. The +1 observed-session case replays baseline fixed quantities at the next observed open; it is an execution diagnostic, not a recalculated signal strategy.",
        "source_identity": {"run_directory": str(run_dir), "report_sha256": report_hash,
            "input_sha256": input_hash, "order_schedule_sha256": order_hash,
            "strategy_hash": report.get("strategy_hash"), "model": report.get("model")},
        "scenarios": scenarios, "selection": "All preregistered scenarios are reported; no scenario is selected or optimized."}
    output_dir.mkdir(parents=True, exist_ok=False)
    destination = output_dir / "price_sensitivity.json"
    temp = output_dir / ".price_sensitivity.json.tmp"
    temp.write_bytes(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    temp.replace(destination)
    if _sha256(report_path.read_bytes()) != report_hash or _sha256(input_path.read_bytes()) != input_hash:
        raise ValueError("source report or frozen input changed while sensitivity was running")
    return destination
