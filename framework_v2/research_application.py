"""Shared, workspace-bounded Python facade for local research services.

This module is an adapter only: financial calculations remain in the fixed
research cores. Model/engine operations use the static research Studio worker;
paper writes require explicit opt-in and durable idempotency keys.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import sysconfig
import threading
import time
import uuid
from contextlib import closing
from typing import Any, Callable


class ResearchApplicationError(RuntimeError):
    """A local research operation failed at a recorded stage."""

    def __init__(self, stage: str, message: str, *, task_dir: Path | None = None,
                 error_type: str = "ResearchApplicationError"):
        self.stage, self.task_dir, self.error_type = stage, task_dir, error_type
        super().__init__(message)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default).encode("utf-8")


def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _write_new(path: Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False, default=_json_default).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded + b"\n")


def _file_ref(role: str, value: str | Path) -> dict[str, Any]:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"{role} must be an explicitly selected file")
    return {"role": role, "path": str(path), "name": path.name,
            "size_bytes": path.stat().st_size, "sha256": _sha_file(path)}


def _bundle_ref(directory: str | Path) -> dict[str, Any]:
    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("factor run must be an explicitly selected directory")
    names = ("contract.json", "report.json", "feature_rows.json", "evaluation_panel.json")
    files = {name: _sha_file(root / name) for name in names}
    return {"path": str(root), "files": files}


def _indicator_code_matches(requested: str, resolved: str) -> bool:
    return resolved == requested or (len(requested) == 4 and len(resolved) == 5
                                     and resolved.startswith(requested))


class ResearchApplicationService:
    """Stable Python entry point over the same fixed research cores as the GUI.

    Inputs are explicit file references. All new run outputs are beneath this
    service's workspace. No method accepts Python code, module names, or an
    interpreter path from a request.
    """

    def __init__(self, workspace: str | Path, *, enable_paper: bool = False):
        if type(enable_paper) is not bool:
            raise TypeError("enable_paper must be an explicit bool")
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.workspace.is_symlink() or not self.workspace.is_dir():
            raise ValueError("workspace must resolve to a local directory")
        self.enable_paper = enable_paper
        self.project_root = Path(__file__).resolve().parents[1]
        self._lock = threading.RLock()

    @staticmethod
    def validate_factor_recipe(recipe: dict | None = None) -> dict:
        from .factor_research import validate_recipe
        return validate_recipe(recipe)

    def capabilities(self) -> dict[str, Any]:
        """Return conservative service availability without importing optional libraries."""
        worker = self.project_root / "framework_v2" / "research_studio_worker.py"
        indicator_worker = self.project_root / "framework_v2" / "indicator_research_worker.py"
        indicators = {provider: self._extension_runtime(
            "indicators", {"provider": provider}) for provider in ("talib", "pandas-ta")}
        models = {name: self._extension_runtime(
            "model-training", {"model_names": [name]}) for name in ("lightgbm", "catboost")}
        engines = {name: self._extension_runtime(
            "engine-comparison", {"backends": [name]}) for name in ("vectorbt", "backtrader")}
        ready_indicator = indicator_worker.is_file() and any(
            state.get("enabled") for state in indicators.values())
        studio_ready = worker.is_file()
        native_runtime = self._extension_runtime("native")
        optional = {"indicators": indicators, "models": models, "engines": engines}
        return {
            "schema": "kabuforge.research_application_capabilities.v1",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "available": {
                "price_research": True, "factor_diagnostics": True,
                "factor_strategy": studio_ready,
                "model_training": studio_ready and any(state.get("enabled") for state in models.values()),
                "engine_comparison": studio_ready and all(state.get("enabled") for state in engines.values()),
                "historical_paper": True,
                "broker_offline_preview": True,
                "broker_read_only_check": (self.project_root / "framework_v2" / "broker_readonly.py").is_file(),
                "price_sensitivity": (self.project_root / "framework_v2" / "price_sensitivity_worker.py").is_file(),
                "indicator_research": ready_indicator,
            },
            "unavailable_reasons": {
                "indicator_research": (None if ready_indicator else
                    ("fixed indicator worker is missing" if not indicator_worker.is_file() else
                     "; ".join(str(state.get("reason")) for state in indicators.values()
                               if state.get("reason")))),
                "model_training": {name: state.get("reason") for name, state in models.items()
                                   if not state.get("enabled")},
                "engine_comparison": {name: state.get("reason") for name, state in engines.items()
                                      if not state.get("enabled")},
            },
            "extension_runtime": {"enabled": bool(native_runtime.get("enabled")),
                                  "versions": native_runtime.get("versions", {}),
                                  "reason": "optional packages are checked per selected operation"},
            "optional_operations": optional,
            "model_and_engine": "static research_studio_worker subprocess; only selected model/backend dependencies are checked",
            "indicator": "static indicator_research_worker subprocess; only the selected provider dependencies are checked",
            "external_actions": False, "network_requested": False,
        }

    def _safe_workspace_path(self, value: str | Path, *, must_exist: bool = True) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve(strict=must_exist)
        if not resolved.is_relative_to(self.workspace) or resolved == self.workspace:
            raise ValueError("mutable research workspace path must stay inside the selected workspace")
        return resolved

    def _new_task(self, operation: str, request: dict[str, Any], *, root_name: str = "research-tasks") -> tuple[str, Path]:
        root = self._safe_workspace_path(self.workspace / root_name, must_exist=False)
        root.mkdir(parents=True, exist_ok=True)
        root = self._safe_workspace_path(root, must_exist=True)
        task_id = uuid.uuid4().hex
        task_dir = self._safe_workspace_path(root / task_id, must_exist=False)
        task_dir.mkdir(exist_ok=False)
        task_dir = self._safe_workspace_path(task_dir, must_exist=True)
        operation_sources = {
            "price_research": ("price_research.py", "local_cache.py"),
            "factor_diagnostics": ("factor_research.py", "local_cache.py"),
            "indicator_research": ("indicator_research_worker.py", "indicator_research.py",
                                   "local_cache.py", "research_runtime.py"),
            "factor_strategy": ("research_studio_worker.py", "factor_strategy_research.py", "price_research.py", "local_cache.py", "research_runtime.py"),
            "model_training": ("research_studio_worker.py", "model_research.py", "factor_research.py", "research_runtime.py"),
            "engine_comparison": ("research_studio_worker.py", "engine_research.py", "price_research.py", "local_cache.py", "research_runtime.py"),
            "price_sensitivity": ("price_sensitivity_worker.py", "price_sensitivity.py", "price_research.py", "local_cache.py"),
            "historical_paper_create": ("historical_paper_research.py", "local_cache.py"),
            "historical_paper_step": ("historical_paper_research.py", "local_cache.py"),
            "historical_paper_run_all": ("historical_paper_research.py", "local_cache.py"),
            "broker_workspace_create": ("broker_research.py", "brokers.py", "execution.py"),
            "broker_order_preview": ("broker_research.py", "brokers.py", "execution.py"),
            "broker_readonly_check": ("broker_readonly.py", "broker_research.py"),
        }
        source_hashes = {"research_application.py": _sha_file(Path(__file__).resolve())}
        for name in operation_sources.get(operation, ()):
            source_hashes[name] = _sha_file(self.project_root / "framework_v2" / name)
        request_doc = {"schema": "kabuforge.research_application_request.v1",
            "task_id": task_id, "operation": operation, "created_at_utc": _utc(),
            "program": "ResearchApplicationService", "python": sys.version.split()[0],
            # `platform.platform()` may call subprocess on Windows to query
            # WMI. Keep request creation deterministic and safe when callers
            # wrap subprocess for a worker protocol test.
            "platform": f"{platform.system()}-{platform.machine()}", "request": request,
            "source_sha256": source_hashes}
        _write_new(task_dir / "application_request.json", request_doc)
        _write_new(task_dir / "launch.json", {"task_id": task_id, "operation": operation,
            "pid": os.getpid(), "started_at_utc": _utc(), "program": "ResearchApplicationService",
            "argv": ["ResearchApplicationService", operation],
            "input_sha256": hashlib.sha256(_canonical(request)).hexdigest(),
            "output_dir": str(task_dir), "recovery": "retain this task; retries receive a new task id"})
        return task_id, task_dir

    def _artifact_refs(self, paths: list[Path], task_dir: Path) -> list[dict[str, Any]]:
        refs = []
        task_root = self._safe_workspace_path(task_dir, must_exist=True)
        for raw in paths:
            path = self._safe_workspace_path(raw, must_exist=True)
            if not path.is_file():
                raise ValueError("returned artifact must be an existing file inside the selected workspace")
            refs.append({"path": str(path), "relative_to_task": str(path.relative_to(task_root))
                         if path.is_relative_to(task_root) else None,
                         "size_bytes": path.stat().st_size, "sha256": _sha_file(path)})
        return refs

    def _validate_result_artifacts(self, value: Any) -> None:
        """Resolve every declared output reference before it is returned or persisted."""
        file_keys = {"artifact_path", "report_path", "receipt_path"}
        directory_keys = {"task_dir", "output_dir", "account_dir", "workspace"}

        def visit(item: Any, *, artifact_map: bool = False) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key == "artifacts":
                        if isinstance(child, dict):
                            for name, ref in child.items():
                                if isinstance(ref, str) and not name.lower().endswith("sha256") and (
                                        name.endswith("_path") or name in {"contract", "feature_rows",
                                            "evaluation_panel", "report", "receipt", "canonical_data",
                                            "frozen_data"} or Path(ref).is_absolute()):
                                    resolved = self._safe_workspace_path(ref, must_exist=True)
                                    if not resolved.is_file():
                                        raise ValueError("declared artifact is not a file inside the selected workspace")
                                else:
                                    visit(ref, artifact_map=True)
                        elif isinstance(child, list):
                            visit(child, artifact_map=True)
                    elif key in file_keys and isinstance(child, str):
                        resolved = self._safe_workspace_path(child, must_exist=True)
                        if not resolved.is_file():
                            raise ValueError("declared artifact is not a file inside the selected workspace")
                    elif key in directory_keys and isinstance(child, str):
                        resolved = self._safe_workspace_path(child, must_exist=True)
                        if not resolved.is_dir():
                            raise ValueError("declared output directory is not inside the selected workspace")
                    else:
                        visit(child, artifact_map=artifact_map)
            elif isinstance(item, list):
                for child in item:
                    if artifact_map and isinstance(child, str):
                        resolved = self._safe_workspace_path(child, must_exist=True)
                        if not resolved.is_file():
                            raise ValueError("declared artifact is not a file inside the selected workspace")
                    else:
                        visit(child, artifact_map=artifact_map)

        visit(value)

    def _execute(self, operation: str, request: dict[str, Any],
                 action: Callable[[Path], tuple[Any, list[Path]]], *,
                 root_name: str = "research-tasks"):
        task_id, task_dir = self._new_task(operation, request, root_name=root_name)
        started = _utc()
        try:
            value, artifacts = action(task_dir)
            self._validate_result_artifacts(value)
            response = {"schema": "kabuforge.research_application_result.v1", "task_id": task_id,
                "operation": operation, "status": "COMPLETED", "readiness": "RESEARCH-ONLY",
                "pit_guarantee": False, "task_dir": str(task_dir), "result": value,
                "artifacts": self._artifact_refs(artifacts, task_dir)}
            _write_new(task_dir / "application_result.json", response)
            _write_new(task_dir / "completion.json", {"task_id": task_id, "status": "COMPLETED",
                "started_at_utc": started, "finished_at_utc": _utc(), "pid": os.getpid(),
                "artifact_count": len(response["artifacts"])})
            return response
        except Exception as exc:
            failure = {"schema": "kabuforge.research_application_failure.v1", "task_id": task_id,
                "operation": operation, "status": "FAILED", "stage": operation,
                "error_type": type(exc).__name__, "reason": str(exc),
                "started_at_utc": started, "finished_at_utc": _utc(), "pid": os.getpid(),
                "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            try:
                _write_new(task_dir / "failure.json", failure)
            except OSError:
                pass
            raise ResearchApplicationError(operation, str(exc), task_dir=task_dir,
                                           error_type=type(exc).__name__) from exc

    def run_price_research(self, manifest_path: str | Path, recipe: dict[str, Any], *,
                           regime_observer: dict | None = None) -> dict[str, Any]:
        from .price_research import preflight_price_research, run_price_research
        manifest = _file_ref("bars_manifest", manifest_path)
        if not isinstance(recipe, dict):
            raise TypeError("price recipe must be an explicit object")
        if regime_observer is not None and regime_observer != {"mode": "off"}:
            raise ValueError("only Regime mode off is available in the public candidate")
        request = {"manifest": manifest, "recipe": recipe, "regime_mode": "off"}
        def action(task_dir):
            preflight = preflight_price_research(manifest_path, recipe, regime_observer)
            _write_new(task_dir / "preflight.json", preflight)
            output = self._safe_workspace_path(task_dir / "outputs" / "price", must_exist=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output = self._safe_workspace_path(output, must_exist=False)
            report_path = run_price_research(manifest_path, recipe, output,
                regime_observer=regime_observer, expected_preflight=preflight["fingerprint"])
            report_path = self._safe_workspace_path(report_path, must_exist=True)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            artifacts = [path for path in (report_path, output / "research_inputs.json") if path.is_file()]
            return {"report": report, "preflight_fingerprint": preflight["fingerprint"],
                    "report_path": str(report_path)}, artifacts
        return self._execute("price_research", request, action)

    def run_factor_diagnostics(self, manifest_path: str | Path,
                               recipe: dict[str, Any] | None = None, *,
                               return_task_envelope: bool = False) -> dict[str, Any]:
        """Run factor diagnostics and preserve the GUI's original report contract.

        Existing GUI callers consume the core report directly, including its
        ``artifacts.contract`` path. New adapters can request the durable task
        envelope explicitly or call :meth:`run_factor_diagnostics_task`.
        """
        from .factor_research import run_factor_research
        manifest = _file_ref("bars_manifest", manifest_path)
        recipe_value = self.validate_factor_recipe(recipe)
        request = {"manifest": manifest, "recipe": recipe_value}
        def action(task_dir):
            output_root = self._safe_workspace_path(self.workspace / "factor-research", must_exist=False)
            output_root.mkdir(parents=True, exist_ok=True)
            output_root = self._safe_workspace_path(output_root, must_exist=True)
            output = self._safe_workspace_path(output_root / ("run-" + uuid.uuid4().hex), must_exist=False)
            result = run_factor_research(manifest_path, output, recipe_value)
            output = self._safe_workspace_path(output, must_exist=True)
            for artifact_name in ("contract", "feature_rows", "evaluation_panel"):
                artifact = result.get("artifacts", {}).get(artifact_name)
                if not isinstance(artifact, str):
                    raise ValueError("factor core returned an incomplete artifact reference")
                checked = self._safe_workspace_path(artifact, must_exist=True)
                if not checked.is_file() or not checked.is_relative_to(output):
                    raise ValueError("factor artifact escaped its isolated output directory")
            report = self._safe_workspace_path(output / "report.json", must_exist=True)
            artifacts = [self._safe_workspace_path(output / name, must_exist=True)
                         for name in ("contract.json", "report.json", "feature_rows.json", "evaluation_panel.json")]
            return {"report": result, "report_path": str(report)}, artifacts
        response = self._execute("factor_diagnostics", request, action)
        return response if return_task_envelope else response["result"]["report"]

    def run_factor_diagnostics_task(self, manifest_path: str | Path,
                                    recipe: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the application task envelope for non-GUI adapters."""
        return self.run_factor_diagnostics(manifest_path, recipe, return_task_envelope=True)

    def run_factor_strategy(self, manifest_path: str | Path, score_artifact_path: str | Path,
                            *, score_source: str, expected_artifact_sha256: str,
                            recipe: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = _file_ref("bars_manifest", manifest_path)
        score = _file_ref("score_artifact", score_artifact_path)
        if score["sha256"] != expected_artifact_sha256.lower():
            raise ValueError("score artifact bytes do not match the explicitly pinned SHA-256")
        if score_source not in {"factor_feature_rows", "model_predictions"}:
            raise ValueError("score_source is outside the static allowlist")
        recipe_value = dict(recipe) if recipe is not None else None
        request = {"manifest": manifest, "score_artifact": score,
                   "score_source": score_source, "recipe": recipe_value}
        return self._run_static_worker("factor_strategy", request, {
            "manifest_path": manifest["path"], "manifest_sha256": manifest["sha256"],
            "score_path": score["path"], "score_sha256": score["sha256"],
            "score_source": score_source, "recipe": recipe_value})

    def run_model_training(self, manifest_path: str | Path, factor_run_dir: str | Path,
                           model_names: list[str]) -> dict[str, Any]:
        manifest = _file_ref("bars_manifest", manifest_path)
        factor_bundle = _bundle_ref(factor_run_dir)
        names = list(model_names) if isinstance(model_names, (tuple, list)) else None
        if not names or len(names) > 2 or len(set(names)) != len(names) or set(names) - {"lightgbm", "catboost"}:
            raise ValueError("model_names must explicitly select lightgbm and/or catboost")
        runtime = self._extension_runtime("model-training", {"model_names": names})
        if not runtime.get("enabled"):
            raise ResearchApplicationError("capability_check", str(runtime.get("reason") or
                "selected model dependencies are unavailable"), error_type="RuntimeUnavailable")
        request = {"manifest": manifest, "factor_bundle": factor_bundle, "model_names": names}
        return self._run_static_worker("model_training", request, {
            "manifest_path": manifest["path"], "manifest_sha256": manifest["sha256"],
            "factor_run_dir": factor_bundle["path"], "factor_bundle_sha256": factor_bundle["files"],
            "model_names": names})

    def run_engine_comparison(self, manifest_path: str | Path,
                              recipes: list[dict[str, Any]]) -> dict[str, Any]:
        manifest = _file_ref("bars_manifest", manifest_path)
        values = list(recipes) if isinstance(recipes, (list, tuple)) else None
        if not values or len(values) > 3:
            raise ValueError("engine comparison requires one to three explicit candidate recipes")
        runtime = self._extension_runtime("engine-comparison", {"backends": ["vectorbt", "backtrader"]})
        if not runtime.get("enabled"):
            raise ResearchApplicationError("capability_check", str(runtime.get("reason") or
                "selected engine dependencies are unavailable"), error_type="RuntimeUnavailable")
        request = {"manifest": manifest, "recipes": values}
        return self._run_static_worker("engine_comparison", request, {
            "manifest_path": manifest["path"], "manifest_sha256": manifest["sha256"],
            "recipes": values})

    def _run_static_worker(self, operation: str, public_request: dict[str, Any], worker_request: dict[str, Any]):
        if operation not in {"factor_strategy", "model_training", "engine_comparison"}:
            raise ValueError("operation is outside the static worker allowlist")
        if operation == "model_training":
            runtime = self._extension_runtime("model-training", {"model_names": worker_request.get("model_names")})
        elif operation == "engine_comparison":
            runtime = self._extension_runtime("engine-comparison", {"backends": ["vectorbt", "backtrader"]})
        else:
            runtime = None
        if runtime is not None and not runtime.get("enabled"):
            raise ResearchApplicationError("capability_check", str(runtime.get("reason") or
                "selected optional workflow dependencies are unavailable"), error_type="RuntimeUnavailable")
        job_id, job_dir = self._new_task(operation, worker_request, root_name="research-studio/jobs")
        _write_new(job_dir / "request.json", {"schema": "kabuforge.research_studio_request.v1",
            "job_id": job_id, "operation": operation, **worker_request})
        # The Studio worker contract is a closed schema. Keep caller convenience
        # metadata in a separate file rather than widening that worker request.
        _write_new(job_dir / "facade_request.json", {"task_id": job_id, "request": public_request,
            "sha256": hashlib.sha256(_canonical(public_request)).hexdigest()})
        launch = {"task_id": job_id, "operation": operation, "program": sys.executable,
            "argv": [sys.executable, "-B", "-m", "framework_v2.research_studio_worker", "--workspace",
                     str(self.workspace), "--job-id", job_id],
            "pid": None, "started_at_utc": _utc(), "python": sys.version.split()[0],
            "request_sha256": hashlib.sha256(_canonical(worker_request)).hexdigest(),
            "stdout_path": str(job_dir / "worker.stdout.log"),
            "stderr_path": str(job_dir / "worker.stderr.log"),
            "recovery": "retain request/logs/terminal receipt; retries use a new job id"}
        launch_path = job_dir / "application_launch.json"
        _write_new(launch_path, launch)
        safe_environment_names = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP",
                                  "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
        env = {name: os.environ[name] for name in safe_environment_names if name in os.environ}
        env["PYTHONPATH"] = str(self.project_root)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        stdout_path, stderr_path = job_dir / "worker.stdout.log", job_dir / "worker.stderr.log"
        started = _utc()
        try:
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                proc = subprocess.Popen(launch["argv"], cwd=job_dir,
                                        env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                launch["pid"] = proc.pid
                # Replace only this operation's own pre-start receipt to add
                # the owned process PID before the worker handles its request.
                launch_path.unlink()
                _write_new(launch_path, launch)
                return_code = proc.wait()
            terminal_path = job_dir / ("result.json" if (job_dir / "result.json").is_file() else "failure.json")
            terminal = json.loads(terminal_path.read_text(encoding="utf-8")) if terminal_path.is_file() else None
            if return_code != 0 or not isinstance(terminal, dict) or terminal.get("status") not in {"COMPLETED", "PARTIAL"}:
                raise RuntimeError(f"static worker exited {return_code}; terminal={terminal.get('status') if isinstance(terminal, dict) else 'missing'}")
            response = {"schema": "kabuforge.research_application_result.v1", "task_id": job_id,
                "operation": operation, "status": terminal["status"], "readiness": "RESEARCH-ONLY",
                "pit_guarantee": False, "task_dir": str(job_dir), "result": terminal,
                "artifacts": self._artifact_refs([terminal_path], job_dir)}
            _write_new(job_dir / "application_result.json", response)
            _write_new(job_dir / "completion.json", {"task_id": job_id, "status": terminal["status"],
                "started_at_utc": started, "finished_at_utc": _utc(), "pid": launch["pid"],
                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)})
            return response
        except Exception as exc:
            if not (job_dir / "failure.json").exists():
                try:
                    _write_new(job_dir / "facade_failure.json", {"task_id": job_id,
                        "operation": operation, "status": "FAILED", "stage": "static_worker",
                        "error_type": type(exc).__name__, "reason": str(exc),
                        "started_at_utc": started, "finished_at_utc": _utc(),
                        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
                        "readiness": "RESEARCH-ONLY", "pit_guarantee": False})
                except OSError:
                    pass
            raise ResearchApplicationError("static_worker", str(exc), task_dir=job_dir,
                                           error_type=type(exc).__name__) from exc

    def _extension_runtime(self, operation: str = "native",
                           choices: dict[str, Any] | None = None) -> dict[str, Any]:
        from .research_runtime import resolve_extension_runtime
        detected = "win-amd64" if os.name == "nt" and sys.maxsize > 2**32 else sysconfig.get_platform()
        return resolve_extension_runtime(self.project_root, platform.python_version(), detected,
                                         operation=operation, choices=choices)

    def run_indicator_research(self, manifest_path: str | Path, code: str, *,
                               sma_period: int = 20, rsi_period: int = 14,
                               atr_period: int = 14, provider: str = "pandas-ta") -> dict[str, Any]:
        """Run the explicitly selected optional indicator implementation."""
        manifest = _file_ref("bars_manifest", manifest_path)
        if not isinstance(code, str) or not code.strip() or len(code) > 32:
            raise ValueError("code must be an explicit nonempty security identifier")
        if provider not in {"talib", "pandas-ta"}:
            raise ValueError("provider must be talib or pandas-ta")
        for name, value, lower, upper in (("sma_period", sma_period, 2, 500),
                                          ("rsi_period", rsi_period, 2, 100),
                                          ("atr_period", atr_period, 2, 100)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in [{lower}, {upper}]")
        expected_engine = "TA-Lib" if provider == "talib" else "pandas-ta"
        runtime = self._extension_runtime("indicators", {"provider": provider})
        worker_module = self.project_root / "framework_v2" / "indicator_research_worker.py"
        if not worker_module.is_file() or not runtime.get("enabled"):
            reason = runtime.get("reason") or "the fixed indicator worker is unavailable"
            raise ResearchApplicationError("capability_check", str(reason), error_type="RuntimeUnavailable")
        request = {"manifest": manifest, "code": code.strip(), "sma_period": sma_period,
                   "rsi_period": rsi_period, "atr_period": atr_period,
                   "provider": provider, "readiness": "RESEARCH-ONLY", "pit_guarantee": False}

        def action(task_dir: Path):
            output_dir = self._safe_workspace_path(task_dir / "outputs" / "indicator", must_exist=False)
            output_dir.mkdir(parents=True, exist_ok=False)
            output_dir = self._safe_workspace_path(output_dir, must_exist=True)
            stdout_path = self._safe_workspace_path(task_dir / "indicator_worker.stdout.log", must_exist=False)
            stderr_path = self._safe_workspace_path(task_dir / "indicator_worker.stderr.log", must_exist=False)
            manifest_path_resolved = Path(manifest["path"]).resolve(strict=True)
            argv = [sys.executable, "-B", "-m", "framework_v2.indicator_research_worker",
                    "--project-root", str(self.project_root), "--manifest", str(manifest_path_resolved),
                    "--output-dir", str(output_dir), "--code", code.strip(),
                    "--sma-period", str(sma_period), "--rsi-period", str(rsi_period),
                    "--atr-period", str(atr_period)]
            if provider != "pandas-ta":
                argv.extend(["--provider", provider])
            request_sha = hashlib.sha256(_canonical(request)).hexdigest()
            launch = {"schema": "kabuforge_indicator_facade_launch.v1", "program": sys.executable,
                "argv": argv, "pid": None, "started_at_utc": _utc(), "request": request,
                "request_sha256": request_sha, "source_manifest_sha256": manifest["sha256"],
                "runtime_paths": list(runtime.get("paths", [])),
                "runtime_versions": runtime.get("versions", {}),
                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
                "output_dir": str(output_dir), "network": "not requested by this fixed local worker",
                "credentials": "not read or resolved", "recovery": "retain this task; retry into a new task id"}
            launch_path = self._safe_workspace_path(task_dir / "indicator_worker_launch.json", must_exist=False)
            _write_new(launch_path, launch)
            # Pass only the Windows/Python environment needed to locate the
            # interpreter and receipt-verified runtime. User/API credentials
            # are not inherited by this local-only worker.
            safe_environment_names = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP",
                                      "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
            env = {name: os.environ[name] for name in safe_environment_names if name in os.environ}
            env["PYTHONPATH"] = str(self.project_root)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            started = time.monotonic()
            process = None
            result = None
            exit_code = None
            timed_out = False
            try:
                with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                    process = subprocess.Popen(argv, cwd=task_dir, env=env,
                        stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                    launch["pid"] = int(process.pid)
                    launch["process_started_at_utc"] = _utc()
                    pending = launch_path.with_name(launch_path.name + ".pending-" + uuid.uuid4().hex)
                    _write_new(pending, launch)
                    pending.replace(launch_path)
                    try:
                        exit_code = process.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        process.terminate()
                        try:
                            exit_code = process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            exit_code = process.wait(timeout=10)
                stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
                for line in stdout_text.splitlines():
                    if line.startswith("INDICATOR_RESULT="):
                        try:
                            result = json.loads(line.split("=", 1)[1])
                        except json.JSONDecodeError:
                            result = None
                elapsed = round(time.monotonic() - started, 3)
                completion = {"schema": "kabuforge_indicator_facade_completion.v1",
                    "pid": launch.get("pid"), "exit_code": exit_code,
                    "ended_at_utc": _utc(), "elapsed_seconds": elapsed,
                    "request_sha256": request_sha, "source_manifest_sha256": manifest["sha256"],
                    "output_dir": str(output_dir), "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "stdout_sha256": _sha_file(stdout_path), "stderr_sha256": _sha_file(stderr_path),
                    "timed_out": timed_out, "result": result,
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
                _write_new(self._safe_workspace_path(task_dir / "indicator_worker_completion.json",
                                                     must_exist=False), completion)
                if timed_out:
                    raise TimeoutError("fixed indicator worker exceeded 300 seconds")
                if exit_code != 0 or not isinstance(result, dict) or result.get("ok") is not True:
                    raise RuntimeError("fixed indicator worker failed; inspect retained worker logs")
                artifact_path = self._safe_workspace_path(result.get("artifact_path", ""), must_exist=True)
                if artifact_path.parent != output_dir or not artifact_path.is_file():
                    raise ValueError("indicator worker artifact escaped its dedicated task output")
                if _sha_file(artifact_path) != result.get("artifact_sha256"):
                    raise ValueError("indicator worker artifact hash does not match its receipt")
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                if (payload.get("schema") != "kabuforge_indicator_research" or
                        type(payload.get("schema_version")) is not int or payload["schema_version"] != 2 or
                        payload.get("readiness") != "RESEARCH-ONLY" or payload.get("pit_guarantee") is not False or
                        payload.get("engine", {}).get("name") != expected_engine or
                        payload.get("source_manifest_sha256") != manifest["sha256"] or
                        not _indicator_code_matches(code.strip(), str(payload.get("security_code", ""))) or
                        payload.get("parameters") != {"sma_period": sma_period, "rsi_period": rsi_period,
                            "macd": {"fast": 12, "slow": 26, "signal": 9}, "atr_period": atr_period}):
                    raise ValueError("indicator worker artifact does not match the frozen facade request")
                rows = payload.get("rows")
                dates = [row.get("date") for row in rows] if isinstance(rows, list) else []
                if not dates or dates != sorted(dates) or len(dates) != len(set(dates)):
                    raise ValueError("indicator worker artifact dates are missing, duplicated, or unordered")
                return {"provider": provider, "worker_result": result,
                    "artifact_path": str(artifact_path), "artifact_sha256": result["artifact_sha256"],
                    "row_count": len(rows), "source_manifest_sha256": manifest["sha256"],
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False}, [artifact_path]
            except Exception:
                # Failure logs and launch metadata are retained in the task folder.
                raise

        return self._execute("indicator_research", request, action)

    def _require_paper(self, enabled: bool, call_id: str, idempotency_key: str) -> None:
        if self.enable_paper is not True or enabled is not True:
            raise PermissionError("historical paper writes require service and call-level enable_paper=True")
        for label, value in (("call_id", call_id), ("idempotency_key", idempotency_key)):
            if not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise ValueError(f"{label} must be a nonempty identifier of at most 128 characters")

    def _paper_db(self) -> Path:
        root = self._safe_workspace_path(self.workspace / "research-application", must_exist=False)
        root.mkdir(exist_ok=True)
        root = self._safe_workspace_path(root, must_exist=True)
        return self._safe_workspace_path(root / "paper_calls.sqlite", must_exist=False)

    def _paper_mutation(self, operation: str, request: dict[str, Any], call_id: str,
                        idempotency_key: str, action: Callable[[], Any]):
        input_hash = hashlib.sha256(_canonical({"operation": operation, "request": request})).hexdigest()
        path = self._paper_db()
        with self._lock, closing(sqlite3.connect(path, timeout=30)) as connection:
            with connection as db:
                db.execute("CREATE TABLE IF NOT EXISTS paper_calls (call_id TEXT PRIMARY KEY, idem TEXT UNIQUE, input_hash TEXT NOT NULL, operation TEXT NOT NULL, state TEXT NOT NULL, response TEXT)")
                db.execute("BEGIN IMMEDIATE")
                by_idem = db.execute("SELECT call_id,input_hash,state,response FROM paper_calls WHERE idem=?",
                                     (idempotency_key,)).fetchone()
                if by_idem:
                    if by_idem[1] != input_hash or by_idem[2] != "SUCCEEDED":
                        raise ResearchApplicationError("paper_idempotency", "idempotency key conflicts or prior state is uncertain")
                    return json.loads(by_idem[3])
                if db.execute("SELECT 1 FROM paper_calls WHERE call_id=?", (call_id,)).fetchone():
                    raise ResearchApplicationError("paper_idempotency", "call_id was already used")
                db.execute("INSERT INTO paper_calls VALUES (?,?,?,?,?,NULL)",
                           (call_id, idempotency_key, input_hash, operation, "STARTED"))
        try:
            response = action()
            encoded = json.dumps(response, ensure_ascii=False, sort_keys=True, allow_nan=False,
                                 default=_json_default)
            with self._lock, closing(sqlite3.connect(path, timeout=30)) as connection:
                with connection as db:
                    db.execute("UPDATE paper_calls SET state='SUCCEEDED',response=? WHERE call_id=? AND state='STARTED'",
                               (encoded, call_id))
            return response
        except Exception as exc:
            with self._lock, closing(sqlite3.connect(path, timeout=30)) as connection:
                with connection as db:
                    db.execute("UPDATE paper_calls SET state='FAILED' WHERE call_id=? AND state='STARTED'", (call_id,))
            raise

    def _paper_action_task(self, operation: str, request: dict[str, Any], action: Callable[[Path, str], Any]):
        task_id, task_dir = self._new_task(operation, request)
        started = _utc()
        try:
            value = action(task_dir, task_id)
            self._validate_result_artifacts(value)
            _write_new(task_dir / "application_result.json", {"schema": "kabuforge.research_application_result.v1",
                "task_id": task_id, "operation": operation, "status": "COMPLETED",
                "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "result": value})
            _write_new(task_dir / "completion.json", {"task_id": task_id, "status": "COMPLETED",
                "started_at_utc": started, "finished_at_utc": _utc(), "pid": os.getpid()})
            return value
        except Exception as exc:
            try:
                _write_new(task_dir / "failure.json", {"task_id": task_id, "operation": operation,
                    "status": "FAILED", "stage": operation, "error_type": type(exc).__name__,
                    "reason": str(exc), "started_at_utc": started, "finished_at_utc": _utc(),
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False})
            except OSError:
                pass
            raise

    def create_historical_paper(self, manifest_path: str | Path, strategy_report_path: str | Path,
                                expected_report_sha256: str, *, enable_paper: bool = False,
                                call_id: str, idempotency_key: str) -> dict[str, Any]:
        self._require_paper(enable_paper, call_id, idempotency_key)
        from .historical_paper_research import create_historical_paper_research
        manifest = _file_ref("bars_manifest", manifest_path)
        report = _file_ref("strategy_report", strategy_report_path)
        if report["sha256"] != expected_report_sha256.lower():
            raise ValueError("strategy report bytes do not match the pinned SHA-256")
        request = {"manifest": manifest, "strategy_report": report,
                   "expected_report_sha256": expected_report_sha256.lower(), "enable_paper": True}
        def action():
            def create(task_dir, task_id):
                account_dir = self._safe_workspace_path(task_dir / "account", must_exist=False)
                paper = create_historical_paper_research(manifest_path, strategy_report_path,
                    expected_report_sha256, account_dir)
                account_dir = self._safe_workspace_path(account_dir, must_exist=True)
                summary = paper.summary()
                response = {"status": "COMPLETED", "task_id": task_id,
                    "account_dir": str(account_dir), "summary": summary,
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
                return response
            return self._paper_action_task("historical_paper_create", {
                **request, "call_id": call_id, "idempotency_key": idempotency_key}, create)
        return self._paper_mutation("historical_paper_create", request, call_id, idempotency_key, action)

    def query_historical_paper(self, account_dir: str | Path, *, include_events: bool = False) -> dict[str, Any]:
        from .historical_paper_research import open_historical_paper_research
        path = self._safe_workspace_path(account_dir)
        if type(include_events) is not bool:
            raise TypeError("include_events must be bool")
        paper = open_historical_paper_research(path)
        summary = paper.summary()
        result = {"summary": summary, "cursor": summary["cursor"],
                  "complete": summary["cursor"] >= summary["total_dates"],
                  "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
        if include_events:
            result["events"] = paper.events()
        return result

    def advance_historical_paper(self, account_dir: str | Path, *, expected_cursor: int,
                                 enable_paper: bool = False, call_id: str,
                                 idempotency_key: str) -> dict[str, Any]:
        self._require_paper(enable_paper, call_id, idempotency_key)
        path = self._safe_workspace_path(account_dir)
        if type(expected_cursor) is not int or expected_cursor < 0:
            raise ValueError("expected_cursor must be a nonnegative integer")
        request = {"account_dir": str(path), "expected_cursor": expected_cursor,
                   "enable_paper": True}
        def action():
            def advance(_task_dir, _task_id):
                from .historical_paper_research import open_historical_paper_research
                paper = open_historical_paper_research(path)
                event = paper.step_next(idempotency_key=idempotency_key, expected_cursor=expected_cursor)
                return {"status": "COMPLETED", "event": event, "summary": paper.summary(),
                        "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            return self._paper_action_task("historical_paper_step", {
                **request, "call_id": call_id, "idempotency_key": idempotency_key}, advance)
        return self._paper_mutation("historical_paper_step", request, call_id, idempotency_key, action)

    def run_historical_paper_all(self, account_dir: str | Path, *, enable_paper: bool = False,
                                 call_id: str, idempotency_key: str) -> dict[str, Any]:
        self._require_paper(enable_paper, call_id, idempotency_key)
        path = self._safe_workspace_path(account_dir)
        request = {"account_dir": str(path), "enable_paper": True}
        def action():
            def run_all(_task_dir, _task_id):
                from .historical_paper_research import open_historical_paper_research
                paper = open_historical_paper_research(path)
                summary = paper.run_all()
                return {"status": "COMPLETED", "summary": summary,
                        "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            return self._paper_action_task("historical_paper_run_all", {
                **request, "call_id": call_id, "idempotency_key": idempotency_key}, run_all)
        return self._paper_mutation("historical_paper_run_all", request, call_id, idempotency_key, action)

    def create_broker_workspace(self, config) -> dict[str, Any]:
        from .broker_research import create_broker_workspace
        if not is_dataclass(config):
            raise TypeError("BrokerResearchConfig is required")
        config_doc = asdict(config)
        ref = config_doc.pop("credential_ref", "")
        request = {"config": config_doc, "credential_ref_sha256": hashlib.sha256(str(ref).encode()).hexdigest()}
        def action(task_dir):
            broker_dir = self._safe_workspace_path(task_dir / "broker-workspace", must_exist=False)
            created = create_broker_workspace(broker_dir, config)
            created = self._safe_workspace_path(created, must_exist=True)
            return {"workspace": str(created), "credential_reference_saved": True,
                    "credential_resolved": False, "network_calls": 0}, [created / "broker_config.json"]
        return self._execute("broker_workspace_create", request, action)

    def preview_broker_order(self, broker_workspace: str | Path, intent, instrument, *, now: datetime) -> dict[str, Any]:
        from .broker_research import (NoCallTransport, create_broker_workspace,
                                      load_broker_workspace, preview_order)
        source = self._safe_workspace_path(broker_workspace)
        config = load_broker_workspace(source)
        request = {"broker_workspace": str(source), "config_sha256": _sha_file(source / "broker_config.json"),
            "intent_sha256": hashlib.sha256(_canonical(intent)).hexdigest(),
            "instrument_sha256": hashlib.sha256(_canonical(instrument)).hexdigest(), "now": now.isoformat()}
        def action(task_dir):
            isolated = self._safe_workspace_path(task_dir / "broker-workspace", must_exist=False)
            create_broker_workspace(isolated, config)
            isolated = self._safe_workspace_path(isolated, must_exist=True)
            transport = NoCallTransport()
            receipt_path = preview_order(isolated, intent, instrument, now=now, transport=transport)
            receipt_path = self._safe_workspace_path(receipt_path, must_exist=True)
            if transport.calls != 0:
                raise RuntimeError("offline broker preview unexpectedly invoked a transport")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            return {"receipt": receipt, "receipt_path": str(receipt_path), "network_calls": 0,
                    "submitted": False, "connected": False}, [isolated / "broker_config.json", receipt_path]
        return self._execute("broker_order_preview", request, action)

    def check_broker_read_only(self, broker_workspace: str | Path, *, timeout: float = 2.0) -> dict[str, Any]:
        """Explicitly run the bounded localhost GET check; never called by startup/capabilities."""
        import math
        from .broker_readonly import BrokerReadOnlyError, check_read_only
        from .broker_research import load_broker_workspace

        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3.0:
            raise ValueError("timeout must be finite and in (0, 3] seconds per request")
        source = self._safe_workspace_path(broker_workspace)
        config = load_broker_workspace(source)
        config_path = source / "broker_config.json"
        request = {"broker_workspace": str(source), "config_sha256": _sha_file(config_path),
            "environment": config.environment, "account_type": config.account_type,
            "exchange": config.exchange,
            "credential_reference_sha256": hashlib.sha256(config.credential_ref.encode("utf-8")).hexdigest(),
            "timeout_seconds_per_request": float(timeout), "explicit_user_action": True}

        def action(task_dir: Path):
            try:
                checked = check_read_only(config, timeout=timeout)
                receipt = {"schema": "kabuforge.broker_read_only_facade_receipt.v1",
                    "status": checked["status"], "readiness": checked["readiness"],
                    "environment": checked["environment"], "endpoint": checked["endpoint"],
                    "requests": checked["requests"], "network_calls": checked["network_calls"],
                    "timeout_seconds_per_request": checked["timeout_seconds_per_request"],
                    "credential_value_persisted": False, "account_values_persisted": False,
                    "source_config_sha256": request["config_sha256"],
                    "readiness_scope": "read-only query; no submission or cancellation"}
            except BrokerReadOnlyError as exc:
                paths = list(exc.attempted_paths)
                receipt = {"schema": "kabuforge.broker_read_only_facade_receipt.v1",
                    "status": "FAILED", "readiness": "NOT_CONNECTED",
                    "environment": config.environment, "failure_code": exc.code,
                    "attempted_paths": paths, "network_calls": len(paths),
                    "timeout_seconds_per_request": float(timeout),
                    "credential_value_persisted": False, "account_values_persisted": False,
                    "source_config_sha256": request["config_sha256"],
                    "readiness_scope": "read-only query; no submission or cancellation"}
            receipt_path = task_dir / "broker_read_only_receipt.json"
            _write_new(receipt_path, receipt)
            return {"check": receipt, "receipt_path": str(receipt_path),
                    "credential_value_persisted": False, "account_values_persisted": False}, [receipt_path]

        return self._execute("broker_readonly_check", request, action)

    def run_price_sensitivity(self, run_directory: str | Path, *,
                              expected_report_sha256: str) -> dict[str, Any]:
        """Launch the fixed sensitivity worker for one explicitly pinned source run."""
        run_dir = Path(run_directory).expanduser().resolve(strict=True)
        if not run_dir.is_dir():
            raise ValueError("run_directory must identify a selected research run")
        report_path = run_dir / "report.json"
        if not report_path.is_file():
            raise ValueError("selected research run has no report.json")
        actual_report_sha = _sha_file(report_path)
        if (not isinstance(expected_report_sha256, str) or len(expected_report_sha256) != 64
                or actual_report_sha != expected_report_sha256.lower()):
            raise ValueError("selected report bytes do not match the explicit SHA-256")
        request = {"run_directory": str(run_dir), "report_sha256": actual_report_sha,
                   "scenario_set": "kabuforge.price_sensitivity.v1"}

        def action(task_dir: Path):
            job_id = task_dir.name
            worker_request = {"schema": "kabuforge.price_sensitivity_request.v1",
                "job_id": job_id, "operation": "price_sensitivity",
                "run_directory": str(run_dir), "report_sha256": actual_report_sha}
            _write_new(task_dir / "request.json", worker_request)
            stdout_path = task_dir / "worker.stdout.log"
            stderr_path = task_dir / "worker.stderr.log"
            argv = [sys.executable, "-B", "-m", "framework_v2.price_sensitivity_worker",
                    "--workspace", str(self.workspace), "--job-id", job_id]
            launch = {"operation": "price_sensitivity", "program": sys.executable,
                "argv": argv, "pid": None, "started_at_utc": _utc(),
                "request_sha256": hashlib.sha256(_canonical(worker_request)).hexdigest(),
                "source_report_sha256": actual_report_sha, "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path), "recovery": "retain this job; retry with a new task id"}
            launch_path = task_dir / "worker_launch.json"
            _write_new(launch_path, launch)
            safe_names = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA",
                          "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
            env = {name: os.environ[name] for name in safe_names if name in os.environ}
            env["PYTHONPATH"] = str(self.project_root)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            started = time.monotonic()
            timed_out = False
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = subprocess.Popen(argv, cwd=task_dir, env=env,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                launch["pid"] = int(process.pid)
                launch["process_started_at_utc"] = _utc()
                launch_path.write_bytes(_canonical(launch) + b"\n")
                try:
                    exit_code = process.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.terminate()
                    try:
                        exit_code = process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        exit_code = process.wait(timeout=10)
            terminal_path = task_dir / ("result.json" if (task_dir / "result.json").is_file() else "failure.json")
            terminal = json.loads(terminal_path.read_text(encoding="utf-8")) if terminal_path.is_file() else None
            if timed_out or exit_code != 0 or not isinstance(terminal, dict):
                raise RuntimeError("price-sensitivity worker failed; inspect retained job logs and terminal receipt")
            if terminal.get("job_id") != job_id or terminal.get("source_report_sha256") != actual_report_sha:
                raise ValueError("price-sensitivity terminal receipt does not match the selected run")
            result_path = self._safe_workspace_path(terminal.get("result_path", ""), must_exist=True)
            if not result_path.is_file() or not result_path.is_relative_to(task_dir / "outputs"):
                raise ValueError("price-sensitivity result escaped the job output directory")
            if _sha_file(result_path) != terminal.get("result_sha256"):
                raise ValueError("price-sensitivity result hash does not match its terminal receipt")
            return {"worker_result": terminal, "artifact_path": str(result_path),
                    "artifact_sha256": terminal["result_sha256"], "source_report_sha256": actual_report_sha,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False}, [terminal_path, result_path]

        return self._execute("price_sensitivity", request, action, root_name="price-sensitivity/jobs")


__all__ = ["ResearchApplicationError", "ResearchApplicationService"]
