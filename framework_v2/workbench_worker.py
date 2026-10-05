"""Isolated local workbench job: python -m framework_v2.workbench_worker --request file.json."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone

from .config import ConfigError, _read_json_snapshot
from .local_io import write_new
from .workbench_service import WorkbenchService


def _phase(job_id: str, action: str, stage: str, started: float, **details) -> None:
    record = {"kind": "workbench_worker_phase.v1", "at": datetime.now(timezone.utc).isoformat(),
              "job_id": job_id, "action": action, "stage": stage,
              "elapsed_seconds": round(time.monotonic() - started, 3), **details}
    print("WORKBENCH_PHASE=" + json.dumps(record, ensure_ascii=False, allow_nan=False),
          file=sys.stderr, flush=True)


def _owned_paths(request: dict, *, require_workspace: bool = False):
    """Validate the fixed workspace/jobs/job-id/output layout before any write."""
    workspace_value = request.get("workspace_path")
    if workspace_value is None:
        if require_workspace:
            raise ConfigError("an explicit workbench workspace identity is required")
        return None
    workspace = Path(workspace_value).resolve(strict=True)
    if not workspace.is_dir():
        raise ConfigError("workbench workspace is not a directory")
    job_id = request["job_id"]
    jobs_lexical = workspace / "jobs"
    jobs_root = jobs_lexical.resolve()
    if not jobs_root.is_relative_to(workspace):
        raise ConfigError("workbench jobs directory escapes its workspace")
    job_root = jobs_root / job_id
    if job_root.exists():
        job_root = job_root.resolve(strict=True)
        if not job_root.is_relative_to(jobs_root):
            raise ConfigError("owned job directory escapes the workspace")
    expected_output = job_root / "output"
    output_value = request.get("output_dir")
    if not isinstance(output_value, str) or not output_value:
        raise ConfigError("workbench output directory is required")
    output_dir = Path(output_value).resolve()
    if output_dir != expected_output.resolve():
        raise ConfigError("workbench output directory does not match the owned job")
    if output_dir.exists() and not output_dir.resolve(strict=True).is_relative_to(job_root):
        raise ConfigError("workbench output directory escapes the owned job")
    return workspace, jobs_root, job_root, output_dir


def _validate_factor_cache_job(request: dict, cache_path: Path) -> None:
    owned = _owned_paths(request, require_workspace=True)
    workspace = owned[0]
    lexical_cache = workspace / "cache" / "history-factors.sqlite"
    expected_cache = lexical_cache.resolve()
    if expected_cache != lexical_cache or cache_path.resolve() != expected_cache or not expected_cache.is_relative_to(workspace):
        raise ConfigError("factor cache path is not the fixed workspace cache")


def _validate_factor_cache_schema(path: Path) -> None:
    """Read-only check for the cache's known schema before opening it for writes."""
    if not path.exists():
        return
    if not path.is_file() or not path.resolve().is_relative_to(path.parent.resolve()):
        raise ConfigError("factor cache path is not a regular in-workspace file")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            objects = {(row[0], row[1]) for row in db.execute(
                "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
            if objects != {("table", "factor_cache_v1")}:
                raise ConfigError("unknown factor cache database objects")
            if db.execute("PRAGMA user_version").fetchone()[0] != 0:
                raise ConfigError("unknown factor cache database version")
            columns = db.execute("PRAGMA table_info(factor_cache_v1)").fetchall()
            expected = [("cache_key", "TEXT", 0, 1), ("payload", "TEXT", 1, 0), ("sha256", "TEXT", 1, 0)]
            actual = [(row[1], row[2].upper(), row[3], row[5]) for row in columns]
            if actual != expected or db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ConfigError("factor cache schema or integrity check failed")
    except sqlite3.DatabaseError as exc:
        raise ConfigError("factor cache is not a readable SQLite database") from exc


def _factor_cache_summary(tracker, cache_path: Path | None) -> dict:
    if tracker is None:
        return {"enabled": False, "path": None, "lookups": 0,
                "namespace": None, "namespace_identity": None,
                "stats": {"hits": 0, "misses": 0, "writes": 0, "corrupt": 0}}
    return {"enabled": True, "path": str(cache_path), "lookups": tracker.lookups,
            "hits": tracker.hits, "misses": tracker.misses, "writes": tracker.writes,
            "corrupt": tracker.corrupt, "namespace": tracker.namespace,
            "namespace_identity": tracker.namespace_identity,
            "stats": {"hits": tracker.hits, "misses": tracker.misses,
                      "writes": tracker.writes, "corrupt": tracker.corrupt}}


def _write_factor_cache_failure(root: Path, job_root: Path, request: dict,
                                summary: dict, error: Exception) -> Path:
    """Persist a fail-closed cache receipt only inside this validated job."""
    owned_root = job_root.resolve(strict=True)
    result_root = root.resolve(strict=True)
    if root.is_symlink() or not result_root.is_relative_to(owned_root):
        raise ConfigError("factor cache failure receipt escaped its owned job")
    receipt_path = result_root / "factor_cache_failure.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ConfigError("factor cache failure receipt already exists")
    receipt = {"kind": "kabuforge.factor-cache-failure.v1",
        "job_id": request.get("job_id"), "status": "FAILED",
        "stats": dict(summary.get("stats") or {}),
        "namespace_identity": summary.get("namespace_identity"),
        "cache_path": summary.get("path"), "fallback_recompute": False,
        "error_type": type(error).__name__, "reason": str(error)}
    write_new(receipt_path, receipt)
    return receipt_path


def _copy_verified(source: str | Path, expected: str, target: Path) -> Path:
    raw = Path(source).resolve().read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ConfigError(f"input changed since preflight: {source}")
    with target.open("xb") as stream:
        stream.write(raw)
    return target


def _verify_copied(manifest: dict, extras: dict[str, Path], source_hashes: dict[str, str],
                   extra_sources: dict[str, str]) -> None:
    for path, expected in manifest["copied_hashes"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ConfigError(f"snapshotted input changed during job: {path}")
    for label, copied in extras.items():
        source = extra_sources[label]
        if hashlib.sha256(copied.read_bytes()).hexdigest() != source_hashes[str(Path(source).resolve())]:
            raise ConfigError(f"snapshotted {label} changed during job")


def run_request(request: dict) -> dict:
    """Dispatch only explicit local actions; each execution owns a new job directory."""
    started = time.monotonic()
    if not isinstance(request, dict):
        raise ConfigError("request must be a JSON object")
    job_id = request.get("job_id")
    action = request.get("action")
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise ConfigError("job_id must be a safe nonempty identifier")
    if action not in {"preflight", "journal", "demo", "plan", "history", "simulate", "guided_demo", "price_research"}:
        raise ConfigError("unsupported workbench action")
    target_action = request.get("target_action")
    cache_requested = isinstance(request.get("factor_cache"), dict) and request["factor_cache"].get("enabled") is True
    require_workspace = (action == "price_research" or
        (action == "preflight" and target_action == "price_research") or cache_requested)
    owned = _owned_paths(request, require_workspace=require_workspace)
    if owned is not None:
        _phase(job_id, action, "workspace.validated", started,
               workspace=str(owned[0]), output_dir=str(owned[3]))
    service = WorkbenchService()
    if action == "journal":
        return {"ok": True, "job_id": job_id, "action": action,
                "result": service.read_journal(request["journal_path"]), "artifacts": [], "errors": []}
    if action == "preflight":
        if target_action == "price_research":
            result = service.preflight_price_research(request["market_manifest"], request["recipe"],
                                                       request.get("regime_observer"))
            _phase(job_id, action, "price_research.preflight", started, ok=bool(result.get("ok")))
            return {"ok": result["ok"], "job_id": job_id, "action": action,
                    "result": result, "artifacts": [], "errors": result["issues"]}
        result = service.preflight(request["run_path"], request.get("mode", "backtest"),
                                   timeline_path=request.get("timeline_path"),
                                   execution_path=request.get("execution_path"),
                                   decision_at=request.get("decision_at"),
                                   target_action=target_action,
                                   factor_cache=request.get("factor_cache"))
        cache_selection = result.get("factor_cache") or {}
        if result.get("ok") and cache_selection.get("enabled"):
            cache_path = Path(cache_selection["cache_path"])
            _validate_factor_cache_job(request, cache_path)
            _validate_factor_cache_schema(cache_path)
        return {"ok": result["ok"], "job_id": job_id, "action": action,
                "result": result, "artifacts": [], "errors": result["issues"]}
    mode = request.get("mode", "backtest")
    if mode == "broker":
        raise ConfigError("broker mode cannot execute from the workbench")
    root = Path(request["output_dir"]).resolve() / job_id
    if owned is not None:
        workspace, jobs_root, job_root, output_dir = owned
        if output_dir.exists() and output_dir.resolve(strict=True) != job_root / "output":
            raise ConfigError("workbench output directory changed before creation")
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.resolve(strict=True) != job_root / "output":
            raise ConfigError("workbench output directory changed during creation")
        root = output_dir / job_id
        if not root.resolve().is_relative_to(job_root):
            raise ConfigError("worker result directory escapes its owned job")
    if root.exists():
        raise FileExistsError(root)
    if action == "price_research":
        _phase(job_id, action, "price_research.preflight", started)
        recipe = request.get("recipe")
        if not isinstance(recipe, dict):
            raise ConfigError("price-research recipe must be an object")
        provider = "talib" if recipe.get("signal_template") == "sma_crossover" and recipe.get("signal_provider") == "talib" else "native"
        from .research_runtime import resolve_research_runtime
        runtime = resolve_research_runtime(Path(__file__).resolve().parents[1],
            operation="indicators" if provider == "talib" else "native",
            choices={"provider": "talib"} if provider == "talib" else None)
        if not runtime.get("enabled"):
            raise ConfigError("selected price-research dependencies are unavailable: " +
                              str(runtime.get("reason") or "runtime unavailable"))
        preflight = service.preflight_price_research(request["market_manifest"], recipe,
                                                     request.get("regime_observer"))
        if not preflight.get("ok"):
            raise ConfigError(f"price research preflight failed: {preflight.get('issues')}")
        expected = request.get("expected_fingerprint")
        if not isinstance(expected, str) or expected != preflight.get("fingerprint"):
            raise ConfigError("price research inputs changed or were not frozen by preflight")
        if owned is not None:
            _, _, job_root, output_dir = owned
            if output_dir.resolve(strict=True) != job_root / "output":
                raise ConfigError("workbench output directory changed during creation")
            root = output_dir / job_id
            if not root.resolve().is_relative_to(job_root):
                raise ConfigError("price-research result directory escapes its owned job")
        from .price_research import run_price_research
        report = run_price_research(request["market_manifest"], recipe, root,
            regime_observer=request.get("regime_observer"), expected_preflight=preflight)
        report = Path(report).resolve(strict=True)
        if owned is not None and not report.is_relative_to(job_root):
            raise ConfigError("price-research report escaped its owned job")
        report_value = json.loads(report.read_text(encoding="utf-8"))
        report_value["workbench_job"] = {"job_id": job_id, "action": action,
            "workspace_path": str(owned[0]) if owned is not None else None,
            "request_file_sha256": request.get("_request_file_sha256"),
            "request_identity_sha256": hashlib.sha256(json.dumps(request, sort_keys=True,
                ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
            "preflight_fingerprint": preflight["fingerprint"], "readiness": "RESEARCH-ONLY",
            "pit_guarantee": False}
        report.write_text(json.dumps(report_value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")
        report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
        _phase(job_id, action, "price_research.completed", started, report_sha256=report_sha)
        return {"ok":True,"job_id":job_id,"action":action,
            "result":{"report":str(report),"report_sha256":report_sha,
                      "preflight_fingerprint":preflight["fingerprint"],
                      "source_manifest_sha256":preflight["manifest_sha256"]},
            "artifacts":[str(report)],"errors":[]}
    if action in {"demo", "guided_demo"}:
        root.mkdir(parents=True, exist_ok=False)
        from .demo import create_demo
        if action=="guided_demo":
            from .guided_strategy import create_guided_demo
            demo=create_guided_demo(root/"demo",request["recipe"])
        else:
            demo = create_demo(root / "demo")
        return {"ok": True, "job_id": job_id, "action": action,
                "result": {"demo_dir": str(demo)}, "artifacts": [str(demo)], "errors": []}
    preflight = service.preflight(request["run_path"], mode,
                                  timeline_path=request.get("timeline_path"),
                                  execution_path=request.get("execution_path"),
                                  decision_at=request.get("decision_at"),
                                  target_action=action,
                                  factor_cache=request.get("factor_cache"))
    if not preflight["ok"]:
        raise ConfigError(f"preflight failed: {preflight['issues']}")
    expected = request.get("expected_fingerprint")
    if expected is not None and expected != preflight["fingerprint"]:
        raise ConfigError("input fingerprint changed since UI preflight")
    root.mkdir(parents=True, exist_ok=False)
    run_copy = service.snapshot_run(request["run_path"], root / "inputs", mode)
    # Verify the copied configuration graph matches the fingerprint observed
    # before the job directory was created.
    manifest = json.loads((root / "inputs" / "workbench_snapshot.json").read_text(encoding="utf-8"))
    for source, digest in manifest["source_hashes"].items():
        if preflight["file_hashes"].get(source) != digest:
            raise ConfigError("configuration changed during job snapshot")
    extras = {}
    extra_sources = {}
    for label in ("timeline", "execution"):
        source = request.get(label + "_path")
        if source is not None:
            copied = _copy_verified(source, preflight["file_hashes"][str(Path(source).resolve())], root / (label + ".json"))
            extras[label] = copied
            extra_sources[label] = source
    _verify_copied(manifest, extras, preflight["file_hashes"], extra_sources)
    artifacts: list[str] = [str(root / "inputs" / "workbench_snapshot.json")]
    if action == "plan":
        from .cli import plan_file
        if "execution" not in extras:
            raise ConfigError("plan requires execution_path")
        document = plan_file(run_copy, extras["execution"], request["decision_at"], request["now"])
        report = root / "plan.json"
        write_new(report, document)
        result = {"report": str(report), "submitted": False}
        artifacts.append(str(report))
    elif action == "history":
        from .history import run_history
        if "timeline" not in extras:
            raise ConfigError("history requires timeline_path")
        report_dir = root / "history"
        cache_path = None
        cache_selection = preflight.get("factor_cache") or {}
        cache_tracker = None
        if cache_selection.get("enabled"):
            cache_path = Path(cache_selection["cache_path"])
            _validate_factor_cache_job(request, cache_path)
            _validate_factor_cache_schema(cache_path)
            from .cache import FactorCache
            from . import history as history_module
            class _TrackedFactorCache(FactorCache):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.hits=0; self.misses=0; self.lookups=0; self.writes=0; self.corrupt=0
                    self.namespace="kabuforge.public_workbench_factor_cache.v1"
                def get(self, key):
                    self.lookups += 1
                    from .cache import FactorCacheCorruptionError
                    try:
                        value = super().get(key)
                    except FactorCacheCorruptionError:
                        self.corrupt += 1
                        raise
                    if value is None: self.misses += 1
                    else: self.hits += 1
                    return value
                def put(self, key, value):
                    result=super().put(key,value)
                    self.writes += 1
                    return result
            cache_tracker = _TrackedFactorCache(cache_path, namespace={
                "kind": "kabuforge.public_workbench_factor_cache.v1",
                "strategy_hash": preflight["strategy_hash"]})
            cache_tracker.namespace="kabuforge.public_workbench_factor_cache.v1"
            original_application = history_module.ApplicationService
            class _CachedApplicationService(original_application):
                def __init__(self): super().__init__(factor_cache=cache_tracker)
            history_module.ApplicationService = _CachedApplicationService
            try:
                try:
                    document = run_history(run_copy, extras["timeline"], output_dir=report_dir)
                except Exception as exc:
                    from .cache import FactorCacheCorruptionError
                    if isinstance(exc, FactorCacheCorruptionError):
                        failure_summary=_factor_cache_summary(cache_tracker,cache_path)
                        _write_factor_cache_failure(root,job_root,request,failure_summary,exc)
                    raise
            finally:
                history_module.ApplicationService = original_application
            cache_summary=_factor_cache_summary(cache_tracker,cache_path)
            document["factor_cache"] = cache_summary
            report_path = report_dir / "report.json"
            if report_path.is_symlink() or not report_path.resolve(strict=True).is_relative_to(job_root):
                raise ConfigError("history report escaped its owned job")
            report_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        else:
            document = run_history(run_copy, extras["timeline"], output_dir=report_dir)
            cache_summary=_factor_cache_summary(None,None)
        result = {"report": str(report_dir / "report.json"), "decisions": len(document["decisions"]),
                  "submitted": False, "factor_cache": cache_summary}
        artifacts.append(result["report"])
    else:
        from .runner import simulate_once
        if "execution" not in extras:
            raise ConfigError("simulate requires execution_path")
        journal = root / "journal.sqlite"
        document = simulate_once(run_copy, extras["execution"],
                                 decision_at=request["decision_at"], now=request["now"], store_path=journal)
        report = root / "simulation.json"
        write_new(report, document)
        result = {"report": str(report), "journal": str(journal), "submitted": False}
        artifacts.extend((str(report), str(journal)))
    _verify_copied(manifest, extras, preflight["file_hashes"], extra_sources)
    return {"ok": True, "job_id": job_id, "action": action, "result": result,
            "artifacts": artifacts, "errors": []}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args(argv)
    job_id = None
    action = None
    try:
        request_path = args.request.resolve(strict=True)
        request, request_sha256 = _read_json_snapshot(request_path)
        job_id, action = request.get("job_id"), request.get("action")
        if isinstance(request, dict) and request.get("workspace_path") is not None:
            owned = _owned_paths(request, require_workspace=True)
            if request_path.parent != owned[2] or not request_path.is_file():
                raise ConfigError("workbench request is outside its owned job directory")
        if isinstance(request, dict):
            request["_request_file_sha256"] = request_sha256
        result = run_request(request)
    except Exception as exc:
        result = {"ok": False, "job_id": job_id, "action": action,
                  "result": None, "artifacts": [], "errors": [{"field": "job", "message": str(exc)}]}
    print("WORKBENCH_RESULT=" + json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
