"""Offline static-operation worker for the price-sensitivity GUI workflow."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import traceback
from typing import Any


REQUEST_SCHEMA = "kabuforge.price_sensitivity_request.v1"
RESULT_SCHEMA = "kabuforge.price_sensitivity_worker_result.v1"
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("terminal worker receipt already exists")
    temp = path.with_name("." + path.name + f".{os.getpid()}.tmp")
    if temp.exists() or temp.is_symlink():
        raise FileExistsError("worker temporary receipt already exists")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if path.exists() or path.is_symlink():
        temp.unlink(missing_ok=True)
        raise FileExistsError("terminal worker receipt already exists")
    temp.replace(path)


def _job_directory(workspace: Path, job_id: str) -> Path:
    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job ID must be lowercase UUID hex")
    workspace = workspace.resolve(strict=True)
    root = (workspace / "price-sensitivity" / "jobs").resolve()
    if not root.is_relative_to(workspace) or root == workspace:
        raise ValueError("job root escapes selected workspace")
    job_dir = (root / job_id).resolve(strict=True)
    if not job_dir.is_relative_to(root) or not job_dir.is_relative_to(workspace) or job_dir == root:
        raise ValueError("job directory escapes workspace")
    return job_dir


def _read_request(workspace: Path, job_id: str) -> tuple[Path, dict]:
    job_dir = _job_directory(workspace, job_id)
    request_path = job_dir / "request.json"
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("sensitivity request cannot be read") from None
    expected = {"schema", "job_id", "operation", "run_directory", "report_sha256"}
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError("request keys do not match the static operation")
    if request.get("schema") != REQUEST_SCHEMA or request.get("job_id") != job_id:
        raise ValueError("unsupported request schema or job identity")
    if request.get("operation") != "price_sensitivity":
        raise ValueError("operation is not in the static allowlist")
    if any((job_dir / name).exists() or (job_dir / name).is_symlink()
           for name in ("result.json", "failure.json")):
        raise ValueError("job already has a terminal result")
    outputs = job_dir / "outputs"
    resolved_outputs = outputs.resolve()
    if not resolved_outputs.is_relative_to(job_dir) or resolved_outputs == job_dir:
        raise ValueError("output directory escapes selected job")
    outputs.mkdir(exist_ok=True)
    if not outputs.resolve(strict=True).is_relative_to(job_dir):
        raise ValueError("output directory escapes selected job")
    return job_dir, request


def _install_offline_guards():
    original = (socket.create_connection, socket.socket.connect, socket.socket.connect_ex)
    def denied(*_args, **_kwargs):
        raise RuntimeError("offline research worker blocks network access")
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    from . import data_connection
    original_loader = data_connection.load_api_key
    def denied_credentials():
        raise PermissionError("price sensitivity workers never read API credentials")
    data_connection.load_api_key = denied_credentials

    def restore():
        socket.create_connection, socket.socket.connect, socket.socket.connect_ex = original
        data_connection.load_api_key = original_loader
    return restore


def run_job(workspace: str | Path, job_id: str) -> dict:
    restore_guards = _install_offline_guards()
    try:
        job_dir, request = _read_request(Path(workspace).resolve(strict=True), job_id)
        started = datetime.now(timezone.utc).isoformat()
        run_dir = Path(request["run_directory"]).expanduser().resolve(strict=True)
        report_path = run_dir / "report.json"
        if not report_path.is_file() or _sha256(report_path) != request["report_sha256"]:
            raise ValueError("selected source report hash does not match request")
        from .price_sensitivity import run_price_sensitivity

        result_path = run_price_sensitivity(run_dir, job_dir / "outputs" / "scenario-run",
                                            expected_report_sha256=request["report_sha256"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        return {"schema": RESULT_SCHEMA, "status": result["status"], "job_id": job_id,
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(), "operation": "price_sensitivity", "offline_guards": {
                "socket_create_connection": "blocked", "socket_connect": "blocked", "socket_connect_ex": "blocked",
                "credential_loader": "data_connection.load_api_key denied"},
            "source_report_sha256": request["report_sha256"], "result_path": str(result_path),
            "result_sha256": _sha256(result_path), "result": result}
    finally:
        restore_guards()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the static local price-sensitivity operation")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).resolve(strict=True)
    if not _JOB_ID.fullmatch(args.job_id):
        print(json.dumps({"status":"FAILED","error_type":"ValueError","reason":"invalid job ID"}), file=sys.stderr)
        return 1
    job_dir = None
    try:
        job_dir = _job_directory(workspace, args.job_id)
        checked_job_dir, _ = _read_request(workspace, args.job_id)
        if checked_job_dir != job_dir:
            raise ValueError("job directory identity changed")
        result = run_job(workspace, args.job_id)
        _write_json(job_dir / "result.json", result)
        print(json.dumps({"status": result["status"], "job_id": args.job_id,
                          "result_sha256": result["result_sha256"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {"schema": RESULT_SCHEMA, "status": "FAILED", "job_id": args.job_id,
            "finished_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
            "operation": "price_sensitivity", "error_type": type(exc).__name__,
            "reason": str(exc), "traceback": traceback.format_exc(limit=8),
            "offline_guards": {"socket_create_connection": "blocked", "socket_connect": "blocked",
                               "socket_connect_ex": "blocked",
                               "credential_loader": "data_connection.load_api_key denied"}}
        if job_dir is not None and not any((job_dir / name).exists() or (job_dir / name).is_symlink()
                                           for name in ("result.json", "failure.json")):
            try:
                _write_json(job_dir / "failure.json", failure)
            except Exception:
                pass
        print(json.dumps({"status": "FAILED", "job_id": args.job_id,
                          "error_type": type(exc).__name__, "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
