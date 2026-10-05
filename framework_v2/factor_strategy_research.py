"""Research-only D-1 strategy replay from frozen factor/model score rows.

The service reads one explicit frozen daily-bars manifest and one explicitly
hash-pinned feature-only or prediction artifact. It never opens factor label,
evaluation-panel, model-report, or broker files.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .price_research import _load_price_research_input


class FactorStrategyResearchError(ValueError):
    """A score-input or replay contract is invalid."""


RECIPE_SCHEMA = "kabuforge.factor_score_strategy_recipe.v1"
DEFAULT_RECIPE: dict[str, Any] = {
    "schema": RECIPE_SCHEMA,
    "count": 2,
    "frequency": "monthly",
    "cash": 2_000_000.0,
    "fee": 0.1,  # percent; 0.1 means 0.1%.
    "minimum_cross_section": 3,
}
_FACTOR_SCHEMA = "kabuforge.factor_feature_rows.v1"
_MODEL_SCHEMA = "kabuforge.model_prediction_rows.v1"
_FORBIDDEN_KEYS = {
    "forward_return", "label_end_date", "label_status", "label_available_at",
    "evaluation_panel", "ic", "rank_ic", "quantile_returns", "label_rows",
}
_FACTOR_FIELDS = re.compile(r"^(?:price_momentum|ma_distance|volatility|rsi)_\d{1,3}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_ABS_CASH_EPS = 1e-8
_POSITION_EPS = 1e-10


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise FactorStrategyResearchError("recipe or identity is not finite JSON") from None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _valid_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value.lower()):
        raise FactorStrategyResearchError(f"{label} must be a 64-character SHA-256 hex digest")
    return value.lower()


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise FactorStrategyResearchError(f"{label} must be an ISO calendar date YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise FactorStrategyResearchError(f"{label} is not a valid calendar date") from None
    if parsed.isoformat() != value:
        raise FactorStrategyResearchError(f"{label} is not a canonical ISO calendar date")
    return value


def validate_recipe(recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(DEFAULT_RECIPE if recipe is None else recipe)
    if set(value) != set(DEFAULT_RECIPE):
        raise FactorStrategyResearchError(f"recipe fields must be exactly {sorted(DEFAULT_RECIPE)}")
    if value.get("schema") != RECIPE_SCHEMA:
        raise FactorStrategyResearchError("unsupported factor-score strategy recipe schema")
    count = value.get("count")
    minimum = value.get("minimum_cross_section")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        raise FactorStrategyResearchError("count must be an integer in [1, 1000]")
    if (isinstance(minimum, bool) or not isinstance(minimum, int)
            or not max(3, count) <= minimum <= 10000):
        raise FactorStrategyResearchError("minimum_cross_section must be an integer >= max(3, count)")
    if value.get("frequency") not in {"daily", "weekly", "monthly"}:
        raise FactorStrategyResearchError("frequency must be daily, weekly, or monthly")
    if isinstance(value.get("cash"), bool) or isinstance(value.get("fee"), bool):
        raise FactorStrategyResearchError("cash and fee must be finite numbers, not booleans")
    try:
        cash = float(value.get("cash")); fee_pct = float(value.get("fee"))
    except (TypeError, ValueError, OverflowError):
        raise FactorStrategyResearchError("cash and fee must be finite numbers") from None
    if (not math.isfinite(cash) or cash <= 0 or not math.isfinite(fee_pct)
            or fee_pct < 0 or fee_pct > 5):
        raise FactorStrategyResearchError("cash must be positive and fee must be in [0, 5] percent")
    return {"schema": RECIPE_SCHEMA, "count": count, "frequency": value["frequency"],
            "cash": cash, "fee": fee_pct, "minimum_cross_section": minimum}


def _scan_for_forbidden_keys(value: Any, path: str = "artifact") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS:
                raise FactorStrategyResearchError(f"score artifact contains forbidden research field: {path}.{key}")
            _scan_for_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_for_forbidden_keys(nested, f"{path}[{index}]")


def _manifest_identity(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FactorStrategyResearchError("frozen-bars manifest cannot be read") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != "kabuforge_local_research_bars":
        raise FactorStrategyResearchError("strategy requires an explicit frozen local-research-bars manifest")
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or selection.get("price_basis") != "raw":
        raise FactorStrategyResearchError("strategy requires a pinned raw-price selection")
    manifest_sha = _sha(manifest_bytes)
    try:
        rows, identity = _load_price_research_input(path)
    except Exception as exc:
        raise FactorStrategyResearchError(f"frozen bars failed verification: {type(exc).__name__}: {exc}") from None
    if _sha_file(path) != manifest_sha:
        raise FactorStrategyResearchError("frozen-bars manifest changed while being read")
    if identity.get("kind") != "kabuforge_local_research_bars" or identity.get("pit_guarantee") is not False:
        raise FactorStrategyResearchError("frozen-bars input lost its pinned or RESEARCH-ONLY identity")
    selected_codes = sorted(set(str(row.get("code")) for row in rows))
    if not selected_codes or len(selected_codes) < 3:
        raise FactorStrategyResearchError("factor-score strategy requires at least three selected securities")
    by_code: dict[str, set[str]] = {}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code")); day = _iso_date(row.get("date"), "bar date")
        key = (day, code)
        if key in by_key:
            raise FactorStrategyResearchError("duplicate code/date bars are not allowed")
        by_key[key] = row
        by_code.setdefault(code, set()).add(day)
        if row.get("selected_price_basis") != "raw":
            raise FactorStrategyResearchError("frozen bars are not explicitly on the raw-price basis")
        try:
            factor = float(row.get("adjustment_factor"))
            close = float(row.get("close")); selected = float(row.get("selected_price"))
            opened = float(row.get("open"))
        except (TypeError, ValueError, OverflowError):
            raise FactorStrategyResearchError("raw bars lack finite open/close/adjustment data") from None
        if not all(math.isfinite(v) for v in (factor, close, selected, opened)):
            raise FactorStrategyResearchError("raw bars contain non-finite price data")
        if factor != 1.0:
            raise FactorStrategyResearchError(f"split event unsupported by frozen strategy replay: {code} {day}")
        if close <= 0 or opened <= 0 or selected != close:
            raise FactorStrategyResearchError("raw signal, execution, and valuation prices are inconsistent")
    calendars = list(by_code.values())
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        raise FactorStrategyResearchError("frozen bars do not have a complete common observed calendar")
    dates = sorted(calendars[0])
    if not dates:
        raise FactorStrategyResearchError("frozen bars are empty")
    identity = {**identity, "manifest_sha256": manifest_sha,
        "selection": selection, "pit_guarantee": False,
        "source_availability": "history visibility unverified"}
    return rows, identity, {"rows": len(rows), "dates": dates, "codes": selected_codes,
                            "by_key": by_key}, manifest_sha


def _artifact_input_matches(artifact_input: Any, bars_identity: dict[str, Any]) -> None:
    if not isinstance(artifact_input, dict):
        raise FactorStrategyResearchError("score artifact lacks a frozen-bars input identity")
    required = ("manifest_sha256", "selected_data_sha256", "selection_identity_sha256",
                "pinned_identity_sha256")
    for name in required:
        if artifact_input.get(name) != bars_identity.get(name):
            raise FactorStrategyResearchError(f"score artifact input identity mismatch: {name}")
    artifact_selection = artifact_input.get("selection")
    pinned_selection = bars_identity.get("selection")
    if not isinstance(artifact_selection, dict) or not isinstance(pinned_selection, dict):
        raise FactorStrategyResearchError("score artifact selection identity is missing")
    for name in ("requested_codes", "matched_codes", "start_date", "end_date",
                 "price_basis", "duplicate_policy", "known_halt_policy"):
        if artifact_selection.get(name) != pinned_selection.get(name):
            raise FactorStrategyResearchError(f"score artifact selection mismatch: {name}")


def _read_score_artifact(path: Path, expected_sha: str, score_source: str,
                         bars_identity: dict[str, Any], codes: list[str], dates: list[str]) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    permitted_name = "feature_rows.json" if score_source == "factor_feature_rows" else "predictions.json"
    if path.name.lower() != permitted_name:
        raise FactorStrategyResearchError(f"score artifact filename must be {permitted_name}; evaluation/report files are not inputs")
    try:
        raw = path.read_bytes()
    except OSError:
        raise FactorStrategyResearchError("score artifact cannot be read") from None
    actual_sha = _sha(raw)
    if actual_sha != expected_sha:
        raise FactorStrategyResearchError("score artifact SHA-256 does not match the pinned expected hash")
    try:
        doc = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise FactorStrategyResearchError("score artifact is not valid UTF-8 JSON") from None
    if _sha_file(path) != actual_sha:
        raise FactorStrategyResearchError("score artifact changed while it was being read")
    _scan_for_forbidden_keys(doc)
    expected_schema = _FACTOR_SCHEMA if score_source == "factor_feature_rows" else _MODEL_SCHEMA
    if not isinstance(doc, dict) or doc.get("schema") != expected_schema:
        raise FactorStrategyResearchError("score artifact schema does not match the selected score source")
    if doc.get("readiness") != "RESEARCH-ONLY" or doc.get("pit_guarantee") is not False:
        raise FactorStrategyResearchError("score artifact must remain RESEARCH-ONLY with PIT unverified")
    if doc.get("contains_forward_labels") is not False:
        raise FactorStrategyResearchError("score artifact must explicitly exclude forward labels")
    _artifact_input_matches(doc.get("input_identity"), bars_identity)
    recipe_sha = _valid_sha(doc.get("recipe_sha256"), "score-generation recipe SHA-256")
    entries = doc.get("rows")
    if not isinstance(entries, list) or not entries:
        raise FactorStrategyResearchError("score artifact has no feature-only rows")
    code_set = set(codes); date_index = {day: index for index, day in enumerate(dates)}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    selected_scores = 0
    model_identity = None
    if score_source == "factor_feature_rows":
        provider = doc.get("provider_identity")
        if not isinstance(provider, dict) or provider.get("id") != "kabuforge.local_daily_factor_research":
            raise FactorStrategyResearchError("factor feature provider identity is unsupported")
        provider_sha = _valid_sha(provider.get("source_sha256"), "factor provider source SHA-256")
        if provider_sha != _sha_file(Path(__file__).resolve().with_name("factor_research.py")):
            raise FactorStrategyResearchError("factor feature provider source has changed since feature generation")
        loader_sha = _valid_sha(provider.get("local_cache_loader_source_sha256"),
                                "factor local-cache loader SHA-256")
        if loader_sha != _sha_file(Path(__file__).resolve().with_name("local_cache.py")):
            raise FactorStrategyResearchError("factor feature local-cache identity is stale")
        source_meta = {"kind": score_source, "artifact_sha256": actual_sha,
            "recipe_sha256": recipe_sha,
            "provider_identity": {"id": provider["id"], "version": str(provider.get("version")),
                "source_sha256": provider_sha, "local_cache_loader_source_sha256": loader_sha}}
        score_field = "composite_score"
    else:
        model_name = doc.get("model_name")
        if model_name not in {"lightgbm", "catboost"}:
            raise FactorStrategyResearchError("model score source must be an allowlisted LightGBM or CatBoost prediction artifact")
        model_sha = _valid_sha(doc.get("model_artifact_sha256"), "model artifact SHA-256")
        model_identity = {"model_name": model_name, "model_artifact_sha256": model_sha}
        source_meta = {"kind": score_source, "artifact_sha256": actual_sha,
            "recipe_sha256": recipe_sha, **model_identity}
        score_field = "prediction"
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise FactorStrategyResearchError(f"score row {index} is not an object")
        code = str(item.get("code", ""))
        signal = _iso_date(item.get("signal_date"), f"score row {index} signal_date")
        cutoff = _iso_date(item.get("d1_cutoff_date"), f"score row {index} d1_cutoff_date")
        execution = _iso_date(item.get("execution_date"), f"score row {index} execution_date")
        if code not in code_set or signal not in date_index or execution not in date_index:
            raise FactorStrategyResearchError(f"score row {index} references a code/date outside the frozen bars")
        if signal != cutoff or signal >= execution or date_index[execution] != date_index[signal] + 1:
            raise FactorStrategyResearchError(f"score row {index} violates D-1 signal/next-observed-open chronology")
        if score_source == "factor_feature_rows":
            allowed = {"code", "signal_date", "d1_cutoff_date", "execution_date",
                       "selected_price_basis", "composite_score", "composite_status"}
            allowed.update(key for key in item if _FACTOR_FIELDS.fullmatch(str(key)))
            if set(item) - allowed:
                raise FactorStrategyResearchError(f"factor feature row {index} contains unsupported fields")
            if item.get("selected_price_basis") != "raw":
                raise FactorStrategyResearchError("factor feature price basis must match raw frozen bars")
        else:
            allowed = {"code", "signal_date", "d1_cutoff_date", "execution_date",
                       "prediction_role", "model_training_label_end_max", "prediction"}
            if set(item) != allowed:
                raise FactorStrategyResearchError(f"model prediction row {index} contains unsupported or missing fields")
            role = item.get("prediction_role")
            if role not in {"validation_diagnostic", "historical_test_diagnostic"}:
                raise FactorStrategyResearchError("model prediction role is not an allowed diagnostic role")
            training_cutoff = _iso_date(item.get("model_training_label_end_max"),
                                        f"model row {index} training cutoff")
            if signal <= training_cutoff:
                raise FactorStrategyResearchError("model prediction signal is not after the maximum training-label end")
            if signal >= "2021-01-01" and role != "historical_test_diagnostic":
                raise FactorStrategyResearchError("model strategy window accepts historical test rows only from 2021 onward")
            if role == "historical_test_diagnostic" and not "2021-01-01" <= signal <= "2022-12-31":
                raise FactorStrategyResearchError("historical model strategy scope is fixed to 2021-2022")
            if role == "validation_diagnostic" and signal >= "2021-01-01":
                raise FactorStrategyResearchError("validation diagnostic rows cannot enter the model strategy window")
        score_value = item.get(score_field)
        if score_value is None:
            score = None
        else:
            if isinstance(score_value, bool):
                raise FactorStrategyResearchError(f"score row {index} value must be finite numeric or null")
            try:
                score = float(score_value)
            except (TypeError, ValueError, OverflowError):
                raise FactorStrategyResearchError(f"score row {index} value must be finite numeric or null") from None
            if not math.isfinite(score):
                raise FactorStrategyResearchError(f"score row {index} value must be finite numeric or null")
        key = (signal, code)
        if key in by_key:
            raise FactorStrategyResearchError(f"duplicate score row for {code} at {signal}")
        clean = {"code": code, "signal_date": signal, "d1_cutoff_date": cutoff,
                 "execution_date": execution, "score": score}
        if score_source == "factor_feature_rows":
            clean["composite_status"] = str(item.get("composite_status", ""))
            if clean["composite_status"] not in {"complete", "incomplete"}:
                raise FactorStrategyResearchError(f"factor row {index} composite status is unsupported")
            if clean["composite_status"] != "complete":
                clean["score"] = None
        else:
            clean.update({"prediction_role": item["prediction_role"],
                          "model_training_label_end_max": item["model_training_label_end_max"]})
        by_key[key] = clean
        if clean["score"] is not None:
            selected_scores += 1
    if _sha_file(path) != actual_sha:
        raise FactorStrategyResearchError("score artifact changed during validation")
    if selected_scores == 0:
        raise FactorStrategyResearchError("score artifact has no finite eligible scores")
    source_meta.update({"score_field": score_field, "eligible_score_rows": selected_scores})
    return doc, by_key, {**source_meta, "model_identity": model_identity}


def _period(day: str, frequency: str) -> Any:
    parsed = date.fromisoformat(day)
    if frequency == "daily":
        return day
    if frequency == "weekly":
        iso = parsed.isocalendar()
        return iso.year, iso.week
    return day[:7]


def _research_strategy(rows: list[dict[str, Any]], input_identity: dict[str, Any],
                       bars: dict[str, Any], score_rows: dict[tuple[str, str], dict[str, Any]],
                       score_meta: dict[str, Any], recipe: dict[str, Any],
                       score_source: str) -> dict[str, Any]:
    all_dates: list[str] = bars["dates"]
    codes: list[str] = bars["codes"]
    by_key: dict[tuple[str, str], dict[str, Any]] = bars["by_key"]
    if score_source == "model_predictions":
        dates = [day for day in all_dates if "2021-01-01" <= day <= "2022-12-31"]
    else:
        dates = list(all_dates)
    if len(dates) < 2:
        raise FactorStrategyResearchError("selected strategy window has fewer than two observed sessions")
    date_index = {day: index for index, day in enumerate(all_dates)}
    cash = float(recipe["cash"]); initial_cash = cash; fee_rate = float(recipe["fee"]) / 100.0
    minimum_cross_section = int(recipe["minimum_cross_section"])
    positions = {code: 0.0 for code in codes}
    nav = []; account_path = []; trades = []; skips = []; schedule = []; decisions = []
    daily_turnover = []; peak = initial_cash; cumulative_fees = 0.0; total_fees = 0.0
    for local_index, day in enumerate(dates):
        full_index = date_index[day]
        orders_today: list[dict[str, Any]] = []
        event = None
        if local_index > 0:
            signal_date = dates[local_index - 1]
            if _period(day, recipe["frequency"]) != _period(signal_date, recipe["frequency"]):
                signal_rows = [score_rows.get((signal_date, code)) for code in codes]
                eligible = [item for item in signal_rows if item is not None and item["score"] is not None]
                if score_source == "model_predictions":
                    eligible = [item for item in eligible
                                if item.get("prediction_role") == "historical_test_diagnostic"
                                and item["signal_date"] >= "2021-01-01"]
                missing_codes = sorted(set(codes) - {item["code"] for item in eligible})
                if len(eligible) < minimum_cross_section:
                    event = {"signal_date": signal_date, "execution_date": day,
                        "status": "skipped_insufficient_cross_section",
                        "eligible_count": len(eligible), "required_count": minimum_cross_section,
                        "universe_count": len(codes), "missing_or_ineligible_codes": missing_codes}
                    skips.append({**event, "reason": "insufficient score coverage; existing holdings retained"})
                else:
                    ranked = sorted(eligible, key=lambda item: (-float(item["score"]), item["code"]))
                    chosen = [item["code"] for item in ranked[:recipe["count"]]]
                    cutoff_score = float(ranked[recipe["count"] - 1]["score"])
                    cutoff_ties = [item["code"] for item in ranked
                                   if float(item["score"]) == cutoff_score]
                    sizing_prices = {code: float(by_key[(signal_date, code)]["close"]) for code in codes}
                    sizing_equity = cash + sum(positions[code] * sizing_prices[code] for code in codes)
                    investable = sizing_equity / (1.0 + 2.0 * fee_rate)
                    target = {code: (investable / recipe["count"] / sizing_prices[code]
                                     if code in chosen else 0.0) for code in codes}
                    score_map = {item["code"]: float(item["score"]) for item in ranked}
                    for code in sorted(codes, key=lambda name: (target[name] - positions[name], name)):
                        delta = target[code] - positions[code]
                        if abs(delta) < 1e-10:
                            continue
                        order = {"signal_date": signal_date, "execution_date": day,
                            "code": code, "side": "buy" if delta > 0 else "sell",
                            "quantity": abs(delta), "sizing_price": sizing_prices[code],
                            "sizing_equity": sizing_equity, "score": score_map.get(code)}
                        schedule.append(order); orders_today.append(order)
                    event = {"signal_date": signal_date, "execution_date": day,
                        "status": "scheduled", "eligible_count": len(eligible),
                        "required_count": minimum_cross_section, "ranked_codes": [item["code"] for item in ranked],
                        "selected_codes": chosen, "cutoff_score": cutoff_score,
                        "cutoff_tie_codes": cutoff_ties,
                        "tie_break": "score descending, then code ascending"}
                if event is not None:
                    decisions.append(event)
        prior_close_equity = (initial_cash if full_index == 0 else cash + sum(
            positions[code] * float(by_key[(all_dates[full_index - 1], code)]["close"])
            for code in codes))
        gross_executed = 0.0; day_fees = 0.0
        for order in orders_today:
            code = order["code"]
            open_price = float(by_key[(day, code)]["open"])
            quantity = float(order["quantity"])
            notional = quantity * open_price
            fee = abs(notional) * fee_rate
            if order["side"] == "sell":
                if quantity > positions[code] + _POSITION_EPS:
                    raise FactorStrategyResearchError("frozen sell quantity exceeds actual long holdings; shorting is disabled")
                sold = min(quantity, positions[code])
                if abs(sold - quantity) > _POSITION_EPS:
                    raise FactorStrategyResearchError("sell order would require quantity resizing")
                notional = sold * open_price; fee = notional * fee_rate
                cash += notional - fee; positions[code] -= sold
                if positions[code] < -_POSITION_EPS:
                    raise FactorStrategyResearchError("long-only position invariant failed")
            elif notional + fee > cash + _ABS_CASH_EPS:
                skip = {**order, "open_price": open_price, "cash_available": cash,
                    "cash_required": notional + fee,
                    "cash_shortfall": notional + fee - cash,
                    "reason": "opening gap exceeds prior-close cash budget; fixed quantity skipped"}
                skips.append(skip)
                continue
            else:
                cash -= notional + fee; positions[code] += quantity
            trade = {"date": day, "signal_date": order["signal_date"], "code": code,
                "side": order["side"], "quantity": quantity,
                "sizing_price": order["sizing_price"], "price": open_price, "fee": fee,
                "score": order.get("score")}
            trades.append(trade); gross_executed += abs(notional); day_fees += fee
            total_fees += fee
        if cash < -_ABS_CASH_EPS:
            raise FactorStrategyResearchError("cash invariant failed")
        cumulative_fees += day_fees
        close_equity = cash + sum(positions[code] * float(by_key[(day, code)]["close"])
                                  for code in codes)
        peak = max(peak, close_equity)
        nav_row = {"at": day, "nav": close_equity / initial_cash,
                   "drawdown": close_equity / peak - 1.0, "cash": cash}
        nav.append(nav_row)
        marked_positions = []
        for code in codes:
            quantity = positions[code]
            if quantity < -_POSITION_EPS:
                raise FactorStrategyResearchError("long-only position invariant failed")
            mark = float(by_key[(day, code)]["close"])
            if quantity > _POSITION_EPS:
                market_value = quantity * mark
                marked_positions.append({"code": code, "quantity": quantity,
                    "mark_price": mark, "market_value": market_value,
                    "weight": market_value / close_equity if close_equity else None})
        account_path.append({"at": day, "cash": cash, "equity": close_equity,
            "position_universe": list(codes), "cash_weight": cash / close_equity if close_equity else None,
            "positions": marked_positions, "fees": day_fees,
            "cumulative_fees": cumulative_fees})
        daily_turnover.append({"at": day, "gross_executed_notional": gross_executed,
            "denominator_prior_close_equity": prior_close_equity,
            "gross_traded_turnover": gross_executed / prior_close_equity if prior_close_equity > 0 else None,
            "basis": "executed buy plus sell notional / prior-close marked equity; skipped orders excluded"})
    return {"model": "daily_bar_next_open_research_v1", "status": "COMPLETED",
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "mode": "research",
        "strategy_template": f"frozen_{score_source}", "strategy_hash": None,
        "frequency": "daily", "nav_frequency": "daily", "annualization_sessions": 252,
        "nav_base_includes_initial": True, "initial_equity": initial_cash,
        "initial_at": dates[0], "initial_nav": 1.0,
        "signal_price_basis": "raw", "execution_price_basis": "raw open",
        "valuation_basis": "rawclose", "execution_valuation_basis": "rawclose",
        "price_basis_semantics": {
            "signals": "selected_price (adjustment_close when adjusted; close when raw)",
            "execution": "original raw open; selected_price never substitutes execution OHLC",
            "valuation": "original raw close; price-only mark, no dividend cash model",
            "pit_guarantee": False,
        },
        "raw_price_only": True, "pit_data_availability": False,
        "score_source": score_meta, "input_identity": input_identity,
        "strategy_recipe": recipe, "score_window": {
            "start_date": dates[0], "end_date": dates[-1],
            "model_scope": "historical test diagnostic scores from 2021-2022 only" if score_source == "model_predictions"
                          else "full selected frozen-bar period; early score warmup may be unavailable"},
        "nav": nav, "account_path": account_path, "trades": trades,
        "skipped_orders": skips, "skips": skips, "fees": total_fees,
        "gross_traded_notional": sum(float(item["gross_executed_notional"]) for item in daily_turnover),
        "daily_turnover": daily_turnover, "order_schedule": schedule,
        "decisions": decisions, "submitted": False,
        "assumptions": ["feature/model score is known at D-1 close; fixed share quantity sized at D-1 raw close",
            "execution uses next observed session raw open; valuation uses raw close",
            "monthly means first observed open in a new calendar month; weekly uses ISO week boundary",
            "scores rank descending with code-ascending tie break; insufficient cross-section skips and retains holdings",
            "opening cash shortfall skips the frozen quantity; no resizing or partial fill",
            "price-only account; no dividends, slippage, board lots, market impact, or corporate actions",
            "history visibility is unverified; this is RESEARCH-ONLY and not PAPER-READY"]}


def run_factor_strategy_research(
    manifest_path: str | Path,
    score_artifact_path: str | Path,
    output_dir: str | Path,
    recipe: dict[str, Any] | None = None,
    *,
    score_source: str,
    expected_artifact_sha256: str,
) -> Path:
    """Replay feature-only or test-window model scores without reading label panels."""
    if score_source not in {"factor_feature_rows", "model_predictions"}:
        raise FactorStrategyResearchError("score_source must be factor_feature_rows or model_predictions")
    strategy_recipe = validate_recipe(recipe)
    expected_artifact_sha256 = _valid_sha(expected_artifact_sha256, "expected artifact SHA-256")
    manifest = Path(manifest_path).resolve(strict=True)
    artifact = Path(score_artifact_path).resolve(strict=True)
    required_name = "feature_rows.json" if score_source == "factor_feature_rows" else "predictions.json"
    if artifact.name.lower() != required_name:
        raise FactorStrategyResearchError(f"only the explicitly selected {required_name} artifact is accepted")
    target = Path(output_dir).resolve()
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True, exist_ok=False)
    source_files = {
        "factor_strategy_research.py": Path(__file__).resolve(),
        "factor_research.py": Path(__file__).resolve().with_name("factor_research.py"),
        "model_research.py": Path(__file__).resolve().with_name("model_research.py"),
        "price_research.py": Path(__file__).resolve().with_name("price_research.py"),
        "local_cache.py": Path(__file__).resolve().with_name("local_cache.py"),
    }
    source_hashes = {name: _sha_file(path) for name, path in source_files.items()}
    contract = {"schema": "kabuforge.factor_score_strategy_contract.v1",
        "status": "PREREGISTERED", "created_at": datetime.now(timezone.utc).isoformat(),
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "input_manifest_path": str(manifest), "manifest_sha256": _sha_file(manifest),
        "score_artifact_path": str(artifact), "score_source": score_source,
        "expected_artifact_sha256": expected_artifact_sha256,
        "recipe": strategy_recipe, "recipe_sha256": _sha(_canonical(strategy_recipe)),
        "model_score_window": {"start_date": "2021-01-01", "end_date": "2022-12-31",
                                "roles": ["historical_test_diagnostic"]}
                               if score_source == "model_predictions" else None,
        "source_sha256": source_hashes,
        "prohibited": ["no-evaluation-panel-read", "no-forward-label-consumption", "no-network",
            "no-credentials", "no-ledger", "no-order-resizing", "not-PIT", "not-PAPER-READY"]}
    _write_new(target / "contract.json", contract)
    try:
        if _sha_file(manifest) != contract["manifest_sha256"]:
            raise FactorStrategyResearchError("frozen bars manifest changed after contract preregistration")
        rows, bars_identity, bars, manifest_sha = _manifest_identity(manifest)
        if manifest_sha != contract["manifest_sha256"]:
            raise FactorStrategyResearchError("frozen bars manifest identity changed during input verification")
        score_doc, score_rows, score_meta = _read_score_artifact(
            artifact, expected_artifact_sha256, score_source, bars_identity, bars["codes"], bars["dates"])
        if score_source == "model_predictions":
            # Training/validation rows are validated and hashed but never become strategy signals.
            score_rows = {key: value for key, value in score_rows.items()
                          if value.get("prediction_role") == "historical_test_diagnostic"
                          and "2021-01-01" <= value["signal_date"] <= "2022-12-31"}
        report = _research_strategy(rows, bars_identity, bars, score_rows,
                                    score_meta, strategy_recipe, score_source)
        report["strategy_hash"] = contract["recipe_sha256"]
        report["input_hash"] = _sha(_canonical({"manifest_sha256": manifest_sha,
            "selected_data_sha256": bars_identity.get("selected_data_sha256"),
            "artifact_sha256": expected_artifact_sha256,
            "recipe_sha256": contract["recipe_sha256"]}))
        report["source_sha256"] = source_hashes
        report["score_artifact_identity"] = {key: score_doc.get(key) for key in (
            "schema", "recipe_sha256", "model_name", "model_artifact_sha256") if key in score_doc}
        _write_new(target / "report.json", report)
        receipt = {"schema": "kabuforge.factor_score_strategy_receipt.v1",
            "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "input_manifest_sha256": manifest_sha,
            "score_artifact_sha256": expected_artifact_sha256,
            "strategy_recipe_sha256": contract["recipe_sha256"],
            "score_source": score_source,
            "report_sha256": _sha_file(target / "report.json"),
            "contract_sha256": _sha_file(target / "contract.json"),
            "source_sha256": source_hashes}
        _write_new(target / "receipt.json", receipt)
        return target / "report.json"
    except Exception as exc:
        failure = {"schema": "kabuforge.factor_score_strategy_failure.v1", "status": "FAILED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "error_type": type(exc).__name__, "reason": str(exc),
            "contract_sha256": _sha_file(target / "contract.json"), "source_sha256": source_hashes}
        _write_new(target / "failure.json", failure)
        if isinstance(exc, FactorStrategyResearchError):
            raise
        raise FactorStrategyResearchError(f"factor-score strategy failed: {type(exc).__name__}: {exc}") from None


__all__ = ["DEFAULT_RECIPE", "FactorStrategyResearchError", "run_factor_strategy_research", "validate_recipe"]
