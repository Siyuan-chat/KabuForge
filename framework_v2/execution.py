"""Immutable, broker-neutral execution contracts. No I/O or order submission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ExecutionError(ValueError):
    """Invalid account, quote, instrument, order, or execution evidence."""


def money(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ExecutionError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} must be numeric") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ExecutionError(f"{label} must be finite{' and positive' if positive else ''}")
    return result


def quantity(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0) or (not positive and value < 0):
        raise ExecutionError(f"{label} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def aware(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionError(f"{label} must be a timezone-aware datetime")
    return value


def _code(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionError("code must be nonempty text")
    return value


@dataclass(frozen=True)
class Position:
    code: str
    quantity: int
    average_cost: Decimal

    def __post_init__(self) -> None:
        _code(self.code)
        quantity(self.quantity, "position quantity")
        cost = money(self.average_cost, "average_cost")
        if cost < 0:
            raise ExecutionError("average_cost cannot be negative")
        object.__setattr__(self, "average_cost", cost)


@dataclass(frozen=True)
class AccountState:
    account_id: str
    revision: str
    equity: Decimal
    available_cash: Decimal
    positions: tuple[Position, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.account_id, str) or not self.account_id or
                not isinstance(self.revision, str) or not self.revision):
            raise ExecutionError("account_id and revision are required")
        equity = money(self.equity, "equity", positive=True)
        cash = money(self.available_cash, "available_cash")
        if cash < 0:
            raise ExecutionError("available_cash cannot be negative")
        try:
            positions = tuple(self.positions)
        except TypeError as exc:
            raise ExecutionError("positions must be Position records") from exc
        if any(not isinstance(item, Position) for item in positions):
            raise ExecutionError("positions must be Position records")
        codes = [item.code for item in positions]
        if len(codes) != len(set(codes)):
            raise ExecutionError("duplicate account position code")
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "available_cash", cash)
        object.__setattr__(self, "positions", tuple(sorted(positions, key=lambda item: item.code)))


@dataclass(frozen=True)
class Quote:
    code: str
    bid: Decimal
    ask: Decimal
    asof: datetime

    def __post_init__(self) -> None:
        _code(self.code)
        object.__setattr__(self, "bid", money(self.bid, "bid", positive=True))
        object.__setattr__(self, "ask", money(self.ask, "ask", positive=True))
        if self.bid > self.ask:
            raise ExecutionError("crossed quote: bid exceeds ask")
        aware(self.asof, "quote.asof")


@dataclass(frozen=True)
class Instrument:
    code: str
    lot_size: int
    tick_size: Decimal
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _code(self.code)
        quantity(self.lot_size, "lot_size", positive=True)
        object.__setattr__(self, "tick_size", money(self.tick_size, "tick_size", positive=True))
        if self.expires_at is not None:
            aware(self.expires_at, "instrument.expires_at")


@dataclass(frozen=True)
class BrokerCapabilities:
    order_types: frozenset[str]
    time_in_force: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.order_types, (set, frozenset, tuple, list)) or not isinstance(
            self.time_in_force, (set, frozenset, tuple, list)
        ):
            raise ExecutionError("capabilities must be collections of names")
        types = frozenset(self.order_types)
        tif = frozenset(self.time_in_force)
        if not types.issubset({"market", "limit"}) or not tif.issubset({"DAY"}):
            raise ExecutionError("unsupported capability declaration")
        object.__setattr__(self, "order_types", types)
        object.__setattr__(self, "time_in_force", tif)


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    idempotency_key: str
    account_id: str
    account_revision: str
    decision_identity: str
    strategy_hash: str
    code: str
    side: str
    quantity: int
    order_type: str
    limit_price: Decimal | None
    time_in_force: str
    created_at: datetime
    valid_until: datetime
    estimated_price: Decimal
    estimated_fee: Decimal

    def __post_init__(self) -> None:
        for label in ("intent_id", "idempotency_key", "account_id", "account_revision",
                      "decision_identity", "strategy_hash"):
            if not isinstance(getattr(self, label), str) or not getattr(self, label):
                raise ExecutionError(f"{label} is required")
        _code(self.code)
        if self.side not in {"buy", "sell"} or self.order_type not in {"market", "limit"} or self.time_in_force != "DAY":
            raise ExecutionError("invalid side/order type/time-in-force")
        quantity(self.quantity, "order quantity", positive=True)
        if self.order_type == "limit":
            object.__setattr__(self, "limit_price", money(self.limit_price, "limit_price", positive=True))
        elif self.limit_price is not None:
            raise ExecutionError("market order cannot have a limit price")
        aware(self.created_at, "created_at")
        aware(self.valid_until, "valid_until")
        if self.valid_until <= self.created_at:
            raise ExecutionError("order validity must end after creation")
        object.__setattr__(self, "estimated_price", money(self.estimated_price, "estimated_price", positive=True))
        fee = money(self.estimated_fee, "estimated_fee")
        if fee < 0:
            raise ExecutionError("estimated_fee cannot be negative")
        object.__setattr__(self, "estimated_fee", fee)


class OrderStatus(str, Enum):
    SUBMITTING = "SUBMITTING"
    UNKNOWN = "UNKNOWN"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderEvent:
    intent_id: str
    status: OrderStatus
    occurred_at: datetime
    broker_order_id: str | None = None
    reason: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.event_id, str) or not self.event_id or
                not isinstance(self.intent_id, str) or not self.intent_id or
                not isinstance(self.status, OrderStatus)):
            raise ExecutionError("event needs stable event/intent IDs and known status")
        aware(self.occurred_at, "event.occurred_at")
        if self.broker_order_id is not None and (not isinstance(self.broker_order_id, str) or not self.broker_order_id):
            raise ExecutionError("broker_order_id must be nonempty text or null")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ExecutionError("event reason must be text or null")


@dataclass(frozen=True)
class Fill:
    intent_id: str
    trade_id: str
    code: str
    side: str
    quantity: int
    price: Decimal
    fee: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.intent_id, str) or not self.intent_id or not isinstance(self.trade_id, str) or not self.trade_id:
            raise ExecutionError("fill IDs are required")
        _code(self.code)
        if self.side not in {"buy", "sell"}:
            raise ExecutionError("fill side is invalid")
        quantity(self.quantity, "fill quantity", positive=True)
        object.__setattr__(self, "price", money(self.price, "fill price", positive=True))
        fee = money(self.fee, "fill fee")
        if fee < 0:
            raise ExecutionError("fill fee cannot be negative")
        object.__setattr__(self, "fee", fee)
        aware(self.occurred_at, "fill.occurred_at")


@dataclass(frozen=True)
class OrderPlan:
    intents: tuple[OrderIntent, ...]
    skipped: Mapping[str, tuple[str, ...]]
    estimated_turnover: Decimal
    remaining_cash: Decimal

    def __post_init__(self) -> None:
        try:
            intents = tuple(self.intents)
        except TypeError as exc:
            raise ExecutionError("plan intents must be OrderIntent") from exc
        if any(not isinstance(item, OrderIntent) for item in intents):
            raise ExecutionError("plan intents must be OrderIntent")
        ids = [item.intent_id for item in intents]
        if len(ids) != len(set(ids)):
            raise ExecutionError("duplicate intent ID")
        object.__setattr__(self, "intents", intents)
        if not isinstance(self.skipped, Mapping) or any(
            not isinstance(code, str) or not code or
            not isinstance(reasons, (tuple, list)) or
            any(not isinstance(reason, str) or not reason for reason in reasons)
            for code, reasons in self.skipped.items()
        ):
            raise ExecutionError("skipped reasons must map codes to nonempty text reasons")
        object.__setattr__(self, "skipped", MappingProxyType({
            code: tuple(reasons) for code, reasons in self.skipped.items()}))
        turnover = money(self.estimated_turnover, "estimated_turnover")
        if turnover < 0:
            raise ExecutionError("estimated_turnover cannot be negative")
        object.__setattr__(self, "estimated_turnover", turnover)
        object.__setattr__(self, "remaining_cash", money(self.remaining_cash, "remaining_cash"))
        if self.remaining_cash < 0:
            raise ExecutionError("planned remaining cash cannot be negative")


@dataclass(frozen=True)
class ExecutionReport:
    plan: OrderPlan
    events: tuple[OrderEvent, ...] = ()
    fills: tuple[Fill, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, OrderPlan):
            raise ExecutionError("report requires OrderPlan")
        try:
            events, fills = tuple(self.events), tuple(self.fills)
        except TypeError as exc:
            raise ExecutionError("report events/fills must be typed records") from exc
        if any(not isinstance(item, OrderEvent) for item in events) or any(not isinstance(item, Fill) for item in fills):
            raise ExecutionError("report events/fills must be typed records")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "fills", fills)
