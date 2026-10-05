"""Offline, D-1 daily-bar factor diagnostics with separately sealed labels.

The service consumes one explicit frozen local research-bars manifest. It has
no network, directory discovery, dynamic imports, factor cache, or strategy
order side effects. All results remain RESEARCH-ONLY with PIT unverified.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from typing import Any

import numpy as np
import pandas as pd

from . import local_cache
from .local_cache import load_research_bars
from .local_io import write_new


RECIPE_SCHEMA = "kabuforge.factor_research_recipe.v1"
DEFAULT_RECIPE: dict[str, Any] = {
    "schema": RECIPE_SCHEMA,
    "label": {"horizon_sessions": 5},
    "minimum_cross_section": 3,
    "quantiles": 3,
    "factors": [{"id": "price_momentum", "windows": [20, 60]}],
    "composition": {
        "normalization": "rank",
        "missing_policy": "complete_case",
        "weights": {"price_momentum_20": 0.5, "price_momentum_60": 0.5},
    },
}
_FACTOR_IDS = {"price_momentum", "ma_distance", "volatility", "rsi"}


class FactorResearchError(ValueError):
    """An explicit local factor-research contract was violated."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FactorResearchError(f"recipe or identity is not finite JSON: {type(exc).__name__}") from None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise FactorResearchError(f"{label} must be finite numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FactorResearchError(f"{label} must be finite numeric") from None
    if not math.isfinite(number):
        raise FactorResearchError(f"{label} must be finite numeric")
    return number


def _int_range(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise FactorResearchError(f"{label} must be an integer in [{low}, {high}]")
    return value


def validate_recipe(recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a fresh, strict recipe document; unknown executable fields fail closed."""
    value = json.loads(json.dumps(DEFAULT_RECIPE)) if recipe is None else recipe
    if not isinstance(value, dict):
        raise FactorResearchError("recipe must be a JSON object")
    allowed = {"schema", "label", "minimum_cross_section", "quantiles", "factors", "composition"}
    if set(value) != allowed:
        raise FactorResearchError(f"recipe fields must be exactly {sorted(allowed)}")
    if value.get("schema") != RECIPE_SCHEMA:
        raise FactorResearchError("unsupported factor research recipe schema")
    label = value.get("label")
    if not isinstance(label, dict) or set(label) != {"horizon_sessions"}:
        raise FactorResearchError("label must contain only horizon_sessions")
    horizon = _int_range(label["horizon_sessions"], "horizon_sessions", 1, 252)
    minimum = _int_range(value.get("minimum_cross_section"), "minimum_cross_section", 3, 10000)
    quantiles = _int_range(value.get("quantiles"), "quantiles", 2, 20)
    if minimum < quantiles:
        raise FactorResearchError("minimum_cross_section must be at least quantiles")
    factors = value.get("factors")
    if not isinstance(factors, list) or not factors:
        raise FactorResearchError("factors must be a non-empty list")
    normalized_factors = []
    names = []
    for item in factors:
        if not isinstance(item, dict) or set(item) != {"id", "windows"}:
            raise FactorResearchError("each factor requires exactly id and windows")
        factor_id = item["id"]
        if factor_id not in _FACTOR_IDS:
            raise FactorResearchError(f"unsupported factor id: {factor_id!r}")
        windows = item["windows"]
        if not isinstance(windows, list) or not windows:
            raise FactorResearchError("factor windows must be a non-empty list")
        parsed = [_int_range(window, f"{factor_id} window", 2, 500) for window in windows]
        if len(set(parsed)) != len(parsed):
            raise FactorResearchError(f"duplicate {factor_id} windows are not allowed")
        normalized_factors.append({"id": factor_id, "windows": parsed})
        names.extend(f"{factor_id}_{window}" for window in parsed)
    if len(set(names)) != len(names):
        raise FactorResearchError("factor windows must produce unique feature names")
    composition = value.get("composition")
    if not isinstance(composition, dict) or set(composition) != {"normalization", "missing_policy", "weights"}:
        raise FactorResearchError("composition requires normalization, missing_policy, and weights")
    normalization = composition["normalization"]
    if normalization not in {"rank", "zscore"}:
        raise FactorResearchError("composition normalization must be rank or zscore")
    missing_policy = composition["missing_policy"]
    if missing_policy not in {"complete_case", "neutral_zero"}:
        raise FactorResearchError("composition missing_policy must be complete_case or neutral_zero")
    weights = composition["weights"]
    if not isinstance(weights, dict) or not weights or set(weights) - set(names):
        raise FactorResearchError("composition weights must map known feature names")
    parsed_weights = {str(name): _finite_number(weight, f"weight {name}")
                      for name, weight in weights.items()}
    if not any(weight != 0.0 for weight in parsed_weights.values()):
        raise FactorResearchError("at least one composition weight must be nonzero")
    return {
        "schema": RECIPE_SCHEMA,
        "label": {"horizon_sessions": horizon},
        "minimum_cross_section": minimum,
        "quantiles": quantiles,
        "factors": normalized_factors,
        "composition": {"normalization": normalization,
                         "missing_policy": missing_policy,
                         "weights": parsed_weights},
    }


def _feature_names(recipe: dict[str, Any]) -> list[str]:
    return [f"{item['id']}_{window}" for item in recipe["factors"] for window in item["windows"]]


def _wilder_rsi(prices: np.ndarray, window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(prices)
    if len(prices) <= window:
        return result
    changes = np.diff(prices)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)
    average_gain = float(gains[:window].mean())
    average_loss = float(losses[:window].mean())

    def value(gain: float, loss: float) -> float:
        if gain == 0.0 and loss == 0.0:
            return 50.0
        if loss == 0.0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    result[window] = value(average_gain, average_loss)
    for index in range(window + 1, len(prices)):
        change_index = index - 1
        average_gain = ((window - 1) * average_gain + float(gains[change_index])) / window
        average_loss = ((window - 1) * average_loss + float(losses[change_index])) / window
        result[index] = value(average_gain, average_loss)
    return result


def _build_rows(bars: pd.DataFrame, recipe: dict[str, Any]) -> list[dict[str, Any]]:
    required = {"date", "code", "open", "close", "selected_price", "selected_price_basis"}
    if not required.issubset(bars.columns):
        raise FactorResearchError(f"frozen bars lack fields: {sorted(required - set(bars.columns))}")
    if bars.empty:
        raise FactorResearchError("frozen bars are empty")
    frame = bars.copy(deep=True).sort_values(["code", "date"], kind="stable").reset_index(drop=True)
    if frame.duplicated(["code", "date"]).any():
        raise FactorResearchError("duplicate security/date rows reached factor service")
    calendars = {str(code): tuple(group["date"].astype(str))
                 for code, group in frame.groupby("code", sort=True)}
    reference_calendar = next(iter(calendars.values()))
    mismatched = [code for code, calendar in calendars.items() if calendar != reference_calendar]
    if mismatched:
        raise FactorResearchError(
            f"factor research requires a complete common observed-date calendar; mismatched codes: {mismatched}")
    rows: list[dict[str, Any]] = []
    horizon = recipe["label"]["horizon_sessions"]
    for code, group in frame.groupby("code", sort=True):
        group = group.sort_values("date", kind="stable").reset_index(drop=True)
        dates = group["date"].astype(str).tolist()
        selected = pd.to_numeric(group["selected_price"], errors="coerce").to_numpy(dtype=float)
        opens = pd.to_numeric(group["open"], errors="coerce").to_numpy(dtype=float)
        if (not np.isfinite(selected).all() or not np.isfinite(opens).all()
                or (selected <= 0).any() or (opens <= 0).any()):
            raise FactorResearchError(f"selected price and raw open must be positive finite values: {code}")
        feature_arrays: dict[str, list[float | None]] = {}
        for factor in recipe["factors"]:
            for window in factor["windows"]:
                name = f"{factor['id']}_{window}"
                values: list[float | None] = [None] * len(selected)
                if factor["id"] == "price_momentum":
                    for index in range(window, len(selected)):
                        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                            values[index] = float(selected[index] / selected[index - window] - 1.0)
                elif factor["id"] == "ma_distance":
                    for index in range(window - 1, len(selected)):
                        sample = selected[index - window + 1:index + 1]
                        scale = float(np.max(sample))
                        average = float(scale * np.mean(sample / scale))
                        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                            values[index] = float(selected[index] / average - 1.0)
                elif factor["id"] == "volatility":
                    returns = np.full(len(selected), np.nan, dtype=float)
                    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                        returns[1:] = selected[1:] / selected[:-1] - 1.0
                    for index in range(window, len(selected)):
                        values[index] = float(np.std(returns[index - window + 1:index + 1], ddof=1))
                elif factor["id"] == "rsi":
                    values = _wilder_rsi(selected, window)
                if any(value is not None and not math.isfinite(float(value)) for value in values):
                    raise FactorResearchError(f"non-finite feature calculation: {name} for {code}")
                feature_arrays[name] = values
        for index, signal_date in enumerate(dates):
            execution_index = index + 1
            label_end_index = execution_index + horizon if execution_index < len(dates) else None
            entry_open = float(opens[execution_index]) if execution_index < len(dates) else None
            exit_open = float(opens[label_end_index]) if label_end_index is not None and label_end_index < len(dates) else None
            if execution_index >= len(dates):
                label_status = "no_next_observed_open"
            elif exit_open is None:
                label_status = "insufficient_future_horizon"
            else:
                label_status = "available"
            row = {
                "code": str(code), "signal_date": signal_date,
                "d1_cutoff_date": signal_date,
                "execution_date": dates[execution_index] if execution_index < len(dates) else None,
                "label_start_date": dates[execution_index] if execution_index < len(dates) else None,
                "label_end_date": dates[label_end_index] if label_end_index is not None and label_end_index < len(dates) else None,
                "selected_price_basis": str(group.iloc[index]["selected_price_basis"]),
            }
            for name, values in feature_arrays.items():
                value = values[index]
                row[name] = float(value) if value is not None and math.isfinite(float(value)) else None
            if entry_open is not None and exit_open is not None:
                with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                    forward_return = float(exit_open / entry_open - 1.0)
                if not math.isfinite(forward_return):
                    raise FactorResearchError(
                        f"non-finite forward label calculation: {code} at {signal_date}")
                row["forward_return"] = forward_return
            else:
                row["forward_return"] = None
            row["label_status"] = label_status
            rows.append(row)
    rows.sort(key=lambda row: (row["signal_date"], row["code"]))
    return rows


def _tie_counts(values: list[float]) -> dict[str, int]:
    counts = Counter(values)
    tied_groups = [count for count in counts.values() if count > 1]
    return {"tie_group_count": len(tied_groups),
            "tied_observation_count": sum(tied_groups),
            "tied_pair_count": sum(count * (count - 1) // 2 for count in tied_groups)}


def _rank_normalize(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=float, index=values.index)
    count = len(values)
    ranks = values.rank(method="average", ascending=True)
    if count == 1:
        return pd.Series(0.0, index=values.index, dtype=float)
    return (ranks - (count + 1.0) / 2.0) / (count - 1.0)


def _safe_mean(values: list[float], label: str) -> float:
    if not values:
        raise FactorResearchError(f"cannot calculate mean of empty {label}")
    scale = max(abs(float(value)) for value in values)
    if not math.isfinite(scale):
        raise FactorResearchError(f"non-finite value in {label}")
    if scale == 0.0:
        return 0.0
    result = float(scale * np.mean(np.asarray(values, dtype=float) / scale))
    if not math.isfinite(result):
        raise FactorResearchError(f"non-finite mean for {label}")
    return result


def _compose(rows: list[dict[str, Any]], recipe: dict[str, Any]) -> None:
    composition = recipe["composition"]
    weights = composition["weights"]
    names = [name for name, weight in weights.items() if weight != 0.0]
    max_abs_weight = max(abs(weights[name]) for name in names)
    scaled_weights = {name: weights[name] / max_abs_weight for name in names}
    weight_denominator = math.fsum(abs(weight) for weight in scaled_weights.values())
    if not math.isfinite(weight_denominator) or weight_denominator <= 0:
        raise FactorResearchError("composition weight normalization is not finite and positive")
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["signal_date"]].append(row)
    for date_rows in by_date.values():
        normalized: dict[str, dict[str, float | None]] = {}
        for name in names:
            valid_rows = [row for row in date_rows if row.get(name) is not None]
            values = pd.Series({row["code"]: float(row[name]) for row in valid_rows}, dtype=float)
            if composition["normalization"] == "rank":
                series = _rank_normalize(values)
            elif values.empty:
                series = pd.Series(dtype=float)
            else:
                scale = float(np.max(np.abs(values.to_numpy(dtype=float))))
                scaled_values = values / scale if scale > 0 else values * 0.0
                deviation = float(scaled_values.std(ddof=0))
                series = ((scaled_values - float(scaled_values.mean())) / deviation
                          if deviation > 0 and math.isfinite(deviation) else scaled_values * 0.0)
            if not np.isfinite(series.to_numpy(dtype=float)).all():
                raise FactorResearchError(f"non-finite normalized component: {name}")
            normalized[name] = {str(code): float(value) for code, value in series.items()}
        for row in date_rows:
            available = [normalized[name].get(row["code"]) for name in names]
            present = [value is not None for value in available]
            if composition["missing_policy"] == "complete_case" and not all(present):
                row["composite_score"] = None
                row["composite_status"] = "missing_component_complete_case"
                continue
            if not any(present):
                row["composite_score"] = None
                row["composite_status"] = "no_available_components"
                continue
            score = math.fsum(scaled_weights[name] * (0.0 if value is None else value)
                              for name, value in zip(names, available)) / weight_denominator
            if not math.isfinite(score):
                raise FactorResearchError("non-finite composition score")
            row["composite_score"] = float(score)
            row["composite_status"] = ("neutral_zero_missing" if not all(present) else "complete")


def _stable_buckets(rows: list[dict[str, Any]], field: str, quantiles: int) -> tuple[dict[str, int], dict[str, Any], bool]:
    values = [float(row[field]) for row in rows]
    ties = _tie_counts(values)
    constant = len(set(values)) <= 1
    ordered = sorted(rows, key=lambda row: (float(row[field]), row["code"]))
    assignment = {row["code"]: min(quantiles, ((rank * quantiles) // len(ordered)) + 1)
                  for rank, row in enumerate(ordered)}
    value_buckets: dict[float, set[int]] = defaultdict(set)
    for row in ordered:
        value_buckets[float(row[field])].add(assignment[row["code"]])
    split_ties = any(len(buckets) > 1 for buckets in value_buckets.values())
    return assignment, ties, constant or split_ties


def _correlation(left: list[float], right: list[float], *, rank: bool) -> float | None:
    if len(left) < 2 or len(set(left)) <= 1 or len(set(right)) <= 1:
        return None
    x = pd.Series(left, dtype=float)
    y = pd.Series(right, dtype=float)
    if rank:
        x = x.rank(method="average")
        y = y.rank(method="average")
    result = float(x.corr(y, method="pearson"))
    return result if math.isfinite(result) else None


def _analyze(rows: list[dict[str, Any]], feature_names: list[str], recipe: dict[str, Any],
             selected_codes: list[str]) -> dict[str, Any]:
    minimum, quantiles = recipe["minimum_cross_section"], recipe["quantiles"]
    analysis_names = [*feature_names, "composite_score"]
    dates = sorted({row["signal_date"] for row in rows})
    by_date = {day: [row for row in rows if row["signal_date"] == day] for day in dates}
    factor_results: dict[str, Any] = {}
    for name in analysis_names:
        daily = []
        top_by_day: dict[str, set[str] | None] = {}
        for day in dates:
            day_rows = by_date[day]
            feature_rows = [row for row in day_rows if row.get(name) is not None]
            labeled = [row for row in feature_rows if row.get("forward_return") is not None]
            values_all = [float(row[name]) for row in feature_rows]
            constant_all = bool(values_all) and len(set(values_all)) == 1
            ties_all = _tie_counts(values_all) if values_all else {
                "tie_group_count": 0, "tied_observation_count": 0, "tied_pair_count": 0}
            values = [float(row[name]) for row in labeled]
            returns = [float(row["forward_return"]) for row in labeled]
            n = len(labeled)
            constant = bool(values) and len(set(values)) == 1
            label_constant = bool(returns) and len(set(returns)) == 1
            status = "ok"
            ic = rank_ic = None
            if len(feature_rows) < minimum:
                status = "insufficient_feature_cross_section"
            elif constant_all:
                status = "constant_factor_no_information"
            elif n < minimum:
                status = "insufficient_labeled_cross_section"
            elif constant:
                status = "constant_factor_no_information"
            elif label_constant:
                status = "constant_forward_label"
            else:
                ic = _correlation(values, returns, rank=False)
                rank_ic = _correlation(values, returns, rank=True)
                if ic is None or rank_ic is None:
                    status = "undefined_correlation"
            quantile_rows = []
            tie_info = {"tie_group_count": 0, "tied_observation_count": 0, "tied_pair_count": 0}
            tie_split = False
            if n >= minimum:
                assignment, tie_info, tie_split = _stable_buckets(labeled, name, quantiles)
                for bucket in range(1, quantiles + 1):
                    members = [row for row in labeled if assignment[row["code"]] == bucket]
                    avg_return = (_safe_mean([row["forward_return"] for row in members],
                                             f"bucket returns {name}/{day}/{bucket}")
                                  if members and not constant else None)
                    quantile_rows.append({"bucket": bucket, "members": len(members),
                        "mean_forward_return": avg_return,
                        "status": "constant_factor_no_information" if constant else
                                 ("ok" if members else "empty_bucket"),
                        "codes": [row["code"] for row in members]})
            elif n:
                quantile_rows.append({"status": "insufficient_labeled_cross_section", "members": n})
            record = {
                "signal_date": day, "selected_universe_count": len(selected_codes),
                "observed_code_count": len(day_rows), "feature_valid_count": len(feature_rows),
                "label_valid_count": n,
                "feature_coverage": len(feature_rows) / len(selected_codes) if selected_codes else None,
                "label_coverage": n / len(selected_codes) if selected_codes else None,
                "ic": ic, "rank_ic": rank_ic, "status": status,
                "factor_constant": constant_all,
                **ties_all,
                "label_status_counts": dict(Counter(row["label_status"] for row in day_rows)),
                "quantile_tie_group_count": tie_info["tie_group_count"],
                "quantile_tied_observation_count": tie_info["tied_observation_count"],
                "quantile_tied_pair_count": tie_info["tied_pair_count"],
                "tie_split_across_buckets": tie_split,
                "quantiles_are_deterministic_display_only": bool(tie_split or constant),
                "quantile_returns": quantile_rows,
            }
            daily.append(record)
            if len(feature_rows) < minimum or constant_all:
                top_by_day[day] = None
            else:
                assignment, _, _ = _stable_buckets(feature_rows, name, quantiles)
                top_by_day[day] = {row["code"] for row in feature_rows
                                   if assignment[row["code"]] == quantiles}
        turnover = []
        previous_day = None
        for day in dates:
            current = top_by_day[day]
            previous = top_by_day.get(previous_day) if previous_day is not None else None
            if current is None:
                value, reason = None, "no_valid_current_top_bucket"
            elif previous is None:
                value, reason = None, "no_valid_previous_top_bucket"
            else:
                overlap = len(current & previous)
                value, reason = 1.0 - overlap / len(current), None
            turnover.append({"signal_date": day, "previous_signal_date": previous_day,
                "previous_top_count": len(previous) if previous is not None else None,
                "current_top_count": len(current) if current is not None else None,
                "overlap_count": len(current & previous) if current is not None and previous is not None else None,
                "turnover": float(value) if value is not None else None,
                "status": "ok" if reason is None else reason,
                "definition": "1 - overlap_count/current_top_count; null when either top bucket is unavailable"})
            previous_day = day
        valid_ic = [item["ic"] for item in daily if item["ic"] is not None]
        valid_rank = [item["rank_ic"] for item in daily if item["rank_ic"] is not None]
        valid_turnover = [item["turnover"] for item in turnover if item["turnover"] is not None]
        quantile_summary = []
        for bucket in range(1, quantiles + 1):
            observations = [q["mean_forward_return"] for day in daily
                            for q in day["quantile_returns"]
                            if q.get("bucket") == bucket and q.get("mean_forward_return") is not None]
            quantile_summary.append({"bucket": bucket, "valid_days": len(observations),
                                     "equal_weight_daily_mean_return": _safe_mean(observations, f"daily bucket returns {bucket}") if observations else None})
        annual = []
        for year in sorted({day[:4] for day in dates}):
            year_days = [item for item in daily if item["signal_date"].startswith(year)]
            ics = [item["ic"] for item in year_days if item["ic"] is not None]
            ranks = [item["rank_ic"] for item in year_days if item["rank_ic"] is not None]
            annual.append({"year": year, "days": len(year_days), "valid_ic_days": len(ics),
                "mean_ic": float(np.mean(ics)) if ics else None,
                "mean_rank_ic": float(np.mean(ranks)) if ranks else None,
                "diagnostic_only": True})
        factor_results[name] = {
            "daily": daily, "turnover": turnover, "annual_descriptive": annual,
            "summary": {"dates": len(dates), "valid_ic_days": len(valid_ic),
                "mean_ic": float(np.mean(valid_ic)) if valid_ic else None,
                "mean_rank_ic": float(np.mean(valid_rank)) if valid_rank else None,
                "ic_win_rate": float(np.mean(np.asarray(valid_ic) > 0)) if valid_ic else None,
                "descriptive_icir": (float(np.mean(valid_ic) / np.std(valid_ic, ddof=1))
                    if len(valid_ic) > 1 and float(np.std(valid_ic, ddof=1)) > 0 else None),
                "descriptive_icir_definition": (
                    "mean daily IC / sample standard deviation of daily IC; nonannualized, "
                    "not a t-statistic or inferential statistic; labels overlap"),
                "mean_top_bucket_turnover": float(np.mean(valid_turnover)) if valid_turnover else None,
                "quantile_returns_equal_weight_daily": quantile_summary,
                "small_cross_section_warning": len(selected_codes) <= quantiles,
            "statistical_inference": "not performed; small selected universe and overlapping labels"},
        }
    correlations = []
    for left_index, left in enumerate(analysis_names):
        for right in analysis_names[left_index + 1:]:
            daily_corr = []
            for day in dates:
                paired = [row for row in by_date[day]
                          if row.get(left) is not None and row.get(right) is not None]
                x = [float(row[left]) for row in paired]
                y = [float(row[right]) for row in paired]
                value = _correlation(x, y, rank=True) if len(paired) >= minimum else None
                daily_corr.append({"signal_date": day, "paired_code_count": len(paired),
                    "spearman_correlation": value,
                    "status": "ok" if value is not None else
                        ("insufficient_same_date_same_code_pairs" if len(paired) < minimum else "constant_factor")})
            valid = [row["spearman_correlation"] for row in daily_corr if row["spearman_correlation"] is not None]
            correlations.append({"left": left, "right": right, "daily": daily_corr,
                "valid_dates": len(valid),
                "mean_daily_spearman": float(np.mean(valid)) if valid else None,
                "pairing": "same signal_date and same security code only"})
    return {"factors": factor_results, "correlations": correlations,
            "small_universe": len(selected_codes) <= quantiles,
            "quantile_tie_policy": "sort factor value ascending, then security code ascending; deterministic display, not an alpha tie-break"}


def _provider_identity() -> dict[str, Any]:
    source = Path(__file__).resolve()
    return {"id": "kabuforge.local_daily_factor_research", "version": "1",
        "source_sha256": _sha256(source.read_bytes()),
        "local_cache_loader_source_sha256": _sha256(Path(local_cache.__file__).resolve().read_bytes()),
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
        "algorithms": {"rsi": "Wilder smoothing; zero-loss=100; flat=50",
            "volatility": "sample standard deviation (ddof=1) of trailing simple daily returns"}}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    raise FactorResearchError(f"unsupported artifact value type: {type(value).__name__}")


def _load_frozen_input(path: Path):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FactorResearchError("frozen local-input manifest cannot be read") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != "kabuforge_local_research_bars":
        raise FactorResearchError("factor research requires one frozen local-research-bars manifest")
    selection = manifest.get("selection")
    if not isinstance(selection, dict):
        raise FactorResearchError("frozen local-input selection is missing")
    if selection.get("price_basis") != "raw":
        raise FactorResearchError("factor labels currently require the frozen raw price basis")
    bars = load_research_bars(path,
        codes=selection.get("requested_codes", ()),
        start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
        price_basis=selection.get("price_basis", ""),
        duplicate_policy=selection.get("duplicate_policy", "reject"),
        known_halt_policy=selection.get("known_halt_policy", "reject"))
    if "adjustment_factor" not in bars.bars:
        raise FactorResearchError("raw-open labels require adjustment_factor coverage to screen split changes")
    factors = pd.to_numeric(bars.bars["adjustment_factor"], errors="coerce")
    factor_values = factors.to_numpy(dtype=float)
    if (factors.isna().any() or not np.isfinite(factor_values).all()
            or (factor_values <= 0).any()):
        raise FactorResearchError("adjustment_factor must be complete, finite, and positive for split screening")
    for code, group in bars.bars.assign(_factor=factors).groupby("code", sort=True):
        if group["_factor"].nunique(dropna=False) != 1:
            raise FactorResearchError(f"split-adjusted raw-open label is unsupported for changing adjustment_factor: {code}")
    native_compatible = bool(np.equal(factor_values, 1.0).all())
    details = bars.source.get("details", {})
    original = details.get("original_source", {})
    identity = {
        "manifest_path": str(path), "manifest_sha256": _sha256(path.read_bytes()),
        "manifest_kind": manifest["kind"], "source_sha256": bars.source["source_sha256"],
        "original_source_sha256": original.get("source_sha256"),
        "selected_data_sha256": bars.selected_data_sha256,
        "selection_identity_sha256": bars.identity_sha256,
        "pinned_identity_sha256": details.get("pinned_identity_sha256"),
        "selection": bars.selection, "coverage": manifest.get("coverage"),
        "revalidated_coverage": bars.coverage,
        "corporate_action_compatibility": {
            "complete_finite_positive_factor": True,
            "constant_within_each_code": True,
            "native_price_research_compatible": native_compatible,
            "statement": ("adjustment_factor is 1.0 for every selected bar"
                if native_compatible else
                "factor-only input: adjustment_factor is constant per code but not 1.0; not Native price-research compatible"),
        },
        "pit_guarantee": False,
        "availability_statement": "historical available_at is unverified; none was inferred",
    }
    return bars, identity


def run_factor_research(manifest_path: str | Path, output_dir: str | Path,
                        recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run an explicit local factor diagnostic into a new, non-overwriting directory.

    ``contract.json`` is written before any forward labels are constructed. The
    feature artifact never contains forward returns; labels live in a separate
    evaluation panel and are not inputs to composite scoring.
    """
    recipe_value = validate_recipe(recipe)
    recipe_hash = _sha256(_canonical_json(recipe_value))
    source_path = Path(manifest_path).expanduser().resolve(strict=True)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise FactorResearchError("output_dir must be a new directory")
    bars, input_identity = _load_frozen_input(source_path)
    provider = _provider_identity()
    contract = {
        "schema": "kabuforge.factor_research_contract.v1", "status": "PREREGISTERED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe": recipe_value, "recipe_sha256": recipe_hash,
        "provider_identity": provider, "input_identity": input_identity,
        "purpose": "engineering and descriptive factor research only",
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "forbidden_inferences": ["not strategy validation", "not paper readiness", "not OOS evidence",
            "no direction or parameter selection from observed returns"],
        "clock": {"feature_cutoff": "signal-date close; signal date is D-1 relative to execution",
            "entry": "next observed session raw open", "label_exit": "raw open h sessions after entry",
            "label_formula": "open[entry_index+horizon_sessions] / open[entry_index] - 1"},
        "composition": "uses features only; never reads forward_return",
        "tie_policy": "stable code ordering for deterministic display; not an alpha tie-break",
        "label_policy": "tail rows remain in evaluation panel with null label and explicit status",
        "statistics": "daily cross-sections are descriptive; overlapping labels and small universe preclude inferential claims",
    }
    target.mkdir(parents=True, exist_ok=False)
    write_new(target / "contract.json", contract)
    try:
        rows = _build_rows(bars.bars, recipe_value)
        _compose(rows, recipe_value)
        feature_fields = ["code", "signal_date", "d1_cutoff_date", "execution_date",
                          "selected_price_basis", *_feature_names(recipe_value),
                          "composite_score", "composite_status"]
        feature_rows = [{key: row.get(key) for key in feature_fields}
                        for row in rows if row.get("execution_date") is not None
                        and row.get("composite_score") is not None]
        evaluation_fields = ["code", "signal_date", "d1_cutoff_date", "execution_date",
            "label_start_date", "label_end_date", "selected_price_basis",
            *_feature_names(recipe_value), "composite_score", "composite_status",
            "forward_return", "label_status"]
        evaluation_rows = [{key: row.get(key) for key in evaluation_fields} for row in rows]
        analysis = _analyze(rows, _feature_names(recipe_value), recipe_value,
                            sorted(bars.bars["code"].astype(str).unique().tolist()))
        # Re-read the frozen package after computation to detect source or pin changes.
        verified, verified_identity = _load_frozen_input(source_path)
        if (_sha256(source_path.read_bytes()) != input_identity["manifest_sha256"]
                or verified.selected_data_sha256 != bars.selected_data_sha256
                or verified.identity_sha256 != bars.identity_sha256
                or verified_identity["pinned_identity_sha256"] != input_identity["pinned_identity_sha256"]):
            raise FactorResearchError("frozen factor input changed during the run")
        feature_doc = {"schema": "kabuforge.factor_feature_rows.v1", "readiness": "RESEARCH-ONLY",
            "pit_guarantee": False, "contains_forward_labels": False,
            "recipe_sha256": recipe_hash, "provider_identity": provider,
            "input_identity": input_identity, "rows": feature_rows}
        evaluation_doc = {"schema": "kabuforge.factor_evaluation_panel.v1", "readiness": "RESEARCH-ONLY",
            "pit_guarantee": False, "recipe_sha256": recipe_hash,
            "provider_identity": provider, "input_identity": input_identity,
            "label_semantics": contract["clock"], "rows": evaluation_rows}
        feature_bytes = _canonical_json(_json_safe(feature_doc))
        evaluation_bytes = _canonical_json(_json_safe(evaluation_doc))
        report = {
            "schema": "kabuforge.factor_research_report.v1", "status": "COMPLETED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "recipe": recipe_value, "recipe_sha256": recipe_hash,
            "provider_identity": provider, "input_identity": input_identity,
            "universe": "selected securities only; not a historical whole-market universe",
            "feature_row_count": len(feature_rows), "evaluation_row_count": len(evaluation_rows),
            "dates": sorted({row["signal_date"] for row in rows}),
            "label_status_counts": dict(Counter(row["label_status"] for row in rows)),
            "feature_missing_counts": {name: sum(row.get(name) is None for row in rows)
                                       for name in _feature_names(recipe_value)},
            "composition_missing_counts": dict(Counter(row["composite_status"] for row in rows)),
            "analysis": analysis,
            "artifacts": {
                "contract": str(target / "contract.json"),
                "feature_rows": str(target / "feature_rows.json"),
                "feature_rows_sha256": _sha256(feature_bytes),
                "evaluation_panel": str(target / "evaluation_panel.json"),
                "evaluation_panel_sha256": _sha256(evaluation_bytes),
            },
            "limitations": ["generated labels are overlapping descriptive forward returns, not validated alpha",
                "source historical availability is unverified; no available_at was inferred",
                "selected codes are not a historical universe; small-cross-section results are illustrative",
                "no costs, dividends, capacity, broker execution, or strategy orders are modeled"],
        }
        write_new(target / "feature_rows.json", feature_doc)
        write_new(target / "evaluation_panel.json", evaluation_doc)
        write_new(target / "report.json", report)
        receipt = {"schema": "kabuforge.factor_research_receipt.v1", "status": "COMPLETED",
            "recipe_sha256": recipe_hash, "input_identity": input_identity,
            "provider_identity": provider, "feature_row_count": len(feature_rows),
            "evaluation_row_count": len(evaluation_rows), "artifacts": report["artifacts"]}
        write_new(target / "receipt.json", receipt)
        return report
    except Exception as exc:
        write_new(target / "failure.json", {"schema": "kabuforge.factor_research_failure.v1",
            "status": "FAILED", "error_type": type(exc).__name__, "reason": str(exc),
            "recipe_sha256": recipe_hash, "input_identity": input_identity,
            "provider_identity": provider})
        raise


__all__ = ["DEFAULT_RECIPE", "FactorResearchError", "run_factor_research", "validate_recipe"]
