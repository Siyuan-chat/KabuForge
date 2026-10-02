"""Exercise the published extension tutorial against the real package boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from kabuforge.api import FactorContext, FactorResult, FactorSpec, StrategySpec, StrategyState
from kabuforge.factors import FactorContractError
from kabuforge.models import StrategyError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "extension_demo.py"
_loader = importlib.util.spec_from_file_location("kabuforge_extension_tutorial", EXAMPLE)
assert _loader is not None and _loader.loader is not None
example = importlib.util.module_from_spec(_loader)
_loader.loader.exec_module(example)


def context_for(snapshot=None):
    snapshot = example.synthetic_snapshot() if snapshot is None else snapshot
    raw = json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()
    frames = {name: pd.DataFrame(item["rows"], columns=item["columns"])
              for name, item in snapshot["datasets"].items()}
    return FactorContext(decision_at=example.DECISION_AT, datasets=frames,
                         data_snapshot_hash=hashlib.sha256(raw).hexdigest())


class ExtensionExampleTests(unittest.TestCase):
    def setUp(self):
        self.spec = FactorSpec.from_config(example.factor_config())

    def decision(self, context, *, config=None, state=None, identity="test", rebalance=True):
        result = example.compute_price_change(self.spec, context)
        strategy = example.PositiveScoreStrategy(config or example.strategy_config(), (self.spec.id,))
        return strategy.decide(results={self.spec.id: result}, context=context,
                               state=state or StrategyState(), decision_identity=identity,
                               rebalance=rebalance)

    def test_application_pipeline_is_offline_and_plans_only(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ):
            root = example.write_example(Path(temp) / "demo")
            result = example.run_example(root)
            self.assertEqual(result.strategy_implementation_id, example.STRATEGY_IMPLEMENTATION)
            self.assertEqual(result.decision.target.weights(), {"SYN_A": 1})
            self.assertEqual(result.risk.allowed.weights(), {"SYN_A": 0.5})
            self.assertIn("position_cap", result.risk.reasons)
            self.assertTrue(result.plan.intents)
            self.assertEqual({intent.code for intent in result.plan.intents}, {"SYN_A"})
            self.assertFalse(example.summarize(result)["orders_submitted"])
            self.assertFalse((root / "output").exists())

    def test_cli_command(self):
        completed = subprocess.run([sys.executable, str(EXAMPLE)], cwd=ROOT,
                                   capture_output=True, text=True, timeout=60, check=True)
        output = json.loads(completed.stdout)
        self.assertTrue(output["synthetic"])
        self.assertFalse(output["orders_submitted"])
        self.assertGreater(output["planned_order_count"], 0)

    def test_input_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = example.write_example(Path(temp) / "demo")
            before = (root / "factor.json").read_bytes()
            with self.assertRaises(FileExistsError):
                example.write_example(root)
            self.assertEqual((root / "factor.json").read_bytes(), before)

    def test_future_price_is_invisible(self):
        full = example.synthetic_snapshot()
        historical = example.synthetic_snapshot()
        historical["datasets"]["prices"]["rows"].pop()
        first = example.compute_price_change(self.spec, context_for(full))
        second = example.compute_price_change(self.spec, context_for(historical))
        pd.testing.assert_frame_equal(first.minimal, second.minimal)
        values = first.minimal.set_index("code")["factor_value"]
        self.assertAlmostEqual(values["SYN_A"], 0.10)
        self.assertAlmostEqual(values["SYN_B"], -0.05)

    def test_naive_availability_fails_closed(self):
        snapshot = example.synthetic_snapshot()
        snapshot["datasets"]["prices"]["rows"][0][3] = "2024-04-26T15:00:00"
        with self.assertRaises(FactorContractError):
            context_for(snapshot)

    def test_invalid_parameters_and_lookback_are_rejected(self):
        for periods in (True, 0, 253, "1"):
            config = example.factor_config()
            config["implementation"]["parameters"]["periods"] = periods
            with self.subTest(periods=periods), self.assertRaises(FactorContractError):
                example.validate_price_change(FactorSpec.from_config(config))
        config = example.factor_config()
        config["lookback"] = 1
        with self.assertRaisesRegex(FactorContractError, "lookback"):
            example.validate_price_change(FactorSpec.from_config(config))
        config = example.factor_config()
        config["implementation"]["parameters"]["extra"] = 1
        with self.assertRaises(FactorContractError):
            example.validate_price_change(FactorSpec.from_config(config))

    def test_duplicate_or_invalid_visible_prices_are_rejected(self):
        snapshot = example.synthetic_snapshot()
        snapshot["datasets"]["prices"]["rows"].append(
            list(snapshot["datasets"]["prices"]["rows"][0]))
        with self.assertRaisesRegex(FactorContractError, "duplicate"):
            example.compute_price_change(self.spec, context_for(snapshot))
        for value in (0, -1, None, "not-a-price", True):
            snapshot = example.synthetic_snapshot()
            snapshot["datasets"]["prices"]["rows"][0][2] = value
            with self.subTest(value=value), self.assertRaises(FactorContractError):
                example.compute_price_change(self.spec, context_for(snapshot))

    def test_missing_history_is_explicit(self):
        snapshot = example.synthetic_snapshot()
        snapshot["datasets"]["prices"]["rows"].pop(2)
        context = context_for(snapshot)
        result = example.compute_price_change(self.spec, context)
        self.assertTrue(pd.isna(result.minimal.set_index("code").loc["SYN_B", "factor_value"]))
        with self.assertRaisesRegex(StrategyError, "missing"):
            self.decision(context)
        config = example.strategy_config()
        config["portfolio"]["parameters"]["missing_policy"] = "drop"
        decision = self.decision(context, config=config)
        self.assertEqual(decision.dropped_codes, ("SYN_B",))
        self.assertEqual(decision.target.weights(), {"SYN_A": 1})

    def test_no_rebalance_and_liquidation_are_distinct(self):
        state = StrategyState(regime="example", cooldown_until="2024-05-02",
                              transition_state={"counter": 2})
        held = self.decision(context_for(), state=state, identity="hold", rebalance=False)
        self.assertIsNone(held.target)
        self.assertEqual(held.state.last_decision_identity, "hold")
        self.assertEqual(held.state.regime, state.regime)
        self.assertEqual(held.state.to_json(), StrategyState.from_json(held.state.to_json()).to_json())
        snapshot = example.synthetic_snapshot()
        snapshot["datasets"]["prices"]["rows"][1][2] = 90
        cash = self.decision(context_for(snapshot), identity="cash")
        self.assertIsNotNone(cash.target)
        self.assertEqual(cash.target.positions, ())
        self.assertTrue(cash.scores)

    def test_duplicate_decision_identity_is_rejected(self):
        first = self.decision(context_for(), identity="same")
        with self.assertRaisesRegex(StrategyError, "already been processed"):
            self.decision(context_for(), state=first.state, identity="same")

    def test_invalid_results_and_future_signal_are_rejected(self):
        context = context_for()
        result = example.compute_price_change(self.spec, context)
        bad = result.minimal
        bad.loc[0, "factor_value"] = float("inf")
        with self.assertRaises(FactorContractError):
            FactorResult(bad, result.detail, result.summary)
        duplicated = pd.concat([result.minimal, result.minimal.iloc[:1]], ignore_index=True)
        with self.assertRaises(FactorContractError):
            FactorResult(duplicated, result.detail, result.summary)
        future = result.minimal
        future["signal_date"] = "2024-05-02"
        future_result = FactorResult(future, result.detail, result.summary, binding_id=self.spec.id)
        strategy = example.PositiveScoreStrategy(example.strategy_config(), (self.spec.id,))
        with self.assertRaisesRegex(StrategyError, "future"):
            strategy.decide(results={self.spec.id: future_result}, context=context,
                            state=StrategyState(), decision_identity="future")

    def test_registration_is_explicit_and_validated(self):
        app = example.build_service()
        with self.assertRaisesRegex(ValueError, "already registered"):
            app.register_factor(example.FACTOR_IMPLEMENTATION, "1",
                                example.compute_price_change, example.validate_price_change)
        with self.assertRaisesRegex(TypeError, "validator"):
            app.register_factor("example.invalid", "1", example.compute_price_change, None)
        with self.assertRaisesRegex(ValueError, "already registered"):
            app.strategy_registry.register(StrategySpec(example.STRATEGY_IMPLEMENTATION, "1"),
                                           example.PositiveScoreStrategy)
        with self.assertRaisesRegex(ValueError, "unknown"):
            app.registry.require("missing", "1")
        with self.assertRaisesRegex(ValueError, "unknown"):
            app.strategy_registry.require(StrategySpec("missing", "1"))

    def test_bound_input_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = example.write_example(Path(temp) / "demo")
            app = example.build_service()
            resolved = app.validate(root / "run.json")
            with (root / "snapshot.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "changed"):
                example._read_bound_json(root / "snapshot.json", resolved.data_snapshot_hash)

    def test_documented_json_matches_executable_example(self):
        for locale in ("en_US", "zh_CN", "ja_JP"):
            for name, expected in (
                ("FACTOR_API.md", [example.factor_config()]),
                ("STRATEGY_API.md", [example.strategy_config(), example.run_config()]),
            ):
                with self.subTest(locale=locale, document=name):
                    text = (ROOT / "docs" / locale / name).read_text(encoding="utf-8")
                    blocks = re.findall(r"```json\n(.*?)```", text, re.S)
                    self.assertEqual([json.loads(block) for block in blocks], expected)


if __name__ == "__main__":
    unittest.main()
