from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from framework_v2 import price_research


def _explicit_fixture_rows():
    rows = []
    start = date(2022, 1, 3)
    for offset in range(75):
        day = (start + timedelta(days=offset)).isoformat()
        for code, phase in (("1111", 0.0), ("2222", 0.7)):
            close = 100.0 + offset * (0.21 if code == "1111" else 0.13)
            close += 2.0 * __import__("math").sin(offset / 4.0 + phase)
            rows.append({"code": code, "date": day, "open": close * 1.001,
                         "close": close, "adjustment_factor": 1.0})
    return rows


class PublicRegimeOffTests(unittest.TestCase):
    def test_none_and_exact_off_share_fingerprint_and_financial_output(self):
        rows = _explicit_fixture_rows()
        recipe = {"count": 1, "lookback": 5, "cash": 100_000.0,
                  "fee": 0.1, "frequency": "weekly"}
        identity = {"kind": "explicit_test_fixture", "pit_guarantee": False}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "fixture-manifest.json"
            manifest.write_text(json.dumps({"fixture": "synthetic-unit-test-v1"}), encoding="utf-8")
            loader = patch.object(price_research, "_load_price_research_input",
                                  return_value=(rows, identity))
            with loader:
                ordinary = price_research.preflight_price_research(manifest, recipe)
                explicit_off = price_research.preflight_price_research(
                    manifest, recipe, {"mode": "off"})
                self.assertEqual(ordinary["fingerprint"], explicit_off["fingerprint"])
                ordinary_path = price_research.run_price_research(
                    manifest, recipe, root / "run-none")
                explicit_path = price_research.run_price_research(
                    manifest, recipe, root / "run-off", regime_observer={"mode": "off"})
            ordinary_report = json.loads(ordinary_path.read_text(encoding="utf-8"))
            explicit_report = json.loads(explicit_path.read_text(encoding="utf-8"))
            self.assertEqual(ordinary_report, explicit_report)
            self.assertEqual(ordinary_report["input_source"]["kind"], "explicit_test_fixture")
            self.assertFalse(ordinary_report["input_source"]["pit_guarantee"])
            self.assertEqual(ordinary_report["regime_observer"]["mode"], "off")
            self.assertGreater(len(ordinary_report["nav"]), 1)

    def test_enabled_and_private_bridge_parameters_fail_before_loading_data(self):
        recipe = {"count": 1, "lookback": 5, "cash": 100_000.0,
                  "fee": 0.1, "frequency": "weekly"}
        invalid_observers = (
            {"mode": "observe"},
            {"mode": "off", "input_path": "private.json"},
            object(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with patch.object(price_research, "_load_price_research_input",
                              side_effect=AssertionError("invalid Regime must fail before input access")) as loader:
                for observer in invalid_observers:
                    with self.subTest(observer=repr(observer)):
                        with self.assertRaises(ValueError):
                            price_research.preflight_price_research(manifest, recipe, observer)
                for private_recipe in (
                    {**recipe, "regime_mode": "historical_reconstruction"},
                    {**recipe, "regime_observer": {"mode": "off", "bridge": "private"}},
                    {**recipe, "regime_input_sha256": "private-bridge"},
                ):
                    with self.subTest(recipe=private_recipe):
                        with self.assertRaises(ValueError):
                            price_research.preflight_price_research(manifest, private_recipe)
                loader.assert_not_called()
        self.assertNotIn("framework_v2.regime_observer", __import__("sys").modules)


if __name__ == "__main__":
    unittest.main()
