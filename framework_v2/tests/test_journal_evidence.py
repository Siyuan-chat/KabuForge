import json
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
import unittest
from framework_v2.store import Store,StoreError
from framework_v2.execution import AccountState,OrderPlan

class EvidenceTests(unittest.TestCase):
    def test_evidence_atomic_replay_and_original_schema_not_mutated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); account=AccountState("synthetic","0",1000,1000,())
            plan=OrderPlan((),{},0,1000); store=Store(root/"new.sqlite")
            kwargs=dict(decision_identity="d",strategy_hash="s",evidence={"state":{"last_decision_identity":"d"},"snapshot":"hash"})
            def fail(phase):
                if phase=="before_commit": raise RuntimeError("injected")
            with self.assertRaises(RuntimeError): store.register_batch("run",plan,account,**kwargs,failure_hook=fail)
            self.assertEqual(store.export_view()["run_evidence"],[])
            store.register_batch("run",plan,account,**kwargs)
            store.register_batch("run",plan,account,**kwargs)
            self.assertEqual(json.loads(store.export_view()["run_evidence"][0]["payload"]),kwargs["evidence"])
            with self.assertRaises(StoreError): store.register_batch("run",plan,account,**{**kwargs,"evidence":{"snapshot":"changed"}})
            old=root/"unversioned.sqlite"
            with closing(sqlite3.connect(old)) as db,db: db.execute("CREATE TABLE unrelated(x)")
            with self.assertRaisesRegex(StoreError,"migration"): Store(old)
            with closing(sqlite3.connect(old)) as db:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[("unrelated",)])

if __name__=="__main__": unittest.main()
