"""Optional price-indicator calculations for explicit GUI research runs."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module, metadata
import hashlib
import json
import math
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class IndicatorRun:
    code: str
    source_kind: str
    pit_guarantee: bool
    talib_version: str
    sma_period: int
    rsi_period: int
    price_field: str
    input_sha256: str
    rows: tuple[dict, ...]
    atr_period: int = 14
    engine_name: str = "TA-Lib"
    atr_price_field: str = "original raw OHLC"


def calculate_talib_indicators(
    bars: Iterable[dict], code: str, *, sma_period: int = 20, rsi_period: int = 14, atr_period: int = 14,
    source_kind: str = "J-Quants downloaded bars; historical visibility unverified", talib_module=None,
) -> IndicatorRun:
    """Calculate trailing SMA/RSI/MACD from one code's ordered daily bars.

    This is a research display, not a strategy signal or execution instruction.
    Downloaded J-Quants bars remain current API views without verified
    ``available_at`` and therefore cannot carry a strict PIT guarantee.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("A security code is required")
    if type(sma_period) is not int or not 2 <= sma_period <= 500:
        raise ValueError("SMA period must be between 2 and 500")
    if type(rsi_period) is not int or not 2 <= rsi_period <= 100:
        raise ValueError("RSI period must be between 2 and 100")
    if type(atr_period) is not int or not 2 <= atr_period <= 100:
        raise ValueError("ATR period must be between 2 and 100")
    requested = code.strip()
    all_rows = list(bars)
    exact = [row for row in all_rows if str(row.get("code", "")) == requested]
    selected_rows = exact or [row for row in all_rows if len(requested) == 4 and len(str(row.get("code", ""))) == 5 and str(row.get("code", "")).startswith(requested)]
    matched_codes = {str(row.get("code", "")) for row in selected_rows}
    if len(matched_codes) > 1:
        raise ValueError("Security code matches multiple 5-character codes; enter the full code")
    code = next(iter(matched_codes), requested)
    if not selected_rows:
        raise ValueError("No bars matched the requested security code")
    selected = sorted(selected_rows, key=lambda row: str(row.get("date", "")))
    if sma_period > len(selected) or rsi_period > len(selected) or atr_period > len(selected):
        raise ValueError("Indicator period exceeds the available bar count")
    if len(selected) < 35:
        raise ValueError("Not enough daily bars for SMA, RSI, MACD, and ATR warm-up")
    dates = [str(row.get("date", "")) for row in selected]
    from datetime import date
    if any(not value for value in dates) or len(set(dates)) != len(dates):
        raise ValueError("Bars must have unique, non-empty dates")
    try:
        if any(date.fromisoformat(value).isoformat() != value for value in dates):
            raise ValueError
    except ValueError:
        raise ValueError("Bars must use valid ISO calendar dates") from None
    price_field = "adjustment_close" if all(row.get("adjustment_close") is not None for row in selected) else "close"
    closes = []
    atr_opens, atr_highs, atr_lows, atr_closes = [], [], [], []
    for row in selected:
        value = row.get(price_field)
        try:
            close = float(value)
        except (TypeError, ValueError):
            raise ValueError("Every bar must have a numeric close") from None
        if not math.isfinite(close) or close <= 0:
            raise ValueError("Every bar close must be finite and positive")
        closes.append(close)
        if price_field == "adjustment_close":
            fields = ("adjustment_open", "adjustment_high", "adjustment_low", "adjustment_close")
            error = "Adjusted-price indicators require a complete same-basis adjusted OHLC record"
        else:
            fields = ("open", "high", "low", "close")
            error = "Raw-price indicators require a complete original raw OHLC record"
        try:
            open_price, high, low, atr_close = (float(row[field]) for field in fields)
        except (KeyError, TypeError, ValueError):
            raise ValueError(error) from None
        if (not all(math.isfinite(value) and value > 0 for value in (open_price, high, low, atr_close))
                or high < max(open_price, atr_close) or low > min(open_price, atr_close) or high < low):
            raise ValueError("ATR requires valid same-basis OHLC bars with high/low enclosing open and close")
        atr_opens.append(open_price); atr_highs.append(high); atr_lows.append(low); atr_closes.append(atr_close)

    talib = talib_module or import_module("talib")
    close_array = np.asarray(closes, dtype=np.float64)
    sma = talib.SMA(close_array, timeperiod=sma_period)
    rsi = talib.RSI(close_array, timeperiod=rsi_period)
    macd, macd_signal, macd_hist = talib.MACD(close_array, fastperiod=12, slowperiod=26, signalperiod=9)
    atr = talib.ATR(np.asarray(atr_highs, dtype=np.float64), np.asarray(atr_lows, dtype=np.float64),
                    np.asarray(atr_closes, dtype=np.float64), timeperiod=atr_period)

    def finite_or_none(value):
        number = float(value)
        if math.isnan(number):
            return None
        if not math.isfinite(number):
            raise ValueError("TA-Lib returned a non-finite indicator value")
        return number

    values = tuple(np.asarray(value, dtype=np.float64) for value in (sma, rsi, macd, macd_signal, macd_hist, atr))
    if any(len(column) != len(selected) for column in values):
        raise ValueError("TA-Lib returned an unexpected result length")
    sma, rsi, macd, macd_signal, macd_hist, atr = values
    result_rows = tuple({
        "date": dates[index], "code": code.strip(), "close": closes[index],
        "sma": finite_or_none(sma[index]), "rsi": finite_or_none(rsi[index]),
        "macd": finite_or_none(macd[index]), "macd_signal": finite_or_none(macd_signal[index]),
        "macd_histogram": finite_or_none(macd_hist[index]), "atr": finite_or_none(atr[index]),
    } for index in range(len(selected)))
    try:
        version = metadata.version("TA-Lib")
    except metadata.PackageNotFoundError:
        version = str(getattr(talib, "__version__", "unknown"))
    identity_payload = json.dumps(
        [{"date": dates[index], "code": code, "price_field": price_field,
          "close": closes[index], "atr_open": atr_opens[index], "atr_high": atr_highs[index],
          "atr_low": atr_lows[index], "atr_close": atr_closes[index]}
         for index in range(len(selected))], sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return IndicatorRun(code, source_kind, False, version, sma_period, rsi_period, price_field,
                        hashlib.sha256(identity_payload).hexdigest(), result_rows, atr_period,
                        "TA-Lib", "adjusted OHLC" if price_field == "adjustment_close" else "original raw OHLC")


def calculate_pandas_ta_indicators(
    bars: Iterable[dict], code: str, *, sma_period: int = 20, rsi_period: int = 14,
    atr_period: int = 14,
    source_kind: str = "J-Quants downloaded bars; historical visibility unverified",
    pandas_ta_module=None,
) -> IndicatorRun:
    """Calculate the same price-only panel with pandas-ta in an isolated worker."""
    import numpy as np
    from importlib import metadata

    if type(sma_period) is not int or not 2 <= sma_period <= 500:
        raise ValueError("SMA period must be between 2 and 500")
    if type(rsi_period) is not int or not 2 <= rsi_period <= 100:
        raise ValueError("RSI period must be between 2 and 100")
    if type(atr_period) is not int or not 2 <= atr_period <= 100:
        raise ValueError("ATR period must be between 2 and 100")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("A security code is required")
    requested = code.strip()
    all_rows = list(bars)
    exact = [row for row in all_rows if str(row.get("code", "")) == requested]
    selected_rows = exact or [row for row in all_rows if len(requested) == 4 and
                              len(str(row.get("code", ""))) == 5 and str(row.get("code", "")).startswith(requested)]
    matched_codes = {str(row.get("code", "")) for row in selected_rows}
    if len(matched_codes) > 1:
        raise ValueError("Security code matches multiple 5-character codes; enter the full code")
    code = next(iter(matched_codes), requested)
    if not selected_rows:
        raise ValueError("No bars matched the requested security code")
    selected = sorted(selected_rows, key=lambda row: str(row.get("date", "")))
    if sma_period > len(selected) or rsi_period > len(selected) or atr_period > len(selected):
        raise ValueError("Indicator period exceeds the available bar count")
    if len(selected) < 35:
        raise ValueError("Not enough daily bars for SMA, RSI, MACD, and ATR warm-up")
    dates = [str(row.get("date", "")) for row in selected]
    from datetime import date
    if any(not value for value in dates) or len(set(dates)) != len(dates):
        raise ValueError("Bars must have unique, non-empty dates")
    try:
        if any(date.fromisoformat(value).isoformat() != value for value in dates):
            raise ValueError
    except ValueError:
        raise ValueError("Bars must use valid ISO calendar dates") from None

    price_field = "adjustment_close" if all(row.get("adjustment_close") is not None for row in selected) else "close"
    closes, atr_opens, atr_highs, atr_lows, atr_closes = [], [], [], [], []
    for row in selected:
        if price_field == "adjustment_close":
            fields = ("adjustment_open", "adjustment_high", "adjustment_low", "adjustment_close")
            error = "Adjusted-price indicators require a complete same-basis adjusted OHLC record"
        else:
            fields = ("open", "high", "low", "close")
            error = "Raw-price indicators require a complete original raw OHLC record"
        try:
            close = float(row[price_field]); open_price, high, low, atr_close = (float(row[field]) for field in fields)
        except (KeyError, TypeError, ValueError):
            raise ValueError(error) from None
        if (not all(math.isfinite(value) and value > 0 for value in (close, open_price, high, low, atr_close))
                or high < max(open_price, atr_close) or low > min(open_price, atr_close) or high < low):
            raise ValueError("Indicators require finite positive prices and valid same-basis OHLC bars")
        closes.append(close); atr_opens.append(open_price); atr_highs.append(high)
        atr_lows.append(low); atr_closes.append(atr_close)

    ta = pandas_ta_module or import_module("pandas_ta")
    import pandas as pd
    close_series = pd.Series(closes, dtype="float64")
    high_series = pd.Series(atr_highs, dtype="float64")
    low_series = pd.Series(atr_lows, dtype="float64")
    # Pin every provider to pandas-ta's Python implementation even when TA-Lib
    # happens to be installed in the isolated extension runtime.
    sma = ta.sma(close_series, length=sma_period, talib=False)
    rsi = ta.rsi(close_series, length=rsi_period, talib=False)
    macd_frame = ta.macd(close_series, fast=12, slow=26, signal=9, talib=False)
    atr_close_series = pd.Series(atr_closes, dtype="float64")
    # pandas-ta ATR's native default is RMA with presma=True. Pass it
    # explicitly so an installed TA-Lib cannot silently change the method.
    atr = ta.atr(high_series, low_series, atr_close_series, length=atr_period,
                 talib=False, presma=True)
    if sma is None or rsi is None or macd_frame is None or atr is None:
        raise ValueError("pandas-ta returned no indicator values")
    macd_columns = {str(column).upper(): column for column in macd_frame.columns}
    def pick(prefix: str):
        matches = [column for name, column in macd_columns.items() if name.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"pandas-ta MACD result missing unique {prefix} field")
        return macd_frame[matches[0]].to_numpy(dtype=np.float64)

    values = [item.to_numpy(dtype=np.float64) if hasattr(item, "to_numpy") else np.asarray(item, dtype=np.float64)
              for item in (sma, rsi)]
    macd, macd_hist, macd_signal = pick("MACD_"), pick("MACDH_"), pick("MACDS_")
    atr_values = atr.to_numpy(dtype=np.float64) if hasattr(atr, "to_numpy") else np.asarray(atr, dtype=np.float64)
    arrays = [*values, macd, macd_signal, macd_hist, atr_values]
    if any(len(column) != len(selected) for column in arrays):
        raise ValueError("pandas-ta returned an unexpected result length")

    def finite_or_none(value):
        number = float(value)
        if math.isnan(number):
            return None
        if not math.isfinite(number):
            raise ValueError("pandas-ta returned a non-finite indicator value")
        return number

    result_rows = tuple({
        "date": dates[index], "code": code, "close": closes[index],
        "sma": finite_or_none(arrays[0][index]), "rsi": finite_or_none(arrays[1][index]),
        "macd": finite_or_none(macd[index]), "macd_signal": finite_or_none(macd_signal[index]),
        "macd_histogram": finite_or_none(macd_hist[index]), "atr": finite_or_none(atr_values[index]),
    } for index in range(len(selected)))
    version = metadata.version("pandas-ta")
    identity_payload = json.dumps(
        [{"date": dates[index], "code": code, "price_field": price_field, "close": closes[index],
          "atr_open": atr_opens[index], "atr_high": atr_highs[index], "atr_low": atr_lows[index],
          "atr_close": atr_closes[index]}
         for index in range(len(selected))], sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return IndicatorRun(code, source_kind, False, version, sma_period, rsi_period, price_field,
                        hashlib.sha256(identity_payload).hexdigest(), result_rows, atr_period,
        "pandas-ta", "adjusted OHLC" if price_field == "adjustment_close" else "original raw OHLC")
