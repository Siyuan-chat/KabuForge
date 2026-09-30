"""Read-only workbench queries and explicit isolated input snapshots."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .application import ApplicationService
from .config import ConfigError, _read_json_snapshot
from .local_io import account_from_file, execution_from_file
from .workbench_model import ConfigDocument


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class WorkbenchService:
    """Local inspection facade; only snapshot_run writes, under caller's new directory."""

    def compatibility(self, path: str | Path) -> dict[str, Any]:
        try:
            doc = ConfigDocument(path)
            issues = doc.validate()
            return {"compatible": not issues, "issues": issues,
                    "kind": doc.data.get("kind"), "conversion_required": doc.data.get("kind") not in {"run", "strategy", "factor"}}
        except Exception as exc:
            return {"compatible": False, "issues": [{"field": "$", "message": str(exc)}],
                    "kind": None, "conversion_required": True}

    def catalog(self, directory: str | Path) -> list[dict[str, str]]:
        root = Path(directory).resolve()
        if not root.is_dir():
            raise ConfigError("catalog directory does not exist")
        items = []
        for path in sorted(root.glob("*.json")):
            try:
                value, _ = _read_json_snapshot(path)
            except ConfigError:
                continue
            if value.get("kind") in {"run", "strategy", "factor"}:
                items.append({"path": str(path), "id": str(value.get("id", "")),
                              "kind": value["kind"], "version": str(value.get("version", "")),
                              "display_name":str(value.get("metadata",{}).get("display_name",value.get("id","")))})
        return items

    def preflight(self, run_path: str | Path, mode: str = "backtest", *,
                  timeline_path: str | Path | None = None,
                  execution_path: str | Path | None = None,
                  decision_at: str | None = None) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        result: dict[str, Any] = {"ok": False, "issues": issues, "strategy_hash": None,
                                  "fingerprint": None, "datasets": {}, "config_hashes": {},
                                  "file_hashes": {}, "mode": mode, "strategy_id": None,
                                  "strategy_version": None, "account_id": None, "cutoff": None}
        if mode not in {"backtest", "paper", "fake", "broker"}:
            issues.append({"field": "mode", "message": "unknown mode"})
        if mode == "broker":
            issues.append({"field": "mode", "message": "broker execution is unavailable in the workbench"})
        try:
            resolved = ApplicationService().validate(run_path)
            hashes = dict(resolved.file_hashes)
            run = Path(run_path).resolve()
            result["strategy_hash"] = resolved.strategy_hash
            result["strategy_id"] = resolved.strategy["id"]
            result["strategy_version"] = resolved.strategy["version"]
            result["cutoff"] = decision_at or resolved.run["clock"]["end"]
            result["file_hashes"] = hashes
            config_paths = [run, (run.parent / resolved.run["strategy"]).resolve()]
            strategy_path = config_paths[1]
            config_paths.extend((strategy_path.parent / ref).resolve() for ref in resolved.strategy["factors"])
            result["config_hashes"] = {str(p): hashes[str(p)] for p in config_paths}
            snapshot_path = (run.parent / resolved.run["data_snapshot"]).resolve()
            snapshot, _ = _read_json_snapshot(snapshot_path)
            if snapshot.get("format") == "snapshot.parquet.v1":
                from .data_snapshot import snapshot_frames
                frames = snapshot_frames(snapshot_path, snapshot)
                snapshot = {"format": "snapshot.inline.v1", "datasets": {
                    name: {"columns": list(frame.columns),
                           "rows": list(frame.itertuples(index=False, name=None))}
                    for name, frame in frames.items()}}
            if snapshot.get("format") != "snapshot.inline.v1" or not isinstance(snapshot.get("datasets"), dict):
                raise ConfigError("unsupported snapshot manifest")
            account = account_from_file((run.parent / resolved.run["account_ref"]).resolve(),
                                        expected_hash=resolved.account_hash)
            result["account_id"] = account.account_id
            for factor in resolved.factors:
                for requirement in factor["data_requirements"]:
                    dataset = requirement["dataset"]
                    table = snapshot["datasets"].get(dataset)
                    if not isinstance(table, dict):
                        raise ConfigError(f"missing required dataset: {dataset}")
                    missing = set(requirement["fields"]) - set(table.get("columns", []))
                    if missing:
                        raise ConfigError(f"missing fields in {dataset}: {sorted(missing)}")
            cutoff = None
            if decision_at is not None:
                cutoff = datetime.fromisoformat(decision_at)
                if cutoff.tzinfo is None:
                    raise ConfigError("decision_at needs a timezone")
            for name, table in snapshot["datasets"].items():
                if not isinstance(table, dict) or not isinstance(table.get("columns"), list) or not isinstance(table.get("rows"), list):
                    raise ConfigError(f"invalid dataset table: {name}")
                columns = table["columns"]
                if len(set(columns)) != len(columns) or any(len(row) != len(columns) for row in table["rows"]):
                    raise ConfigError(f"invalid dataset shape: {name}")
                if "available_at" not in columns:
                    raise ConfigError(f"dataset {name} has no available_at PIT column")
                rows = table["rows"]
                at_index = columns.index("available_at") if "available_at" in columns else None
                dates = []
                known_dates = []
                known = 0
                for row in rows:
                    if at_index is not None:
                        stamp = datetime.fromisoformat(str(row[at_index]))
                        if stamp.tzinfo is None:
                            raise ConfigError(f"unknown available_at timezone in {name}")
                        dates.append(stamp)
                        if cutoff is None or stamp <= cutoff:
                            known += 1
                            known_dates.append(stamp)
                result["datasets"][name] = {"coverage": {"rows": len(rows), "known_rows": known if at_index is not None else None},
                                            "cutoff": cutoff.isoformat() if cutoff else None,
                                            "freshness": max(known_dates).isoformat() if known_dates else None,
                                            "latest_known_at": max(known_dates).isoformat() if known_dates else None,
                                            "latest_available_at": max(dates).isoformat() if dates else None}
            for label, path in (("timeline", timeline_path), ("execution", execution_path)):
                if path is not None:
                    _, digest = _read_json_snapshot(Path(path).resolve())
                    hashes[str(Path(path).resolve())] = digest
                    if label == "execution":
                        execution_from_file(path)
                    else:
                        timeline, _ = _read_json_snapshot(Path(path).resolve())
                        if timeline.get("format") not in {"execution.timeline.v1", "execution.daily_bars.v2"} or not isinstance(timeline.get("sessions"), list) or not timeline["sessions"]:
                            raise ConfigError("unsupported or empty execution timeline")
            identity = {"file_hashes": hashes, "strategy_hash": resolved.strategy_hash,
                        "mode": mode, "decision_at": decision_at}
            result["fingerprint"] = _digest(identity)
            if mode != resolved.run["mode"]:
                # Mode override is explicit and never changes strategy identity.
                result["mode_override"] = True
        except Exception as exc:
            issues.append({"field": "run", "message": str(exc)})
        result["ok"] = not issues
        return result

    def describe_run(self, run_path: str | Path, mode: str = "backtest") -> dict[str, Any]:
        path = Path(run_path).resolve()
        resolved = ApplicationService().validate(path)
        account_path = (path.parent / resolved.run["account_ref"]).resolve()
        account, _ = _read_json_snapshot(account_path)
        return {"strategy_id": resolved.strategy["id"], "strategy_version": resolved.strategy["version"],
                "account_id": account.get("account_id"), "cutoff": resolved.run["clock"]["end"],
                "mode": mode, "filepaths": sorted(resolved.file_hashes), "strategy_hash": resolved.strategy_hash}

    def snapshot_run(self, run_path: str | Path, destination: str | Path,
                     mode: str = "backtest") -> Path:
        evidence = self.preflight(run_path, mode)
        if not evidence["ok"]:
            raise ConfigError(f"cannot snapshot invalid run: {evidence['issues']}")
        root = Path(destination).resolve()
        if root.exists():
            raise FileExistsError(root)
        sources = [Path(p) for p in evidence["file_hashes"]]
        ancestor = Path(os.path.commonpath([str(p.parent) for p in sources]))
        run_source = Path(run_path).resolve()
        root.mkdir(parents=True, exist_ok=False)
        copied: dict[str, str] = {}
        for source in sources:
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != evidence["file_hashes"][str(source)]:
                raise ConfigError(f"input changed during snapshot: {source}")
            target = root / source.relative_to(ancestor)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
            copied[str(target)] = hashlib.sha256(raw).hexdigest()
        run_copy = root / run_source.relative_to(ancestor)
        run_config = json.loads(run_copy.read_text(encoding="utf-8"))
        run_config["mode"] = mode
        # Contain even a valid ../output reference within this isolated job.
        run_config["output_dir"] = "_results"
        run_copy.write_text(json.dumps(run_config, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        copied[str(run_copy)] = hashlib.sha256(run_copy.read_bytes()).hexdigest()
        manifest = {"source_fingerprint": evidence["fingerprint"], "source_hashes": evidence["file_hashes"],
                    "copied_hashes": copied, "run_path": str(run_copy), "mode": mode}
        (root / "workbench_snapshot.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_copy

    def read_journal(self, path: str | Path) -> dict[str, Any]:
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"accounts", "positions", "orders", "events", "fills"}
            if not required <= tables:
                raise ConfigError("unsupported journal schema")
            view = {name: [dict(row) for row in db.execute(f"SELECT * FROM {name}")]
                    for name in sorted(required)}
            blockers = [{"intent_id": row["intent_id"], "reason": "broker reconciliation required; do not resend"}
                        for row in view["orders"] if row["status"] in {"UNKNOWN", "SUBMITTING"}]
            blockers.extend({"account_id": row["account_id"], "reason": "account reconciliation required"}
                            for row in view["accounts"] if row["reconciliation_required"])
            db.commit()
            return {**view, "blockers": blockers}
        finally:
            db.close()

    def broker_capabilities(self) -> dict[str, Any]:
        return {
            "kabu": {"level": "protocol_mapping_mock_tested", "cash_equity": True,
                     "submit": True, "cancel": True, "account_query": True, "order_query": True,
                     "fill_query": "raw_order_details_only", "live_verified": False,
                     "source": "https://kabucom.github.io/kabusapi/ptal/"},
            "rakuten": {"level": "vba_mapping_mock_tested", "cash_equity": True,
                        "submit": True, "cancel": True, "account_query": False, "order_query": False,
                        "live_verified": False,
                        "source": "https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_06.html"},
            "neotrade": {"level": "vba_mapping_mock_tested", "cash_equity": True,
                         "submit": True, "cancel": True, "account_query": False, "order_query": False,
                         "live_verified": False,
                         "source": "https://www.sbineotrade.jp/manual/pdf/manual_api_VBA_function.pdf"},
        }
