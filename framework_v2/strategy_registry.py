"""Explicit strategy implementations used by the application boundary.

The registry is intentionally in-memory: configuration names an approved
implementation, but never imports or evaluates arbitrary code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .factors import FactorContext, FactorResult
from .models import StrategyDecision, StrategyState


@runtime_checkable
class Strategy(Protocol):
    """The decision contract required by :class:`ApplicationService`."""

    def decide(
        self,
        *,
        results: Mapping[str, FactorResult],
        context: FactorContext,
        state: StrategyState,
        decision_identity: str,
        rebalance: bool = True,
    ) -> StrategyDecision: ...


@dataclass(frozen=True)
class StrategySpec:
    """A trusted strategy implementation identity."""

    implementation_id: str
    implementation_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.implementation_id, str) or not self.implementation_id:
            raise ValueError("strategy implementation id is required")
        if not isinstance(self.implementation_version, str) or not self.implementation_version:
            raise ValueError("strategy implementation version is required")


StrategyFactory = Callable[[Mapping[str, Any], tuple[str, ...]], Strategy]


class StrategyRegistry:
    """Map approved strategy identities to factories without dynamic imports."""

    def __init__(self) -> None:
        self._items: dict[StrategySpec, StrategyFactory] = {}

    def register(self, spec: StrategySpec, factory: StrategyFactory) -> None:
        if not isinstance(spec, StrategySpec) or not callable(factory):
            raise TypeError("strategy registry requires a StrategySpec and callable factory")
        if spec in self._items:
            raise ValueError(f"strategy implementation already registered: {spec}")
        self._items[spec] = factory

    def contains(self, spec: StrategySpec) -> bool:
        return spec in self._items

    def catalog(self) -> tuple[StrategySpec, ...]:
        """Return registered identities in stable implementation/version order."""
        return tuple(sorted(
            self._items,
            key=lambda spec: (spec.implementation_id, spec.implementation_version),
        ))

    def require(self, spec: StrategySpec) -> StrategyFactory:
        if not isinstance(spec, StrategySpec):
            raise TypeError("strategy registry requires a StrategySpec")
        try:
            return self._items[spec]
        except KeyError as exc:
            raise ValueError(f"unknown strategy implementation: {spec}") from exc

    def create(
        self, spec: StrategySpec, config: Mapping[str, Any], factor_ids: tuple[str, ...]
    ) -> Strategy:
        strategy = self.require(spec)(config, factor_ids)
        if not isinstance(strategy, Strategy):
            raise TypeError("strategy factory returned an invalid contract")
        return strategy


def spec_from_config(config: Mapping[str, Any]) -> StrategySpec:
    """Resolve a strategy spec while preserving the v1 configuration contract.

    v1 strategy files have no implementation field.  They always select the
    built-in composite implementation; their ``version`` is a configuration
    version and is not an implementation version.
    """
    implementation = config.get("implementation")
    if implementation is None:
        return StrategySpec("composite_factor", "1")
    if not isinstance(implementation, Mapping):
        raise ValueError("strategy implementation must be a mapping")
    return StrategySpec(
        str(implementation.get("id", "")), str(implementation.get("version", ""))
    )


class CompositeFactorStrategyAdapter:
    """Expose the v1 composite implementation through the registry contract."""

    def __init__(self, config: Mapping[str, Any], factor_ids: tuple[str, ...]) -> None:
        # This local import prevents the registry API from importing strategy
        # algorithms until the approved built-in is selected.
        from .strategy import CompositeFactorStrategy
        self._implementation = CompositeFactorStrategy(config, factor_ids=factor_ids)

    def decide(
        self,
        *,
        results: Mapping[str, FactorResult],
        context: FactorContext,
        state: StrategyState,
        decision_identity: str,
        rebalance: bool = True,
    ) -> StrategyDecision:
        return self._implementation.decide_with_audit(
            results=results,
            context=context,
            state=state,
            decision_identity=decision_identity,
            rebalance=rebalance,
        )
