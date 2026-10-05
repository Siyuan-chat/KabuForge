"""Artificial indicator paths verify numeric/provider contracts, not market evidence."""
from __future__ import annotations

from datetime import date, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.util import find_spec
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import framework_v2.indicator_research as indicator_module
import framework_v2.local_cache as local_cache_module
from framework_v2.indicator_research import (
    IndicatorRun,
    calculate_pandas_ta_indicators,
    calculate_talib_indicators,
)


class _FakeTaLib:
    __version__ = "test-double"

    @staticmethod
    def SMA(values, *, timeperiod):
        assert values.dtype == np.float64
        return np.full(len(values), np.nan, dtype=np.float64)

    @staticmethod
    def RSI(values, *, timeperiod):
        assert values.dtype == np.float64
        return np.full(len(values), 50.0, dtype=np.float64)

    @staticmethod
    def MACD(values, *, fastperiod, slowperiod, signalperiod):
        assert values.dtype == np.float64
        assert (fastperiod, slowperiod, signalperiod) == (12, 26, 9)
        data = np.arange(len(values), dtype=np.float64)
        return data, data - 1, np.ones(len(values), dtype=np.float64)

    @staticmethod
    def ATR(high, low, close, *, timeperiod):
        assert high.dtype == low.dtype == close.dtype == np.float64
        assert timeperiod == 14
        return np.full(len(close), 2.5, dtype=np.float64)


class _NativePandasTa:
    """Records provider switches while returning finite artificial series."""

    def __init__(self):
        import pandas as pd
        self.pd = pd
        self.calls = {}

    def sma(self, close, *, length, talib):
        self.calls["sma"] = {"length": length, "talib": talib}
        return self.pd.Series(np.full(len(close), 10.0))

    def rsi(self, close, *, length, talib):
        self.calls["rsi"] = {"length": length, "talib": talib}
        values = np.full(len(close), 50.0)
        values[:length] = np.nan
        return self.pd.Series(values)

    def macd(self, close, *, fast, slow, signal, talib):
        self.calls["macd"] = {"fast": fast, "slow": slow, "signal": signal, "talib": talib}
        values = np.arange(len(close), dtype=np.float64)
        return self.pd.DataFrame({"MACD_12_26_9": values, "MACDh_12_26_9": values - 1,
                                  "MACDs_12_26_9": values / 2})

    def atr(self, high, low, close, *, length, talib, presma):
        self.calls["atr"] = {"length": length, "talib": talib, "presma": presma}
        values = np.full(len(close), 2.0)
        values[:length] = np.nan
        return self.pd.Series(values)


class IndicatorResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (indicator_module, local_cache_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")

    @staticmethod
    def bars():
        start = date(2024, 1, 1)
        return [
            {"date": (start + timedelta(days=offset)).isoformat(), "code": "72030",
             "open": 100 + offset, "high": 102 + offset, "low": 99 + offset,
             "close": 100 + offset, "adjustment_open": 200 + offset,
             "adjustment_high": 202 + offset, "adjustment_low": 199 + offset,
             "adjustment_close": 200 + offset}
            for offset in reversed(range(35))
        ]

    def test_talib_receives_float64_and_reports_identity_and_unverified_pit(self):
        with patch("framework_v2.indicator_research.metadata.version", side_effect=PackageNotFoundError):
            run = calculate_talib_indicators(self.bars(), "7203", sma_period=10, rsi_period=7,
                                              source_kind="artificial fixture", talib_module=_FakeTaLib)
        self.assertEqual(run.code, "72030")
        self.assertEqual(run.source_kind, "artificial fixture")
        self.assertFalse(run.pit_guarantee)
        self.assertEqual(run.price_field, "adjustment_close")
        self.assertEqual(run.rows[0]["date"], "2024-01-01")
        self.assertEqual(run.rows[0]["close"], 200)
        self.assertIsNone(run.rows[-1]["sma"])
        self.assertEqual(run.rows[-1]["macd_histogram"], 1.0)
        self.assertEqual(run.rows[-1]["atr"], 2.5)
        self.assertEqual(run.atr_price_field, "adjusted OHLC")
        self.assertEqual(len(run.input_sha256), 64)

    def test_ambiguous_short_code_and_insufficient_history_fail(self):
        rows = self.bars() + [{"date": "2024-03-01", "code": "72031", "close": 10}]
        with self.assertRaisesRegex(ValueError, "multiple"):
            calculate_talib_indicators(rows, "7203", talib_module=_FakeTaLib)
        with self.assertRaisesRegex(ValueError, "available bar count"):
            calculate_talib_indicators(self.bars(), "72030", sma_period=100, talib_module=_FakeTaLib)

    def test_periods_are_strict_and_atr_requires_same_basis_ohlc(self):
        with self.assertRaisesRegex(ValueError, "SMA period"):
            calculate_talib_indicators(self.bars(), "72030", sma_period=True, talib_module=_FakeTaLib)
        incomplete = [{key: value for key, value in row.items() if not key.startswith("adjustment_")}
                      for row in self.bars()]
        incomplete = [dict(row, adjustment_close=row["close"] * 2) for row in incomplete]
        with self.assertRaisesRegex(ValueError, "same-basis adjusted OHLC"):
            calculate_talib_indicators(incomplete, "72030", talib_module=_FakeTaLib)

    def test_invalid_dates_ohlc_and_nonfinite_provider_outputs_fail_closed(self):
        bad_date = self.bars()
        bad_date[0]["date"] = "2024-02-30"
        with self.assertRaisesRegex(ValueError, "ISO calendar"):
            calculate_talib_indicators(bad_date, "72030", talib_module=_FakeTaLib)
        bad_ohlc = self.bars()
        bad_ohlc[0]["adjustment_high"] = 1
        with self.assertRaisesRegex(ValueError, "same-basis OHLC"):
            calculate_talib_indicators(bad_ohlc, "72030", talib_module=_FakeTaLib)

        class InfiniteTaLib(_FakeTaLib):
            @staticmethod
            def ATR(high, low, close, *, timeperiod):
                values = np.ones(len(close))
                values[-1] = np.inf
                return values

        with self.assertRaisesRegex(ValueError, "non-finite"):
            calculate_talib_indicators(self.bars(), "72030", talib_module=InfiniteTaLib)

    def test_talib_missing_provider_has_a_specific_error(self):
        with patch("framework_v2.indicator_research.import_module", side_effect=ModuleNotFoundError("talib")):
            with self.assertRaisesRegex(ModuleNotFoundError, "talib"):
                calculate_talib_indicators(self.bars(), "72030")

    def test_pandas_ta_missing_provider_has_a_specific_error(self):
        with patch("framework_v2.indicator_research.import_module",
                   side_effect=ModuleNotFoundError("pandas_ta")):
            with self.assertRaisesRegex(ModuleNotFoundError, "pandas_ta"):
                calculate_pandas_ta_indicators(self.bars(), "72030")

    def test_pandas_ta_forces_native_functions_and_sma_seeded_atr(self):
        provider = _NativePandasTa()
        with patch("framework_v2.indicator_research.metadata.version", return_value="test-native"):
            run = calculate_pandas_ta_indicators(self.bars(), "72030", sma_period=10,
                rsi_period=7, atr_period=14, pandas_ta_module=provider)
        self.assertEqual(run.engine_name, "pandas-ta")
        self.assertEqual(run.talib_version, "test-native")
        self.assertEqual(run.atr_price_field, "adjusted OHLC")
        self.assertEqual(provider.calls, {
            "sma": {"length": 10, "talib": False},
            "rsi": {"length": 7, "talib": False},
            "macd": {"fast": 12, "slow": 26, "signal": 9, "talib": False},
            "atr": {"length": 14, "talib": False, "presma": True},
        })
        self.assertTrue(all(row["atr"] is None for row in run.rows[:14]))
        self.assertEqual(run.rows[14]["atr"], 2.0)
        self.assertFalse(run.pit_guarantee)

    def test_actual_talib_provider_or_exact_unavailable_error(self):
        if find_spec("talib") is None:
            with self.assertRaisesRegex(ModuleNotFoundError, "talib"):
                calculate_talib_indicators(self.bars(), "72030")
            return
        run = calculate_talib_indicators(self.bars(), "72030", sma_period=10, rsi_period=7)
        self.assertEqual(run.engine_name, "TA-Lib")
        self.assertFalse(run.pit_guarantee)
        self.assertAlmostEqual(run.rows[-1]["sma"], 229.5)
        self.assertGreaterEqual(run.rows[-1]["rsi"], 0.0)
        self.assertLessEqual(run.rows[-1]["rsi"], 100.0)
        self.assertGreater(run.rows[-1]["atr"], 0.0)

    def test_actual_pandas_ta_provider_or_exact_unavailable_error(self):
        if find_spec("pandas_ta") is None:
            with self.assertRaisesRegex(ModuleNotFoundError, "pandas_ta"):
                calculate_pandas_ta_indicators(self.bars(), "72030")
            return
        run: IndicatorRun = calculate_pandas_ta_indicators(
            self.bars(), "72030", sma_period=10, rsi_period=7, atr_period=14)
        self.assertEqual(run.engine_name, "pandas-ta")
        self.assertFalse(run.pit_guarantee)
        self.assertAlmostEqual(run.rows[-1]["sma"], 229.5)
        self.assertGreaterEqual(run.rows[-1]["rsi"], 0.0)
        self.assertLessEqual(run.rows[-1]["rsi"], 100.0)
        self.assertIsNone(run.rows[12]["atr"])
        self.assertAlmostEqual(run.rows[13]["atr"], 3.0)
        self.assertAlmostEqual(run.rows[14]["atr"], 3.0)
        self.assertTrue(all(row["date"] for row in run.rows))


if __name__ == "__main__":
    unittest.main()
