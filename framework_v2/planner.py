"""Deterministic, local-only cash-equity order planning.

Prices and fees here are estimates, never promises about broker fills.  In
particular, expected sale proceeds are excluded from the buy-side cash pool.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Mapping
from zoneinfo import ZoneInfo

from .execution import (AccountState, BrokerCapabilities, ExecutionError, Instrument,
                        OrderIntent, OrderPlan, Quote, aware, money)
from .models import TargetPortfolio


@dataclass(frozen=True)
class FeeModel:
    """Conservative per-order estimate: max(minimum_fee, notional * rate)."""

    commission_rate: Decimal = Decimal(0)
    minimum_fee: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        for label in ("commission_rate", "minimum_fee"):
            value = money(getattr(self, label), label)
            if value < 0:
                raise ExecutionError(f"{label} cannot be negative")
            object.__setattr__(self, label, value)

    def estimate(self, notional: Decimal) -> Decimal:
        notional = money(notional, "notional")
        if notional < 0:
            raise ExecutionError("notional cannot be negative")
        return max(self.minimum_fee, notional * self.commission_rate)


def _lots(value: Decimal, lot_notional: Decimal) -> int:
    return int((value / lot_notional).to_integral_value(rounding=ROUND_FLOOR))


def _identity(account: AccountState, decision_identity: str, strategy_hash: str,
              code: str, side: str, qty: int, order_type: str,
              limit_price: Decimal | None, tif: str, valid_until: datetime) -> str:
    payload = {
        "account_id": account.account_id, "account_revision": account.revision,
        "decision_identity": decision_identity, "strategy_hash": strategy_hash,
        "code": code, "side": side, "quantity": qty,
        "order_type": order_type, "limit_price": str(limit_price) if limit_price is not None else None,
        "time_in_force": tif, "valid_until": valid_until.isoformat(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Planner:
    """Construct broker-neutral intents without I/O or account mutation.

    ``turnover_budget`` and ``estimated_turnover`` are fractions of account
    equity.  DAY expires at the next Asia/Tokyo midnight.  A missing or invalid
    code is skipped, not replaced with another security.  No mode enters the
    intent identity, so identical inputs across local execution modes agree.
    """

    def plan(
        self, target: TargetPortfolio | None, account: AccountState,
        quotes: Mapping[str, Quote], instruments: Mapping[str, Instrument],
        capabilities: BrokerCapabilities, *, now: datetime,
        decision_identity: str, strategy_hash: str, turnover_budget: Decimal,
        fee_model: FeeModel, order_type: str = "market", time_in_force: str = "DAY",
        limit_prices: Mapping[str, Decimal] | None = None,
        max_quote_age_seconds: int = 60,
    ) -> OrderPlan:
        if target is not None and not isinstance(target, TargetPortfolio):
            raise ExecutionError("target must be a full TargetPortfolio or None")
        if not isinstance(account, AccountState) or not isinstance(capabilities, BrokerCapabilities):
            raise ExecutionError("account/capabilities contract is invalid")
        if not isinstance(fee_model, FeeModel):
            raise ExecutionError("fee_model must be FeeModel")
        aware(now, "now")
        if not isinstance(decision_identity, str) or not decision_identity:
            raise ExecutionError("decision_identity is required")
        if not isinstance(strategy_hash, str) or not strategy_hash:
            raise ExecutionError("strategy_hash is required")
        budget = money(turnover_budget, "turnover_budget")
        if budget < 0:
            raise ExecutionError("turnover_budget cannot be negative")
        if type(max_quote_age_seconds) is not int or max_quote_age_seconds < 0:
            raise ExecutionError("max_quote_age_seconds must be a nonnegative integer")
        if order_type not in {"market", "limit"} or order_type not in capabilities.order_types:
            raise ExecutionError("order type unsupported by broker capability")
        if time_in_force != "DAY" or time_in_force not in capabilities.time_in_force:
            raise ExecutionError("time-in-force unsupported by broker capability")
        for name, source, cls in (("quotes", quotes, Quote), ("instruments", instruments, Instrument)):
            if not isinstance(source, Mapping):
                raise ExecutionError(f"{name} must be a code mapping")
            if any(not isinstance(item, cls) or code != item.code for code, item in source.items()):
                raise ExecutionError(f"{name} keys and records must match")
        if limit_prices is not None and not isinstance(limit_prices, Mapping):
            raise ExecutionError("limit_prices must be a code mapping")
        if target is None:
            return OrderPlan((), {}, Decimal(0), account.available_cash)
        if any(position.weight < 0 for position in target.positions):
            raise ExecutionError("cash-equity planner does not support short targets")
        targets = {
            position.code: (position.amount if position.amount is not None
                            else position.weight * account.equity)
            for position in target.positions
        }
        if sum(targets.values(), Decimal(0)) > account.equity:
            raise ExecutionError("cash-equity target notional exceeds equity")

        tokyo = now.astimezone(ZoneInfo("Asia/Tokyo"))
        valid_until = datetime.combine(tokyo.date() + timedelta(days=1), time.min,
                                       tzinfo=ZoneInfo("Asia/Tokyo"))
        cash = account.available_cash
        turnover_left = account.equity * budget
        positions = {item.code: item.quantity for item in account.positions}
        skipped: dict[str, list[str]] = {}
        sells: list[OrderIntent] = []
        buys: list[OrderIntent] = []

        def skip(code: str, reason: str) -> None:
            skipped.setdefault(code, []).append(reason)

        def quote_instrument(code: str) -> tuple[Quote, Instrument] | None:
            quote = quotes.get(code)
            instrument = instruments.get(code)
            if quote is None:
                skip(code, "missing_quote")
            if instrument is None:
                skip(code, "missing_instrument")
            if quote is None or instrument is None:
                return None
            if quote.asof > now:
                skip(code, "future_quote")
                return None
            if (now - quote.asof).total_seconds() > max_quote_age_seconds:
                skip(code, "stale_quote")
                return None
            if instrument.expires_at is not None and instrument.expires_at <= now:
                skip(code, "expired_instrument")
                return None
            return quote, instrument

        def price_for(code: str, side: str, quote: Quote, instrument: Instrument) -> tuple[Decimal, Decimal | None] | None:
            if order_type == "market":
                return (quote.bid if side == "sell" else quote.ask), None
            raw_limit = None if limit_prices is None else limit_prices.get(code)
            try:
                limit = money(raw_limit, "limit_price", positive=True)
            except ExecutionError:
                skip(code, "invalid_limit_price")
                return None
            if limit % instrument.tick_size != 0:
                skip(code, "invalid_limit_tick")
                return None
            return limit, limit

        def intent(code: str, side: str, qty: int, px: Decimal,
                   limit: Decimal | None, fee: Decimal) -> OrderIntent:
            digest = _identity(account, decision_identity, strategy_hash, code, side,
                               qty, order_type, limit, time_in_force, valid_until)
            return OrderIntent(digest, digest, account.account_id, account.revision,
                               decision_identity, strategy_hash, code, side, qty,
                               order_type, limit, time_in_force, now, valid_until, px, fee)

        # First size all sells; their expected proceeds never replenish cash.
        for code in sorted(set(positions) | set(targets)):
            current = positions.get(code, 0)
            target_notional = targets.get(code, Decimal(0))
            if current == 0 and target_notional == 0:
                continue
            pair = quote_instrument(code)
            if pair is None:
                continue
            quote, instrument = pair
            desired = _lots(target_notional, quote.ask * instrument.lot_size) * instrument.lot_size
            delta = desired - current
            if delta >= 0:
                continue
            sized = (-delta // instrument.lot_size) * instrument.lot_size
            if sized == 0:
                skip(code, "below_lot")
                continue
            if sized < -delta:
                skip(code, "odd_lot_residual")
            priced = price_for(code, "sell", quote, instrument)
            if priced is None:
                continue
            px, limit = priced
            qty = min(sized, _lots(turnover_left, px * instrument.lot_size) * instrument.lot_size)
            if qty == 0:
                skip(code, "turnover_budget")
                continue
            fee = fee_model.estimate(px * qty)
            uncovered_fee = max(Decimal(0), fee - px * qty)
            if uncovered_fee > cash:
                skip(code, "insufficient_fee_cash")
                continue
            sells.append(intent(code, "sell", qty, px, limit, fee))
            turnover_left -= px * qty
            # The sale can cover its own fee; its remaining proceeds are still
            # unconfirmed and never become this plan's buy-side cash.
            cash -= uncovered_fee
            if qty < sized:
                skip(code, "turnover_budget")

        for code in sorted(targets):
            target_notional = targets[code]
            if target_notional <= 0:
                continue
            current = positions.get(code, 0)
            pair = quote_instrument(code)
            if pair is None:
                continue
            quote, instrument = pair
            priced = price_for(code, "buy", quote, instrument)
            if priced is None:
                continue
            px, limit = priced
            # A high buy limit must not enlarge the target notional beyond its
            # requested weight; quote.ask remains the lower-bound estimate.
            sizing_px = max(quote.ask, px)
            desired = _lots(target_notional, sizing_px * instrument.lot_size) * instrument.lot_size
            if Decimal(desired) * sizing_px < target_notional:
                skip(code, "target_rounded_to_lot")
            delta = desired - current
            if delta <= 0:
                continue
            lot_notional = px * instrument.lot_size
            max_lots = min(delta // instrument.lot_size, _lots(turnover_left, lot_notional))
            if max_lots == 0:
                skip(code, "turnover_budget")
                continue
            # Exact Decimal fee/cash check over integer lots; no floating rounding.
            low, high = 0, max_lots
            while low < high:
                mid = (low + high + 1) // 2
                cost = lot_notional * mid
                if cost + fee_model.estimate(cost) <= cash:
                    low = mid
                else:
                    high = mid - 1
            qty = low * instrument.lot_size
            if qty == 0:
                skip(code, "insufficient_cash_including_fee")
                continue
            notional = px * qty
            fee = fee_model.estimate(notional)
            buys.append(intent(code, "buy", qty, px, limit, fee))
            turnover_left -= notional
            cash -= notional + fee
            if qty < delta:
                skip(code, "cash_or_turnover_limited")

        intents = tuple(sells + buys)
        used = sum((item.estimated_price * item.quantity for item in intents), Decimal(0))
        if used > account.equity * budget or cash < 0:
            raise ExecutionError("planned cash or turnover invariant failed")
        return OrderPlan(intents, {code: tuple(reasons) for code, reasons in skipped.items()},
                         used / account.equity, cash)
