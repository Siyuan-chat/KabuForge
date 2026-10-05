"""Artificial account-path fixtures test evidence-gated contribution accounting."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from importlib.util import find_spec

import framework_v2.report_account_analysis as account_analysis_module
import framework_v2.report_dashboard as dashboard_module
from framework_v2.report_account_analysis import analyze_account_path
from framework_v2.report_dashboard import dependency_status


def reconciled_report():
    return {
        "initial_equity": 100.0,
        "account_path": [
            {"at":"2024-01-02","cash":89.0,"equity":101.0,"position_universe":["A"],"fees":1.0,
             "positions":[{"code":"A","quantity":1.0,"mark_price":12.0,"market_value":12.0,"weight":12/101}]},
            {"at":"2024-01-03","cash":89.0,"equity":103.0,"position_universe":["A"],"fees":0.0,
             "positions":[{"code":"A","quantity":1.0,"mark_price":14.0,"market_value":14.0,"weight":14/103}]},
            {"at":"2024-01-04","cash":101.0,"equity":101.0,"position_universe":["A"],"fees":1.0,"positions":[]},
        ],
        "trades":[
            {"date":"2024-01-02","code":"A","side":"buy","quantity":1.0,"price":10.0,"fee":1.0},
            {"date":"2024-01-04","code":"A","side":"sell","quantity":1.0,"price":13.0,"fee":1.0},
        ],
    }


class ReportAccountAnalysisTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (account_analysis_module, dashboard_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")

    def test_daily_contributions_reconcile_and_holdings_metrics_are_evidence_based(self):
        result=analyze_account_path(reconciled_report())
        self.assertTrue(result["available"],result["reason"])
        self.assertEqual([row["security_count"] for row in result["holdings"]],[1,1,0])
        self.assertAlmostEqual(result["holdings"][0]["security_hhi"],(12/101)**2)
        self.assertAlmostEqual(result["holdings"][2]["cash_weight"],1.0)
        self.assertAlmostEqual(result["per_security_daily"]["A"][0],2.0)
        self.assertAlmostEqual(result["per_security_daily"]["A"][1],2.0)
        self.assertAlmostEqual(result["per_security_daily"]["A"][2],-1.0)
        self.assertAlmostEqual(result["reconciliation"]["nav_change"],0.01)
        self.assertAlmostEqual(result["reconciliation"]["contribution_change"],0.01)
        self.assertLess(result["reconciliation"]["max_daily_equity_residual"],1e-9)

    def test_missing_price_universe_or_fee_evidence_never_defaults_to_zero(self):
        report=reconciled_report()
        report["account_path"][0]["positions"][0].pop("mark_price")
        result=analyze_account_path(report)
        self.assertFalse(result["available"])
        self.assertIn("price evidence",result["reason"])

        report=reconciled_report()
        report["account_path"][1].pop("position_universe")
        self.assertFalse(analyze_account_path(report)["available"])

        report=reconciled_report()
        report["account_path"][0]["fees"]=None
        self.assertFalse(analyze_account_path(report)["available"])

    def test_wrong_account_equity_or_market_value_reconciliation_is_unavailable(self):
        report=reconciled_report()
        report["account_path"][1]["equity"]+=0.25
        result=analyze_account_path(report)
        self.assertFalse(result["available"])
        self.assertTrue(any(word in result["reason"] for word in ("reconcile","conflicts")))

        report=reconciled_report()
        report["account_path"][0]["positions"][0]["market_value"]=999
        result=analyze_account_path(report)
        self.assertFalse(result["available"])
        self.assertIn("conflicts",result["reason"])

    def test_dashboard_adds_actual_concentration_and_reconciled_contribution_figures(self):
        if find_spec("plotly") is None:
            with self.assertRaisesRegex(ModuleNotFoundError, "plotly"):
                __import__("plotly.graph_objects")
            return
        import plotly.graph_objects as go
        from framework_v2.report_dashboard import _build_figures, _strategy_series
        report=reconciled_report()
        report.update({"model":"daily_bar_next_open_research_v1","nav_frequency":"daily",
            "nav_base_includes_initial":True,"initial_nav":1.0,"initial_at":"2024-01-02",
            "nav":[{"at":row["at"],"nav":row["equity"]/100,"drawdown":None}
                   for row in report["account_path"]]})
        dates_observed,return_dates,returns,_=_strategy_series(report)
        class Plots:
            def snapshot(self,title):
                figure=go.Figure(); figure.update_layout(title=title); return figure
        figures,_=_build_figures(report,return_dates,returns,[],2,None,
            SimpleNamespace(plots=Plots()),"en_US")
        self.assertEqual(len(figures),17)
        concentration=figures[13]
        self.assertEqual([trace.name for trace in concentration.data],
            ["Held securities","Maximum security weight","Security-weight HHI"])
        self.assertEqual(list(concentration.data[0].y),[1,1,0])
        contribution=figures[14]
        self.assertEqual(len(contribution.data),3)
        self.assertAlmostEqual(float(contribution.data[-1].y[-1]),.01)
        self.assertEqual(contribution.layout.paper_bgcolor,"#0D1117")
        self.assertIn("Verified frozen bars",figures[15].layout.annotations[0].text)
        self.assertIn("No qualified historical reconstruction timeline",figures[16].layout.annotations[0].text)


if __name__ == "__main__":
    unittest.main()
