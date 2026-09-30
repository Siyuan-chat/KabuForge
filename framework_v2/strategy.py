"""Deterministic factor composition and explicit, traceable risk projection."""

from __future__ import annotations

import ast
from decimal import Decimal, DecimalException
from typing import Any, Mapping

import pandas as pd

from framework_v2.config import _validate_formula
from framework_v2.factors import FactorContext, FactorResult
from framework_v2.models import (
    RiskDecision, StrategyDecision, StrategyError, StrategyState,
    TargetPortfolio, finite_decimal,
)


def _score(node: ast.AST, values: Mapping[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Expression):
        return _score(node.body, values)
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return finite_decimal(node.value, "formula constant")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        child = _score(node.operand, values)
        return child if isinstance(node.op, ast.UAdd) else -child
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = _score(node.left, values), _score(node.right, values)
        try:
            if isinstance(node.op, ast.Add):
                answer = left + right
            elif isinstance(node.op, ast.Sub):
                answer = left - right
            elif isinstance(node.op, ast.Mult):
                answer = left * right
            else:
                answer = left / right
        except (DecimalException, ZeroDivisionError) as exc:
            raise StrategyError("invalid or zero-divisor scoring formula") from exc
        return finite_decimal(answer, "score")
    raise StrategyError(f"forbidden scoring syntax: {type(node).__name__}")


def _preprocess(values: Mapping[str, Decimal], policy: str) -> dict[str, Decimal]:
    if policy == "none":
        return dict(values)
    if not values:
        return {}
    if policy == "zscore":
        mean = sum(values.values(), Decimal(0)) / Decimal(len(values))
        variance = sum(((value - mean) ** 2 for value in values.values()), Decimal(0)) / Decimal(len(values))
        spread = variance.sqrt()
        return {code: (value - mean) / spread if spread else Decimal(0)
                for code, value in values.items()}
    if policy == "rank":
        ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
        groups: dict[Decimal, list[int]] = {}
        for index, (_, value) in enumerate(ordered):
            groups.setdefault(value, []).append(index)
        denominator = Decimal(max(1, len(ordered) - 1))
        return {code: (Decimal(sum(groups[value])) / Decimal(len(groups[value]))) / denominator
                for code, value in ordered}
    raise StrategyError(f"unknown preprocessing policy: {policy}")


class CompositeFactorStrategy:
    """Compose named factor values with a bounded arithmetic expression.

    ``factor_ids`` come from already resolved factor references. This first
    version supports equal-weight top-N long/short selection. It makes no
    claim of numerical compatibility with either legacy composite formula.
    """

    def __init__(self, config: Mapping[str, Any], *, factor_ids: tuple[str, ...]) -> None:
        if config.get("kind") != "strategy" or not factor_ids or len(set(factor_ids)) != len(factor_ids):
            raise StrategyError("validated strategy and unique factor ids are required")
        self.factor_ids = tuple(factor_ids)
        self.formula = config["scoring"]["formula"]
        try:
            _validate_formula(self.formula, set(self.factor_ids))
        except ValueError as exc:
            raise StrategyError(str(exc)) from exc
        self.tree = ast.parse(self.formula, mode="eval")
        portfolio = config["portfolio"]
        if portfolio["construction"] not in {"equal_weight", "rank"}:
            raise StrategyError("only equal_weight or rank alias is supported")
        parameters = dict(portfolio["parameters"])
        if "top_n" in parameters and "count" in parameters and parameters["top_n"] != parameters["count"]:
            raise StrategyError("top_n conflicts with legacy count")
        top_n = parameters.get("top_n", parameters.get("count", 20))
        self.long_count = parameters.get("long_count", top_n)
        self.short_count = parameters.get("short_count", 0)
        if type(self.long_count) is not int or self.long_count < 0 or type(self.short_count) is not int or self.short_count < 0:
            raise StrategyError("long_count and short_count must be nonnegative integers")
        if "long_count" in parameters and ("top_n" in parameters or "count" in parameters) and self.long_count != top_n:
            raise StrategyError("long_count conflicts with top_n/count")
        self.long_gross = finite_decimal(parameters.get("long_gross", 1 if self.long_count else 0), "long_gross")
        self.short_gross = finite_decimal(parameters.get("short_gross", 0), "short_gross")
        if self.long_gross < 0 or self.short_gross < 0:
            raise StrategyError("gross allocations cannot be negative")
        if self.short_count == 0 and self.short_gross != 0 or self.short_count > 0 and self.short_gross == 0:
            raise StrategyError("short_count and short_gross must both be positive or both zero")
        if self.long_count == 0 and self.long_gross != 0:
            raise StrategyError("long_gross requires long_count")
        self.preprocess = parameters.get("preprocess", "none")
        self.missing_policy = parameters.get("missing_policy", "reject")
        if self.preprocess not in {"none", "zscore", "rank"} or self.missing_policy not in {"reject", "drop"}:
            raise StrategyError("invalid preprocessing or missing policy")

    def decide(self, *, results: Mapping[str, FactorResult], context: FactorContext,
               state: StrategyState, decision_identity: str,
               rebalance: bool = True) -> tuple[TargetPortfolio | None, StrategyState]:
        """Compatibility shorthand; new callers should persist decide_with_audit."""
        audit = self.decide_with_audit(results=results, context=context, state=state,
                                       decision_identity=decision_identity, rebalance=rebalance)
        return audit.target, audit.state

    def decide_with_audit(self, *, results: Mapping[str, FactorResult], context: FactorContext,
                          state: StrategyState, decision_identity: str,
                          rebalance: bool = True) -> StrategyDecision:
        """Return full target, new state, scores, factor transforms, and dropped codes."""
        if not isinstance(state, StrategyState) or not decision_identity:
            raise StrategyError("state and decision identity are required")
        if decision_identity == state.last_decision_identity:
            raise StrategyError("decision identity has already been processed")
        new_state = StrategyState(decision_identity, state.regime,
                                  state.cooldown_until, state.transition_state)
        if not rebalance:
            return StrategyDecision(None, new_state, {}, (), (), self.preprocess,
                                    self.missing_policy, {}, {})
        if set(results) != set(self.factor_ids):
            raise StrategyError("factor result ids must match resolved references")
        universe = context.universe()
        codes = sorted(universe["code"].astype(str).tolist())
        if len(codes) != len(set(codes)):
            raise StrategyError("duplicate universe code")
        raw: dict[str, dict[str, Decimal]] = {}
        for factor_id in self.factor_ids:
            result = results[factor_id]
            if not isinstance(result, FactorResult):
                raise StrategyError(f"invalid factor result: {factor_id}")
            frame = result.minimal
            if result.binding_id is not None and result.binding_id != factor_id:
                raise StrategyError(f"factor binding does not match result id: {factor_id}")
            if result.binding_id is None and not frame["factor_name"].eq(factor_id).all():
                raise StrategyError(f"factor_name does not match result id: {factor_id}")
            for date_col in ("signal_date", "data_end_date"):
                for value in frame[date_col].dropna():
                    stamp = pd.Timestamp(value)
                    if stamp.tzinfo is None:
                        stamp = stamp.tz_localize("Asia/Tokyo")
                    if stamp.tz_convert("UTC") > context.decision_at:
                        raise StrategyError(f"future {factor_id}.{date_col}")
            mapping: dict[str, Decimal] = {}
            for row in frame.itertuples(index=False):
                code = str(getattr(row, "code"))
                value = getattr(row, "factor_value")
                if pd.notna(value):
                    mapping[code] = finite_decimal(value, f"{factor_id}.factor_value")
            raw[factor_id] = mapping
        eligible = [code for code in codes if all(code in raw[item] for item in self.factor_ids)]
        dropped = tuple(sorted(set(codes) - set(eligible)))
        if self.missing_policy == "reject" and len(eligible) != len(codes):
            raise StrategyError(f"missing factor values for codes: {list(dropped)}")
        processed = {factor_id: _preprocess({code: raw[factor_id][code] for code in eligible}, self.preprocess)
                     for factor_id in self.factor_ids}
        scores = {code: _score(self.tree, {factor_id: processed[factor_id][code]
                                           for factor_id in self.factor_ids}) for code in eligible}
        ranked_long = sorted(scores, key=lambda code: (-scores[code], code))
        longs = ranked_long[:self.long_count]
        remaining = set(scores) - set(longs)
        ranked_short = sorted(remaining, key=lambda code: (scores[code], code))
        shorts = ranked_short[:self.short_count]
        weights: dict[str, Decimal] = {}
        if longs:
            weights.update({code: self.long_gross / Decimal(len(longs)) for code in longs})
        if shorts:
            weights.update({code: -self.short_gross / Decimal(len(shorts)) for code in shorts})
        return StrategyDecision(TargetPortfolio.from_weights(weights), new_state,
                                scores, tuple(ranked_long), dropped, self.preprocess,
                                self.missing_policy, raw, processed)


def _turnover(current: Mapping[str, Decimal], target: Mapping[str, Decimal]) -> Decimal:
    return sum((abs(target.get(code, Decimal(0)) - current.get(code, Decimal(0)))
                for code in set(current) | set(target)), Decimal(0))


class RiskPolicy:
    """Project targets through position/gross/net/cash/turnover constraints."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.max_position = finite_decimal(config["max_position_weight"], "max_position_weight")
        self.max_gross = finite_decimal(config["max_gross_exposure"], "max_gross_exposure")
        self.min_net = finite_decimal(config.get("min_net_exposure", -1), "min_net_exposure")
        self.max_net = finite_decimal(config.get("max_net_exposure", 1), "max_net_exposure")
        self.turnover_budget = finite_decimal(config.get("turnover_budget", 2), "turnover_budget")
        self.allow_short = config.get("allow_short", False)
        if (self.max_position <= 0 or self.max_position > 1 or self.max_gross <= 0
                or self.min_net < -1 or self.max_net > 1
                or self.min_net > self.max_net or self.turnover_budget < 0
                or not isinstance(self.allow_short, bool)):
            raise StrategyError("invalid risk constraints")

    def _valid(self, target: TargetPortfolio) -> bool:
        return (all(abs(item.weight) <= self.max_position for item in target.positions)
                and target.gross <= self.max_gross
                and self.min_net <= target.net <= self.max_net
                and target.cash_residual >= 0
                and (self.allow_short or target.short_gross == 0))

    def apply(self, raw: TargetPortfolio | None,
              current: TargetPortfolio) -> RiskDecision:
        """Return raw/allowed targets and exact reasons without mutating either."""
        if not isinstance(current, TargetPortfolio):
            raise StrategyError("current must be TargetPortfolio")
        current_valid = self._valid(current)
        reasons: list[str] = [] if current_valid else ["current_limit_breach"]
        if raw is None:
            return RiskDecision(None, None, tuple((*reasons, "no_rebalance")), self.turnover_budget,
                                Decimal(0), Decimal(0), current.cash_residual)
        if not isinstance(raw, TargetPortfolio):
            raise StrategyError("raw target must be TargetPortfolio or None")
        proposed = raw.weights()
        if not self.allow_short and any(weight < 0 for weight in proposed.values()):
            proposed = {code: weight for code, weight in proposed.items() if weight > 0}
            reasons.append("short_disabled")
        clipped = {code: max(-self.max_position, min(self.max_position, weight))
                   for code, weight in proposed.items()}
        if clipped != proposed:
            reasons.append("position_cap")
        proposed = clipped
        positive = sum((weight for weight in proposed.values() if weight > 0), Decimal(0))
        if positive > 1:
            proposed = {code: weight / positive if weight > 0 else weight
                        for code, weight in proposed.items()}
            reasons.append("cash_residual")
        gross = sum((abs(weight) for weight in proposed.values()), Decimal(0))
        if gross > self.max_gross:
            scale = self.max_gross / gross
            proposed = {code: weight * scale for code, weight in proposed.items()}
            reasons.append("gross_cap")
        projected = TargetPortfolio.from_weights(proposed)
        if not self.min_net <= projected.net <= self.max_net:
            reasons.append("net_limit_reject")
            if current_valid:
                projected = current
            else:
                reasons.append("no_feasible_projection")
                return RiskDecision(raw, None, tuple(reasons), self.turnover_budget,
                                    _turnover(current.weights(), raw.weights()),
                                    Decimal(0), current.cash_residual)
        requested = _turnover(current.weights(), raw.weights())
        desired = _turnover(current.weights(), projected.weights())
        if desired > self.turnover_budget:
            ratio = self.turnover_budget / desired
            old, new = current.weights(), projected.weights()
            proposed = {code: old.get(code, Decimal(0)) +
                        (new.get(code, Decimal(0)) - old.get(code, Decimal(0))) * ratio
                        for code in set(old) | set(new)}
            projected = TargetPortfolio.from_weights(proposed)
            reasons.append("turnover_budget")
        if not self._valid(projected):
            reasons.append("recovery_blocked_by_turnover_budget" if not current_valid
                           else "no_feasible_projection")
            return RiskDecision(raw, None, tuple(reasons), self.turnover_budget,
                                requested, Decimal(0), current.cash_residual)
        allowed_turnover = _turnover(current.weights(), projected.weights())
        if allowed_turnover > self.turnover_budget:
            # Decimal division can round a three-way interpolation one unit
            # above budget. Remove the excess from one moving position.
            correction = allowed_turnover - self.turnover_budget
            adjusted = projected.weights()
            before = current.weights()
            for code in sorted(adjusted):
                movement = adjusted[code] - before.get(code, Decimal(0))
                if movement:
                    step = min(abs(movement), correction)
                    adjusted[code] -= step if movement > 0 else -step
                    correction -= step
                    if correction <= 0:
                        break
            projected = TargetPortfolio.from_weights(adjusted)
            allowed_turnover = _turnover(before, projected.weights())
            if allowed_turnover > self.turnover_budget or not self._valid(projected):
                reasons.append("turnover_rounding_block")
                return RiskDecision(raw, None, tuple(reasons), self.turnover_budget,
                                    requested, Decimal(0), current.cash_residual)
            reasons.append("turnover_rounding_adjusted")
        if raw.positions == () and projected.positions:
            reasons.append("liquidation_incomplete")
        return RiskDecision(raw, projected, tuple(reasons), self.turnover_budget,
                            requested, allowed_turnover, projected.cash_residual)
