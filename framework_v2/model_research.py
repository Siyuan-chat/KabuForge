"""Fixed-split, offline tree-model diagnostics for frozen factor-research runs.

This module intentionally implements a tiny, fixed LightGBM/CatBoost workflow.
It does not tune, select factors, connect to a broker, or claim OOS readiness.
Optional model packages are imported from the caller's isolated worker runtime.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from typing import Any

import numpy as np
import pandas as pd

from .factor_research import validate_recipe
from .local_io import write_new


class ModelResearchError(ValueError):
    """An input or fixed model-research contract was violated."""


_SUPPORTED_MODELS = {"lightgbm", "catboost"}
_SPLITS = {
    "train": {"signal_start": "2017-01-01", "signal_end": "2019-12-31",
              "label_end_exclusive": "2020-01-01"},
    "validation": {"signal_start": "2020-01-01", "signal_end": "2020-12-31",
                   "label_end_exclusive": "2021-01-01"},
    "test": {"signal_start": "2021-01-01", "signal_end": "2022-12-31",
             "label_end_inclusive": "2022-12-31"},
}
_MODEL_PARAMETERS = {
    "lightgbm": {"n_estimators": 32, "max_depth": 2, "num_leaves": 4,
                 "learning_rate": 0.05, "min_child_samples": 20,
                 "verbosity": -1, "deterministic": True, "force_col_wise": True,
                 "n_jobs": 1, "random_state": 42},
    "catboost": {"iterations": 32, "depth": 2, "learning_rate": 0.05,
                 "loss_function": "RMSE", "random_seed": 42, "verbose": False,
                 "allow_writing_files": False, "thread_count": 1},
}
_LABEL_FIELDS = {"forward_return", "label_status", "label_start_date", "label_end_date"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModelResearchError(f"identity is not finite JSON: {type(exc).__name__}") from None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ModelResearchError(f"factor-research artifact cannot be read: {path.name}") from None
    if not isinstance(value, dict):
        raise ModelResearchError(f"factor-research artifact must be a JSON object: {path.name}")
    return value


def _model_runtime(model_name: str) -> tuple[Any, dict[str, Any]]:
    """Import only the two fixed supported modules; never accept import paths."""
    try:
        if model_name == "lightgbm":
            import lightgbm
            model_module = lightgbm
        else:
            import catboost
            model_module = catboost
    except ImportError as exc:
        raise ModelResearchError(
            f"optional {model_name} runtime is unavailable: {type(exc).__name__}") from None
    module_path = Path(model_module.__file__).resolve()
    return model_module, {
        "name": model_name, "version": str(model_module.__version__),
        "module_path": str(module_path), "module_sha256": _sha256_file(module_path),
        "workflow_source_sha256": _sha256_file(Path(__file__).resolve()),
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
    }


def _input_bundle(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    report_path = run_dir / "report.json"
    feature_path = run_dir / "feature_rows.json"
    evaluation_path = run_dir / "evaluation_panel.json"
    contract_path = run_dir / "contract.json"
    paths = {"report": report_path, "contract": contract_path,
             "feature_rows": feature_path, "evaluation_panel": evaluation_path}
    hashes = {key: _sha256_file(path) for key, path in paths.items() if path.is_file()}
    if len(hashes) != len(paths):
        missing = sorted(set(paths) - set(hashes))
        raise ModelResearchError(f"factor-research files are missing: {missing}")
    report = _read_json(report_path)
    contract = _read_json(contract_path)
    features = _read_json(feature_path)
    evaluation = _read_json(evaluation_path)
    if report.get("schema") != "kabuforge.factor_research_report.v1" or report.get("status") != "COMPLETED":
        raise ModelResearchError("input is not a completed factor-research report")
    if report.get("readiness") != "RESEARCH-ONLY" or report.get("pit_guarantee") is not False:
        raise ModelResearchError("factor input must remain RESEARCH-ONLY with PIT unverified")
    if features.get("schema") != "kabuforge.factor_feature_rows.v1" or features.get("contains_forward_labels") is not False:
        raise ModelResearchError("feature artifact schema or no-label contract is invalid")
    if features.get("readiness") != "RESEARCH-ONLY" or features.get("pit_guarantee") is not False:
        raise ModelResearchError("feature artifact must remain RESEARCH-ONLY with PIT unverified")
    if evaluation.get("schema") != "kabuforge.factor_evaluation_panel.v1":
        raise ModelResearchError("evaluation-panel schema is invalid")
    if evaluation.get("readiness") != "RESEARCH-ONLY" or evaluation.get("pit_guarantee") is not False:
        raise ModelResearchError("evaluation panel must remain RESEARCH-ONLY with PIT unverified")
    if contract.get("status") != "PREREGISTERED" or contract.get("readiness") != "RESEARCH-ONLY":
        raise ModelResearchError("factor input contract is not preregistered RESEARCH-ONLY")
    recipe = validate_recipe(report.get("recipe"))
    recipe_hash = hashlib.sha256(_canonical_json(recipe)).hexdigest()
    if (report.get("recipe_sha256") != recipe_hash or features.get("recipe_sha256") != recipe_hash
            or evaluation.get("recipe_sha256") != recipe_hash
            or contract.get("recipe_sha256") != recipe_hash
            or contract.get("recipe") != recipe):
        raise ModelResearchError("factor recipe identity does not match its feature artifact")
    declared_artifacts = report.get("artifacts")
    if (not isinstance(declared_artifacts, dict)
            or declared_artifacts.get("feature_rows_sha256") != hashlib.sha256(_canonical_json(features)).hexdigest()
            or declared_artifacts.get("evaluation_panel_sha256") != hashlib.sha256(_canonical_json(evaluation)).hexdigest()):
        raise ModelResearchError("factor artifact canonical hashes do not match the report")
    identity = report.get("input_identity")
    if not isinstance(identity, dict):
        raise ModelResearchError("factor input identity is missing")
    for artifact in (contract, features, evaluation):
        if artifact.get("input_identity") != identity:
            raise ModelResearchError("factor artifacts do not share one input identity")
    if (features.get("provider_identity") != report.get("provider_identity")
            or evaluation.get("provider_identity") != report.get("provider_identity")
            or contract.get("provider_identity") != report.get("provider_identity")):
        raise ModelResearchError("factor provider identity differs across artifacts")
    if not isinstance(features.get("rows"), list) or not isinstance(evaluation.get("rows"), list):
        raise ModelResearchError("factor artifacts do not contain row lists")
    current_hashes = {key: _sha256_file(path) for key, path in paths.items()}
    if current_hashes != hashes:
        raise ModelResearchError("factor artifacts changed while they were being read")
    return report, contract, features, evaluation, hashes


def _date_key(row: dict[str, Any]) -> tuple[str, str]:
    code, signal_date = row.get("code"), row.get("signal_date")
    if not isinstance(code, str) or not code or not isinstance(signal_date, str):
        raise ModelResearchError("factor row requires string code and signal_date")
    try:
        if date.fromisoformat(signal_date).isoformat() != signal_date:
            raise ValueError
    except ValueError:
        raise ModelResearchError("signal_date must be an ISO calendar date") from None
    return code, signal_date


def _index_rows(rows: list[dict[str, Any]], *, label_rows: bool) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ModelResearchError("factor row is not an object")
        key = _date_key(row)
        if key in result:
            raise ModelResearchError(f"duplicate code/signal_date row: {key[0]} {key[1]}")
        if not label_rows and _LABEL_FIELDS.intersection(row):
            raise ModelResearchError("feature rows contain forbidden forward-label fields")
        signal_date = key[1]
        cutoff = row.get("d1_cutoff_date")
        if cutoff != signal_date:
            raise ModelResearchError(f"D-1 feature cutoff must equal signal_date: {key[0]} {signal_date}")
        execution = row.get("execution_date")
        if execution is not None:
            try:
                if date.fromisoformat(execution).isoformat() != execution or execution <= signal_date:
                    raise ValueError
            except (TypeError, ValueError):
                raise ModelResearchError(f"execution_date must be a later ISO date: {key[0]} {signal_date}") from None
        if not label_rows and execution is None:
            raise ModelResearchError(f"feature row lacks an execution date: {key[0]} {signal_date}")
        if label_rows:
            status = row.get("label_status")
            start, end, target = row.get("label_start_date"), row.get("label_end_date"), row.get("forward_return")
            if status == "available":
                try:
                    if (execution is None or not isinstance(start, str) or not isinstance(end, str)
                            or date.fromisoformat(start).isoformat() != start
                            or date.fromisoformat(end).isoformat() != end
                            or start < execution or end <= start):
                        raise ValueError
                except (TypeError, ValueError):
                    raise ModelResearchError(f"available label chronology is invalid: {key[0]} {signal_date}") from None
                if (isinstance(target, bool) or not isinstance(target, (int, float))
                        or not math.isfinite(float(target))):
                    raise ModelResearchError(f"available label must be finite: {key[0]} {signal_date}")
            elif target is not None:
                raise ModelResearchError(f"non-available label must have a null return: {key[0]} {signal_date}")
        result[key] = row
    return result


def _feature_columns(recipe: dict[str, Any]) -> list[str]:
    return [f"{item['id']}_{window}" for item in recipe["factors"] for window in item["windows"]]


def _build_samples(feature_doc: dict[str, Any], evaluation_doc: dict[str, Any],
                   feature_columns: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    features = _index_rows(feature_doc["rows"], label_rows=False)
    labels = _index_rows(evaluation_doc["rows"], label_rows=True)
    if not features:
        raise ModelResearchError("feature artifact is empty")
    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in _SPLITS}
    counts = {name: {"candidate_feature_rows": 0, "accepted_rows": 0,
                     "purged_label_boundary": 0, "excluded_missing_label": 0}
              for name in _SPLITS}
    for key, feature_row in sorted(features.items(), key=lambda item: (item[0][1], item[0][0])):
        code, signal_date = key
        split_name = next((name for name, window in _SPLITS.items()
                           if window["signal_start"] <= signal_date <= window["signal_end"]), None)
        if split_name is None:
            continue
        counts[split_name]["candidate_feature_rows"] += 1
        if any(column not in feature_row for column in feature_columns):
            raise ModelResearchError(f"feature row is missing a recipe column: {code} {signal_date}")
        values = []
        for column in feature_columns:
            value = feature_row[column]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ModelResearchError(f"model feature must be finite and complete: {column} {code} {signal_date}")
            values.append(float(value))
        label_row = labels.get(key)
        if label_row is None or label_row.get("label_status") != "available" or label_row.get("forward_return") is None:
            counts[split_name]["excluded_missing_label"] += 1
            continue
        label_end = label_row.get("label_end_date")
        if not isinstance(label_end, str):
            raise ModelResearchError(f"available label lacks label_end_date: {code} {signal_date}")
        window = _SPLITS[split_name]
        if "label_end_exclusive" in window:
            inside = label_end < window["label_end_exclusive"]
        else:
            inside = label_end <= window["label_end_inclusive"]
        if not inside:
            counts[split_name]["purged_label_boundary"] += 1
            continue
        target = label_row["forward_return"]
        if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(float(target)):
            raise ModelResearchError(f"forward label must be finite: {code} {signal_date}")
        samples[split_name].append({"code": code, "signal_date": signal_date,
            "execution_date": feature_row.get("execution_date"),
            "label_end_date": label_end, "features": values, "target": float(target)})
        counts[split_name]["accepted_rows"] += 1
    if not samples["train"]:
        raise ModelResearchError("purged fixed training split contains no labeled rows")
    if not samples["validation"] or not samples["test"]:
        raise ModelResearchError("purged fixed validation/test split contains no labeled rows")
    # The boundary predicates above must make all training/validation labels
    # strictly earlier than the next period's signal dates.
    if max(row["label_end_date"] for row in samples["train"]) >= _SPLITS["validation"]["signal_start"]:
        raise ModelResearchError("purged training labels overlap the validation signal window")
    if max(row["label_end_date"] for row in samples["validation"]) >= _SPLITS["test"]["signal_start"]:
        raise ModelResearchError("purged validation labels overlap the test signal window")
    return samples, counts


def _make_model(model_name: str, module: Any):
    if model_name == "lightgbm":
        return module.LGBMRegressor(**_MODEL_PARAMETERS[model_name])
    return module.CatBoostRegressor(**_MODEL_PARAMETERS[model_name])


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, Any]:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if y.size == 0 or y.shape != p.shape or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ModelResearchError("model evaluation arrays must be non-empty, aligned, and finite")
    error = p - y
    if not np.isfinite(error).all():
        raise ModelResearchError("model evaluation residuals are non-finite")
    scale = float(np.max(np.abs(error)))
    mae = 0.0 if scale == 0.0 else float(scale * np.mean(np.abs(error) / scale))
    rmse = 0.0 if scale == 0.0 else float(scale * np.sqrt(np.mean((error / scale) ** 2)))
    if not math.isfinite(mae) or not math.isfinite(rmse):
        raise ModelResearchError("model evaluation metrics are non-finite")
    y_rank = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    p_rank = pd.Series(p).rank(method="average").to_numpy(dtype=float)
    correlation = None
    rank_correlation = None
    if y.size > 1 and np.std(y) > 0 and np.std(p) > 0:
        correlation = float(np.corrcoef(y, p)[0, 1])
        if np.std(y_rank) > 0 and np.std(p_rank) > 0:
            rank_correlation = float(np.corrcoef(y_rank, p_rank)[0, 1])
    return {"rows": int(y.size), "mae": mae,
        "rmse": rmse,
        "pearson_correlation": correlation, "spearman_correlation": rank_correlation,
        "interpretation": "descriptive only; not fresh OOS or strategy performance"}


def _fit_predict(model_name: str, model: Any, samples: dict[str, list[dict[str, Any]]],
                 feature_rows: dict[tuple[str, str], dict[str, Any]],
                 feature_columns: list[str]):
    train = samples["train"]
    x_train = np.asarray([row["features"] for row in train], dtype=float)
    y_train = np.asarray([row["target"] for row in train], dtype=float)
    if not np.isfinite(x_train).all() or not np.isfinite(y_train).all():
        raise ModelResearchError("training matrix or labels are non-finite")
    model.fit(x_train, y_train)
    predictions = {}
    for key, row in sorted(feature_rows.items(), key=lambda item: (item[0][1], item[0][0])):
        values = []
        for column in feature_columns:
            value = row.get(column)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ModelResearchError(f"prediction feature must be finite and complete: {column} {key[0]} {key[1]}")
            values.append(float(value))
        score = float(model.predict(np.asarray([values], dtype=float))[0])
        if not math.isfinite(score):
            raise ModelResearchError(f"model emitted a non-finite prediction: {key[0]} {key[1]}")
        predictions[key] = score
    split_metrics = {}
    for split_name, rows in samples.items():
        split_metrics[split_name] = _metrics([row["target"] for row in rows],
            [predictions[(row["code"], row["signal_date"])] for row in rows])
    return predictions, split_metrics


def _sample_ranges(samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    result = {}
    for name, rows in samples.items():
        result[name] = {
            "rows": len(rows),
            "signal_date_min": min((row["signal_date"] for row in rows), default=None),
            "signal_date_max": max((row["signal_date"] for row in rows), default=None),
            "label_end_date_min": min((row["label_end_date"] for row in rows), default=None),
            "label_end_date_max": max((row["label_end_date"] for row in rows), default=None),
        }
    return result


def _save_model(model_name: str, model: Any, target: Path) -> Path:
    if model_name == "lightgbm":
        path = target / "model.txt"
        model.booster_.save_model(str(path))
    else:
        path = target / "model.cbm"
        model.save_model(str(path), format="cbm")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ModelResearchError("model artifact was not written")
    return path


def run_model_research(factor_run_dir: str | Path, output_dir: str | Path,
                       model_name: str) -> dict[str, Any]:
    """Fit one fixed estimator and create predictions from no-label feature rows."""
    if not isinstance(model_name, str) or model_name not in _SUPPORTED_MODELS:
        raise ModelResearchError(f"model_name must be one of {sorted(_SUPPORTED_MODELS)}")
    source_dir = Path(factor_run_dir).expanduser().resolve(strict=True)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise ModelResearchError("output_dir must be a new directory")
    report, factor_contract, feature_doc, evaluation_doc, source_hashes = _input_bundle(source_dir)
    recipe = validate_recipe(report["recipe"])
    feature_columns = _feature_columns(recipe)
    feature_rows = _index_rows(feature_doc["rows"], label_rows=False)
    samples, split_counts = _build_samples(feature_doc, evaluation_doc, feature_columns)
    # Validate every supplied row and its D-1/label chronology before importing
    # an optional estimator. Invalid research inputs should not be masked by a
    # missing LightGBM/CatBoost installation.
    model_module, runtime = _model_runtime(model_name)
    parameters = dict(_MODEL_PARAMETERS[model_name])
    training_label_end_max = max(row["label_end_date"] for row in samples["train"])
    contract = {
        "schema": "kabuforge.model_research_contract.v1", "status": "PREREGISTERED",
        "created_at": datetime.now(timezone.utc).isoformat(), "readiness": "RESEARCH-ONLY",
        "pit_guarantee": False,
        "model_name": model_name, "random_seed": 42,
        "parameters": parameters, "features": feature_columns,
        "preprocessing": "none; no scaling, imputation, feature selection, or target-derived transform",
        "splits": _SPLITS, "purge_rule": "label_end_date must be strictly before the next split boundary",
        "label_semantics": evaluation_doc.get("label_semantics"),
        "train_validation_role": "validation is reported only; no hyperparameter or feature selection is performed",
        "test_role": "historical diagnostic only; this observed window is not fresh OOS evidence",
        "training_label_end_max": training_label_end_max,
        "prediction_contract": "only validation/test feature rows after the maximum training-label end are emitted; training-period predictions stay out of the strategy-facing artifact",
        "factor_input": {"recipe_sha256": report["recipe_sha256"],
            "input_identity": report["input_identity"],
            "factor_provider_identity": report["provider_identity"],
            "source_file_sha256": source_hashes},
        "model_runtime": runtime,
        "forbidden_inferences": ["not validated alpha", "not strategy performance", "not PAPER-READY",
            "not fresh OOS evidence", "no model or feature auto-selection"],
    }
    target.mkdir(parents=True, exist_ok=False)
    write_new(target / "contract.json", contract)
    try:
        model = _make_model(model_name, model_module)
        predictions, metrics = _fit_predict(model_name, model, samples, feature_rows, feature_columns)
        # Source bytes must remain identical from preregistration through training.
        for name, expected in source_hashes.items():
            if _sha256_file(source_dir / f"{name}.json") != expected:
                raise ModelResearchError(f"factor input changed during model run: {name}")
        model_path = _save_model(model_name, model, target)
        prediction_rows = []
        for (code, signal_date), row in sorted(feature_rows.items(), key=lambda item: (item[0][1], item[0][0])):
            if signal_date < _SPLITS["validation"]["signal_start"]:
                continue
            if signal_date <= training_label_end_max:
                raise ModelResearchError("prediction signal date is not after the training-label cutoff")
            role = ("validation_diagnostic" if signal_date <= _SPLITS["validation"]["signal_end"]
                    else "historical_test_diagnostic")
            prediction_rows.append({"code": code, "signal_date": signal_date,
                "d1_cutoff_date": row.get("d1_cutoff_date"),
                "execution_date": row.get("execution_date"),
                "prediction_role": role,
                "model_training_label_end_max": training_label_end_max,
                "prediction": predictions[(code, signal_date)]})
        if any(_LABEL_FIELDS.intersection(row) for row in prediction_rows):
            raise ModelResearchError("prediction artifact unexpectedly contains label fields")
        model_identity = {"file": str(model_path), "sha256": _sha256_file(model_path),
                          "bytes": model_path.stat().st_size}
        prediction_doc = {"schema": "kabuforge.model_prediction_rows.v1",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "contains_forward_labels": False,
            "input_identity": report["input_identity"],
            "recipe_sha256": report["recipe_sha256"], "model_name": model_name,
            "model_artifact_sha256": model_identity["sha256"], "rows": prediction_rows}
        prediction_path = target / "predictions.json"
        write_new(prediction_path, prediction_doc)
        report_doc = {
            "schema": "kabuforge.model_research_report.v1", "status": "COMPLETED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "model_name": model_name,
            "random_seed": 42, "parameters": parameters, "features": feature_columns,
            "split_counts": split_counts, "metrics": metrics,
            "split_ranges": _sample_ranges(samples),
            "prediction_row_count": len(prediction_rows),
            "model_training_label_end_max": training_label_end_max,
            "prediction_signal_date_min": min((row["signal_date"] for row in prediction_rows), default=None),
            "prediction_rows": {"file": str(prediction_path),
                "sha256": _sha256_file(prediction_path),
                "contains_forward_labels": False},
            "model_artifact": model_identity,
            "input_identity": report["input_identity"],
            "factor_source_file_sha256": source_hashes,
            "recipe_sha256": report["recipe_sha256"], "model_runtime": runtime,
            "limitations": ["2017-2022 has been observed; validation/test are not fresh OOS",
                "only the fixed 3-code universe is represented", "forward labels overlap within splits",
                "no costs, turnover, portfolio construction, benchmark, or execution is modeled"],
        }
        write_new(target / "report.json", report_doc)
        write_new(target / "receipt.json", {
            "schema": "kabuforge.model_research_receipt.v1", "status": "COMPLETED",
            "model_name": model_name, "readiness": "RESEARCH-ONLY",
            "pit_guarantee": False,
            "contract_sha256": _sha256_file(target / "contract.json"),
            "report_sha256": _sha256_file(target / "report.json"),
            "predictions_sha256": _sha256_file(target / "predictions.json"),
            "model_sha256": _sha256_file(model_path),
        })
        return report_doc
    except Exception as exc:
        failure = {"schema": "kabuforge.model_research_failure.v1", "status": "FAILED",
            "model_name": model_name, "readiness": "RESEARCH-ONLY",
            "pit_guarantee": False, "error_type": type(exc).__name__,
            "reason": str(exc), "source_file_sha256": source_hashes,
            "model_runtime": runtime}
        write_new(target / "failure.json", failure)
        raise


__all__ = ["ModelResearchError", "run_model_research"]
