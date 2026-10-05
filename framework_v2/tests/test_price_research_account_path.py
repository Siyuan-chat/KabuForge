"""Artificial bars verify account evidence without changing the price replay."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import unittest

import framework_v2.price_research as price_research_module
from framework_v2.price_research import research_bars


def bars(count=18, *, opening_gap=None):
    rows=[]
    day=date(2024,1,1)
    closes=[100,101,102,103,104,105,103,106,108,107,110,111,109,112,114,113,116,118]
    for index in range(count):
        while day.weekday()>=5: day+=timedelta(days=1)
        close=closes[index]
        open_price=(opening_gap if index==3 and opening_gap is not None else close)
        rows.append({"code":"4502","date":day.isoformat(),"open":float(open_price),"close":float(close),
                     "adjustment_factor":1.0})
        day+=timedelta(days=1)
    return rows


def recipe(template="price_momentum"):
    return {"signal_template":template,"count":1,"frequency":"daily","cash":1000.0,"fee":0.1,
            "lookback":2,"fast_period":2,"slow_period":3,"signal_provider":"native"}


class PriceResearchAccountPathTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[2]
        self.assertTrue(Path(price_research_module.__file__).resolve().is_relative_to(project_root),
                        f"test imported non-candidate implementation: {price_research_module.__file__}")

    def test_momentum_emits_complete_account_orders_skip_fees_and_one_way_turnover(self):
        report=research_bars(bars(opening_gap=1000.0),recipe())
        self.assertEqual(len(report["account_path"]),len(report["nav"]))
        self.assertEqual(len(report["daily_turnover"]),len(report["nav"]))
        self.assertEqual(len(report["order_schedule"]),len(report["trades"])+len(report["skipped_orders"]))
        skipped=report["skipped_orders"][0]
        self.assertEqual(skipped["signal_date"],report["nav"][2]["at"])
        self.assertEqual(skipped["execution_date"],report["nav"][3]["at"])
        self.assertGreater(skipped["cash_shortfall"],0)
        self.assertEqual(skipped["open_price"],1000.0)
        self.assertEqual(skipped["quantity"],report["order_schedule"][0]["quantity"],
                         "the D-1 sized quantity must survive an opening-gap skip")
        self.assertEqual(report["account_path"][3]["fees"],0.0)
        self.assertEqual(report["daily_turnover"][3]["gross_traded_turnover"],0.0)
        self.assertTrue(report["account_path"][-1]["positions"])
        self.assertAlmostEqual(sum(item["weight"] for item in report["account_path"][-1]["positions"])
                               +report["account_path"][-1]["cash_weight"],1.0,places=10)
        self.assertIn("both sides included",report["daily_turnover"][3]["basis"])
        self.assertAlmostEqual(sum(item["fees"] for item in report["account_path"]),report["fees"])
        self.assertAlmostEqual(report["account_path"][-1]["cumulative_fees"],report["fees"])

    def test_account_enrichment_preserves_the_price_momentum_financial_stream(self):
        report=research_bars(bars(),recipe())
        payload={key:report[key] for key in ("nav","trades","fees")}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
            ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        self.assertEqual(digest,"47929a0ee2d699a0c0f48ee830eb26eceadfa5d7e46dd2ba6b4c6744e48961fa")

    def test_ma_and_momentum_both_emit_daily_fee_and_turnover_evidence(self):
        for template in ("price_momentum","sma_crossover"):
            with self.subTest(template=template):
                report=research_bars(bars(),recipe(template))
                self.assertEqual(len(report["account_path"]),len(report["nav"]))
                self.assertEqual(len(report["daily_turnover"]),len(report["nav"]))
                self.assertEqual(sum(row["fees"] for row in report["account_path"]),report["fees"])
                self.assertTrue(all(row["denominator_prior_close_equity"]>0 for row in report["daily_turnover"]))
                self.assertTrue(any("gross traded turnover" in item for item in report["assumptions"]))


if __name__=="__main__":
    unittest.main()
