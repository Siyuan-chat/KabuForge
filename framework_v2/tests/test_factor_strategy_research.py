"""Artificial engineering fixtures test fixed-score replay, not strategy evidence."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import framework_v2.factor_strategy_research as strategy_module
import framework_v2.local_cache as local_cache_module
import framework_v2.price_research as price_research_module
import framework_v2.topix_benchmark as topix_module
from framework_v2 import factor_research, local_cache
from framework_v2.factor_strategy_research import (
    DEFAULT_RECIPE,
    FactorStrategyResearchError,
    run_factor_strategy_research,
    validate_recipe,
)
from framework_v2.price_research import _load_price_research_input
from framework_v2.topix_benchmark import attach_local_topix


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bars(dates: list[str], opens: dict[str, list[float]] | None = None) -> list[dict]:
    codes = ["4502", "6758", "8306"]
    opens = opens or {code: [10.0] * len(dates) for code in codes}
    rows = []
    for code in codes:
        for index, day in enumerate(dates):
            opened = float(opens[code][index])
            close = 10.0
            rows.append({"date": day, "code": code, "open": opened,
                "high": max(opened, close) * 1.01, "low": min(opened, close) * 0.99,
                "close": close, "volume": 1000.0, "adjustment_factor": 1.0,
                "adjustment_close": close})
    return rows


def _frozen(root: Path, rows: list[dict]) -> Path:
    source = root / "bars.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    loaded = local_cache.load_research_bars(source,
        codes=["4502", "6758", "8306"],
        start_date=min(row["date"] for row in rows),
        end_date=max(row["date"] for row in rows), price_basis="raw")
    return loaded.freeze(root / "frozen")


def _input_identity(manifest: Path) -> dict:
    _rows, identity = _load_price_research_input(manifest)
    pinned = json.loads(manifest.read_text(encoding="utf-8"))
    return {**identity, "manifest_sha256": _digest(manifest), "selection": pinned["selection"]}


def _write_doc(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return _digest(path)


def _factor_artifact(root: Path, manifest: Path, scores_by_signal: dict[str, list[float | None]],
                     *, mutate_row=None) -> Path:
    rows = _bars(sorted({day for signal in scores_by_signal for day in (signal,)}))
    # The caller's real frozen bars define the calendar; score date helpers create
    # chronological rows below without manufacturing any OHLC values.
    bar_rows, _identity = _load_price_research_input(manifest)
    dates = sorted({str(row["date"]) for row in bar_rows})
    input_identity = _input_identity(manifest)
    feature_rows = []
    for signal, scores in scores_by_signal.items():
        index = dates.index(signal)
        if index + 1 >= len(dates):
            raise AssertionError("fixture score needs a next observed bar")
        for code, score in zip(("4502", "6758", "8306"), scores):
            item = {"code": code, "signal_date": signal, "d1_cutoff_date": signal,
                "execution_date": dates[index + 1], "selected_price_basis": "raw",
                "price_momentum_20": 0.0 if score is None else float(score),
                "composite_score": score, "composite_status": "complete" if score is not None else "incomplete"}
            if mutate_row:
                mutate_row(item)
            feature_rows.append(item)
    artifact = {"schema": "kabuforge.factor_feature_rows.v1", "readiness": "RESEARCH-ONLY",
        "pit_guarantee": False, "contains_forward_labels": False,
        "recipe_sha256": "b" * 64,
        "provider_identity": {"id": "kabuforge.local_daily_factor_research", "version": "1",
            "source_sha256": hashlib.sha256(Path(factor_research.__file__).read_bytes()).hexdigest(),
            "local_cache_loader_source_sha256": hashlib.sha256(Path(local_cache.__file__).read_bytes()).hexdigest()},
        "input_identity": input_identity, "rows": feature_rows}
    path = root / "feature_rows.json"
    _write_doc(path, artifact)
    return path


def _model_artifact(root: Path, manifest: Path, rows: list[dict]) -> Path:
    artifact = {"schema": "kabuforge.model_prediction_rows.v1", "readiness": "RESEARCH-ONLY",
        "pit_guarantee": False, "contains_forward_labels": False,
        "input_identity": _input_identity(manifest), "recipe_sha256": "c" * 64,
        "model_name": "lightgbm", "model_artifact_sha256": "d" * 64, "rows": rows}
    path = root / "predictions.json"
    _write_doc(path, artifact)
    return path


class FactorStrategyResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (strategy_module, local_cache_module, price_research_module, topix_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.tmp = tempfile.TemporaryDirectory(prefix="factor-score-strategy-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_factor_score_tie_warmup_gap_and_fixed_quantity_replay(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
        opens = {"4502": [10, 10, 100, 10], "6758": [10, 10, 10, 10], "8306": [10, 10, 10, 10]}
        manifest = _frozen(self.root, _bars(dates, opens))
        artifact = _factor_artifact(self.root, manifest, {dates[1]: [1.0, 1.0, 1.0]})
        recipe = {**DEFAULT_RECIPE, "cash": 1000.0, "count": 2,
                  "frequency": "daily", "minimum_cross_section": 3}
        first = run_factor_strategy_research(manifest, artifact, self.root / "run-a", recipe,
            score_source="factor_feature_rows", expected_artifact_sha256=_digest(artifact))
        second = run_factor_strategy_research(manifest, artifact, self.root / "run-b", recipe,
            score_source="factor_feature_rows", expected_artifact_sha256=_digest(artifact))
        report = json.loads(first.read_text(encoding="utf-8"))
        repeated = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(report["order_schedule"], repeated["order_schedule"])
        self.assertEqual(report["input_hash"], repeated["input_hash"])
        self.assertEqual(len(report["nav"]), len(dates))
        self.assertEqual(report["decisions"][0]["status"], "skipped_insufficient_cross_section")
        self.assertEqual(report["decisions"][0]["eligible_count"], 0)
        selected = next(item for item in report["decisions"] if item["status"] == "scheduled")
        self.assertEqual(selected["selected_codes"], ["4502", "6758"])
        self.assertEqual(selected["cutoff_tie_codes"], ["4502", "6758", "8306"])
        skipped_gap = next(item for item in report["skipped_orders"]
                           if item["execution_date"] == dates[2] and item["code"] == "4502")
        self.assertIn("fixed quantity skipped", skipped_gap["reason"])
        planned = next(item for item in report["order_schedule"]
                       if item["execution_date"] == dates[2] and item["code"] == "4502")
        self.assertAlmostEqual(skipped_gap["quantity"], planned["quantity"], places=12)
        self.assertTrue(any(item["code"] == "6758" and item["date"] == dates[2]
                            for item in report["trades"]))
        self.assertFalse(report["pit_guarantee"])
        self.assertEqual(report["valuation_basis"], "rawclose")

    def test_model_strategy_uses_only_historical_test_rows_in_2021_2022(self):
        dates = ["2020-12-31", "2021-01-04", "2021-01-05", "2021-01-06"]
        manifest = _frozen(self.root, _bars(dates))
        predictions = []
        # A validation score before 2021 is validated as diagnostic metadata but
        # never becomes a strategy signal.
        for code, score in zip(("4502", "6758", "8306"), (9.0, 8.0, 7.0)):
            predictions.append({"code": code, "signal_date": dates[0], "d1_cutoff_date": dates[0],
                "execution_date": dates[1], "prediction_role": "validation_diagnostic",
                "model_training_label_end_max": "2020-12-30", "prediction": score})
            predictions.append({"code": code, "signal_date": dates[1], "d1_cutoff_date": dates[1],
                "execution_date": dates[2], "prediction_role": "historical_test_diagnostic",
                "model_training_label_end_max": "2019-12-30", "prediction": score})
        artifact = _model_artifact(self.root, manifest, predictions)
        report_path = run_factor_strategy_research(manifest, artifact, self.root / "model-run",
            {**DEFAULT_RECIPE, "cash": 1000.0, "frequency": "daily"},
            score_source="model_predictions", expected_artifact_sha256=_digest(artifact))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["score_window"]["start_date"], dates[1])
        self.assertEqual(report["score_window"]["end_date"], dates[-1])
        self.assertEqual([item["at"] for item in report["nav"]], dates[1:])
        self.assertTrue(all(item["signal_date"] >= "2021-01-01" for item in report["order_schedule"]))
        self.assertTrue(all(item["prediction_role"] == "historical_test_diagnostic"
                            for item in report["decisions"] if "prediction_role" in item))
        receipt = json.loads((report_path.parent / "receipt.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["pit_guarantee"])

    def test_bad_d1_model_cutoff_and_artifact_hash_fail_closed(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        manifest = _frozen(self.root, _bars(dates))
        base = {"code": "4502", "signal_date": dates[0], "d1_cutoff_date": dates[0],
            "execution_date": dates[1], "prediction_role": "historical_test_diagnostic",
            "model_training_label_end_max": "2021-01-04", "prediction": 0.1}
        rows = [dict(base, code=code) for code in ("4502", "6758", "8306")]
        artifact = _model_artifact(self.root, manifest, rows)
        recipe = {**DEFAULT_RECIPE, "frequency": "daily"}
        with self.assertRaisesRegex(FactorStrategyResearchError, "training-label end"):
            run_factor_strategy_research(manifest, artifact, self.root / "bad-cutoff", recipe,
                score_source="model_predictions", expected_artifact_sha256=_digest(artifact))
        self.assertTrue((self.root / "bad-cutoff" / "failure.json").is_file())
        with self.assertRaisesRegex(FactorStrategyResearchError, "SHA-256"):
            run_factor_strategy_research(manifest, artifact, self.root / "bad-hash", recipe,
                score_source="model_predictions", expected_artifact_sha256="0" * 64)
        self.assertTrue((self.root / "bad-hash" / "failure.json").is_file())

        bad_d1 = [dict(row, d1_cutoff_date="2021-01-03") for row in rows]
        bad_artifact = self.root / "bad-d1"; bad_artifact.mkdir()
        model_path = _model_artifact(bad_artifact, manifest, bad_d1)
        with self.assertRaisesRegex(FactorStrategyResearchError, "D-1"):
            run_factor_strategy_research(manifest, model_path, self.root / "bad-d1-run", recipe,
                score_source="model_predictions", expected_artifact_sha256=_digest(model_path))

    def test_evaluation_panel_poison_is_not_opened(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        manifest = _frozen(self.root, _bars(dates))
        artifact = _factor_artifact(self.root, manifest, {dates[0]: [1.0, 0.0, -1.0]})
        poison = artifact.parent / "evaluation_panel.json"
        poison.write_text('{"poison": true}', encoding="utf-8")
        original = Path.read_bytes
        attempted = []
        def guarded_read(path):
            if path.name == "evaluation_panel.json":
                attempted.append(str(path))
                raise AssertionError("strategy attempted to open a forward-label evaluation panel")
            return original(path)
        with patch.object(Path, "read_bytes", guarded_read):
            report = run_factor_strategy_research(manifest, artifact, self.root / "poison-safe-run",
                {**DEFAULT_RECIPE, "cash": 1000.0, "frequency": "daily"},
                score_source="factor_feature_rows", expected_artifact_sha256=_digest(artifact))
        self.assertEqual(attempted, [])
        self.assertTrue(report.is_file())

    def test_monthly_boundary_rebalances_on_first_observed_open_only(self):
        dates = ["2021-01-04", "2021-01-05", "2021-02-01", "2021-02-02"]
        manifest = _frozen(self.root, _bars(dates))
        artifact = _factor_artifact(self.root, manifest, {
            dates[0]: [3.0, 2.0, 1.0],
            dates[1]: [3.0, 2.0, 1.0],
        })
        report_path = run_factor_strategy_research(manifest, artifact, self.root / "monthly-run",
            {**DEFAULT_RECIPE, "cash": 1000.0}, score_source="factor_feature_rows",
            expected_artifact_sha256=_digest(artifact))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual([item["execution_date"] for item in report["order_schedule"]], [dates[2], dates[2]])

    def test_recipe_requires_three_cross_section_and_rejects_boolean_money(self):
        with self.assertRaisesRegex(FactorStrategyResearchError, r"max\(3, count\)"):
            validate_recipe({**DEFAULT_RECIPE, "minimum_cross_section": 2})
        with self.assertRaisesRegex(FactorStrategyResearchError, "not booleans"):
            validate_recipe({**DEFAULT_RECIPE, "cash": True})
        with self.assertRaisesRegex(FactorStrategyResearchError, "not booleans"):
            validate_recipe({**DEFAULT_RECIPE, "fee": False})

    def test_report_contract_can_attach_exact_date_topix_annotation(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        manifest = _frozen(self.root, _bars(dates))
        artifact = _factor_artifact(self.root, manifest, {dates[0]: [3.0, 2.0, 1.0]})
        report_path = run_factor_strategy_research(manifest, artifact, self.root / "topix-run",
            {**DEFAULT_RECIPE, "cash": 1000.0, "frequency": "daily"},
            score_source="factor_feature_rows", expected_artifact_sha256=_digest(artifact))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        parquet = self.root / "index_prices.parquet"
        parquet.write_bytes(b"isolated patched-reader fixture")
        frame = pd.DataFrame([{"date": day, "index_code": "TOPIX", "close": 1700.0 + index}
                              for index, day in enumerate(dates)])
        with patch("pandas.read_parquet", return_value=frame):
            enriched = attach_local_topix(report, parquet)
        self.assertEqual(enriched["benchmark_provenance"]["aligned_date_count"], len(dates))
        self.assertEqual(enriched["benchmark_nav"]["TOPIX"][0]["at"], dates[0])


if __name__ == "__main__":
    unittest.main()
