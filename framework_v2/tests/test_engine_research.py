"""Artificial price paths test replay semantics; no fixture is a market benchmark."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import framework_v2.engine_research as engine_research_module
import framework_v2.local_cache as local_cache_module
import framework_v2.price_research as price_research_module
from framework_v2.engine_research import (
    DEFAULT_RECIPE,
    EngineResearchError,
    _backtrader_replay,
    _compare,
    _vectorbt_replay,
    run_engine_research,
)
from framework_v2.local_cache import load_research_bars
from framework_v2.price_research import research_bars


def _market_rows(dates: list[str], prices: dict[str, list[float]],
                 opens: dict[str, list[float]] | None = None) -> list[dict]:
    opens = opens or prices
    rows = []
    for code, closes in prices.items():
        for index, day in enumerate(dates):
            opened = float(opens[code][index])
            close = float(closes[index])
            rows.append({"date": day, "code": code, "open": opened,
                "high": max(opened, close) * 1.01, "low": min(opened, close) * 0.99,
                "close": close, "volume": 1000.0, "adjustment_factor": 1.0,
                "adjustment_close": close})
    return rows


def _freeze_csv(root: Path, rows: list[dict], codes: list[str]) -> Path:
    source = root / "bars.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loaded = load_research_bars(source, codes=codes,
        start_date=min(row["date"] for row in rows),
        end_date=max(row["date"] for row in rows), price_basis="raw")
    return loaded.freeze(root / "frozen-bars")


class EngineResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (engine_research_module, local_cache_module, price_research_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.tmp = tempfile.TemporaryDirectory(prefix="engine-research-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_native_rejects_split_period_and_incomplete_common_calendar(self):
        dates = ["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06"]
        rows = _market_rows(dates, {"4502": [10, 11, 12, 13], "6758": [10, 11, 12, 13]})
        split_rows = [dict(row, adjustment_factor=(2.0 if row["date"] == dates[-1] else 1.0))
                      for row in rows]
        recipe = {**DEFAULT_RECIPE, "lookback": 2, "count": 1, "frequency": "daily"}
        with self.assertRaisesRegex(ValueError, "Split-adjusted periods"):
            research_bars(split_rows, recipe)
        missing = [row for row in rows if not (row["code"] == "6758" and row["date"] == dates[1])]
        with self.assertRaisesRegex(ValueError, "Incomplete common calendar"):
            research_bars(missing, recipe)

    def test_comparison_flags_different_fill_price_and_fee_when_account_totals_match(self):
        timeline = [{"at": "2022-01-04", "cash": 949.95, "equity": 999.95,
                     "nav": .99995, "fees": .05, "cumulative_fees": .05,
                     "positions": [{"code": "4502", "quantity": 5.0}]}]
        native = {"backend": "native", "timeline": timeline, "fees": .05,
            "fills": [{"date": "2022-01-04", "code": "4502", "side": "buy",
                       "quantity": 5.0, "price": 10.0, "fee": .05}], "skips": []}
        other = {"backend": "vectorbt", "timeline": [dict(timeline[0])], "fees": .055,
            "fills": [{"date": "2022-01-04", "code": "4502", "side": "buy",
                       "quantity": 5.0, "price": 11.0, "fee": .055}], "skips": []}
        comparison = _compare(native, other, {"absolute": 1e-8, "relative": 0.0})
        self.assertTrue(comparison["daily_account_within_tolerance"])
        self.assertFalse(comparison["execution_stream_matches"])
        self.assertEqual(comparison["status"], "EXECUTION_STREAM_DIFFERENCES")
        self.assertEqual({"price", "fee"},
                         set(comparison["fill_differences"][0]["differences"]))

    def test_vectorbt_actual_shared_cash_sells_before_buys(self):
        if importlib.util.find_spec("vectorbt") is None:
            with self.assertRaisesRegex(EngineResearchError, "optional VectorBT runtime unavailable"):
                _vectorbt_replay([], [], [], [], 1000.0, .001)
            return
        dates = ["2022-01-03", "2022-01-04", "2022-01-05"]
        rows = _market_rows(dates, {"4502": [10, 10, 10], "6758": [10, 10, 12]},
            {"4502": [10, 10, 12], "6758": [10, 10, 12]})
        schedule = [
            {"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
             "side": "buy", "quantity": 50.0, "sizing_price": 10.0},
            {"signal_date": dates[1], "execution_date": dates[2], "code": "4502",
             "side": "sell", "quantity": 50.0, "sizing_price": 10.0},
            {"signal_date": dates[1], "execution_date": dates[2], "code": "6758",
             "side": "buy", "quantity": 50.0, "sizing_price": 10.0},
        ]
        result, runtime = _vectorbt_replay(rows, dates, ["4502", "6758"], schedule, 1000.0, .001)
        self.assertEqual(runtime["backend"], "vectorbt")
        self.assertEqual([(fill["date"], fill["code"], fill["side"]) for fill in result["fills"]],
                         [(dates[1], "4502", "buy"), (dates[2], "4502", "sell"),
                          (dates[2], "6758", "buy")])
        self.assertEqual(result["skips"], [])
        self.assertAlmostEqual(result["timeline"][-1]["cash"], 498.3, places=6)

    def test_backtrader_actual_shared_cash_sells_before_buys(self):
        if importlib.util.find_spec("backtrader") is None:
            with self.assertRaisesRegex(EngineResearchError, "optional Backtrader runtime unavailable"):
                _backtrader_replay([], [], [], [], 1000.0, .001)
            return
        dates = ["2022-01-03", "2022-01-04", "2022-01-05"]
        rows = _market_rows(dates, {"4502": [10, 10, 10], "6758": [10, 10, 12]},
            {"4502": [10, 10, 12], "6758": [10, 10, 12]})
        schedule = [
            {"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
             "side": "buy", "quantity": 50.0, "sizing_price": 10.0},
            {"signal_date": dates[1], "execution_date": dates[2], "code": "4502",
             "side": "sell", "quantity": 50.0, "sizing_price": 10.0},
            {"signal_date": dates[1], "execution_date": dates[2], "code": "6758",
             "side": "buy", "quantity": 50.0, "sizing_price": 10.0},
        ]
        result, runtime = _backtrader_replay(rows, dates, ["4502", "6758"], schedule, 1000.0, .001)
        self.assertEqual(runtime["backend"], "backtrader")
        self.assertFalse(runtime["cheat_on_close"])
        self.assertEqual([(fill["date"], fill["code"], fill["side"]) for fill in result["fills"]],
                         [(dates[1], "4502", "buy"), (dates[2], "4502", "sell"),
                          (dates[2], "6758", "buy")])
        self.assertEqual(result["skips"], [])
        self.assertAlmostEqual(result["timeline"][-1]["cash"], 498.3, places=5)

    def test_backtrader_rejected_prior_buy_cannot_turn_frozen_sell_into_short(self):
        if importlib.util.find_spec("backtrader") is None:
            with self.assertRaisesRegex(EngineResearchError, "optional Backtrader runtime unavailable"):
                _backtrader_replay([], [], [], [], 1000.0, .001)
            return
        dates = ["2022-01-03", "2022-01-04", "2022-01-05"]
        rows = _market_rows(dates, {"4502": [10, 10, 10]}, {"4502": [10, 30, 10]})
        schedule = [
            {"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
             "side": "buy", "quantity": 50.0, "sizing_price": 10.0},
            {"signal_date": dates[1], "execution_date": dates[2], "code": "4502",
             "side": "sell", "quantity": 50.0, "sizing_price": 10.0},
        ]
        result, _runtime = _backtrader_replay(rows, dates, ["4502"], schedule, 1000.0, .001)
        self.assertEqual(result["fills"], [])
        self.assertEqual(len(result["skips"]), 2)
        self.assertEqual(result["skips"][1]["observed_status"], "no_sufficient_long_position")
        self.assertTrue(all(position["quantity"] >= 0
                            for item in result["timeline"] for position in item["positions"]))

    def test_actual_engine_replays_record_native_gap_skip_and_preregister_contract(self):
        if importlib.util.find_spec("vectorbt") is None:
            with self.assertRaisesRegex(EngineResearchError, "optional VectorBT runtime unavailable"):
                _vectorbt_replay([], [], [], [], 1000.0, .001)
            return
        if importlib.util.find_spec("backtrader") is None:
            with self.assertRaisesRegex(EngineResearchError, "optional Backtrader runtime unavailable"):
                _backtrader_replay([], [], [], [], 1000.0, .001)
            return
        dates = ["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06", "2022-01-07"]
        closes = {"4502": [10, 11, 12, 14, 15], "6758": [10, 9, 8, 7, 6]}
        opens = {"4502": [10, 11, 12, 30, 14], "6758": [10, 9, 8, 7, 6]}
        manifest = _freeze_csv(self.root, _market_rows(dates, closes, opens), ["4502", "6758"])
        out = self.root / "replay"
        recipe = {**DEFAULT_RECIPE, "cash": 1000.0, "lookback": 2,
                  "count": 1, "frequency": "daily"}
        receipt_path = run_engine_research(manifest, out, recipe)
        self.assertEqual(receipt_path.resolve(), (out / "receipt.json").resolve())
        contract = json.loads((out / "contract.json").read_text(encoding="utf-8"))
        frozen = json.loads((out / "frozen_order_schedule.json").read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["status"], "PREREGISTERED")
        self.assertFalse(contract["pit_guarantee"])
        self.assertFalse(frozen["pit_guarantee"])
        self.assertEqual(frozen["schedule_sha256"], receipt["order_schedule_sha256"])
        native = json.loads((out / "native.json").read_text(encoding="utf-8"))
        first_gap_day = dates[3]
        self.assertTrue(any(item["execution_date"] == first_gap_day
                            for item in native["skips"]))
        for backend in ("vectorbt", "backtrader"):
            self.assertEqual(receipt["backend_status"][backend]["status"], "COMPLETED",
                             receipt["backend_status"][backend])
            result = json.loads((out / f"{backend}.json").read_text(encoding="utf-8"))
            self.assertFalse(result["pit_guarantee"])
            self.assertTrue(any(item.get("execution_date") == first_gap_day
                                for item in result["skips"]))
            self.assertEqual(result["order_schedule_sha256"], frozen["schedule_sha256"])
            self.assertEqual(len(result["timeline"]), len(dates))
            self.assertTrue(all(item["at"] in dates for item in result["timeline"]))
            comparison = json.loads((out / f"comparison_{backend}.json").read_text(encoding="utf-8"))
            self.assertIn(comparison["status"], {
                "MATCHED_WITHIN_TOLERANCE", "EXECUTION_STREAM_DIFFERENCES", "FINANCIAL_DIFFERENCES"})


if __name__ == "__main__":
    unittest.main()
