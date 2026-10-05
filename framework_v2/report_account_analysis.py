"""Derive holdings concentration and security P&L from report evidence only."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _day(value):
    try:
        text = str(value)
        try:
            return date.fromisoformat(text)
        except ValueError:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _unavailable(reason):
    return {"available": False, "reason": reason, "holdings": [], "contributions": [],
            "daily_contributions": [], "reconciliation": None}


def analyze_account_path(report: dict) -> dict:
    """Return evidence-backed concentration and attribution, or an explicit reason.

    Attribution uses closing marks and signed actual fill cash flows. It is only
    called available when daily security P&L less actual fees reconciles to the
    report's equity change for every account observation.
    """
    accounts = report.get("account_path") if isinstance(report, dict) else None
    trades = report.get("trades") if isinstance(report, dict) else None
    initial = _number(report.get("initial_equity")) if isinstance(report, dict) else None
    if not isinstance(accounts, list) or not accounts:
        return _unavailable("daily account path is missing")
    if not isinstance(trades, list):
        return _unavailable("actual fill evidence is missing")
    if initial is None or initial <= 0:
        return _unavailable("positive initial account equity is not evidenced")

    by_day = {}
    for row in accounts:
        if not isinstance(row, dict):
            return _unavailable("account path contains an invalid row")
        day = _day(row.get("at"))
        equity = _number(row.get("equity"))
        if day is None or equity is None or equity <= 0 or day in by_day:
            return _unavailable("account dates or equity values are invalid or duplicated")
        by_day[day] = row
    days = sorted(by_day)

    fills = defaultdict(list)
    for fill in trades:
        if not isinstance(fill, dict):
            return _unavailable("actual fill evidence contains an invalid row")
        day = _day(fill.get("date", fill.get("at")))
        code = str(fill.get("code") or "")
        quantity = _number(fill.get("quantity"))
        price = _number(fill.get("price"))
        fee = _number(fill.get("fee"))
        side = str(fill.get("side") or "").lower()
        if day not in by_day or not code or quantity is None or quantity <= 0 or price is None or price <= 0 or fee is None or fee < 0:
            return _unavailable("fills require an observed date, code, positive quantity/price and actual fee")
        if side in {"buy", "b"}:
            signed_quantity = quantity
        elif side in {"sell", "s"}:
            signed_quantity = -quantity
        else:
            return _unavailable("fill side is not a recognized buy or sell")
        fills[day].append((code, signed_quantity, price, fee))

    prior_quantity = defaultdict(float)
    prior_marks = {}
    cumulative = defaultdict(float)
    contribution_rows = []
    daily_rows = []
    per_security_daily = defaultdict(list)
    holdings_rows = []
    maximum_residual = 0.0
    for index, day in enumerate(days):
        row = by_day[day]
        universe = row.get("position_universe")
        positions = row.get("positions")
        if not isinstance(universe, list) or not isinstance(positions, list):
            return _unavailable(f"position universe or held positions are missing at {day.isoformat()}")
        universe_set = {str(code) for code in universe}
        current_quantity = defaultdict(float)
        current_marks = {}
        market_values = {}
        weights = {}
        for pos in positions:
            if not isinstance(pos, dict):
                return _unavailable(f"position row is invalid at {day.isoformat()}")
            code = str(pos.get("code") or "")
            quantity = _number(pos.get("quantity"))
            mark = _number(pos.get("mark_price"))
            market_value = _number(pos.get("market_value"))
            if not code or code not in universe_set or quantity is None or quantity <= 0 or mark is None or mark <= 0:
                return _unavailable(f"positive holding lacks valid close-price evidence at {day.isoformat()}")
            derived_value = quantity * mark
            if market_value is not None and not math.isclose(market_value, derived_value, rel_tol=1e-8, abs_tol=1e-6):
                return _unavailable(f"position market value conflicts with quantity and close mark at {day.isoformat()}")
            current_quantity[code] = quantity
            current_marks[code] = mark
            market_values[code] = derived_value
            weight = _number(pos.get("weight"))
            equity = _number(row.get("equity"))
            derived_weight = derived_value / equity if equity and equity > 0 else None
            if weight is not None and derived_weight is not None and not math.isclose(weight, derived_weight, rel_tol=1e-8, abs_tol=1e-8):
                return _unavailable(f"position weight conflicts with market value and equity at {day.isoformat()}")
            if weight is None:
                weight = derived_weight
            if weight is None:
                return _unavailable(f"holding weight cannot be determined at {day.isoformat()}")
            weights[code] = weight

        # A universe declaration says omitted symbols are not held today. It
        # does not supply a missing mark for any currently held symbol.
        held_codes = [code for code in universe_set if current_quantity.get(code, 0.0) > 0]
        cash = _number(row.get("cash"))
        equity = _number(row.get("equity"))
        if cash is None or equity is None:
            return _unavailable(f"cash or equity is missing at {day.isoformat()}")
        weights["cash"] = cash / equity
        if any(not math.isfinite(value) for value in weights.values()):
            return _unavailable(f"holding weights are non-finite at {day.isoformat()}")
        security_weights = [weights[code] for code in held_codes]
        holdings_rows.append({"at": day.isoformat(), "security_count": len(held_codes),
            "max_security_weight": max(security_weights) if security_weights else 0.0,
            "security_hhi": sum(weight * weight for weight in security_weights),
            "cash_weight": weights["cash"]})

        day_fill_values = defaultdict(float)
        day_fees = 0.0
        for code, signed_quantity, price, fee in fills.get(day, []):
            day_fill_values[code] += signed_quantity * price
            day_fees += fee
        reported_fees = _number(row.get("fees"))
        if reported_fees is None or not math.isclose(reported_fees, day_fees, rel_tol=1e-8, abs_tol=1e-6):
            return _unavailable(f"daily actual fees do not reconcile with fills at {day.isoformat()}")

        securities = set(prior_quantity) | set(current_quantity) | set(day_fill_values)
        day_pnl = {}
        for code in securities:
            q_close = current_quantity.get(code, 0.0)
            q_previous = prior_quantity.get(code, 0.0)
            if q_close and code not in current_marks:
                return _unavailable(f"closing price evidence is missing for {code} at {day.isoformat()}")
            if q_previous and code not in prior_marks:
                return _unavailable(f"previous close evidence is missing for {code} before {day.isoformat()}")
            close_value = q_close * current_marks[code] if q_close else 0.0
            previous_value = q_previous * prior_marks[code] if q_previous else 0.0
            pnl = close_value - previous_value - day_fill_values.get(code, 0.0)
            if not math.isfinite(pnl):
                return _unavailable(f"security P&L is non-finite for {code} at {day.isoformat()}")
            day_pnl[code] = pnl
            cumulative[code] += pnl
            if code not in per_security_daily:
                per_security_daily[code] = [0.0] * index
        for code in cumulative:
            per_security_daily[code].append(day_pnl.get(code, 0.0))
        prior_equity = initial if index == 0 else _number(by_day[days[index - 1]].get("equity"))
        equity_change = equity - prior_equity
        residual = sum(day_pnl.values()) - day_fees - equity_change
        maximum_residual = max(maximum_residual, abs(residual))
        tolerance = max(1e-5, abs(equity) * 1e-9)
        if abs(residual) > tolerance:
            return _unavailable(f"security contribution and fees fail equity reconciliation at {day.isoformat()} (residual {residual:.8g})")
        daily_rows.append({"at": day.isoformat(), "security_pnl": sum(day_pnl.values()),
            "fees": day_fees, "equity_change": equity_change, "residual": residual})
        prior_quantity = defaultdict(float, current_quantity)
        # For flat positions, no future price is needed unless a later fill
        # opens them; the current-day fill and close are already included.
        prior_marks = {code: current_marks[code] for code in current_quantity if code in current_marks}

    contributions = [{"code": code, "cumulative_pnl": value,
        "normalized_contribution": value / initial} for code, value in sorted(cumulative.items())]
    ending_equity = _number(by_day[days[-1]].get("equity"))
    nav_change = (ending_equity - initial) / initial
    contribution_total = sum(item["normalized_contribution"] for item in contributions) - sum(
        row["fees"] for row in daily_rows) / initial
    if not math.isclose(contribution_total, nav_change, rel_tol=1e-8, abs_tol=1e-8):
        return _unavailable("cumulative security contributions less actual fees do not reconcile to NAV change")
    return {"available": True, "reason": None, "holdings": holdings_rows,
        "contributions": contributions, "daily_contributions": daily_rows,
        "per_security_daily": {code: values for code, values in per_security_daily.items()},
        "reconciliation": {"initial_equity": initial, "ending_equity": ending_equity,
            "nav_change": nav_change, "contribution_change": contribution_total,
            "max_daily_equity_residual": maximum_residual,
            "basis": "close-mark security P&L less actual fees; no cash interest"}}
