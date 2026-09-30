"""Isolated local workbench job: python -m framework_v2.workbench_worker --request file.json."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .config import ConfigError, _read_json_snapshot
from .local_io import write_new
from .workbench_service import WorkbenchService


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
    if not isinstance(request, dict):
        raise ConfigError("request must be a JSON object")
    job_id = request.get("job_id")
    action = request.get("action")
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise ConfigError("job_id must be a safe nonempty identifier")
    if action not in {"preflight", "journal", "demo", "plan", "history", "simulate", "guided_demo", "price_research"}:
        raise ConfigError("unsupported workbench action")
    service = WorkbenchService()
    if action == "journal":
        return {"ok": True, "job_id": job_id, "action": action,
                "result": service.read_journal(request["journal_path"]), "artifacts": [], "errors": []}
    if action == "preflight":
        result = service.preflight(request["run_path"], request.get("mode", "backtest"),
                                   timeline_path=request.get("timeline_path"),
                                   execution_path=request.get("execution_path"),
                                   decision_at=request.get("decision_at"))
        return {"ok": result["ok"], "job_id": job_id, "action": action,
                "result": result, "artifacts": [], "errors": result["issues"]}
    mode = request.get("mode", "backtest")
    if mode == "broker":
        raise ConfigError("broker mode cannot execute from the workbench")
    root = Path(request["output_dir"]).resolve() / job_id
    if root.exists():
        raise FileExistsError(root)
    if action == "price_research":
        from .price_research import run_price_research
        report=run_price_research(request["market_manifest"],request["recipe"],root)
        return {"ok":True,"job_id":job_id,"action":action,"result":{"report":str(report)},"artifacts":[str(report)],"errors":[]}
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
                                  decision_at=request.get("decision_at"))
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
        document = run_history(run_copy, extras["timeline"], output_dir=report_dir)
        result = {"report": str(report_dir / "report.json"), "decisions": len(document["decisions"]),
                  "submitted": False}
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
        request, _ = _read_json_snapshot(args.request)
        job_id, action = request.get("job_id"), request.get("action")
        result = run_request(request)
    except Exception as exc:
        result = {"ok": False, "job_id": job_id, "action": action,
                  "result": None, "artifacts": [], "errors": [{"field": "job", "message": str(exc)}]}
    print("WORKBENCH_RESULT=" + json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
