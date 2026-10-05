"""Artificial report fixtures verify summary methodology and missing evidence."""
from __future__ import annotations

import unittest
from pathlib import Path

import framework_v2.report_analysis as report_analysis_module
from framework_v2.report_analysis import summarize_report


class ReportAnalysisTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        self.assertTrue(Path(report_analysis_module.__file__).resolve().is_relative_to(project_root),
                        f"test imported non-candidate implementation: {report_analysis_module.__file__}")

    def test_uses_explicit_initial_nav_and_marks_first_month_partial_without_it(self):
        report = {"nav": [
            {"at": "2024-01-15", "nav": 1.0, "cash": 500},
            {"at": "2024-01-31", "nav": 1.1, "cash": 400},
            {"at": "2024-02-29", "nav": 1.2, "cash": 300},
        ]}
        partial = summarize_report(report)
        self.assertIsNone(partial["period_return"])
        self.assertAlmostEqual(partial["observed_window_return"], 0.2)
        self.assertIn("start_partial", partial["monthly_returns"][0]["coverage"])
        self.assertEqual(partial["monthly_returns"][0]["start_at"], "2024-01-15")
        self.assertEqual(partial["monthly_returns"][0]["end_at"], "2024-01-31")
        report.update(nav_base_includes_initial=True, initial_nav=1.0, initial_at="2024-01-01T09:00:00+09:00")
        complete = summarize_report(report)
        self.assertAlmostEqual(complete["period_return"], 0.2)
        self.assertAlmostEqual(complete["annualized_return"], 1.2 ** (365.2425 / 59) - 1)
        self.assertIn("initial_capital_to_month_end_observed", complete["monthly_returns"][0]["coverage"])
        self.assertEqual(complete["monthly_returns"][0]["start_at"], "2024-01-01")
        self.assertIn("calendar_month_end_observed_trading_day_completeness_unverified", complete["monthly_returns"][0]["coverage"])
        self.assertIsNone(complete["annualized_volatility"])
        self.assertFalse(complete["benchmark_available"])

    def test_annualized_risk_requires_declared_frequency_and_zero_vol_sharpe_is_missing(self):
        report = {
            "nav": [{"at": f"2024-01-{day:02}", "nav": 1.0, "drawdown": 0.0, "cash": 100} for day in (1, 2, 3)],
            "nav_base_includes_initial": True, "initial_nav": 1.0, "initial_at": "2024-01-01",
            "nav_frequency": "daily", "fees": 12.5,
        }
        summary = summarize_report(report)
        self.assertEqual(summary["annualized_volatility"], 0.0)
        self.assertIsNone(summary["sharpe"])
        self.assertEqual(summary["sharpe_reason"], "zero observed return volatility")
        self.assertEqual(summary["fees"], 12.5)
        self.assertEqual(summary["latest_cash"], 100)
        self.assertEqual(summary["drawdown_basis"], "reported NAV drawdown series")

    def test_explicit_initial_nav_is_used_as_ratio_for_annualization(self):
        report = {
            "nav": [{"at": "2024-01-01", "nav": 2.5}, {"at": "2025-01-01", "nav": 3.0}],
            "nav_base_includes_initial": True, "initial_nav": 2.0, "initial_at": "2024-01-01",
        }
        summary = summarize_report(report)
        self.assertAlmostEqual(summary["period_return"], 0.5)
        self.assertAlmostEqual(summary["annualized_return"], 1.5 ** (365.2425 / 366) - 1)

    def test_invalid_initial_nav_does_not_assume_normalized_unit_base(self):
        report = {
            "nav": [{"at": "2024-01-01", "nav": 2.0}, {"at": "2024-02-01", "nav": 2.2}],
            "nav_base_includes_initial": True, "initial_at": "2024-01-01",
        }
        summary = summarize_report(report)
        self.assertIsNone(summary["period_return"])
        self.assertIsNone(summary["annualized_return"])
        self.assertEqual(summary["return_basis"], "first to last displayed NAV only")
        self.assertTrue(any("no normalized NAV default" in item for item in summary["warnings"]))

    def test_invalid_fee_and_overflowed_return_are_not_reported_as_complete_risk(self):
        report = {
            "nav": [{"at": "2024-01-01", "nav": 1e-308}, {"at": "2024-01-02", "nav": 1e308},
                    {"at": "2024-01-03", "nav": 1.1e308}],
            "nav_frequency": "daily", "fees": "Infinity",
        }
        summary = summarize_report(report)
        self.assertIsNone(summary["fees"])
        self.assertEqual(summary["fees_reason"], "fee value is invalid")
        self.assertIsNone(summary["annualized_volatility"])
        self.assertIsNone(summary["sharpe"])
        self.assertIn("invalid or overflowed", summary["annualized_volatility_reason"])
        self.assertEqual(summary["sharpe_reason"], "a return is invalid or overflowed")

    def test_missing_fee_evidence_duplicate_dates_and_incomplete_drawdown_are_reported(self):
        report = {"nav": [
            {"at": "2024-01-01", "nav": 1.0, "drawdown": 0.0},
            {"at": "2024-01-02", "nav": 0.8},
            {"at": "2024-01-02", "nav": 0.9},
        ], "trades": [{"price": 10, "quantity": 1}]}
        summary = summarize_report(report)
        self.assertIsNone(summary["fees"])
        self.assertIn("fee", summary["fees_reason"])
        self.assertEqual(summary["drawdown_basis"], "displayed NAV window only")
        self.assertAlmostEqual(summary["max_drawdown"], -0.1)
        self.assertTrue(any("Duplicate NAV date" in warning for warning in summary["warnings"]))
        self.assertTrue(any("drawdown series is incomplete" in warning for warning in summary["warnings"]))


if __name__ == "__main__":
    unittest.main()
