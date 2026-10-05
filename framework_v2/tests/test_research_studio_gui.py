from __future__ import annotations

import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from framework_v2.factor_research import run_factor_research
from framework_v2.local_cache import load_research_bars
from framework_v2.product_ui import ProductWorkbench
from framework_v2.research_studio_panel import ResearchStudioPanel
from framework_v2.research_studio_worker import run_job


class ResearchStudioGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        import framework_v2.research_studio_panel as panel_module
        candidate=Path(__file__).resolve().parents[2]
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),
                        panel_module.__file__)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.app.processEvents()
        self.tmp.cleanup()

    def _window(self):
        with patch("framework_v2.data_connection.load_api_key", return_value=None):
            window = ProductWorkbench(self.root / "workspace")
        window.show(); self.app.processEvents()
        return window

    def _wait(self, predicate, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.02)
            if predicate(): return
        self.fail(f"bounded GUI wait expired after {timeout}s")

    def _frozen_bars(self, folder):
        first = date(2019, 1, 2); dates=[]; day=first
        while len(dates)<100:
            if day.weekday()<5: dates.append(day.isoformat())
            day += timedelta(days=1)
        rows=[]
        for code, base, slope in (("4502",100.0,.22),("6758",180.0,.31),("8306",75.0,.16)):
            for i, text in enumerate(dates):
                close=base+i*slope+np.sin(i/4+int(code[-1]))*1.1
                rows.append({"Date":text,"Code":code,"Open":close*.999,"High":close*1.01,"Low":close*.99,
                    "Close":close,"Volume":100000+i,"AdjustmentFactor":1.0,"AdjustmentClose":close})
        csv=folder/"bars.csv"; pd.DataFrame(rows).to_csv(csv,index=False)
        selection=load_research_bars(csv,codes=["4502","6758","8306"],start_date=dates[0],end_date=dates[-1],
            price_basis="raw",duplicate_policy="reject",known_halt_policy="reject")
        return Path(selection.freeze(folder/"frozen-input"))

    def test_product_workbench_mounts_studio_and_switches_all_three_languages(self):
        window = self._window()
        try:
            panel = window.research_studio_panel
            manifest = self._frozen_bars(self.root)
            self.assertTrue(window._market_ready(manifest), window._market_status_error)
            self.assertIsInstance(panel, ResearchStudioPanel)
            self.assertEqual(panel.manifest_path, manifest.resolve())
            expected = {"zh_CN":"研究 Studio", "ja_JP":"Research Studio", "en_US":"Research Studio"}
            for locale, title in expected.items():
                window.set_language(locale)
                self.assertIn(title, panel.title())
                self.assertEqual(panel.manifest_path, manifest.resolve())
                self.assertTrue(panel.run_engine_button.text())
                self.assertEqual(panel.lookback20.isChecked(), True)
            self.assertIn("2017–2019", panel.split_note.text())
            self.assertFalse(panel.busy)
        finally:
            window.close(); self.app.processEvents()

    def test_ma_crossover_explains_daily_all_symbol_semantics_and_restores_momentum_controls(self):
        window = self._window()
        try:
            window.template.setCurrentIndex(window.template.findData("market"))
            window.holding_count.setValue(3)
            window.frequency.setCurrentIndex(window.frequency.findData("weekly"))
            window.signal_template.setCurrentIndex(window.signal_template.findData("sma_crossover"))
            self.assertEqual(window.holding_count.value(), 1)
            self.assertEqual(window.frequency.currentData(), "daily")
            self.assertFalse(window.holding_count.isEnabled())
            self.assertFalse(window.frequency.isEnabled())
            self.assertFalse(window.ma_semantics_note.isHidden())
            window.set_language("en_US")
            self.assertIn("all selected symbols", window.ma_semantics_note.text())
            self.assertEqual(window.recipe()["count"], 1)
            self.assertEqual(window.recipe()["frequency"], "daily")
            window.signal_template.setCurrentIndex(window.signal_template.findData("price_momentum"))
            self.assertEqual(window.holding_count.value(), 3)
            self.assertEqual(window.frequency.currentData(), "weekly")
            self.assertTrue(window.holding_count.isEnabled())
            self.assertTrue(window.frequency.isEnabled())
        finally:
            window.close(); self.app.processEvents()

    def test_explicit_model_selection_and_engine_gate_bind_fixed_candidates(self):
        manifest=self._frozen_bars(self.root)
        window=self._window()
        try:
            window._market_ready(manifest)
            panel=window.research_studio_panel
            factor_dir=self.root/"factor-artifacts"; factor_dir.mkdir()
            for name in ("contract.json","report.json","feature_rows.json","evaluation_panel.json"):
                (factor_dir/name).write_text("{}",encoding="utf-8")
            panel.factor_path.setText(str(factor_dir))
            captured=[]
            with patch.object(panel,"_start",side_effect=lambda operation,body: captured.append((operation,body)) or True):
                for selected,expected in (("lightgbm",["lightgbm"]),("catboost",["catboost"]),("both",["lightgbm","catboost"])):
                    panel.model_names.setCurrentIndex(panel.model_names.findData(selected))
                    self.assertTrue(panel.train_models())
                    operation,body=captured[-1]
                    self.assertEqual(operation,"model_training")
                    self.assertEqual(body["model_names"],expected)
                    self.assertEqual(body["manifest_sha256"],hashlib.sha256(manifest.read_bytes()).hexdigest())

            panel.lookback20.setChecked(False); panel.lookback60.setChecked(False)
            self.assertFalse(panel.compare_engines())
            self.assertIn("select at least one",panel.status.text())
            panel.lookback20.setChecked(True)
            with patch.object(panel,"_start",side_effect=lambda operation,body: captured.append((operation,body)) or True):
                self.assertTrue(panel.compare_engines())
            operation,body=captured[-1]
            self.assertEqual(operation,"engine_comparison")
            self.assertEqual(body["manifest_sha256"],hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual([item["lookback"] for item in body["recipes"]],[20])

            with patch("framework_v2.research_runtime.resolve_extension_runtime",
                       return_value={"enabled":False,"reason":"engineering fixture: backend runtime unavailable"}):
                self.assertFalse(panel._start("engine_comparison",body))
            self.assertIn("engineering fixture",panel.status.text())
            self.assertFalse(panel.busy)
        finally:
            window.close(); self.app.processEvents()

    def test_studio_qprocess_failure_is_terminal_and_can_restart(self):
        window = self._window()
        try:
            panel = window.research_studio_panel
            manifest = self._frozen_bars(self.root)
            feature = self.root / "feature_rows.json"; feature.write_text("{}", encoding="utf-8")
            self.assertTrue(window._market_ready(manifest), window._market_status_error)
            panel.score_source.setCurrentIndex(0); panel.score_path.setText(str(feature))
            self.assertTrue(panel.run_strategy())
            first_job = panel._active_job
            self._wait(lambda: not panel.busy)
            self.assertTrue((first_job / "failure.json").is_file())
            self.assertTrue((first_job / "launch.json").is_file())
            self.assertTrue((first_job / "exit.json").is_file())
            failure = json.loads((first_job / "failure.json").read_text(encoding="utf-8"))
            self.assertIn("socket.create_connection/connect/connect_ex denied", failure["offline_guards"])
            self.assertEqual(panel.last_result["status"], "FAILED")
            self.assertTrue(panel.run_strategy())
            second_job = panel._active_job
            self.assertNotEqual(first_job, second_job)
            self._wait(lambda: not panel.busy)
            self.assertTrue((second_job / "failure.json").is_file())
            self.assertFalse(panel.busy)
        finally:
            if window.research_studio_panel.busy:
                self._wait(lambda: not window.research_studio_panel.busy)
            window.close(); self.app.processEvents()

    def test_failed_to_start_writes_terminal_receipts_and_releases_busy_state(self):
        window = self._window()
        try:
            panel = window.research_studio_panel
            manifest = self._frozen_bars(self.root)
            self.assertTrue(window._market_ready(manifest), window._market_status_error)
            feature = self.root / "feature_rows.json"; feature.write_text("{}", encoding="utf-8")
            panel.score_path.setText(str(feature))
            with patch("framework_v2.research_studio_panel.sys.executable", str(self.root / "missing-python.exe")):
                self.assertTrue(panel.run_strategy())
                job = panel._active_job
                self._wait(lambda: not panel.busy, timeout=10)
            self.assertTrue((job / "launch.json").is_file())
            self.assertTrue((job / "exit.json").is_file())
            launch = json.loads((job / "launch.json").read_text(encoding="utf-8"))
            self.assertIsNone(launch["pid"])
            self.assertEqual(panel.last_result["error_type"], "QProcessStartError")
        finally:
            if window.research_studio_panel.busy: self._wait(lambda: not window.research_studio_panel.busy)
            window.close(); self.app.processEvents()

    def test_studio_qprocess_completes_real_feature_score_research_and_opens_result(self):
        manifest = self._frozen_bars(self.root)
        factor_dir = self.root / "factor-run"
        factor_report = run_factor_research(manifest, factor_dir)
        window = self._window()
        try:
            window._market_ready(manifest)
            panel = window.research_studio_panel
            panel.score_source.setCurrentIndex(0)
            panel.score_path.setText(factor_report["artifacts"]["feature_rows"])
            self.assertTrue(panel.run_strategy())
            job_dir = panel._active_job
            self._wait(lambda: not panel.busy, timeout=90)
            self.assertEqual(panel.last_result["status"], "COMPLETED")
            self.assertTrue((job_dir/"result.json").is_file())
            self.assertEqual(window.report["model"], "daily_bar_next_open_research_v1")
            self.assertTrue(window.report["nav"])
            self.assertEqual(window.report["input_identity"]["manifest_sha256"], panel.last_result["manifest_sha256"])
            self.assertTrue(panel.open_report_button.isEnabled())
            self.assertTrue(panel.result.toPlainText())
            expected_benchmark = {"zh_CN":"未载入TOPIX", "ja_JP":"TOPIX未読込", "en_US":"TOPIX not loaded"}
            for language in ("zh_CN", "ja_JP", "en_US"):
                window.set_language(language)
                self.assertEqual(window.report["model"], "daily_bar_next_open_research_v1")
                self.assertNotIn("frozen_factor_feature_rows", window.strategy_badge.text())
                self.assertIn(expected_benchmark[language], window.result_summary.text())
        finally:
            if window.research_studio_panel.busy: self._wait(lambda: not window.research_studio_panel.busy, timeout=90)
            window.close(); self.app.processEvents()

    def test_manifest_change_invalidates_active_generation_and_parent_close_is_blocked(self):
        window = self._window()
        try:
            panel = window.research_studio_panel
            first = self.root / "a.json"; second = self.root / "b.json"
            first.write_text("{}", encoding="utf-8"); second.write_text("{}", encoding="utf-8")
            panel.set_manifest(first)
            panel._busy = True
            generation = panel._generation
            panel.set_manifest(second)
            self.assertGreater(panel._generation, generation)
            self.assertEqual(panel.manifest_path, second.resolve())
            self.assertIn("变化", panel.status.text())
            window.close(); self.app.processEvents()
            self.assertTrue(window.isVisible())
            panel._busy = False
            window.close(); self.app.processEvents()
            self.assertFalse(window.isVisible())
        finally:
            if window.isVisible():
                window.research_studio_panel._busy = False
                window.close(); self.app.processEvents()

    def test_static_worker_rejects_unknown_operation_and_writes_receipt(self):
        workspace = self.root / "workspace"; job_id = "a" * 32
        job = workspace / "research-studio" / "jobs" / job_id
        job.mkdir(parents=True)
        (job / "request.json").write_text(json.dumps({"schema":"kabuforge.research_studio_request.v1",
            "job_id":job_id,"operation":"execute_arbitrary_module","module":"os"}), encoding="utf-8")
        result = run_job(workspace, job_id)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["readiness"], "RESEARCH-ONLY")
        self.assertTrue((job / "failure.json").is_file())
        self.assertFalse((job / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
