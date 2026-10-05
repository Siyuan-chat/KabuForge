"""Derived performance summaries for existing, immutable backtest reports."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import math
from statistics import mean, stdev


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _safe_return(end: float, start: float):
    result = end / start - 1
    return result if math.isfinite(result) else None


def summarize_report(report: dict) -> dict:
    """Derive readable metrics and report incomplete evidence instead of filling it."""
    warnings = []
    points = []
    for row in report.get("nav") or []:
        if not isinstance(row, dict):
            warnings.append("A NAV row is not an object and was skipped")
            continue
        value = _number(row.get("nav"))
        try:
            day = date.fromisoformat(str(row.get("at", ""))[:10])
        except ValueError:
            warnings.append("A NAV row has an invalid date and was skipped")
            continue
        if value is None or value <= 0:
            warnings.append("A NAV row has a missing or invalid value and was skipped")
            continue
        points.append({"date": day, "nav": value, "cash": _number(row.get("cash")), "source": row})
    ordered = sorted(points, key=lambda item: item["date"])
    by_date = {}
    for point in ordered:
        if point["date"] in by_date:
            warnings.append(f"Duplicate NAV date {point['date'].isoformat()}; later row retained")
        by_date[point["date"]] = point
    points = list(by_date.values())
    empty = {
        "observation_count": 0, "period_return": None, "observed_window_return": None,
        "annualized_return": None, "annualized_volatility": None,
        "annualized_volatility_reason": "no valid NAV observations", "sharpe": None,
        "sharpe_reason": "no valid NAV observations", "sharpe_basis": "not calculated",
        "max_drawdown": None, "drawdown_basis": "unavailable", "latest_cash": None,
        "fees": None, "fees_reason": "fee evidence unavailable", "trade_count": None,
        "average_plan_turnover": None, "benchmark_available": False,
        "monthly_returns": [], "return_basis": "unavailable", "warnings": warnings,
    }
    if not points:
        return empty

    values = [point["nav"] for point in points]
    returns = [_safe_return(right, left) for left, right in zip(values, values[1:])]
    if any(value is None for value in returns):
        warnings.append("A period return overflowed; risk statistics are unavailable")
    visible_return = _safe_return(values[-1], values[0]) if len(values) > 1 else None
    base_known = report.get("nav_base_includes_initial") is True
    initial_nav = _number(report.get("initial_nav")) if base_known else None
    period_return = _safe_return(values[-1], initial_nav) if initial_nav and initial_nav > 0 else None
    return_basis = "from explicit initial NAV" if period_return is not None else "first to last displayed NAV only"
    if base_known and (initial_nav is None or initial_nav <= 0):
        warnings.append("Initial NAV is missing or invalid; no normalized NAV default was assumed")

    initial_at = report.get("initial_at") if base_known else None
    elapsed_days = None
    if initial_at:
        try:
            elapsed_days = (points[-1]["date"] - date.fromisoformat(str(initial_at)[:10])).days
        except ValueError:
            warnings.append("Initial NAV date is invalid; annualized return is unavailable")
    annualized_return = None
    if period_return is not None and elapsed_days and elapsed_days > 0 and period_return > -1:
        try:
            annualized_return = math.expm1(math.log1p(period_return) * 365.2425 / elapsed_days)
        except (OverflowError, ValueError):
            warnings.append("Annualized return overflowed and is unavailable")

    frequency = report.get("nav_frequency")
    annualization = {"daily": 252, "weekly": 52}.get(frequency)
    valid_returns = [value for value in returns if value is not None]
    returns_complete = len(valid_returns)==len(returns)
    deviation = stdev(valid_returns) if returns_complete and len(valid_returns) > 1 else None
    try:
        volatility = deviation * math.sqrt(annualization) if annualization and deviation is not None else None
        if volatility is not None and not math.isfinite(volatility):
            volatility = None
    except OverflowError:
        volatility = None
    if volatility is None:
        volatility_reason = "declare daily or weekly NAV frequency and supply at least two returns"
    else:
        volatility_reason = None
    try:
        sharpe = mean(valid_returns) / deviation * math.sqrt(annualization) if returns_complete and annualization and deviation and deviation > 0 else None
    except (OverflowError,ValueError,ZeroDivisionError):
        sharpe=None
    if sharpe is not None and not math.isfinite(sharpe):
        sharpe = None
    sharpe_reason = None if sharpe is not None else (
        "a return is invalid or overflowed" if not returns_complete else
        "zero observed return volatility" if deviation == 0 else "declare daily or weekly NAV frequency and supply at least two returns"
    )
    if not returns_complete:
        volatility=None
        volatility_reason="a return is invalid or overflowed; risk statistics are unavailable"

    supplied_drawdowns = [_number(point["source"].get("drawdown")) for point in points]
    if supplied_drawdowns and all(value is not None for value in supplied_drawdowns):
        max_drawdown = min(supplied_drawdowns)
        drawdown_basis = "reported NAV drawdown series"
    else:
        if any(value is not None for value in supplied_drawdowns):
            warnings.append("Reported drawdown series is incomplete; recalculated from the displayed NAV window")
        peak = values[0]
        window_drawdowns = []
        for value in values:
            peak = max(peak, value)
            window_drawdowns.append(value / peak - 1)
        max_drawdown = min(window_drawdowns)
        drawdown_basis = "displayed NAV window only"

    month_groups: dict[str, list[dict]] = {}
    for point in points:
        month_groups.setdefault(point["date"].strftime("%Y-%m"), []).append(point)
    monthly = []
    prior_close = None
    initial_day=None
    if base_known and initial_at:
        try: initial_day=date.fromisoformat(str(initial_at)[:10])
        except ValueError: initial_day=None
    for index, (month, rows) in enumerate(month_groups.items()):
        if prior_close is not None:
            base = prior_close
        elif base_known and initial_nav is not None and initial_at and str(initial_at)[:7] == month:
            base = initial_nav
        else:
            base = rows[0]["nav"]
        month_end = monthrange(rows[-1]["date"].year, rows[-1]["date"].month)[1]
        observed_end = rows[-1]["date"].day
        coverage = []
        if index == 0:
            if base_known and initial_nav is not None and initial_day and initial_day.strftime("%Y-%m")==month:
                coverage.append("initial_capital_to_month_end_observed")
            else:
                coverage.append("start_partial")
        coverage.append("month_end_not_observed" if observed_end < month_end else "calendar_month_end_observed_trading_day_completeness_unverified")
        monthly_return = _safe_return(rows[-1]["nav"], base)
        if monthly_return is None:
            warnings.append(f"Monthly return for {month} overflowed")
        start_at=initial_day.isoformat() if index==0 and base_known and initial_nav is not None and initial_day and initial_day.strftime("%Y-%m")==month else rows[0]["date"].isoformat()
        monthly.append({"month": month,"start_at":start_at,"end_at":rows[-1]["date"].isoformat(),
                        "return": monthly_return,"end_nav": rows[-1]["nav"],"coverage": coverage})
        prior_close = rows[-1]["nav"]

    trades = report.get("trades")
    if trades is None:
        journal = report.get("journal", report.get("execution", {}).get("view", {}))
        trades = journal.get("fills") if isinstance(journal, dict) else None
    fee_value = report.get("fees")
    fee_reason = None if fee_value is not None else "fee evidence unavailable"
    if fee_value is None and trades is not None:
        fee_rows = []
        for row in trades:
            if not isinstance(row, dict):
                continue
            detail = row
            if isinstance(row.get("payload"), str):
                try:
                    detail = json.loads(row["payload"])
                except ValueError:
                    continue
            fee = _number(detail.get("fee"))
            if fee is not None:
                fee_rows.append(fee)
        if trades and len(fee_rows) == len(trades):
            fee_value = sum(fee_rows)
            fee_reason = None
        else:
            fee_reason = "complete fee values were not supplied for every trade"
    try:
        fees = _number(Decimal(str(fee_value))) if fee_value is not None else None
        if fees is not None and fees < 0: fees=None
        if fee_value is not None and fees is None: fee_reason="fee value is invalid"
    except (InvalidOperation, ValueError, TypeError):
        fees = None
        fee_reason = "fee value is invalid"

    turnovers = []
    for decision in report.get("decisions") or []:
        value = _number(decision.get("plan", {}).get("estimated_turnover"))
        if value is not None:
            turnovers.append(value)
    return {
        "observation_count": len(points), "period_return": period_return,
        "observed_window_return": visible_return, "annualized_return": annualized_return,
        "annualized_volatility": volatility, "annualized_volatility_reason": volatility_reason,
        "sharpe": sharpe, "sharpe_reason": sharpe_reason,
        "sharpe_basis": f"unadjusted, risk-free rate 0; {frequency or 'frequency unknown'} NAV observations",
        "max_drawdown": max_drawdown, "drawdown_basis": drawdown_basis,
        "latest_cash": points[-1]["cash"], "fees": fees, "fees_reason": fee_reason,
        "trade_count": len(trades) if trades is not None else None,
        "average_plan_turnover": mean(turnovers) if turnovers else None,
        "benchmark_available": bool(report.get("benchmark_nav")), "monthly_returns": monthly,
        "return_basis": return_basis, "warnings": warnings,
    }
