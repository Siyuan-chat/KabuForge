"""Synthetic strategy and risk checks; no market or account data."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from framework_v2.config import load_config
from framework_v2.factors import FactorContext, FactorResult
from framework_v2.models import StrategyError, StrategyState, TargetPortfolio, TargetPosition
from framework_v2.strategy import CompositeFactorStrategy, RiskPolicy


def context(codes: tuple[str, ...] = ("1001", "1002", "1003")) -> FactorContext:
    universe = pd.DataFrame({
        "asof_date": ["2025-01-06"] * len(codes), "code": list(codes),
        "in_universe": [True] * len(codes),
        "available_at": ["2025-01-07T09:00:00+09:00"] * len(codes),
    })
    return FactorContext(decision_at="2025-01-07T10:00:00+09:00",
                         datasets={"universe": universe}, data_snapshot_hash="synthetic")


def factor(name: str, codes: tuple[str, ...], values: tuple[float, ...]) -> FactorResult:
    minimal = pd.DataFrame({
        "code": list(codes), "factor_name": [name] * len(codes),
        "factor_value": list(values), "signal_date": ["2025-01-06"] * len(codes),
        "data_end_date": ["2025-01-06"] * len(codes),
        "rebalance_date": ["2025-01-07"] * len(codes),
    })
    return FactorResult(minimal, pd.DataFrame(), {}, factor_id=name)


def config(*, formula: str = "a + b", parameters: dict | None = None,
           construction: str = "equal_weight") -> dict:
    return {
        "kind": "strategy", "scoring": {"formula": formula},
        "portfolio": {"construction": construction, "parameters": parameters or {}},
    }


def results(a=(3.0, 2.0, 1.0), b=(0.0, 0.0, 0.0)) -> dict[str, FactorResult]:
    codes = ("1001", "1002", "1003")
    return {"a": factor("a", codes, a), "b": factor("b", codes, b)}


class StrategyTests(unittest.TestCase):
    def test_none_vs_empty_target_and_partial_liquidation(self) -> None:
        strategy = CompositeFactorStrategy(config(), factor_ids=("a", "b"))
        none_target, state = strategy.decide(results=results(), context=context(),
                                              state=StrategyState(), decision_identity="d1",
                                              rebalance=False)
        self.assertIsNone(none_target)
        self.assertEqual(state.last_decision_identity, "d1")
        empty_target, _ = strategy.decide(results=results(), context=context(()),
                                           state=state, decision_identity="d2")
        self.assertEqual(empty_target.positions, ())
        policy = RiskPolicy({"max_position_weight": 1, "max_gross_exposure": 1,
                             "turnover_budget": 0.2})
        current = TargetPortfolio.from_weights({"1001": Decimal("0.5")})
        unchanged = policy.apply(None, current)
        self.assertIsNone(unchanged.allowed)
        partial = policy.apply(empty_target, current)
        self.assertEqual(partial.allowed.weights()["1001"], Decimal("0.3"))
        self.assertIn("liquidation_incomplete", partial.reasons)
        self.assertEqual(partial.allowed_turnover, Decimal("0.2"))

    def test_tie_break_and_input_unchanged(self) -> None:
        source = results(a=(1, 1, 1))
        before = source["a"].minimal
        target, _ = CompositeFactorStrategy(
            config(parameters={"top_n": 2}), factor_ids=("a", "b")
        ).decide(results=source, context=context(), state=StrategyState(), decision_identity="tie")
        self.assertEqual(list(target.weights()), ["1001", "1002"])
        self.assertEqual(target.weights()["1001"], Decimal("0.5"))
        pd.testing.assert_frame_equal(source["a"].minimal, before)

    def test_missing_policy_reject_or_drop(self) -> None:
        source = results(a=(3, np.nan, 1))
        reject = CompositeFactorStrategy(config(), factor_ids=("a", "b"))
        with self.assertRaisesRegex(StrategyError, "missing factor"):
            reject.decide(results=source, context=context(), state=StrategyState(),
                          decision_identity="reject")
        drop = CompositeFactorStrategy(
            config(parameters={"missing_policy": "drop", "top_n": 3}), factor_ids=("a", "b")
        )
        target, _ = drop.decide(results=source, context=context(), state=StrategyState(),
                                decision_identity="drop")
        self.assertEqual(set(target.weights()), {"1001", "1003"})
        audit = drop.decide_with_audit(results=source, context=context(),
                                       state=StrategyState(), decision_identity="audit")
        self.assertEqual(audit.dropped_codes, ("1002",))
        self.assertEqual(audit.ranked_codes, ("1001", "1003"))
        self.assertEqual(audit.preprocess, "none")
        self.assertEqual(audit.missing_policy, "drop")
        self.assertEqual(audit.factor_inputs["a"]["1001"], Decimal("3.0"))
        self.assertEqual(audit.scores["1001"], Decimal("3.0"))
        with self.assertRaises(TypeError):
            audit.scores["1001"] = Decimal(999)

    def test_forbidden_formula_division_and_nonfinite(self) -> None:
        for formula in ("a.__class__", "__import__('os')", "a ** 2"):
            with self.subTest(formula=formula), self.assertRaises(StrategyError):
                CompositeFactorStrategy(config(formula=formula), factor_ids=("a", "b"))
        zero = CompositeFactorStrategy(config(formula="a / b"), factor_ids=("a", "b"))
        with self.assertRaisesRegex(StrategyError, "zero-divisor"):
            zero.decide(results=results(), context=context(), state=StrategyState(),
                        decision_identity="zero")
        with self.assertRaises(StrategyError):
            TargetPosition("1001", Decimal("Infinity"))
        bad = results()
        future = bad["a"].minimal
        future["data_end_date"] = ["2025-01-07 11:00:00"] * len(future)
        bad["a"] = FactorResult(future, pd.DataFrame(), {}, factor_id="a")
        with self.assertRaisesRegex(StrategyError, "future"):
            CompositeFactorStrategy(config(), factor_ids=("a", "b")).decide(
                results=bad, context=context(), state=StrategyState(),
                decision_identity="future-result")

    def test_long_short_gross_net_and_risk_caps(self) -> None:
        strategy = CompositeFactorStrategy(
            config(parameters={"long_count": 1, "short_count": 1,
                               "long_gross": 0.6, "short_gross": 0.2}),
            factor_ids=("a", "b"),
        )
        raw, _ = strategy.decide(results=results(), context=context(),
                                 state=StrategyState(), decision_identity="ls")
        self.assertEqual(raw.weights(), {"1001": Decimal("0.6"), "1003": Decimal("-0.2")})
        self.assertEqual(raw.gross, Decimal("0.8"))
        self.assertEqual(raw.net, Decimal("0.4"))
        policy = RiskPolicy({"max_position_weight": 0.4, "max_gross_exposure": 0.5,
                             "allow_short": True, "turnover_budget": 2})
        decision = policy.apply(raw, TargetPortfolio(()))
        self.assertEqual(decision.raw, raw)
        self.assertLessEqual(decision.allowed.gross, Decimal("0.5"))
        self.assertLessEqual(max(abs(w) for w in decision.allowed.weights().values()), Decimal("0.4"))
        self.assertIn("position_cap", decision.reasons)
        self.assertIn("gross_cap", decision.reasons)

    def test_net_rejection_cash_and_turnover_trace(self) -> None:
        current = TargetPortfolio(())
        raw = TargetPortfolio.from_weights({"1001": 0.8, "1002": -0.1})
        policy = RiskPolicy({"max_position_weight": 1, "max_gross_exposure": 2,
                             "min_net_exposure": -0.2, "max_net_exposure": 0.3,
                             "allow_short": True, "turnover_budget": 0.5})
        rejected = policy.apply(raw, current)
        self.assertEqual(rejected.allowed.positions, ())
        self.assertIn("net_limit_reject", rejected.reasons)
        raw_cash = TargetPortfolio.from_weights({"1001": 0.8, "1002": 0.8})
        policy_cash = RiskPolicy({"max_position_weight": 1, "max_gross_exposure": 2,
                                  "turnover_budget": 0.5})
        decision = policy_cash.apply(raw_cash, current)
        self.assertGreater(decision.requested_turnover, decision.allowed_turnover)
        self.assertLessEqual(decision.allowed_turnover, Decimal("0.5"))
        self.assertGreaterEqual(decision.cash_residual, 0)
        self.assertIn("cash_residual", decision.reasons)
        self.assertIn("turnover_budget", decision.reasons)

    def test_existing_limit_breach_can_recover_or_blocks_with_reason(self) -> None:
        current = TargetPortfolio.from_weights({"1001": 0.8})
        policy = RiskPolicy({"max_position_weight": 0.5, "max_gross_exposure": 1,
                             "turnover_budget": 0.4})
        no_action = policy.apply(None, current)
        self.assertIsNone(no_action.allowed)
        self.assertIn("current_limit_breach", no_action.reasons)
        empty = policy.apply(TargetPortfolio(()), current)
        self.assertEqual(empty.allowed.weights(), {"1001": Decimal("0.4")})
        self.assertIn("liquidation_incomplete", empty.reasons)
        reduced = policy.apply(TargetPortfolio.from_weights({"1001": 0.4}), current)
        self.assertEqual(reduced.allowed.weights(), {"1001": Decimal("0.4")})
        blocked = RiskPolicy({"max_position_weight": 0.5, "max_gross_exposure": 1,
                              "turnover_budget": 0.2}).apply(TargetPortfolio(()), current)
        self.assertIsNone(blocked.allowed)
        self.assertIn("recovery_blocked_by_turnover_budget", blocked.reasons)

    def test_three_way_decimal_turnover_never_exceeds_tiny_budget(self) -> None:
        raw = TargetPortfolio.from_weights({"a": Decimal(1) / 3,
                                            "b": Decimal(1) / 3,
                                            "c": Decimal(1) / 3})
        for budget in (Decimal("0.1"), Decimal("0.000000000000000000000000001")):
            with self.subTest(budget=budget):
                policy = RiskPolicy({"max_position_weight": 1, "max_gross_exposure": 1,
                                     "turnover_budget": budget})
                decision = policy.apply(raw, TargetPortfolio(()))
                self.assertIsNotNone(decision.allowed)
                self.assertLessEqual(decision.allowed_turnover, budget)

    def test_state_json_roundtrip_and_deep_freeze(self) -> None:
        source = {"phase": {"seen": ["a"]}}
        state = StrategyState("decision-1", "risk_off", "2025-01-08T09:00:00+09:00", source)
        source["phase"]["seen"].append("b")
        self.assertEqual(state.transition_state["phase"]["seen"], ("a",))
        self.assertEqual(StrategyState.from_json(state.to_json()).to_json(), state.to_json())
        with self.assertRaises(StrategyError):
            StrategyState.from_json('{"regime":null,"regime":null}')

    def test_schema_rank_count_compatibility_and_unknown_parameters(self) -> None:
        full = {
            "schema_version": "1.0", "id": "s", "version": "1", "kind": "strategy",
            "universe": {"snapshot": "synthetic"}, "factors": ["f.json"],
            "scoring": {"formula": "a"},
            "portfolio": {"construction": "rank", "parameters": {"count": 2}},
            "risk": {"max_position_weight": 0.5, "max_gross_exposure": 1},
            "rebalance": {"frequency": "daily"},
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "strategy.json"
            path.write_text(json.dumps(full), encoding="utf-8")
            self.assertEqual(load_config(path)["portfolio"]["parameters"]["count"], 2)
            full["portfolio"]["parameters"]["unknown"] = 1
            path.write_text(json.dumps(full), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)
        with self.assertRaisesRegex(StrategyError, "conflicts"):
            CompositeFactorStrategy(config(parameters={"count": 1, "top_n": 2}), factor_ids=("a", "b"))


if __name__ == "__main__":
    unittest.main()
