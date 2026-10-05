from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, timedelta
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from framework_v2.factor_report_dashboard import build_factor_dashboard
from framework_v2.factor_research import run_factor_research
from framework_v2.local_cache import load_research_bars
from framework_v2.product_ui import ProductWorkbench
from framework_v2.research_application import ResearchApplicationService


class FactorResearchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        import framework_v2.factor_research_panel as panel_module
        candidate=Path(__file__).resolve().parents[2]
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),
                        panel_module.__file__)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.app.processEvents()
        self.temp.cleanup()

    def _manifest(self, count=100):
        first = date(2020, 8, 3)
        dates = []
        day = first
        while len(dates) < count:
            if day.weekday() < 5:
                dates.append(day.isoformat())
            day += timedelta(days=1)
        rows = []
        for code, base, slope in (("4502", 100.0, .22), ("6758", 180.0, .31), ("8306", 75.0, .16)):
            for index, day_text in enumerate(dates):
                close = base + index * slope + np.sin(index / 4.0 + int(code[-1])) * 1.1
                rows.append({"Date": day_text, "Code": code, "Open": close * (1 + (index % 3 - 1) * .001),
                    "High": close * 1.01, "Low": close * .99, "Close": close,
                    "Volume": 100_000 + index, "AdjustmentFactor": 1.0, "AdjustmentClose": close})
        source = self.root / "bars.csv"
        pd.DataFrame(rows).to_csv(source, index=False)
        selection = load_research_bars(source, codes=["4502", "6758", "8306"],
            start_date=dates[0], end_date=dates[-1], price_basis="raw",
            duplicate_policy="reject", known_halt_policy="reject")
        return Path(selection.freeze(self.root / "frozen-input"))

    def _report(self, manifest):
        return run_factor_research(manifest, self.root / "factor-run")

    def test_user_workbench_mounts_factor_panel_and_locale_switch_preserves_inputs(self):
        manifest = self._manifest()
        with patch("framework_v2.data_connection.load_api_key", return_value=None):
            window = ProductWorkbench(self.root / "workspace")
        try:
            window.show()
            self.app.processEvents()
            self.assertTrue(hasattr(window, "factor_research_panel"))
            panel = window.factor_research_panel
            window._market_ready(manifest)
            self.assertEqual(panel.manifest_path, manifest.resolve())
            panel.fast_window.setValue(21)
            panel.slow_window.setValue(61)
            panel.fast_weight.setValue(.7)
            panel.slow_direction.setCurrentIndex(1)
            panel.horizon.setValue(7)
            recipe_before = panel.recipe()
            load_states = []
            panel.view.loadFinished.connect(load_states.append)
            for language, expected in (("zh_CN", "因子诊断"), ("ja_JP", "ファクター診断"),
                                       ("en_US", "Factor diagnostics")):
                window.set_language(language)
                self.assertIn(expected, panel.title())
                self.assertEqual(panel.manifest_path, manifest.resolve())
                self.assertEqual(panel.recipe(), recipe_before)
            self.assertTrue(panel.start())
            self._wait_for(lambda: not panel.busy and panel.report is not None, timeout=40)
            self._wait_for(lambda: ("All six chart types are loaded" in panel.status.text()
                                    or "failed" in panel.status.text().lower()
                                    or "unavailable" in panel.status.text().lower()), timeout=25)
            dom_diagnostic = []
            panel.view.page().runJavaScript(
                "JSON.stringify({plots:document.querySelectorAll('.plotly-graph-div').length,plotly:typeof Plotly,ready:document.documentElement.dataset.plotlyReady,registered:!!window.Plotly})",
                dom_diagnostic.append)
            self._wait_for(lambda: bool(dom_diagnostic), timeout=5)
            dom_value = json.loads(dom_diagnostic[-1])
            self.assertIn("All six chart types are loaded", panel.status.text(),
                f"status={panel.status.text()!r} loadFinished={load_states!r} url={panel.view.url().toString()!r} "
                f"dom={dom_value!r} html_bytes={[Path(path).stat().st_size for path in panel.dashboard_paths.values()]}")
            self.assertEqual(set(panel.dashboard_paths), {"zh_CN", "ja_JP", "en_US"})
            dom = []
            panel.view.page().runJavaScript(
                "JSON.stringify({lang:document.documentElement.lang,plots:document.querySelectorAll('.plotly-graph-div').length,plotly:typeof Plotly})",
                dom.append)
            self._wait_for(lambda: bool(dom), timeout=10)
            self.assertEqual(json.loads(dom[-1]), {"lang": "en_US", "plots": 6, "plotly": "object"})
            feature_artifact = Path(panel.report["artifacts"]["feature_rows"])
            label_artifact = Path(panel.report["artifacts"]["evaluation_panel"])
            self.assertTrue(feature_artifact.is_file())
            self.assertTrue(label_artifact.is_file())
            window.set_language("ja_JP")
            self._wait_for(lambda: "6種類のチャート" in panel.status.text(), timeout=20)
            self.assertIn("シグナル日", panel.status.text())
            self.assertNotIn("Signal dates", panel.status.text())
            dom = []
            panel.view.page().runJavaScript("JSON.stringify(document.documentElement.lang)", dom.append)
            self._wait_for(lambda: bool(dom), timeout=10)
            self.assertEqual(json.loads(dom[-1]), "ja_JP")
            window._market_invalidated()
            self.assertIsNone(panel.manifest_path)
            self.assertFalse(panel.run_button.isEnabled())
        finally:
            window.document._dirty = False
            window.close()
            self.app.processEvents()

    def test_real_report_renders_three_localized_dashboards_with_actual_manifest_identity(self):
        manifest = self._manifest()
        report = self._report(manifest)
        report["analysis"]["correlations"] = []
        outputs = []
        for language, expected_title in (("zh_CN", "因子研究诊断"), ("ja_JP", "ファクター研究診断"),
                                         ("en_US", "Factor research diagnostics")):
            result = build_factor_dashboard(report, self.root / "factor-run", language)
            document = Path(result["path"]).read_text(encoding="utf-8")
            self.assertEqual(result["plot_count"], 6)
            self.assertIn(expected_title, document)
            self.assertIn("4502", document)
            self.assertIn("2020-08-03", document)
            self.assertIn("2020-12-18", document)
            self.assertIn("—", document)
            if language == "en_US":
                self.assertIn("not strategy NAV", document)
            self.assertIsNone(re.search(r"<script[^>]+src=[\"']https?://", document, re.I))
            outputs.append(result)
        self.assertEqual({item["language"] for item in outputs}, {"zh_CN", "ja_JP", "en_US"})

    def test_worker_stays_locked_until_its_thread_exits_and_parent_close_is_deferred(self):
        manifest = self._manifest()
        started = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        calls = {"value": 0}
        contract = self.root / "fake-run" / "contract.json"
        contract.parent.mkdir()
        contract.write_text("{}", encoding="utf-8")
        report = {"dates": ["2020-08-03", "2020-08-04"], "feature_row_count": 6,
            "evaluation_row_count": 6, "artifacts": {"contract": str(contract)}}
        window = None

        def run_fake(_service, _manifest, _recipe):
            index = calls["value"]
            calls["value"] += 1
            started[index].set()
            if not release[index].wait(10):
                raise TimeoutError("test worker release timed out")
            return report

        def dashboard_fake(_report, _output, language):
            return {"path": str(contract), "language": language}

        with patch("framework_v2.data_connection.load_api_key", return_value=None), \
             patch.object(ResearchApplicationService, "run_factor_diagnostics", run_fake), \
             patch("framework_v2.factor_report_dashboard.build_factor_dashboard", dashboard_fake):
            window = ProductWorkbench(self.root / "workspace-worker")
            panel = window.factor_research_panel
            panel._load_dashboard = lambda _language: None
            window.set_language("en_US")
            panel.set_manifest(manifest)
            window.show()
            self.assertTrue(panel.start())
            self.assertTrue(started[0].wait(5))
            self.assertTrue(panel.busy)
            self.assertFalse(panel.start())
            replacement_manifest = self.root / "replacement-manifest.json"
            replacement_manifest.write_text("{}", encoding="utf-8")
            panel.set_manifest(replacement_manifest)
            self.assertEqual(panel.manifest_path, replacement_manifest.resolve())
            self.assertIsNone(panel.report)
            close_event = QCloseEvent()
            window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            release[0].set()
            self._wait_for(lambda: not panel.busy)
            self.assertIsNone(panel.report, "a stale worker must not publish under a replacement manifest")
            self.assertEqual(panel.dashboard_paths, {})
            self.assertIn("discarded", panel.status.text().lower())
            panel.clear_manifest()
            self.assertFalse(panel.run_button.isEnabled())
            panel.set_manifest(manifest)
            self.assertTrue(panel.start(), "a completed worker must not leave a stale thread lock")
            self.assertTrue(started[1].wait(5))
            self.assertTrue(panel.busy)
            release[1].set()
            self._wait_for(lambda: not panel.busy)
            self.assertEqual(calls["value"], 2)
            window.document._dirty = False
            self.assertTrue(window.close())
            self.app.processEvents()

    def _wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.01)
        self.fail("condition did not complete before the bounded GUI-test timeout")


if __name__ == "__main__":
    unittest.main()
