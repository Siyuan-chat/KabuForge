"""Artificial factor labels exercise fixed research splits, not predictive efficacy."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from framework_v2.factor_research import DEFAULT_RECIPE, validate_recipe
import framework_v2.model_research as model_research_module
from framework_v2.model_research import ModelResearchError, run_model_research


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _canonical_hash(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class ModelResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        self.assertTrue(Path(model_research_module.__file__).resolve().is_relative_to(project_root),
                        f"test imported non-candidate implementation: {model_research_module.__file__}")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.factor_dir = self.root / "factor-run"
        self.factor_dir.mkdir()
        self._factor_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def _factor_fixture(self):
        recipe = validate_recipe()
        recipe_hash = hashlib.sha256(json.dumps(recipe, sort_keys=True,
            ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        identity = {"manifest_kind": "kabuforge_local_research_bars",
            "manifest_sha256": "a" * 64, "selected_data_sha256": "b" * 64,
            "pit_guarantee": False}
        provider = {"id": "test.factor-provider", "version": "fixture-v1",
            "source_sha256": "c" * 64}
        contract = {"schema": "kabuforge.factor_research_contract.v1",
            "status": "PREREGISTERED", "readiness": "RESEARCH-ONLY",
            "input_identity": identity, "provider_identity": provider,
            "recipe": recipe, "recipe_sha256": recipe_hash}
        feature_doc = {"schema": "kabuforge.factor_feature_rows.v1",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "contains_forward_labels": False, "recipe_sha256": recipe_hash,
            "input_identity": identity, "provider_identity": provider, "rows": []}
        evaluation_doc = {"schema": "kabuforge.factor_evaluation_panel.v1",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "recipe_sha256": recipe_hash, "input_identity": identity,
            "provider_identity": provider, "rows": []}
        codes = ("4502", "6758", "8306")
        for year in range(2017, 2023):
            first = date(year, 11, 1)
            for index in range(30):
                signal_date = (first + timedelta(days=index * 2)).isoformat()
                execution_date = (date.fromisoformat(signal_date) + timedelta(days=1)).isoformat()
                label_end = (date.fromisoformat(signal_date) + timedelta(days=6)).isoformat()
                for code_index, code in enumerate(codes):
                    feature20 = (index - 10) * 0.001 + code_index * 0.004 + (year - 2017) * 0.0003
                    feature60 = (index % 11 - 5) * 0.002 + code_index * 0.006
                    target = (code_index - 1) * 0.002 + (index % 7 - 3) * 0.0007 + (year - 2019) * 0.0002
                    feature_doc["rows"].append({"code": code, "signal_date": signal_date,
                        "d1_cutoff_date": signal_date, "execution_date": execution_date,
                        "selected_price_basis": "raw", "price_momentum_20": feature20,
                        "price_momentum_60": feature60, "composite_score": feature20 + feature60,
                        "composite_status": "complete"})
                    evaluation_doc["rows"].append({"code": code, "signal_date": signal_date,
                        "d1_cutoff_date": signal_date, "execution_date": execution_date,
                        "label_start_date": execution_date, "label_end_date": label_end,
                        "selected_price_basis": "raw", "price_momentum_20": feature20,
                        "price_momentum_60": feature60, "composite_score": feature20 + feature60,
                        "composite_status": "complete", "forward_return": target,
                        "label_status": "available"})
        report = {"schema": "kabuforge.factor_research_report.v1", "status": "COMPLETED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "recipe": recipe, "recipe_sha256": recipe_hash, "input_identity": identity,
            "provider_identity": provider,
            "artifacts": {"feature_rows_sha256": _canonical_hash(feature_doc),
                          "evaluation_panel_sha256": _canonical_hash(evaluation_doc)}}
        _write(self.factor_dir / "contract.json", contract)
        _write(self.factor_dir / "feature_rows.json", feature_doc)
        _write(self.factor_dir / "evaluation_panel.json", evaluation_doc)
        _write(self.factor_dir / "report.json", report)

    def test_model_path_does_not_accept_arbitrary_module_names(self):
        with self.assertRaisesRegex(ModelResearchError, "model_name must be"):
            run_model_research(self.factor_dir, self.root / "bad-model", "os.system")

    def test_modified_factor_rows_without_updated_canonical_identity_are_rejected(self):
        path = self.factor_dir / "evaluation_panel.json"
        evaluation = json.loads(path.read_text(encoding="utf-8"))
        evaluation["rows"][0]["forward_return"] += 0.01
        _write(path, evaluation)
        with self.assertRaisesRegex(ModelResearchError, "canonical hashes"):
            run_model_research(self.factor_dir, self.root / "tampered", "lightgbm")

    def test_bad_d1_clock_is_rejected_even_if_report_hash_is_rewritten(self):
        feature_path = self.factor_dir / "feature_rows.json"
        report_path = self.factor_dir / "report.json"
        features = json.loads(feature_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        features["rows"][0]["d1_cutoff_date"] = "2017-01-01"
        _write(feature_path, features)
        report["artifacts"]["feature_rows_sha256"] = _canonical_hash(features)
        _write(report_path, report)
        with self.assertRaisesRegex(ModelResearchError, "D-1 feature cutoff"):
            run_model_research(self.factor_dir, self.root / "bad-clock", "lightgbm")

    def test_fixed_splits_purge_and_prediction_artifact_excludes_labels(self):
        if importlib.util.find_spec("lightgbm") is None:
            with self.assertRaisesRegex(ModelResearchError, "optional lightgbm runtime is unavailable"):
                run_model_research(self.factor_dir, self.root / "lightgbm", "lightgbm")
            return
        out = self.root / "lightgbm"
        result = run_model_research(self.factor_dir, out, "lightgbm")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["readiness"], "RESEARCH-ONLY")
        self.assertIs(result["pit_guarantee"], False)
        self.assertEqual(result["random_seed"], 42)
        self.assertEqual(result["features"], ["price_momentum_20", "price_momentum_60"])
        contract = json.loads((out / "contract.json").read_text(encoding="utf-8"))
        self.assertIs(contract["pit_guarantee"], False)
        self.assertEqual(contract["splits"]["train"]["signal_start"], "2017-01-01")
        self.assertEqual(contract["splits"]["validation"]["signal_start"], "2020-01-01")
        self.assertEqual(contract["splits"]["test"]["signal_start"], "2021-01-01")
        self.assertIn("strictly before", contract["purge_rule"])
        self.assertEqual(contract["model_runtime"]["name"], "lightgbm")
        self.assertGreater(result["split_counts"]["train"]["purged_label_boundary"], 0)
        self.assertGreater(result["split_counts"]["validation"]["purged_label_boundary"], 0)
        self.assertGreater(result["split_counts"]["test"]["purged_label_boundary"], 0)
        self.assertLess(result["split_ranges"]["train"]["label_end_date_max"],
                        contract["splits"]["validation"]["signal_start"])
        self.assertLess(result["split_ranges"]["validation"]["label_end_date_max"],
                        contract["splits"]["test"]["signal_start"])
        self.assertLessEqual(result["split_ranges"]["test"]["label_end_date_max"], "2022-12-31")
        predictions = json.loads((out / "predictions.json").read_text(encoding="utf-8"))
        self.assertEqual(predictions["schema"], "kabuforge.model_prediction_rows.v1")
        self.assertIs(predictions["pit_guarantee"], False)
        self.assertFalse(predictions["contains_forward_labels"])
        self.assertTrue(predictions["rows"])
        self.assertTrue(all(row["signal_date"] >= "2020-01-01" for row in predictions["rows"]))
        self.assertTrue(all(row["signal_date"] > result["model_training_label_end_max"]
                            for row in predictions["rows"]))
        self.assertNotIn("training", {row["prediction_role"] for row in predictions["rows"]})
        self.assertEqual({row["prediction_role"] for row in predictions["rows"]},
                         {"validation_diagnostic", "historical_test_diagnostic"})
        self.assertTrue(all(not {"forward_return", "label_end_date", "label_status"}.intersection(row)
                            for row in predictions["rows"]))
        self.assertEqual(result["prediction_row_count"], len(predictions["rows"]))
        self.assertEqual(result["prediction_rows"]["sha256"],
                         hashlib.sha256((out / "predictions.json").read_bytes()).hexdigest())
        receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
        self.assertIs(receipt["pit_guarantee"], False)
        self.assertEqual(receipt["model_sha256"], result["model_artifact"]["sha256"])
        self.assertTrue(all(metrics["rows"] > 0 for metrics in result["metrics"].values()))

    def test_catboost_fixed_training_uses_no_local_training_files(self):
        if importlib.util.find_spec("catboost") is None:
            with self.assertRaisesRegex(ModelResearchError, "optional catboost runtime is unavailable"):
                run_model_research(self.factor_dir, self.root / "catboost", "catboost")
            return
        out = self.root / "catboost"
        result = run_model_research(self.factor_dir, out, "catboost")
        self.assertEqual(result["model_name"], "catboost")
        self.assertTrue(result["model_artifact"]["file"].endswith("model.cbm"))
        params = result["parameters"]
        self.assertEqual(params["random_seed"], 42)
        self.assertEqual(params["thread_count"], 1)
        self.assertFalse(params["allow_writing_files"])
        self.assertEqual({path.name for path in out.iterdir()},
                         {"contract.json", "model.cbm", "predictions.json", "report.json", "receipt.json"})

    def test_label_boundary_policy_is_saved_before_fit_and_validation_not_used_for_selection(self):
        if importlib.util.find_spec("lightgbm") is None:
            with self.assertRaisesRegex(ModelResearchError, "optional lightgbm runtime is unavailable"):
                run_model_research(self.factor_dir, self.root / "contract", "lightgbm")
            return
        result = run_model_research(self.factor_dir, self.root / "contract", "lightgbm")
        contract = json.loads((self.root / "contract" / "contract.json").read_text(encoding="utf-8"))
        self.assertIn("no hyperparameter or feature selection", contract["train_validation_role"])
        self.assertTrue(result["metrics"]["validation"]["interpretation"].startswith("descriptive only"))
        self.assertTrue(result["metrics"]["test"]["interpretation"].startswith("descriptive only"))


if __name__ == "__main__":
    unittest.main()
