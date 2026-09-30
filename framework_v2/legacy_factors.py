"""Explicit compatibility boundary for the seven private legacy factor names.

Callers register runner callables and PIT-aware loader factories themselves.
This module never imports a legacy module, selects an alternate formula, or
executes a factor merely because a matching name appears in JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from framework_v2.factors import FactorContext, FactorContractError, FactorResult, FactorSpec, _plain


PUBLIC_MOMENTUM_IMPLEMENTATION_ID = "public.momentum_12_1"

# The public 12-1 momentum sample is a different implementation from the
# private residual-momentum strategy. It is never substituted here.
LEGACY_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "quality": ("private.quality", ("fundamental_loader",)),
    "value": ("private.value", ("fundamental_loader",)),
    "residual_momentum": ("private.residual_momentum", ("close_loader",)),
    "dual_ma": ("private.dual_ma", ("price_loader",)),
    "reversal": ("private.reversal", ("panel_price_loader", "price_loader")),
    "attention": ("private.attention", ("attention_loader",)),
    "behaviour": ("private.behaviour", ("behaviour_loader",)),
}

LegacyRunner = Callable[..., dict[str, Any]]
LoaderFactory = Callable[[FactorContext], Callable[..., Any]]


@dataclass(frozen=True)
class _RunnerBinding:
    version: str
    function: LegacyRunner
    legacy_name: str
    result_name: str
    capabilities: tuple[str, ...]


class LegacyFactorRegistry:
    """Allow-list of seven runner names and explicit loader capabilities."""

    def __init__(self) -> None:
        self._runners: dict[str, _RunnerBinding] = {}
        self._loaders: dict[str, LoaderFactory] = {}

    def register_runner(self, name: str, version: str, function: LegacyRunner) -> None:
        if name not in LEGACY_CONTRACTS:
            raise FactorContractError(f"unknown legacy factor: {name}")
        implementation_id, capabilities = LEGACY_CONTRACTS[name]
        if implementation_id in self._runners or not version or not callable(function):
            raise FactorContractError(f"invalid or duplicate legacy runner: {name}")
        self._runners[implementation_id] = _RunnerBinding(version, function, name, name, capabilities)

    def register_public_runner(self, name: str, version: str, function: LegacyRunner) -> None:
        """Explicitly register public code; never infer its identity from a filename.

        The public legacy filename residual_momentum contains a 12-1 momentum
        implementation. Its implementation ID and result column stay distinct.
        """
        if name not in LEGACY_CONTRACTS:
            raise FactorContractError(f"unknown public legacy factor: {name}")
        implementation_id = PUBLIC_MOMENTUM_IMPLEMENTATION_ID if name == "residual_momentum" else f"public.{name}"
        if implementation_id in self._runners or not version or not callable(function):
            raise FactorContractError(f"invalid or duplicate public runner: {name}")
        result_name = "momentum_12_1" if name == "residual_momentum" else name
        self._runners[implementation_id] = _RunnerBinding(
            version, function, name, result_name, LEGACY_CONTRACTS[name][1])

    def _require_binding(self, spec: FactorSpec) -> _RunnerBinding:
        binding = self._runners.get(spec.implementation_id)
        if binding is None or binding.version != spec.implementation_version:
            raise FactorContractError(
                f"missing runner version for {spec.implementation_id}: {spec.implementation_version}; "
                "cannot replace an unregistered implementation")
        return binding

    def register_loader(self, capability: str, factory: LoaderFactory) -> None:
        known = {item for _, capabilities in LEGACY_CONTRACTS.values() for item in capabilities}
        if capability not in known or capability in self._loaders or not callable(factory):
            raise FactorContractError(f"invalid or duplicate loader capability: {capability}")
        self._loaders[capability] = factory

    def bind(self, spec: FactorSpec, context: FactorContext) -> tuple[LegacyRunner, dict[str, Any]]:
        """Return an approved runner and config with all required loaders bound."""
        binding = self._require_binding(spec)
        required = binding.capabilities
        missing = set(required) - set(self._loaders)
        if missing:
            raise FactorContractError(f"missing loader capabilities for {spec.id}: {sorted(missing)}")
        config = _plain(spec.config["implementation"]["parameters"])
        forbidden = set(config) & {
            "allow_yfinance_fallback", "save_minimal_path", "save_detail_path",
            "jquants_client", "jquants_api_key", "api_key", "data_source",
            "asof_date", "rebalance_date", *required,
        }
        if forbidden:
            raise FactorContractError(f"reserved legacy parameters: {sorted(forbidden)}")
        local_date = context.decision_at.tz_convert("Asia/Tokyo").tz_localize(None).normalize()
        config.update({
            "asof_date": local_date, "rebalance_date": local_date,
            "allow_yfinance_fallback": False,
            "save_minimal_path": None, "save_detail_path": None,
        })
        for capability in required:
            loader = self._loaders[capability](context)
            if not callable(loader):
                raise FactorContractError(f"loader factory did not bind callable: {capability}")
            config[capability] = loader
        if binding.legacy_name in {"quality", "value"}:
            config["mode"] = "historical_local"
        return binding.function, config


class LegacyFactorAdapter:
    """Run only explicitly registered legacy code against the PIT universe.

    Registered runner/loader callables are trusted code. Their numerical
    equivalence and behavior require independent tests against the private
    implementations; the registry itself does not prove either property.
    """

    def __init__(self, registry: LegacyFactorRegistry) -> None:
        self.registry = registry

    def run(self, spec: FactorSpec, context: FactorContext) -> FactorResult:
        runner, config = self.registry.bind(spec, context)
        universe = context.universe()
        local_date = config["rebalance_date"]
        result = runner(universe=universe.copy(deep=True), rebalance_date=local_date,
                        config=config)
        binding = self.registry._require_binding(spec)
        return FactorResult.from_legacy_dict(result, factor_id=binding.result_name,
                                            binding_id=spec.id)
