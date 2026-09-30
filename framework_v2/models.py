"""Immutable strategy targets, state, and inspectable risk decisions."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Iterable, Mapping


class StrategyError(ValueError):
    """Invalid strategy input, state, target, score, or risk constraint."""


def finite_decimal(value: Any, label: str) -> Decimal:
    """Convert a numeric input to a finite Decimal without binary-float leakage."""
    if isinstance(value, bool):
        raise StrategyError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise StrategyError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise StrategyError(f"{label} must be finite")
    return result


@dataclass(frozen=True)
class TargetPosition:
    code: str
    weight: Decimal
    amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise StrategyError("position code must be nonempty")
        object.__setattr__(self, "weight", finite_decimal(self.weight, "position weight"))
        if self.amount is not None:
            amount = finite_decimal(self.amount, "position amount")
            if amount < 0:
                raise StrategyError("position amount cannot be negative")
            object.__setattr__(self, "amount", amount)


@dataclass(frozen=True)
class TargetPortfolio:
    """Full target. Empty positions mean a requested liquidation to cash."""

    positions: tuple[TargetPosition, ...]

    def __post_init__(self) -> None:
        positions = tuple(self.positions)
        if any(not isinstance(item, TargetPosition) for item in positions):
            raise StrategyError("positions must be TargetPosition values")
        codes = [item.code for item in positions]
        if len(codes) != len(set(codes)):
            raise StrategyError("duplicate target position code")
        object.__setattr__(self, "positions", tuple(sorted(positions, key=lambda item: item.code)))

    @classmethod
    def from_weights(cls, weights: Mapping[str, Any]) -> "TargetPortfolio":
        return cls(tuple(TargetPosition(code, finite_decimal(weight, "weight"))
                         for code, weight in weights.items() if finite_decimal(weight, "weight") != 0))

    def weights(self) -> dict[str, Decimal]:
        return {item.code: item.weight for item in self.positions}

    @property
    def long_gross(self) -> Decimal:
        return sum((item.weight for item in self.positions if item.weight > 0), Decimal(0))

    @property
    def short_gross(self) -> Decimal:
        return -sum((item.weight for item in self.positions if item.weight < 0), Decimal(0))

    @property
    def gross(self) -> Decimal:
        return self.long_gross + self.short_gross

    @property
    def net(self) -> Decimal:
        return self.long_gross - self.short_gross

    @property
    def cash_residual(self) -> Decimal:
        """Unallocated long-side capital budget; excludes short-sale proceeds.

        This is a planning constraint, never a broker account cash balance.
        """
        return Decimal(1) - self.long_gross


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return copy.deepcopy(value)


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class StrategyState:
    """Explicit persisted state; no regime or cooldown algorithm is implied."""

    last_decision_identity: str | None = None
    regime: str | None = None
    cooldown_until: str | None = None
    transition_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label in ("last_decision_identity", "regime", "cooldown_until"):
            value = getattr(self, label)
            if value is not None and (not isinstance(value, str) or not value):
                raise StrategyError(f"{label} must be a nonempty string or null")
        if not isinstance(self.transition_state, Mapping):
            raise StrategyError("transition_state must be a JSON object")
        plain = _plain_json(self.transition_state)
        try:
            json.dumps(plain, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise StrategyError(f"transition_state must be finite JSON: {exc}") from exc
        object.__setattr__(self, "transition_state", _freeze_json(plain))

    def to_json(self) -> str:
        return json.dumps({
            "last_decision_identity": self.last_decision_identity,
            "regime": self.regime, "cooldown_until": self.cooldown_until,
            "transition_state": _plain_json(self.transition_state),
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, text: str) -> "StrategyState":
        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise StrategyError(f"duplicate state JSON key: {key}")
                result[key] = value
            return result
        try:
            value = json.loads(text, object_pairs_hook=unique_pairs,
                               parse_constant=lambda token: (_ for _ in ()).throw(StrategyError(f"nonfinite state: {token}")))
        except (json.JSONDecodeError, TypeError) as exc:
            raise StrategyError(f"invalid state JSON: {exc}") from exc
        expected = {"last_decision_identity", "regime", "cooldown_until", "transition_state"}
        if not isinstance(value, dict) or set(value) != expected:
            raise StrategyError("state JSON has missing or unknown fields")
        return cls(**value)


@dataclass(frozen=True)
class RiskDecision:
    """Raw request, allowed target, reasons, and turnover evidence.

    ``cash_residual`` is a long-side planning budget (1 - long gross), not
    actual account cash and not 1 - net exposure.
    """

    raw: TargetPortfolio | None
    allowed: TargetPortfolio | None
    reasons: tuple[str, ...]
    turnover_budget: Decimal
    requested_turnover: Decimal
    allowed_turnover: Decimal
    cash_residual: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        for label in ("turnover_budget", "requested_turnover", "allowed_turnover", "cash_residual"):
            object.__setattr__(self, label, finite_decimal(getattr(self, label), label))


@dataclass(frozen=True)
class StrategyDecision:
    """Immutable scoring audit accompanying a full target or no-rebalance."""

    target: TargetPortfolio | None
    state: StrategyState
    scores: Mapping[str, Decimal]
    ranked_codes: tuple[str, ...]
    dropped_codes: tuple[str, ...]
    preprocess: str
    missing_policy: str
    factor_inputs: Mapping[str, Mapping[str, Decimal]]
    factor_processed: Mapping[str, Mapping[str, Decimal]]

    def __post_init__(self) -> None:
        if self.target is not None and not isinstance(self.target, TargetPortfolio):
            raise StrategyError("target must be TargetPortfolio or None")
        if not isinstance(self.state, StrategyState):
            raise StrategyError("state must be StrategyState")
        for label in ("scores", "factor_inputs", "factor_processed"):
            source = getattr(self, label)
            if label == "scores":
                frozen = MappingProxyType({str(code): finite_decimal(value, "score")
                                           for code, value in source.items()})
            else:
                frozen = MappingProxyType({str(name): MappingProxyType({
                    str(code): finite_decimal(value, f"{name} value")
                    for code, value in items.items()}) for name, items in source.items()})
            object.__setattr__(self, label, frozen)
        object.__setattr__(self, "ranked_codes", tuple(self.ranked_codes))
        object.__setattr__(self, "dropped_codes", tuple(self.dropped_codes))
