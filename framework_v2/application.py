"""Shared, side-effect-free decision service for local execution frontends."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping
import hashlib
import pandas as pd
from .config import ImplementationRegistry, ResolvedRun, resolve_run
from .execution import AccountState, Quote, Instrument, BrokerCapabilities, OrderPlan, ExecutionError
from .factors import FactorContext, FactorSpec, FactorResult
from .legacy_provider import BuiltinFactors
from .models import StrategyState, StrategyDecision, RiskDecision, TargetPortfolio
from .planner import Planner, FeeModel
from .strategy import RiskPolicy
from .strategy_registry import (CompositeFactorStrategyAdapter, StrategyRegistry,
                                StrategySpec, spec_from_config)

@dataclass(frozen=True)
class RunResult:
    strategy_hash: str
    decision_identity: str
    factors: Mapping[str, FactorResult]
    decision: StrategyDecision
    risk: RiskDecision
    plan: OrderPlan
    strategy_implementation_id: str = "composite_factor"
    strategy_implementation_version: str = "1"

class ApplicationService:
    def __init__(self, builtins: BuiltinFactors | None = None, *, factor_cache=None,
                 strategy_registry: StrategyRegistry | None = None):
        self.builtins=builtins or BuiltinFactors()
        self.factor_cache=factor_cache
        self.strategy_registry=strategy_registry or StrategyRegistry()
        composite_spec=StrategySpec("composite_factor", "1")
        if not self.strategy_registry.contains(composite_spec):
            self.strategy_registry.register(
                composite_spec,
                lambda config, factor_ids: CompositeFactorStrategyAdapter(config, factor_ids),
            )
        self.registry=ImplementationRegistry()
        self.validators={}
        for implementation,version in self.builtins.versions.items():
            self.registry.register(implementation,version,self.builtins.compute)
            self.validators[(implementation,version)]=self.builtins.validate_spec

    def register_factor(self, implementation_id, version, function, validator):
        """Trusted application code only; no config-driven import or evaluation."""
        if not callable(validator): raise TypeError("implementation parameter validator is required")
        self.registry.register(implementation_id,version,function)
        self.validators[(implementation_id,version)]=validator

    def validate(self, path) -> ResolvedRun:
        result=resolve_run(path,self.registry)
        for factor in result.factors:
            spec=FactorSpec.from_config(factor)
            self.validators[(spec.implementation_id,spec.implementation_version)](spec)
        self.build_strategy(result.strategy, tuple(factor["id"] for factor in result.factors))
        return result

    def build_strategy(self, config: Mapping, factor_ids: tuple[str, ...]):
        """Resolve an approved strategy implementation without dynamic imports."""
        return self.strategy_registry.create(spec_from_config(config), config, factor_ids)

    def plan(self, resolved: ResolvedRun, *, context: FactorContext,
             account: AccountState, research_marks: Mapping[str, Decimal],
             quotes: Mapping[str, Quote], instruments: Mapping[str, Instrument],
             now: datetime, state: StrategyState | None = None,
             capabilities: BrokerCapabilities | None = None) -> RunResult:
        """Research marks belong to the decision snapshot, never execution quotes.

        Frontends supply separate contexts and quotes, with explicit clocks.
        This service cannot submit, write to a ledger or contact a broker.
        """
        if context.data_snapshot_hash != resolved.data_snapshot_hash:
            raise ExecutionError("research snapshot identity differs from resolved run")
        if dict(resolved.strategy["universe"]) != {"snapshot":"universe"}:
            raise ExecutionError("decision service currently requires the explicit universe dataset")
        if pd.Timestamp(now) < context.decision_at:
            raise ExecutionError("execution precedes decision")
        day=context.decision_at.tz_convert("Asia/Tokyo").date().isoformat()
        if not resolved.run["clock"]["start"] <= day <= resolved.run["clock"]["end"]:
            raise ExecutionError("decision outside run clock")
        identity=resolved.strategy_hash+":"+context.data_snapshot_hash+":"+context.decision_at.isoformat()
        results={}
        universe_identity=hashlib.sha256(context.universe().to_json(orient="split",date_format="iso").encode()).hexdigest()
        for factor in resolved.factors:
            spec=FactorSpec.from_config(factor)
            key=spec.cache_key(data_snapshot_hash=context.data_snapshot_hash,universe_identity=universe_identity,decision_at=context.decision_at)
            result=None if self.factor_cache is None else self.factor_cache.get(key)
            if result is None:
                implementation=resolved.implementation_bindings[(spec.implementation_id,spec.implementation_version)]
                result=implementation(spec,context)
                if not isinstance(result,FactorResult): raise ExecutionError("factor implementation returned an invalid contract")
                if self.factor_cache is not None: self.factor_cache.put(key,result)
            results[factor["id"]]=result
        strategy=self.build_strategy(resolved.strategy,tuple(results))
        decision=strategy.decide(results=results,context=context,
            state=state or StrategyState(),decision_identity=identity)
        weights={}
        for position in account.positions:
            if position.quantity:
                price=Decimal(str(research_marks.get(position.code,"NaN")))
                if not price.is_finite() or price<=0:
                    raise ExecutionError("missing research mark for existing position: "+position.code)
                weights[position.code]=price*position.quantity/account.equity
        risk=RiskPolicy(resolved.strategy["risk"]).apply(decision.target,TargetPortfolio.from_weights(weights))
        plan=Planner().plan(risk.allowed,account,quotes,instruments,
            capabilities or BrokerCapabilities(frozenset({"market","limit"}),frozenset({"DAY"})),
            now=now,decision_identity=identity,strategy_hash=resolved.strategy_hash,
            turnover_budget=risk.turnover_budget,
            fee_model=FeeModel(**dict(resolved.run["fees"])))
        spec=spec_from_config(resolved.strategy)
        return RunResult(resolved.strategy_hash,identity,results,decision,risk,plan,
                         spec.implementation_id,spec.implementation_version)
