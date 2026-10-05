"""Artificial weekday-only fixtures exercise contracts; no fixture is market evidence."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import framework_v2.factor_research as factor_research_module
import framework_v2.local_cache as local_cache_module
from framework_v2.factor_research import (
    DEFAULT_RECIPE, FactorResearchError, _analyze, _build_rows, _compose,
    _stable_buckets, run_factor_research, validate_recipe,
)
from framework_v2.local_cache import load_research_bars


class FactorResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (factor_research_module, local_cache_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _frozen_manifest(self, count=92, split_factor=False, constant_factor=1.0):
        # Explicit weekday-only synthetic fixture; not an exchange calendar or alpha sample.
        first = date(2020, 8, 3)
        dates = []
        day = first
        while len(dates) < count:
            if day.weekday() < 5:
                dates.append(day.isoformat())
            day += timedelta(days=1)
        rows = []
        code_base = {"4502": 100.0, "6758": 180.0, "8306": 75.0}
        for code, base in code_base.items():
            code_n = int(code[-1])
            closes = []
            for index, day_text in enumerate(dates):
                close = base + index * (0.16 + code_n * 0.005) + np.sin(index / (3.0 + code_n)) * (1.2 + code_n * 0.1)
                closes.append(float(close))
                rows.append({"Date": day_text, "Code": code, "Open": close * (1.0 + ((index + code_n) % 5 - 2) * 0.001),
                    "High": close * 1.01, "Low": close * 0.99, "Close": close,
                    "Volume": 100000 + index,
                    "AdjustmentFactor": (0.5 if split_factor and index >= count // 2
                                          else constant_factor),
                    "AdjustmentClose": close})
        source = self.root / "bars.csv"
        frame = pd.DataFrame(rows)
        frame.to_csv(source, index=False)
        selection = load_research_bars(source, codes=list(code_base), start_date=dates[0],
            end_date=dates[-1], price_basis="raw", duplicate_policy="reject",
            known_halt_policy="reject")
        self.assertEqual(selection.coverage["duplicate_rows_removed"], 0)
        self.assertIsNone(selection.coverage["verified_halt_exclusion"])
        return selection.freeze(self.root / "frozen-input"), selection, dates, rows

    def test_default_contract_is_fixed_and_dynamic_execution_fields_are_rejected(self):
        normalized = validate_recipe()
        self.assertEqual(normalized["label"]["horizon_sessions"], 5)
        self.assertEqual(normalized["minimum_cross_section"], 3)
        self.assertEqual(normalized["quantiles"], 3)
        self.assertEqual(normalized["composition"]["weights"],
                         {"price_momentum_20": 0.5, "price_momentum_60": 0.5})
        with self.assertRaisesRegex(FactorResearchError, "exactly"):
            validate_recipe({**DEFAULT_RECIPE, "expression": "__import__('os')"})
        with self.assertRaisesRegex(FactorResearchError, "unsupported factor"):
            validate_recipe({**DEFAULT_RECIPE,
                "factors": [{"id": "__import__", "windows": [5]}]})
        bad = {**DEFAULT_RECIPE, "composition": {**DEFAULT_RECIPE["composition"],
                                                   "weights": {"price_momentum_20": float("nan")}}}
        with self.assertRaisesRegex(FactorResearchError, "finite"):
            validate_recipe(bad)

    def test_frozen_policies_d1_features_forward_labels_and_separate_artifacts(self):
        manifest, selected, dates, _ = self._frozen_manifest()
        out = self.root / "run-one"
        original_build = _build_rows

        def require_preregistered(*args, **kwargs):
            contract = json.loads((out / "contract.json").read_text(encoding="utf-8"))
            self.assertEqual(contract["status"], "PREREGISTERED")
            return original_build(*args, **kwargs)

        with patch("framework_v2.factor_research._build_rows", side_effect=require_preregistered):
            report = run_factor_research(manifest, out)
        self.assertEqual(report["readiness"], "RESEARCH-ONLY")
        self.assertEqual(report["input_identity"]["selection"]["duplicate_policy"], "reject")
        self.assertEqual(report["input_identity"]["selection"]["known_halt_policy"], "reject")
        self.assertTrue(report["input_identity"]["corporate_action_compatibility"][
            "native_price_research_compatible"])
        frozen_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(report["input_identity"]["coverage"], frozen_manifest["coverage"])
        self.assertEqual(report["input_identity"]["revalidated_coverage"]["rows"], 92 * 3)
        self.assertFalse(report["input_identity"]["pit_guarantee"])
        feature_doc = json.loads((out / "feature_rows.json").read_text(encoding="utf-8"))
        evaluation = json.loads((out / "evaluation_panel.json").read_text(encoding="utf-8"))
        self.assertFalse(feature_doc["contains_forward_labels"])
        self.assertTrue(all("forward_return" not in row and "label_end_date" not in row
                            for row in feature_doc["rows"]))
        self.assertTrue(all("forward_return" in row for row in evaluation["rows"]))

        example = next(row for row in evaluation["rows"]
                       if row["code"] == "4502" and row["signal_date"] == dates[65])
        expected_source = selected.bars.loc[selected.bars["code"].eq("4502")].reset_index(drop=True)
        at = expected_source.index[expected_source["date"].eq(dates[65])][0]
        self.assertEqual(example["d1_cutoff_date"], dates[65])
        self.assertEqual(example["execution_date"], dates[66])
        self.assertEqual(example["label_start_date"], dates[66])
        self.assertEqual(example["label_end_date"], dates[71])
        expected_label = float(expected_source.loc[at + 6, "open"] / expected_source.loc[at + 1, "open"] - 1)
        self.assertAlmostEqual(example["forward_return"], expected_label, places=12)
        expected_momentum = float(expected_source.loc[at, "selected_price"] /
                                  expected_source.loc[at - 20, "selected_price"] - 1)
        self.assertAlmostEqual(example["price_momentum_20"], expected_momentum, places=12)
        terminal = [row for row in evaluation["rows"] if row["signal_date"] == dates[-1]]
        self.assertEqual(len(terminal), 3)
        self.assertTrue(all(row["forward_return"] is None and row["label_status"] == "no_next_observed_open"
                            for row in terminal))
        self.assertTrue(report["analysis"]["small_universe"])
        self.assertTrue(report["analysis"]["factors"]["price_momentum_20"]["summary"]["small_cross_section_warning"])

        # Later prices may change the labels, but never the feature vector at an earlier D-1 cutoff.
        changed = selected.bars.copy(deep=True)
        group_index = changed.index[changed["code"].eq("4502")].tolist()
        signal_index = next(index for index in group_index if changed.loc[index, "date"] == dates[65])
        for index in group_index:
            if changed.loc[index, "date"] > dates[65]:
                changed.loc[index, "selected_price"] *= 7.0
        before_rows = original_build(selected.bars, validate_recipe())
        after_rows = original_build(changed, validate_recipe())
        before = next(row for row in before_rows if row["code"] == "4502" and row["signal_date"] == dates[65])
        after = next(row for row in after_rows if row["code"] == "4502" and row["signal_date"] == dates[65])
        self.assertEqual(before["price_momentum_20"], after["price_momentum_20"])

        incomplete = selected.bars.drop(index=selected.bars.index[
            selected.bars["code"].eq("4502")][20]).reset_index(drop=True)
        with self.assertRaisesRegex(FactorResearchError, "complete common observed-date calendar"):
            _build_rows(incomplete, validate_recipe())

    def test_feature_and_evaluation_artifacts_reproduce_under_same_identity(self):
        manifest, _, _, _ = self._frozen_manifest()
        first = run_factor_research(manifest, self.root / "run-a")
        second = run_factor_research(manifest, self.root / "run-b")
        self.assertEqual(first["recipe_sha256"], second["recipe_sha256"])
        self.assertEqual(first["input_identity"]["pinned_identity_sha256"],
                         second["input_identity"]["pinned_identity_sha256"])
        self.assertEqual(first["artifacts"]["feature_rows_sha256"],
                         second["artifacts"]["feature_rows_sha256"])
        self.assertEqual(first["artifacts"]["evaluation_panel_sha256"],
                         second["artifacts"]["evaluation_panel_sha256"])
        self.assertEqual(len(first["provider_identity"]["source_sha256"]), 64)
        self.assertEqual(len(first["provider_identity"]["local_cache_loader_source_sha256"]), 64)
        with self.assertRaisesRegex(FactorResearchError, "new directory"):
            run_factor_research(manifest, self.root / "run-a")

    def test_adjusted_feature_input_is_rejected_until_label_basis_is_supported(self):
        manifest, _, _, _ = self._frozen_manifest()
        edited = self.root / "adjusted-request.json"
        frozen = json.loads(manifest.read_text(encoding="utf-8"))
        frozen["selection"]["price_basis"] = "adjusted"
        edited.write_text(json.dumps(frozen), encoding="utf-8")
        with self.assertRaisesRegex(FactorResearchError, "raw price basis"):
            run_factor_research(edited, self.root / "adjusted-run")
        self.assertFalse((self.root / "adjusted-run").exists())

    def test_changing_split_factor_rejected_for_raw_open_labels(self):
        manifest, _, _, _ = self._frozen_manifest(split_factor=True)
        with self.assertRaisesRegex(FactorResearchError, "changing adjustment_factor"):
            run_factor_research(manifest, self.root / "split-run")
        self.assertFalse((self.root / "split-run").exists())

    def test_constant_nonunit_adjustment_factor_is_marked_not_native_compatible(self):
        manifest, _, _, _ = self._frozen_manifest(constant_factor=0.5)
        report = run_factor_research(manifest, self.root / "factor-only-run")
        compatibility = report["input_identity"]["corporate_action_compatibility"]
        self.assertFalse(compatibility["native_price_research_compatible"])
        self.assertIn("not Native", compatibility["statement"])

    def test_ties_are_deterministic_and_constant_factors_have_no_information(self):
        tied = [{"code": code, "x": 1.0} for code in ("8306", "4502", "6758")]
        first, ties, split = _stable_buckets(tied, "x", 3)
        second, _, _ = _stable_buckets(list(reversed(tied)), "x", 3)
        self.assertEqual(first, second)
        self.assertEqual(ties["tie_group_count"], 1)
        self.assertEqual(ties["tied_observation_count"], 3)
        self.assertEqual(ties["tied_pair_count"], 3)
        self.assertTrue(split)
        rows = [{"signal_date": "2024-01-01", "code": code, "x": 1.0,
                 "composite_score": 1.0, "forward_return": i / 100.0,
                 "label_status": "available"}
                for i, code in enumerate(("4502", "6758", "8306"))]
        recipe = validate_recipe()
        result = _analyze(rows, ["x"], recipe, ["4502", "6758", "8306"])
        metric = result["factors"]["x"]["daily"][0]
        self.assertEqual(metric["status"], "constant_factor_no_information")
        self.assertTrue(metric["quantiles_are_deterministic_display_only"])
        self.assertTrue(all(item["mean_forward_return"] is None
                            for item in metric["quantile_returns"]))

    def test_cross_section_floor_and_missing_component_policies_are_explicit(self):
        rows = [{"code": "4502", "signal_date": "2024-01-01", "x": 1.0, "y": 1.0},
                {"code": "6758", "signal_date": "2024-01-01", "x": 2.0, "y": None},
                {"code": "8306", "signal_date": "2024-01-01", "x": 3.0, "y": 3.0}]
        drop_recipe = validate_recipe({**DEFAULT_RECIPE,
            "factors": [{"id": "price_momentum", "windows": [2]}, {"id": "ma_distance", "windows": [2]}],
            "composition": {"normalization": "rank", "missing_policy": "complete_case",
                            "weights": {"price_momentum_2": 1.0, "ma_distance_2": 1.0}}})
        # Exercise composition directly with the recipe's generated feature names.
        composition_rows = [{"code": item["code"], "signal_date": item["signal_date"],
                             "price_momentum_2": item["x"], "ma_distance_2": item["y"]} for item in rows]
        _compose(composition_rows, drop_recipe)
        self.assertIsNone(composition_rows[1]["composite_score"])
        neutral_recipe = validate_recipe({**drop_recipe,
            "composition": {**drop_recipe["composition"], "missing_policy": "neutral_zero"}})
        neutral_rows = [{"code": item["code"], "signal_date": item["signal_date"],
                         "price_momentum_2": item["x"], "ma_distance_2": item["y"]} for item in rows]
        _compose(neutral_rows, neutral_recipe)
        self.assertIsNotNone(neutral_rows[1]["composite_score"])
        self.assertEqual(neutral_rows[1]["composite_status"], "neutral_zero_missing")

        sparse = [{"signal_date": "2024-01-02", "code": code, "x": value,
                   "composite_score": value, "forward_return": 0.01, "label_status": "available"}
                  for code, value in (("4502", 1.0), ("6758", 2.0))]
        report = _analyze(sparse, ["x"], validate_recipe(), ["4502", "6758", "8306"])
        daily = report["factors"]["x"]["daily"][0]
        self.assertIsNone(daily["ic"])
        self.assertEqual(daily["status"], "insufficient_feature_cross_section")
        self.assertEqual(report["factors"]["x"]["turnover"][0]["status"], "no_valid_current_top_bucket")

    def test_zero_weight_missing_component_does_not_block_and_huge_weights_normalize_safely(self):
        recipe = validate_recipe({**DEFAULT_RECIPE,
            "factors": [{"id": "price_momentum", "windows": [2]},
                        {"id": "ma_distance", "windows": [2]}],
            "composition": {"normalization": "rank", "missing_policy": "complete_case",
                            "weights": {"price_momentum_2": 1e308, "ma_distance_2": 0.0}}})
        rows = [{"signal_date": "2024-01-01", "code": code,
                 "price_momentum_2": value, "ma_distance_2": None}
                for code, value in (("4502", 1.0), ("6758", 2.0), ("8306", 3.0))]
        _compose(rows, recipe)
        self.assertTrue(all(row["composite_score"] is not None for row in rows))
        self.assertTrue(all(np.isfinite(row["composite_score"]) for row in rows))

        both_active = validate_recipe({**recipe,
            "composition": {**recipe["composition"],
                            "weights": {"price_momentum_2": 1e308, "ma_distance_2": 1e308}}})
        full_rows = [{**row, "ma_distance_2": float(4 - index)}
                     for index, row in enumerate(rows)]
        _compose(full_rows, both_active)
        self.assertTrue(all(np.isfinite(row["composite_score"]) for row in full_rows))

    def test_icir_is_nonannualized_mean_over_sample_std_and_warns_about_overlap(self):
        rows = []
        returns_by_day = ([0.0, 1.0, 2.0], [2.0, 1.0, 0.0],
                          [1.0, 3.0, 1.0], [0.0, 1.0, 2.0])
        for day_index, returns in enumerate(returns_by_day):
            for code, score, forward_return in zip(("4502", "6758", "8306"),
                                                   (1.0, 2.0, 3.0), returns):
                rows.append({"signal_date": f"2024-01-0{day_index + 1}", "code": code,
                    "x": score, "composite_score": score, "forward_return": forward_return,
                    "label_status": "available"})
        summary = _analyze(rows, ["x"], validate_recipe(), ["4502", "6758", "8306"])[
            "factors"]["x"]["summary"]
        daily_ic = [row["ic"] for row in _analyze(
            rows, ["x"], validate_recipe(), ["4502", "6758", "8306"]
        )["factors"]["x"]["daily"] if row["ic"] is not None]
        expected = float(np.mean(daily_ic) / np.std(daily_ic, ddof=1))
        self.assertAlmostEqual(summary["descriptive_icir"], expected)
        self.assertNotAlmostEqual(summary["descriptive_icir"], expected * np.sqrt(len(daily_ic)))
        self.assertIn("nonannualized", summary["descriptive_icir_definition"])
        self.assertIn("labels overlap", summary["descriptive_icir_definition"])

    def test_extreme_finite_prices_fail_closed_on_feature_or_forward_label_overflow(self):
        recipe = validate_recipe({**DEFAULT_RECIPE,
            "label": {"horizon_sessions": 1},
            "factors": [{"id": "price_momentum", "windows": [2]}],
            "composition": {"normalization": "rank", "missing_policy": "complete_case",
                            "weights": {"price_momentum_2": 1.0}}})
        days = [f"2024-01-0{i}" for i in range(1, 5)]
        label_overflow = pd.DataFrame({"date": days, "code": ["4502"] * 4,
            "open": [1.0, 1e-308, 1e308, 1.0], "close": [10.0] * 4,
            "selected_price": [10.0] * 4, "selected_price_basis": ["raw"] * 4})
        with self.assertRaisesRegex(FactorResearchError, "non-finite forward label"):
            _build_rows(label_overflow, recipe)
        feature_overflow = label_overflow.copy()
        feature_overflow["open"] = 1.0
        feature_overflow["selected_price"] = [1e-308, 10.0, 1e308, 10.0]
        with self.assertRaisesRegex(FactorResearchError, "non-finite feature calculation"):
            _build_rows(feature_overflow, recipe)


if __name__ == "__main__":
    unittest.main()
