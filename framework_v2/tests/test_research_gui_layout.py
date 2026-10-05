"""Public product mounting, explicit-input gating, and locale invariants."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QProcess
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from framework_v2.config import ConfigError
from framework_v2.product_ui import ProductWorkbench
from framework_v2.workbench_worker import _factor_cache_summary, _write_factor_cache_failure


class ProductMountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.window = ProductWorkbench(self.workspace)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.document._dirty = False
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_public_research_panels_mount_and_market_requires_selected_source(self):
        window = self.window
        self.assertNotIn("Private Engine", window.windowTitle())
        self.assertEqual(window.template.currentData(), "market")
        self.assertIsNone(window.market_manifest)
        self.assertFalse(window.create_strategy())
        self.assertIn("选择并冻结", window.guide_summary.text())
        for name in (
            "local_cache_panel", "factor_cache_panel", "indicator_panel",
            "factor_research_panel", "research_studio_panel",
            "historical_paper_panel", "broker_research_panel",
            "price_sensitivity_panel", "integrations_panel",
        ):
            self.assertIsNotNone(getattr(window, name), name)
        self.assertEqual(window.paper_tabs.tabText(0), "本地历史研究回放")
        self.assertEqual(window.broker_tabs.tabText(0), "离线订单映射预览")
        self.assertIsNone(window.connection)
        self.assertFalse(window.connection_button.isHidden())

    def test_language_switch_preserves_recipe_inputs_and_localizes_custom_controls(self):
        window = self.window
        window.signal_template.setCurrentIndex(window.signal_template.findData("sma_crossover"))
        window.fast_period.setValue(17)
        window.slow_period.setValue(55)
        window.set_language("ja_JP")
        self.assertEqual(window.signal_template.currentData(), "sma_crossover")
        self.assertEqual(window.fast_period.value(), 17)
        self.assertEqual(window.slow_period.value(), 55)
        self.assertTrue(window.strategy_badge.text().startswith("戦略："))
        self.assertNotIn("策略", window.strategy_badge.text())
        self.assertIn("ローカルデータ", window.template.itemText(0))
        window.set_language("en_US")
        self.assertEqual(window.signal_template.currentData(), "sma_crossover")
        self.assertEqual(window.fast_period.value(), 17)
        self.assertEqual(window.slow_period.value(), 55)
        self.assertIn("local data", window.template.itemText(0))
        self.assertEqual(window.dashboard_button.text(), "Build offline interactive report")

    def test_crossover_disables_unused_count_and_frequency_then_restores_them(self):
        window = self.window
        window.holding_count.setValue(3)
        window.frequency.setCurrentIndex(window.frequency.findData("weekly"))
        window.signal_template.setCurrentIndex(window.signal_template.findData("sma_crossover"))
        self.assertFalse(window.holding_count.isEnabled())
        self.assertFalse(window.frequency.isEnabled())
        self.assertEqual(window.holding_count.value(), 1)
        self.assertEqual(window.frequency.currentData(), "daily")
        window.signal_template.setCurrentIndex(window.signal_template.findData("price_momentum"))
        self.assertTrue(window.holding_count.isEnabled())
        self.assertTrue(window.frequency.isEnabled())
        self.assertEqual(window.holding_count.value(), 3)
        self.assertEqual(window.frequency.currentData(), "weekly")

    def test_price_report_badges_and_assumptions_refresh_in_all_locales(self):
        window = self.window
        report = {
            "model": "daily_bar_next_open_research_v1",
            "recipe": {"name": "MA teaching", "signal_template": "sma_crossover"},
            "strategy_parameters": {"fast_period": 20, "slow_period": 60},
            "nav": [
                {"at": "2021-01-04", "nav": 1.0, "drawdown": 0.0},
                {"at": "2021-01-05", "nav": 1.01, "drawdown": 0.0},
                {"at": "2021-01-06", "nav": 0.99, "drawdown": -0.02},
            ],
            "trades": [], "skipped_orders": [], "fees": None,
            "benchmark_provenance": {"benchmark": "TOPIX", "adapter_version": "topix-local-close-v1"},
        }
        window.show_report(report)
        self.assertEqual(window.cutoff_badge.text(), "研究结束：2021-01-06")
        window.set_language("ja_JP")
        self.assertEqual(window.cutoff_badge.text(), "研究終了：2021-01-06")
        self.assertIn("MAクロス", window.assumptions.text())
        self.assertIn("TOPIX価格指数", window.result_summary.text())
        window.set_language("en_US")
        self.assertEqual(window.cutoff_badge.text(), "Research end: 2021-01-06")
        self.assertIn("MA crossover", window.assumptions.text())
        self.assertIn("TOPIX price index", window.result_summary.text())

    def test_attached_topix_is_rebased_on_exact_nav_dates_in_preview_without_mutating_report(self):
        report = {
            "model": "daily_bar_next_open_research_v1",
            "nav": [
                {"at": "2021-01-04", "nav": 1.0, "drawdown": 0.0},
                {"at": "2021-01-05", "nav": 1.01, "drawdown": 0.0},
                {"at": "2021-01-06", "nav": 0.99, "drawdown": -0.0198019802},
            ],
            "benchmark_nav": {"TOPIX": [
                {"at": "2021-01-04", "nav": 100.0},
                {"at": "2021-01-05", "nav": 110.0},
                {"at": "2021-01-06", "nav": 105.0},
            ]},
            "benchmark_provenance": {"benchmark": "TOPIX", "adapter_version": "topix-local-close-v1"},
        }
        original = copy.deepcopy(report)
        self.window.set_language("en_US")
        self.window.show_report(report)
        self.assertEqual(self.window.nav_chart.dates, [row["at"] for row in report["nav"]])
        self.assertEqual(self.window.nav_chart.series, [
            ("Strategy NAV", [1.0, 1.01, 0.99]),
            ("TOPIX price index (no dividends; first date rebased to 1)", [1.0, 1.1, 1.05]),
        ])
        self.assertEqual(self.window.drawdown_chart.series[1], (
            "TOPIX drawdown", [0.0, 0.0, 1.05 / 1.1 - 1.0]))
        self.assertEqual(report, original)
        self.assertEqual(self.window.report, original)

    def test_missing_or_misaligned_topix_never_adds_a_preview_curve(self):
        base = {
            "model": "daily_bar_next_open_research_v1",
            "nav": [
                {"at": "2021-01-04", "nav": 1.0, "drawdown": 0.0},
                {"at": "2021-01-05", "nav": 1.01, "drawdown": 0.0},
                {"at": "2021-01-06", "nav": 0.99, "drawdown": -0.02},
            ],
        }
        cases = [
            copy.deepcopy(base),
            {**copy.deepcopy(base), "benchmark_nav": {"TOPIX": [
                {"at": "2021-01-04", "nav": 100.0}, {"at": "2021-01-06", "nav": 105.0}]},
             "benchmark_provenance": {"benchmark": "TOPIX", "adapter_version": "topix-local-close-v1"}},
            {**copy.deepcopy(base), "benchmark_nav": {"SYNTHETIC": [
                {"at": "2021-01-04", "nav": 100.0}, {"at": "2021-01-05", "nav": 102.0},
                {"at": "2021-01-06", "nav": 105.0}]},
             "benchmark_provenance": {"benchmark": "SYNTHETIC", "adapter_version": "synthetic-v1"}},
            {**copy.deepcopy(base), "benchmark_nav": {"TOPIX": [
                {"at": "2021-01-04", "nav": 100.0}, {"at": "2021-01-05", "nav": 0.0},
                {"at": "2021-01-06", "nav": 105.0}]},
             "benchmark_provenance": {"benchmark": "TOPIX", "adapter_version": "topix-local-close-v1"}},
            {**copy.deepcopy(base), "benchmark_nav": {"TOPIX": [
                {"at": "2021-01-04", "nav": 1e-308}, {"at": "2021-01-05", "nav": 1e308},
                {"at": "2021-01-06", "nav": 1e-307}]},
             "benchmark_provenance": {"benchmark": "TOPIX", "adapter_version": "topix-local-close-v1"}},
        ]
        for report in cases:
            with self.subTest(provenance=report.get("benchmark_provenance")):
                original = copy.deepcopy(report)
                self.window.show_report(report)
                self.assertEqual(len(self.window.nav_chart.series), 1)
                self.assertEqual(len(self.window.drawdown_chart.series), 1)
                self.assertEqual(report, original)

    def test_factor_cache_summary_and_failure_are_visible_and_localized(self):
        panel = self.window.factor_cache_panel
        panel.toggle.setChecked(False)
        panel.show_summary({"enabled": False, "stats": {"hits": 0, "misses": 0,
            "writes": 0, "corrupt": 0}, "namespace_identity": None})
        self.assertIn("关闭", panel.status.text())

        tracker = SimpleNamespace(hits=2, misses=1, writes=1, corrupt=0,
            lookups=3, namespace="kabuforge.public_workbench_factor_cache.v1",
            namespace_identity="a" * 64)
        summary = _factor_cache_summary(tracker, Path(self.workspace.name) / "cache.sqlite")
        self.assertEqual(summary["stats"], {"hits": 2, "misses": 1, "writes": 1, "corrupt": 0})
        self.assertEqual(summary["namespace_identity"], "a" * 64)
        panel.show_summary(summary)
        self.assertIn("命中 2", panel.status.text())
        self.assertIn("aaaaaaaaaaaaaaaa", panel.status.text())
        panel.set_language("ja_JP")
        self.assertIn("ヒット 2", panel.status.text())
        panel.set_language("en_US")
        self.assertIn("hits 2", panel.status.text())

        job_root = self.workspace / "jobs" / "job-1"
        output_root = job_root / "output" / "job-1"
        output_root.mkdir(parents=True)
        failure_summary = {**summary, "stats": {"hits": 0, "misses": 0,
            "writes": 0, "corrupt": 1}}
        receipt_path = _write_factor_cache_failure(output_root, job_root,
            {"job_id": "job-1"}, failure_summary, ValueError("corrupt factor cache payload"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["stats"]["corrupt"], 1)
        self.assertFalse(receipt["fallback_recompute"])
        panel.show_failure(receipt_path)
        panel.set_language("ja_JP")
        self.assertIn("再計算していません", panel.status.text())
        panel.set_language("en_US")
        self.assertIn("no recompute fallback", panel.status.text())

        outside = self.workspace / "outside"
        outside.mkdir()
        with self.assertRaises(ConfigError):
            _write_factor_cache_failure(outside, job_root, {"job_id": "escape"},
                failure_summary, ValueError("test"))

    def test_parent_close_is_denied_while_owned_panel_worker_is_active(self):
        class RunningProcess:
            @staticmethod
            def state():
                return QProcess.ProcessState.Running

        self.window.price_sensitivity_panel.process = RunningProcess()
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.nav.currentRow(), 3)
        self.window.price_sensitivity_panel.process = None

    def test_jquants_connection_is_created_only_on_explicit_button_action(self):
        window = self.window
        self.assertIsNone(window.connection)
        with patch("framework_v2.data_connection.load_api_key", return_value=None) as load_key:
            panel = window._open_jquants_connection()
        load_key.assert_called_once_with()
        self.assertIs(panel, window.connection)
        self.assertTrue(window.connection_button.isHidden())
        self.assertFalse(panel.busy)


if __name__ == "__main__":
    unittest.main()
