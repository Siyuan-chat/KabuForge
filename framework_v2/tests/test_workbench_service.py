import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from framework_v2.demo import create_demo
from framework_v2.workbench_service import WorkbenchService
from framework_v2.workbench_worker import run_request


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.demo = create_demo(self.root / "demo")
        self.service = WorkbenchService()

    def test_preflight_identity_snapshot_catalog_and_compatibility(self):
        run = self.demo / "backtest.json"
        before = self.service.preflight(run, decision_at="2024-05-01T09:00:00+09:00")
        self.assertTrue(before["ok"], before["issues"])
        self.assertIn("prices", before["datasets"])
        self.assertEqual(before["strategy_id"], "demo")
        self.assertEqual(before["account_id"], "synthetic-only")
        self.assertEqual(before["cutoff"], "2024-05-01T09:00:00+09:00")
        self.assertGreater(before["datasets"]["prices"]["coverage"]["rows"], 0)
        self.assertTrue(before["datasets"]["prices"]["freshness"])
        for dataset in before["datasets"].values():
            if dataset["latest_known_at"]:
                self.assertLessEqual(datetime.fromisoformat(dataset["latest_known_at"]),
                                     datetime.fromisoformat(before["cutoff"]))
            self.assertEqual(dataset["freshness"], dataset["latest_known_at"])
        self.assertIn("snapshot.json", " ".join(before["file_hashes"]))
        copy = self.service.snapshot_run(run, self.root / "snapshot", "fake")
        self.assertTrue(copy.is_file())
        self.assertEqual(json.loads(copy.read_text())["mode"], "fake")
        self.assertEqual(self.service.preflight(copy, "fake")["strategy_hash"], before["strategy_hash"])
        manifest = json.loads((self.root / "snapshot" / "workbench_snapshot.json").read_text())
        self.assertEqual(manifest["source_hashes"], before["file_hashes"])
        self.assertEqual(self.service.describe_run(run)["account_id"], "synthetic-only")
        self.assertTrue(any(item["kind"] == "run" for item in self.service.catalog(self.demo)))
        legacy = self.root / "legacy.json"
        legacy.write_text('{"foo":1}', encoding="utf-8")
        self.assertTrue(self.service.compatibility(legacy)["conversion_required"])
        changed = json.loads((self.demo / "account.json").read_text())
        changed["equity"] = "2000001"
        (self.demo / "account.json").write_text(json.dumps(changed), encoding="utf-8")
        after = self.service.preflight(run)
        self.assertNotEqual(before["fingerprint"], after["fingerprint"])

    def test_ro_journal_unknown_gate_and_broker_levels(self):
        path = self.root / "journal.sqlite"
        db = sqlite3.connect(path)
        for name in ("accounts", "positions", "orders", "events", "fills"):
            if name == "accounts":
                db.execute("CREATE TABLE accounts(account_id TEXT,reconciliation_required INTEGER)")
                db.execute("INSERT INTO accounts VALUES('a',1)")
            elif name == "orders":
                db.execute("CREATE TABLE orders(intent_id TEXT,status TEXT)")
                db.execute("INSERT INTO orders VALUES('i','UNKNOWN')")
                db.execute("INSERT INTO orders VALUES('j','SUBMITTING')")
            else:
                db.execute(f"CREATE TABLE {name}(id TEXT)")
        db.commit()
        db.close()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        view = self.service.read_journal(path)
        self.assertEqual(view["blockers"][0]["intent_id"], "i")
        self.assertIn("do not resend", view["blockers"][0]["reason"])
        self.assertEqual({item.get("intent_id") for item in view["blockers"] if "intent_id" in item}, {"i", "j"})
        self.assertTrue(any(item.get("account_id") == "a" for item in view["blockers"]))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        with self.assertRaises(FileNotFoundError):
            self.service.read_journal(self.root / "absent.sqlite")
        self.assertFalse((self.root / "absent.sqlite").exists())
        for item in self.service.broker_capabilities().values():
            self.assertFalse(item["live_verified"])

    def test_worker_fingerprint_gate_and_last_line(self):
        run = self.demo / "backtest.json"
        evidence = self.service.preflight(run, execution_path=self.demo / "execution.json",
                                          decision_at="2024-05-01T09:00:00+09:00")
        request = {"job_id": "j1", "action": "plan", "run_path": str(run), "mode": "backtest",
                   "execution_path": str(self.demo / "execution.json"),
                   "decision_at": "2024-05-01T09:00:00+09:00", "now": "2024-05-01T09:00:00+09:00",
                   "output_dir": str(self.root / "jobs"), "expected_fingerprint": evidence["fingerprint"]}
        path = self.root / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-m", "framework_v2.workbench_worker", "--request", str(path)],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        last = result.stdout.splitlines()[-1]
        self.assertTrue(last.startswith("WORKBENCH_RESULT="))
        self.assertTrue(json.loads(last.split("=", 1)[1])["ok"])
        request["job_id"] = "j2"
        request["expected_fingerprint"] = "wrong"
        path.write_text(json.dumps(request), encoding="utf-8")
        denied = subprocess.run([sys.executable, "-B", "-m", "framework_v2.workbench_worker", "--request", str(path)],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((self.root / "jobs" / "j2").exists())
        request["job_id"] = "j3"
        request["expected_fingerprint"] = evidence["fingerprint"]
        account = self.demo / "account.json"
        changed = json.loads(account.read_text(encoding="utf-8"))
        changed["equity"] = "2000001"
        account.write_text(json.dumps(changed), encoding="utf-8")
        path.write_text(json.dumps(request), encoding="utf-8")
        changed_result = subprocess.run([sys.executable, "-B", "-m", "framework_v2.workbench_worker", "--request", str(path)],
                                        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertNotEqual(changed_result.returncode, 0)
        self.assertFalse((self.root / "jobs" / "j3").exists())

    def test_worker_history_simulate_and_journal_local(self):
        base = {"run_path": str(self.demo / "backtest.json"), "mode": "backtest",
                "output_dir": str(self.root / "jobs"),
                "decision_at": "2024-05-01T09:00:00+09:00", "now": "2024-05-01T09:00:00+09:00"}
        simulation = run_request({**base, "job_id": "sim", "action": "simulate",
                                  "execution_path": str(self.demo / "execution.json")})
        self.assertTrue(simulation["ok"])
        self.assertTrue(Path(simulation["result"]["journal"]).is_file())
        queried = run_request({"job_id": "query", "action": "journal",
                               "journal_path": simulation["result"]["journal"]})
        self.assertTrue(queried["ok"])
        self.assertIn("orders", queried["result"])
        history = run_request({**base, "job_id": "history", "action": "history",
                               "timeline_path": str(self.demo / "timeline.json")})
        self.assertTrue(history["ok"])
        self.assertTrue(Path(history["result"]["report"]).is_file())


if __name__ == "__main__":
    unittest.main()
