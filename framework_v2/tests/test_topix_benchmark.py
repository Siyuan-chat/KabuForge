"""Artificial patched-Parquet fixtures test exact-date benchmark alignment only."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

import pandas as pd

import framework_v2.local_cache as local_cache_module
import framework_v2.price_research as price_research_module
import framework_v2.topix_benchmark as topix_module
from framework_v2.topix_benchmark import attach_local_topix, TopixBenchmarkError
from framework_v2.local_cache import load_research_bars
from framework_v2.price_research import _load_price_research_input


def report_model():
    days=[date(2020,1,6)+timedelta(days=offset) for offset in (0,1,2)]
    return {"model":"daily_bar_next_open_research_v1",
        "price_basis_semantics":{"valuation":"original raw close; price-only mark, no dividend cash model"},
        "nav":[{"at":day.isoformat(),"nav":1.0+index*.01} for index,day in enumerate(days)],
        "input_hash":"strategy-input","assumptions":["PIT unavailable"]}


class TopixBenchmarkTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (topix_module, local_cache_module, price_research_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.temporary=tempfile.TemporaryDirectory()
        self.source=Path(self.temporary.name)/"index_prices.parquet"
        self.source.write_bytes(b"isolated test cache bytes")

    def tearDown(self):
        self.temporary.cleanup()

    def test_attaches_only_exact_topix_dates_and_preserves_original_report(self):
        report=report_model()
        original=repr(report)
        frame=pd.DataFrame([
            {"date":"2020-01-06","index_code":"TOPIX","close":1700.0},
            {"date":"2020-01-07","index_code":"TOPIX","close":1710.0},
            {"date":"2020-01-08","index_code":"TOPIX","close":1725.0},
            {"date":"2020-01-06","index_code":"0028","close":99.0},
        ])
        with patch("pandas.read_parquet",return_value=frame) as reader:
            enriched=attach_local_topix(report,self.source)
        reader.assert_called_once()
        self.assertEqual(Path(reader.call_args.args[0]),self.source.resolve())
        self.assertEqual(reader.call_args.kwargs,{"columns":["date","index_code","close"],"engine":"pyarrow"})
        self.assertEqual(repr(report),original)
        self.assertEqual(enriched["benchmark_nav"],{"TOPIX":[
            {"at":"2020-01-06","nav":1700.0},
            {"at":"2020-01-07","nav":1710.0},
            {"at":"2020-01-08","nav":1725.0},
        ]})
        evidence=enriched["benchmark_provenance"]
        self.assertEqual(evidence["benchmark"],"TOPIX")
        self.assertEqual(evidence["benchmark_type"],"price_index")
        self.assertIn("dividends are not included",evidence["benchmark_value_basis"])
        self.assertEqual(evidence["aligned_date_count"],3)
        self.assertEqual(evidence["unmatched_strategy_nav_date_count"],0)
        self.assertEqual(evidence["source_file_sha256"],hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(evidence["original_strategy_report_sha256"],hashlib.sha256(
            json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode("utf-8")
        ).hexdigest())
        self.assertIn("unverified",evidence["source_availability"])
        self.assertFalse(evidence["raw_cache_copied"])

    def test_rejects_non_close_or_unknown_report_model(self):
        report=report_model(); report["model"]="daily_bar_open_with_previous_close_sizing_v2"
        with self.assertRaisesRegex(TopixBenchmarkError,"paired only with daily_bar_next_open_research_v1"):
            attach_local_topix(report,self.source)
        report=report_model(); report["price_basis_semantics"]["valuation"]="unknown"
        with self.assertRaisesRegex(TopixBenchmarkError,"does not declare raw-close"):
            attach_local_topix(report,self.source)

    def test_rejects_duplicate_dates_invalid_values_and_absent_exact_topix(self):
        report=report_model()
        duplicate=pd.DataFrame([
            {"date":"2020-01-06","index_code":"TOPIX","close":1700.0},
            {"date":"2020-01-06","index_code":"TOPIX","close":1701.0},
        ])
        with patch("pandas.read_parquet",return_value=duplicate):
            with self.assertRaisesRegex(TopixBenchmarkError,"duplicate dates"):
                attach_local_topix(report,self.source)
        invalid=pd.DataFrame([{"date":"2020-01-06","index_code":"TOPIX","close":0.0}])
        with patch("pandas.read_parquet",return_value=invalid):
            with self.assertRaisesRegex(TopixBenchmarkError,"finite and positive"):
                attach_local_topix(report,self.source)
        other=pd.DataFrame([{"date":"2020-01-06","index_code":"0028","close":1700.0}])
        with patch("pandas.read_parquet",return_value=other):
            with self.assertRaisesRegex(TopixBenchmarkError,"no exact TOPIX"):
                attach_local_topix(report,self.source)

    def test_requires_matching_dates_without_forward_fill(self):
        report=report_model()
        frame=pd.DataFrame([
            {"date":"2020-01-06","index_code":"TOPIX","close":1700.0},
            {"date":"2020-01-08","index_code":"TOPIX","close":1725.0},
        ])
        report["nav"][1]["at"]="2020-01-07"
        with patch("pandas.read_parquet",return_value=frame):
            with self.assertRaisesRegex(TopixBenchmarkError,"missing 1 of 3 strategy NAV dates.*2020-01-07"):
                attach_local_topix(report,self.source)

    def test_price_research_loader_honors_frozen_duplicate_and_halt_policies(self):
        rows=[]
        for code,base in (("4502",100),("6758",200)):
            regular={"date":"2020-09-30","code":code,"open":base,"high":base+2,
                "low":base-2,"close":base+1,"volume":1000,"adjustment_factor":1.0}
            halt={"date":"2020-10-01","code":code,"open":None,"high":None,
                "low":None,"close":None,"volume":None,"adjustment_factor":1.0}
            rows.extend([regular.copy(),regular.copy(),halt.copy(),halt.copy()])
        source=self.source.with_name("bars.csv")
        pd.DataFrame(rows).to_csv(source,index=False)
        selected=load_research_bars(source,codes=["4502","6758"],start_date="2020-09-30",
            end_date="2020-10-01",price_basis="raw",duplicate_policy="drop_identical",
            known_halt_policy="exclude_verified_tse_halt_20201001")
        frozen=selected.freeze(self.source.parent/"frozen")
        bars,identity=_load_price_research_input(frozen)
        self.assertEqual(len(bars),2)
        self.assertEqual(identity["coverage"]["duplicate_policy"],"drop_identical")
        self.assertEqual(identity["coverage"]["verified_halt_exclusion"]["date"],"2020-10-01")
        self.assertEqual(identity["pinned_selection"]["duplicate_policy"],"drop_identical")
        self.assertEqual(identity["pinned_selection"]["known_halt_policy"],"exclude_verified_tse_halt_20201001")
        self.assertFalse(identity["pit_guarantee"])


if __name__=="__main__":
    unittest.main()
