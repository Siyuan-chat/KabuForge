"""Isolated pandas-ta indicator worker; no network, credentials, or orders."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import sysconfig
import uuid
from pathlib import Path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _page_identities(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = manifest.get("pages", []) if isinstance(manifest, dict) else []
    result = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("file"), str):
            raise ValueError("manifest page identity is invalid")
        source = (manifest_path.parent / page["file"]).resolve(strict=True)
        if not source.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("manifest page path escapes its source directory")
        digest = _hash(source)
        if digest != page.get("sha256"):
            raise ValueError("manifest page hash does not match source")
        result[str(page.get("code", source.name))] = digest
    return result


def _load_bars(manifest_path: Path):
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if manifest.get("kind") == "kabuforge_local_research_bars":
        from .local_cache import load_research_bars
        selection = manifest.get("selection") or {}
        loaded = load_research_bars(manifest_path, codes=selection.get("requested_codes", ()),
            start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
            price_basis=selection.get("price_basis", ""),
            duplicate_policy=selection.get("duplicate_policy", "reject"),
            known_halt_policy=selection.get("known_halt_policy", "reject"))
        rows = loaded.bars.to_dict(orient="records")
        basis = loaded.selection["price_basis"]
        for row in rows:
            row["adjustment_close"] = row["selected_price"] if basis == "adjusted" else None
        identity = {"kind": "kabuforge_local_research_bars",
            "manifest_sha256": loaded.source["source_sha256"],
            "selected_data_sha256": loaded.selected_data_sha256,
            "selection_identity_sha256": loaded.identity_sha256,
            "pinned_identity_sha256": loaded.source["details"]["pinned_identity_sha256"],
            "price_basis": basis, "coverage": loaded.coverage,
            "pit_guarantee": False, "source_availability": "historical visibility unverified"}
        return rows, identity, _hash(manifest_path), (selection, loaded.selected_data_sha256)
    from .data_connection import load_bars
    rows = load_bars(manifest_path)
    identity = {"kind": "jquants_completed_manifest", "manifest_sha256": _hash(manifest_path),
                "price_basis": "raw", "pit_guarantee": False,
                "source_availability": "current API view; historical visibility unverified"}
    if manifest.get("fixture_provenance"):
        identity["fixture_provenance"] = str(manifest["fixture_provenance"])
    return rows, identity, _hash(manifest_path), None


def _verify_frozen(manifest_path: Path, frozen) -> None:
    if frozen is None:
        return
    from .local_cache import load_research_bars
    selection, expected_sha = frozen
    loaded = load_research_bars(manifest_path, codes=selection.get("requested_codes", ()),
        start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
        price_basis=selection.get("price_basis", ""),
        duplicate_policy=selection.get("duplicate_policy", "reject"),
        known_halt_policy=selection.get("known_halt_policy", "reject"))
    if loaded.selected_data_sha256 != expected_sha:
        raise ValueError("Frozen local market input changed during indicator calculation")


def _install_offline_guards():
    original = (socket.create_connection, socket.socket.connect, socket.socket.connect_ex)
    def denied(*_args, **_kwargs):
        raise PermissionError("indicator research worker blocks network access")
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    from . import data_connection
    original_loader = data_connection.load_api_key
    def denied_credentials():
        raise PermissionError("indicator research worker never reads API credentials")
    data_connection.load_api_key = denied_credentials

    def restore():
        socket.create_connection, socket.socket.connect, socket.socket.connect_ex = original
        data_connection.load_api_key = original_loader
    return restore


def run(args) -> dict:
    restore_guards = _install_offline_guards()
    try:
        return _run_guarded(args)
    finally:
        restore_guards()


def _run_guarded(args) -> dict:
    from .research_runtime import resolve_extension_runtime
    package_root = Path(__file__).resolve().parents[1]
    supplied_root = Path(args.project_root).expanduser().resolve(strict=True)
    if supplied_root != package_root:
        raise ValueError("project root must be the installed package root")
    provider = getattr(args, "provider", "pandas-ta")
    if provider not in {"talib", "pandas-ta"}:
        raise ValueError("indicator provider is outside the static allowlist")
    runtime = resolve_extension_runtime(package_root, platform.python_version(), sysconfig.get_platform(),
        operation="indicators", choices={"provider": provider})
    if not runtime.get("enabled"):
        raise RuntimeError("selected indicator dependencies are unavailable: " + str(runtime.get("reason")))
    manifest_path = Path(args.manifest).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve(strict=True)
    if not output_dir.is_dir():
        raise ValueError("indicator output directory must already exist")
    manifest_sha_before = _hash(manifest_path)
    page_shas_before = _page_identities(manifest_path)
    rows, source_identity, _, frozen = _load_bars(manifest_path)
    from .indicator_research import calculate_pandas_ta_indicators, calculate_talib_indicators
    calculate = calculate_talib_indicators if provider == "talib" else calculate_pandas_ta_indicators
    result = calculate(rows, args.code, sma_period=args.sma_period,
        rsi_period=args.rsi_period, atr_period=args.atr_period,
        source_kind=("Frozen local research bars; PIT unverified" if frozen else
            ("Fictional engineering fixture; not J-Quants data" if source_identity.get("fixture_provenance")
             else "Completed J-Quants manifest; historical visibility unverified")))
    _verify_frozen(manifest_path, frozen)
    manifest_sha_after = _hash(manifest_path)
    page_shas_after = _page_identities(manifest_path)
    if manifest_sha_before != manifest_sha_after or page_shas_before != page_shas_after:
        raise ValueError("Source manifest changed while indicators were calculated")
    implementation_path = Path(__file__).with_name("indicator_research.py")
    run_id = uuid.uuid4().hex
    payload = {
        "schema": "kabuforge_indicator_research", "schema_version": 2,
        "run_id": run_id, "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "source_manifest": str(manifest_path), "source_manifest_sha256": manifest_sha_after,
        "source_identity": {**source_identity, "page_sha256": page_shas_after}, "source_kind": result.source_kind,
        "security_code": result.code, "input_sha256": result.input_sha256,
        "price_field": result.price_field, "atr_price_field": result.atr_price_field,
        "parameters": {"sma_period": result.sma_period, "rsi_period": result.rsi_period,
                       "macd": {"fast": 12, "slow": 26, "signal": 9},
                       "atr_period": result.atr_period},
        "engine": {"name": result.engine_name, "version": result.talib_version,
                   "python_version": platform.python_version(),
                   "runtime_paths": list(runtime.get("paths", [])),
                   "implementation_sha256": _hash(implementation_path),
                   "worker_sha256": _hash(Path(__file__).resolve()),
                   "seed_semantics": ({
                       "sma": "pandas-ta native rolling mean; native warm-up NaN retained as null",
                       "rsi": (f"pandas-ta RSI length={result.rsi_period}, drift=1; positive and negative deltas each use "
                               "native RMA alpha=1/length, ewm adjust=False, without an SMA seed; "
                               "RSI=100*avg_gain/(avg_gain+abs(avg_loss)) (RMA/Wilder smoothing recurrence)"),
                       "macd": ("pandas-ta MACD fast=12, slow=26, signal=9; native EMA presma=True seeds each span "
                               "with its initial span SMA then ewm adjust=False; native warm-up retained"),
                       "atr": (f"pandas-ta ATR length={result.atr_period}, talib=False, presma=True; "
                              "initial length-value simple-average true-range seed followed by recursive "
                              f"RMA/Wilder alpha=1/length over {result.atr_price_field}; warm-up retained"),
                       "missing_values": "warm-up NaN is serialized null; dates are never dropped or interpolated"}
                       if provider == "pandas-ta" else {
                       "sma": f"TA-Lib SMA timeperiod={result.sma_period}; native lookback retained",
                       "rsi": f"TA-Lib RSI timeperiod={result.rsi_period}; native lookback retained",
                       "macd": "TA-Lib MACD (12,26,9); native lookback retained",
                       "atr": f"TA-Lib ATR timeperiod={result.atr_period}; {result.atr_price_field}",
                       "missing_values": "warm-up NaN is serialized null; dates are never dropped or interpolated"})},
        "offline_guards": ["socket create_connection/connect/connect_ex denied",
                           "data_connection.load_api_key denied"],
        "rows": result.rows,
    }
    target = output_dir / f"indicator-{run_id}.json"
    if target.parent.resolve() != output_dir or target.exists():
        raise ValueError("refusing to overwrite or escape output directory")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with target.open("xb") as stream:
        stream.write(encoded)
    return {"ok": True, "artifact_path": str(target), "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
            "input_sha256": result.input_sha256, "engine": result.engine_name,
            "version": result.talib_version, "row_count": len(result.rows),
            "manifest_sha256": manifest_sha_after, "pit_guarantee": False}


def main(argv=None) -> int:
    print("INDICATOR_WORKER_STARTED=" + json.dumps({"pid": os.getpid(), "ppid": os.getppid(),
        "executable": sys.executable, "argv": sys.argv, "orig_argv": getattr(sys, "orig_argv", [])},
        ensure_ascii=False), flush=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--sma-period", required=True, type=int)
    parser.add_argument("--rsi-period", required=True, type=int)
    parser.add_argument("--atr-period", required=True, type=int)
    parser.add_argument("--provider", choices=("talib", "pandas-ta"), default="pandas-ta")
    args = parser.parse_args(argv)
    try:
        result = run(args)
        print("INDICATOR_RESULT=" + json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
        return 0
    except Exception as exc:
        print("INDICATOR_RESULT=" + json.dumps({"ok": False,
            "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
