"""Static-operation child worker for local research Studio tasks.

Only the operations and model/backend names declared below are accepted.
The worker receives a workspace plus UUID, then reads one generated request
from that job directory; it never accepts a Python module, script or runtime
path from the request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import sysconfig
import traceback
from typing import Any


_REQUEST_SCHEMA = "kabuforge.research_studio_request.v1"
_RESULT_SCHEMA = "kabuforge.research_studio_result.v1"
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_MODELS = {"lightgbm", "catboost"}
_BACKENDS = {"vectorbt", "backtrader"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_request(workspace: Path, job_id: str) -> tuple[Path, dict[str, Any]]:
    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job id must be a lowercase UUID hex string")
    workspace = workspace.expanduser().resolve(strict=True)
    jobs_root = (workspace / "research-studio" / "jobs").resolve()
    if not jobs_root.is_relative_to(workspace) or jobs_root == workspace:
        raise ValueError("research Studio job root escapes the selected workspace")
    job_dir = (jobs_root / job_id).resolve(strict=True)
    if (not job_dir.is_relative_to(jobs_root) or not job_dir.is_relative_to(workspace)
            or job_dir == jobs_root):
        raise ValueError("job directory escapes the selected workspace")
    request_path = job_dir / "request.json"
    if not request_path.is_file():
        raise ValueError("job request is missing")
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("job request cannot be read as JSON") from None
    if not isinstance(request, dict) or request.get("schema") != _REQUEST_SCHEMA:
        raise ValueError("unsupported research Studio request schema")
    if request.get("job_id") != job_id:
        raise ValueError("job request identity does not match its directory")
    if request.get("operation") not in {"factor_strategy", "model_training", "engine_comparison"}:
        raise ValueError("operation is not in the static worker allowlist")
    if (job_dir / "result.json").exists() or (job_dir / "failure.json").exists():
        raise ValueError("job already has a terminal result")
    output_dir = job_dir / "outputs"
    resolved_output = output_dir.resolve()
    if not resolved_output.is_relative_to(job_dir) or resolved_output == job_dir:
        raise ValueError("research Studio output directory escapes the selected job")
    output_dir.mkdir(exist_ok=True)
    if not output_dir.resolve(strict=True).is_relative_to(job_dir):
        raise ValueError("research Studio output directory escapes the selected job")
    return job_dir, request


def _request_keys(request: dict[str, Any], expected: set[str]) -> None:
    if set(request) != expected:
        raise ValueError("request fields do not match the selected static operation")


def _manifest(request: dict[str, Any]) -> Path:
    path = Path(request["manifest_path"]).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".json":
        raise ValueError("selected frozen manifest is not a JSON file")
    expected = request["manifest_sha256"]
    if not isinstance(expected, str) or _sha256(path) != expected:
        raise ValueError("selected frozen manifest byte hash does not match the request")
    return path


def _factor_strategy(job_dir: Path, request: dict[str, Any]) -> dict[str, Any]:
    _request_keys(request, {"schema", "job_id", "operation", "manifest_path", "manifest_sha256",
                            "score_path", "score_sha256", "score_source", "recipe"})
    manifest = _manifest(request)
    artifact = Path(request["score_path"]).expanduser().resolve(strict=True)
    source = request["score_source"]
    permitted_names = {"factor_feature_rows": "feature_rows.json", "model_predictions": "predictions.json"}
    if source not in permitted_names or artifact.name != permitted_names[source]:
        raise ValueError("score source and permitted artifact filename do not match")
    if not isinstance(request["score_sha256"], str) or _sha256(artifact) != request["score_sha256"]:
        raise ValueError("score artifact byte hash does not match the request")
    from .factor_strategy_research import run_factor_strategy_research

    target = job_dir / "outputs" / "strategy"
    report_path = run_factor_strategy_research(
        manifest, artifact, target, request["recipe"], score_source=source,
        expected_artifact_sha256=request["score_sha256"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {"status": "COMPLETED", "report_path": str(report_path),
            "report_sha256": _sha256(report_path),
            "score_source": source, "score_artifact_sha256": request["score_sha256"]}


def _require_extension_runtime(project_root: Path, operation: str,
                               choices: dict[str, Any]) -> dict[str, Any]:
    """Check only selected installed extras; public paths=[] is a valid runtime."""
    from .research_runtime import resolve_extension_runtime

    detected = "win-amd64" if os.name == "nt" and sys.maxsize > 2**32 else sysconfig.get_platform()
    state = resolve_extension_runtime(project_root, platform.python_version(), detected,
                                      operation=operation, choices=choices)
    if not state.get("enabled"):
        raise RuntimeError("selected optional workflow dependencies are unavailable: " + str(state.get("reason")))
    for path in reversed(state.get("paths", [])):
        sys.path.insert(0, path)
    return state


def _model_training(job_dir: Path, request: dict[str, Any], project_root: Path) -> dict[str, Any]:
    _request_keys(request, {"schema", "job_id", "operation", "manifest_path", "manifest_sha256",
                            "factor_run_dir", "factor_bundle_sha256", "model_names"})
    manifest = _manifest(request)
    model_names = request["model_names"]
    if (not isinstance(model_names, list) or not model_names or len(model_names) > 2
            or any(not isinstance(name, str) for name in model_names)
            or len(set(model_names)) != len(model_names) or set(model_names) - _MODELS):
        raise ValueError("model_names must select one or both statically supported tree models")
    runtime = _require_extension_runtime(project_root, "model-training",
                                         {"model_names": request["model_names"]})
    from .model_research import run_model_research

    factor_run_dir = Path(request["factor_run_dir"]).expanduser().resolve(strict=True)
    if not factor_run_dir.is_dir():
        raise ValueError("factor run selection must be a directory")
    factor_report_path = factor_run_dir / "report.json"
    try:
        factor_report = json.loads(factor_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("selected factor report cannot be read") from None
    selected_identity = factor_report.get("input_identity") if isinstance(factor_report, dict) else None
    if not isinstance(selected_identity, dict) or selected_identity.get("manifest_sha256") != request["manifest_sha256"]:
        raise ValueError("factor run belongs to a different frozen manifest")
    if _sha256(manifest) != request["manifest_sha256"]:
        raise ValueError("selected frozen manifest changed before model training")
    expected_bundle = request["factor_bundle_sha256"]
    required_bundle = {name: _sha256(factor_run_dir / name)
                       for name in ("contract.json", "report.json", "feature_rows.json", "evaluation_panel.json")}
    if not isinstance(expected_bundle, dict) or expected_bundle != required_bundle:
        raise ValueError("factor-run bundle changed after model-training selection")
    results = []
    for model_name in model_names:
        output = job_dir / "outputs" / f"model-{model_name}"
        try:
            report = run_model_research(factor_run_dir, output, model_name)
            prediction_path = Path(report["prediction_rows"]["file"]).resolve(strict=True)
            results.append({"model_name": model_name, "status": "COMPLETED",
                "report_path": str(output / "report.json"),
                "prediction_path": str(prediction_path),
                "prediction_sha256": _sha256(prediction_path),
                "model_sha256": report["model_artifact"]["sha256"],
                "split_counts": report["split_counts"], "metrics": report["metrics"],
                "model_training_label_end_max": report["model_training_label_end_max"],
                "prediction_signal_date_min": report["prediction_signal_date_min"]})
        except Exception as exc:
            failure = output / "failure.json"
            results.append({"model_name": model_name, "status": "FAILED",
                "error_type": type(exc).__name__, "reason": str(exc),
                "failure_path": str(failure) if failure.is_file() else None})
        status = "COMPLETED" if all(item["status"] == "COMPLETED" for item in results) else (
        "FAILED" if all(item["status"] == "FAILED" for item in results) else "PARTIAL")
    return {"status": status, "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "model_runs": results,
            "runtime": {"python": runtime["python_version"], "versions": runtime["versions"]},
            "selection_policy": "all requested results and failures are reported; no model is auto-selected"}


def _engine_comparison(job_dir: Path, request: dict[str, Any], project_root: Path) -> dict[str, Any]:
    _request_keys(request, {"schema", "job_id", "operation", "manifest_path", "manifest_sha256", "recipes"})
    manifest = _manifest(request)
    recipes = request["recipes"]
    if not isinstance(recipes, list) or not 1 <= len(recipes) <= 3:
        raise ValueError("engine comparison accepts one to three preregistered candidates")
    runtime = _require_extension_runtime(project_root, "engine-comparison",
                                         {"backends": ["vectorbt", "backtrader"]})
    from .engine_research import run_engine_research

    results = []
    for recipe in recipes:
        if not isinstance(recipe, dict) or set(recipe) != {"signal_template", "lookback", "count", "frequency", "cash", "fee"}:
            raise ValueError("engine recipe has unexpected fields")
        if (recipe["signal_template"] != "price_momentum" or recipe["lookback"] not in {20, 60}
                or recipe["count"] != 2 or recipe["frequency"] != "monthly"
                or recipe["cash"] != 2_000_000.0 or recipe["fee"] != 0.1):
            raise ValueError("engine candidate is outside the fixed 20/60 lookback teaching set")
        label = f"lookback-{recipe['lookback']}"
        output = job_dir / "outputs" / label
        try:
            receipt_path = run_engine_research(manifest, output, recipe, backends=("vectorbt", "backtrader"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            native_path = output / "native.json"
            native = json.loads(native_path.read_text(encoding="utf-8")) if native_path.is_file() else {}
            timeline = native.get("timeline", [])
            nav_values = [float(row["nav"]) for row in timeline
                          if isinstance(row.get("nav"), (int, float)) and math.isfinite(float(row["nav"]))]
            peak = -math.inf; max_drawdown = None
            if nav_values:
                drawdowns = []
                for value in nav_values:
                    peak = max(peak, value); drawdowns.append(value / peak - 1.0)
                max_drawdown = min(drawdowns)
            comparison_files = []
            for backend, status in receipt.get("backend_status", {}).items():
                comparison_path = output / f"comparison_{backend}.json"
                if comparison_path.is_file():
                    comparison_doc = json.loads(comparison_path.read_text(encoding="utf-8"))
                    comparison_files.append({"backend": backend, "path": str(comparison_path),
                        "status": comparison_doc.get("status"),
                        "daily_account_exceedances": len(comparison_doc.get("daily_account_exceedances", [])),
                        "fill_differences": len(comparison_doc.get("fill_differences", [])),
                        "skip_differences": len(comparison_doc.get("skip_differences", [])),
                        "fee_difference": comparison_doc.get("fees", {}).get("difference"),
                        "fill_count": comparison_doc.get("fill_count"),
                        "skip_count": comparison_doc.get("skip_count")})
            comparison_values = list(receipt.get("comparison_status", {}).values())
            backend_values = [item.get("status") for item in receipt.get("backend_status", {}).values()]
            candidate_status = ("COMPLETED" if backend_values and all(value == "COMPLETED" for value in backend_values)
                               and comparison_values and all(value == "MATCHED_WITHIN_TOLERANCE" for value in comparison_values)
                               else "PARTIAL")
            results.append({"candidate": label, "status": candidate_status,
                "receipt_path": str(receipt_path),
                "native_summary": {"observed_sessions":len(timeline),
                    "start_date":timeline[0].get("at") if timeline else None,
                    "end_date":timeline[-1].get("at") if timeline else None,
                    "ending_normalized_nav":timeline[-1].get("nav") if timeline else None,
                    "ending_cash":timeline[-1].get("cash") if timeline else None,
                    "max_drawdown_from_reported_nav":max_drawdown,
                    "fees":native.get("fees"), "fills":len(native.get("fills",[])),
                    "skips":len(native.get("skips",[]))},
                "backend_status": receipt.get("backend_status", {}),
                "comparison_status": receipt.get("comparison_status", {}),
                "comparisons": comparison_files})
        except Exception as exc:
            results.append({"candidate": label, "status": "FAILED",
                "error_type": type(exc).__name__, "reason": str(exc)})
    status = "COMPLETED" if all(item["status"] == "COMPLETED" for item in results) else (
        "FAILED" if all(item["status"] == "FAILED" for item in results) else "PARTIAL")
    return {"status": status, "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "candidates": results,
            "runtime": {"python": runtime["python_version"], "versions": runtime["versions"]},
            "selection_policy": "all preregistered candidates are reported; none is auto-selected"}


def _install_offline_guards() -> list[str]:
    """Deny network sockets and credential retrieval for every Studio operation."""
    import socket

    def denied(*_args, **_kwargs):
        raise PermissionError("Research Studio workers are offline; network access is blocked")

    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    from . import data_connection

    def denied_credentials():
        raise PermissionError("Research Studio workers never read API credentials")

    data_connection.load_api_key = denied_credentials
    return ["socket.create_connection/connect/connect_ex denied", "data_connection.load_api_key denied"]


def run_job(workspace: str | Path, job_id: str) -> dict[str, Any]:
    workspace_path = Path(workspace).expanduser().resolve(strict=True)
    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job id must be a lowercase UUID hex string")
    workspace_research_root = workspace_path / "research-studio"
    jobs_root = (workspace_research_root / "jobs").resolve(strict=True)
    if not jobs_root.is_relative_to(workspace_path) or jobs_root == workspace_path:
        raise ValueError("research Studio job root escapes the selected workspace")
    job_dir = (jobs_root / job_id).resolve(strict=True)
    if (not job_dir.is_relative_to(jobs_root) or not job_dir.is_relative_to(workspace_path)
            or job_dir == jobs_root):
        raise ValueError("job directory escapes the selected workspace")
    try:
        job_dir, request = _read_request(workspace_path, job_id)
    except Exception as exc:
        failure = {"schema":"kabuforge.research_studio_failure.v1", "job_id":job_id,
            "operation":None, "status":"FAILED", "error_type":type(exc).__name__,
            "reason":str(exc), "readiness":"RESEARCH-ONLY", "pit_guarantee":False}
        if not (job_dir/"result.json").exists() and not (job_dir/"failure.json").exists():
            try:
                with (job_dir/"failure.json").open("x",encoding="utf-8",newline="") as stream:
                    json.dump(failure,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write("\n")
            except OSError: pass
        return failure
    project_root = Path(__file__).resolve().parents[1]
    operation = request["operation"]
    print(json.dumps({"event": "started", "job_id": job_id, "operation": operation}), flush=True)
    offline_guards = []
    try:
        offline_guards = _install_offline_guards()
        if operation == "factor_strategy":
            result = _factor_strategy(job_dir, request)
        elif operation == "model_training":
            result = _model_training(job_dir, request, project_root)
        else:
            result = _engine_comparison(job_dir, request, project_root)
        result_doc = {"schema": _RESULT_SCHEMA, "job_id": job_id, "operation": operation,
                      "manifest_sha256": request.get("manifest_sha256"),
                      "offline_guards": offline_guards, **result}
        with (job_dir / "result.json").open("x", encoding="utf-8", newline="") as stream:
            json.dump(result_doc, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"event": "finished", "job_id": job_id, "status": result_doc["status"]}), flush=True)
        return result_doc
    except Exception as exc:
        failure = {"schema": "kabuforge.research_studio_failure.v1", "job_id": job_id,
            "operation": operation, "status": "FAILED", "error_type": type(exc).__name__,
            "reason": str(exc), "traceback": traceback.format_exc(limit=8),
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "offline_guards": offline_guards}
        try:
            with (job_dir / "failure.json").open("x", encoding="utf-8", newline="") as stream:
                json.dump(failure, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        except OSError:
            pass
        print(json.dumps({"event": "failed", "job_id": job_id,
                          "error_type": failure["error_type"], "reason": failure["reason"]},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return failure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one allowlisted KabuForge research Studio task")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    result = run_job(args.workspace, args.job_id)
    return 0 if result.get("status") in {"COMPLETED", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
