"""GUI and isolated-worker tests for opt-in history factor-cache reuse."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

from PySide6.QtCore import QProcessEnvironment
from PySide6.QtWidgets import QApplication

from framework_v2.config import ConfigError
from framework_v2.demo import create_demo
from framework_v2.factor_cache_panel import FactorCachePanel
from framework_v2.product_ui import ProductWorkbench
from framework_v2.workbench_service import WorkbenchService
from framework_v2.workbench_worker import (_validate_factor_cache_schema,
                                           run_request)


class FactorCacheGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        import framework_v2.factor_cache_panel as panel_module
        candidate=Path(__file__).resolve().parents[2]
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),
                        panel_module.__file__)

    def _wait(self, predicate, timeout=150):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.02)
        self.app.processEvents()
        self.assertTrue(predicate(),"owned ProductWorkbench QProcess did not finish")

    def _fixture_request(self, root, workspace, job_id="bad-path"):
        demo=root/"demo"
        if not demo.exists(): create_demo(demo)
        selection={"schema":"kabuforge.factor-cache-selection.v1","enabled":True,
                   "workspace_path":str(workspace.resolve())}
        evidence=WorkbenchService().preflight(demo/"backtest.json",timeline_path=demo/"timeline.json",
            factor_cache=selection,target_action="history")
        self.assertTrue(evidence["ok"],evidence["issues"])
        return demo,selection,evidence,{"job_id":job_id,"action":"history","mode":"backtest",
            "run_path":str(demo/"backtest.json"),"timeline_path":str(demo/"timeline.json"),
            "workspace_path":str(workspace.resolve()),
            "output_dir":str(workspace/"jobs"/job_id/"output"),"factor_cache":selection,
            "expected_fingerprint":evidence["fingerprint"]}

    def test_panel_defaults_off_localizes_and_invalidates_stale_result(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace=Path(temp)/"workbench"
            window=ProductWorkbench(workspace)
            try:
                panel=window.factor_cache_panel
                self.assertFalse(panel.is_enabled())
                self.assertIn("不会创建",panel.status.text())
                window.preflight_result={"ok":True,"fingerprint":"old"}
                panel.toggle.setChecked(True)
                self.assertIsNone(window.preflight_result)
                self.assertIn("已启用",panel.status.text())
                panel.set_language("ja_JP")
                self.assertIn("履歴ファクター",panel.title().replace("キャッシュ", "キャッシュ"))
                self.assertIn("有効",panel.status.text())
                panel.set_language("en_US")
                self.assertIn("Enabled",panel.status.text())
                panel.show_summary({"stats":{"hits":2,"misses":0,"writes":0,"corrupt":0},
                                    "namespace_identity":"abc123456789"})
                self.assertIn("hits 2",panel.status.text())
                panel.toggle.setChecked(False)
                self.assertIn("no cache file",panel.status.text())
                self.assertNotIn("hits 2",panel.status.text())
                panel.set_busy(True)
                self.assertFalse(panel.toggle.isEnabled())
                panel.set_busy(False)
            finally:
                window.close(); self.app.processEvents()

    def test_preflight_binds_cache_toggle_and_rejects_ineligible_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); demo=create_demo(root/"demo"); workspace=root/"workbench"
            workspace.mkdir()
            disabled={"schema":"kabuforge.factor-cache-selection.v1","enabled":False,
                      "workspace_path":str(workspace.resolve())}
            enabled={**disabled,"enabled":True}
            service=WorkbenchService()
            off=service.preflight(demo/"backtest.json",timeline_path=demo/"timeline.json",
                                  factor_cache=disabled,target_action="history")
            on=service.preflight(demo/"backtest.json",timeline_path=demo/"timeline.json",
                                 factor_cache=enabled,target_action="history")
            self.assertTrue(off["ok"],off["issues"]); self.assertTrue(on["ok"],on["issues"])
            self.assertNotEqual(off["fingerprint"],on["fingerprint"])
            self.assertEqual(on["factor_cache"]["cache_path"],
                             str((workspace/"cache"/"history-factors.sqlite").resolve()))
            self.assertFalse((workspace/"cache").exists())
            paper=service.preflight(demo/"paper.json","paper",timeline_path=demo/"timeline.json",
                                    factor_cache=enabled,target_action="simulate")
            self.assertFalse(paper["ok"])
            unknown={**enabled,"schema":"kabuforge.factor-cache-selection.v999"}
            rejected=service.preflight(demo/"backtest.json",timeline_path=demo/"timeline.json",
                factor_cache=unknown,target_action="history")
            self.assertFalse(rejected["ok"])

    def test_worker_rejects_arbitrary_output_paths_and_unknown_cache_objects(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); workspace=root/"workbench"; workspace.mkdir()
            demo,selection,evidence,request=self._fixture_request(root,workspace)
            request["output_dir"]=str(root/"outside-output")
            with self.assertRaisesRegex(ConfigError,"output directory"):
                run_request(request)

            bad_id="unknown-schema"
            job_directory=workspace/"jobs"/bad_id
            job_directory.mkdir(parents=True)
            cache_path=workspace/"cache"/"history-factors.sqlite"
            cache_path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(cache_path)) as db, db:
                db.execute("CREATE TABLE factor_cache_v1(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL)")
                db.execute("CREATE VIEW unexpected AS SELECT cache_key FROM factor_cache_v1")
            with self.assertRaisesRegex(ConfigError,"objects"):
                _validate_factor_cache_schema(cache_path)
            _,_,bad_evidence,bad_request=self._fixture_request(root,workspace,bad_id)
            bad_request["expected_fingerprint"]=bad_evidence["fingerprint"]
            with self.assertRaisesRegex(ConfigError,"objects"):
                run_request(bad_request)
            self.assertTrue((workspace/"jobs"/bad_id/"output"/bad_id).is_dir())
            self.assertFalse((workspace/"jobs"/bad_id/"output"/bad_id/"history"/"report.json").exists())

    def test_worker_parameter_miss_cache_off_and_corrupt_rejection(self):
        from framework_v2.cache import FactorCacheCorruptionError
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); workspace=root/"workbench"; workspace.mkdir()
            demo=create_demo(root/"demo")

            def run(job_id,enabled,expected=None):
                selection={"schema":"kabuforge.factor-cache-selection.v1","enabled":enabled,
                           "workspace_path":str(workspace.resolve())}
                evidence=WorkbenchService().preflight(demo/"backtest.json",timeline_path=demo/"timeline.json",
                    factor_cache=selection,target_action="history")
                self.assertTrue(evidence["ok"],evidence["issues"])
                jobdir=workspace/"jobs"/job_id; jobdir.mkdir(parents=True)
                request={"job_id":job_id,"action":"history","mode":"backtest",
                    "run_path":str(demo/"backtest.json"),"timeline_path":str(demo/"timeline.json"),
                    "workspace_path":str(workspace.resolve()),
                    "output_dir":str(jobdir/"output"),"factor_cache":selection,
                    "expected_fingerprint":expected or evidence["fingerprint"]}
                envelope=run_request(request)
                report=json.loads(Path(envelope["result"]["report"]).read_text(encoding="utf-8"))
                return {"envelope":envelope,"report":report}

            self.assertFalse((workspace/"cache"/"history-factors.sqlite").exists())
            cold=run("cold",True)
            cold_cache=cold["report"]["factor_cache"]
            self.assertEqual((cold_cache["hits"],cold_cache["misses"],cold_cache["lookups"]),(0,2,2))
            warm=run("warm",True)
            warm_cache=warm["report"]["factor_cache"]
            self.assertEqual((warm_cache["hits"],warm_cache["misses"],warm_cache["lookups"]),(2,0,2))
            factor_path=demo/"quality.json"
            factor=json.loads(factor_path.read_text(encoding="utf-8")); factor["lookback"]+=1
            factor_path.write_text(json.dumps(factor,ensure_ascii=False),encoding="utf-8")
            changed=run("changed-parameter",True)
            changed_cache=changed["report"]["factor_cache"]
            # The public namespace binds the full strategy hash, so changing one
            # recipe field invalidates both factor entries under a new namespace.
            self.assertEqual((changed_cache["hits"],changed_cache["misses"]),(0,2))
            self.assertEqual(changed_cache["namespace"],
                             "kabuforge.public_workbench_factor_cache.v1")

            off_workspace=root/"workbench-off"; off_workspace.mkdir()
            original_workspace=workspace; workspace=off_workspace
            off=run("cache-off",False)
            self.assertNotIn("factor_cache",off["report"])
            self.assertFalse((off_workspace/"cache"/"history-factors.sqlite").exists())
            workspace=original_workspace

            cache_path=workspace/"cache"/"history-factors.sqlite"
            with closing(sqlite3.connect(cache_path)) as db, db:
                db.execute("UPDATE factor_cache_v1 SET payload=?",("{tampered",))
            with self.assertRaises(FactorCacheCorruptionError):
                run("corrupt-entry",True)
            corrupt_report=workspace/"jobs"/"corrupt-entry"/"output"/"corrupt-entry"/"history"/"report.json"
            self.assertFalse(corrupt_report.exists(),"corrupt cache must fail closed before writing a history report")

    def test_product_qprocess_cold_warm_history_and_sanitized_environment(self):
        evidence_root=Path(os.environ.get("KABUFORGE_TEST_EVIDENCE_ROOT",tempfile.gettempdir()))
        evidence=(evidence_root/"factor-cache-gui-qprocess"/
                 (datetime.now().strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]))
        evidence.mkdir(parents=True,exist_ok=False)
        evidence_resolved=evidence.resolve()
        demo=create_demo(evidence/"fixture")
        malicious_path=evidence/"must-not-be-inherited"
        malicious_path.mkdir()
        jobs_seen=[]; environment_seen=[]; locked_seen=[]

        def process_job(window,action,expected_status="COMPLETED",timeout=240):
            job_started=time.monotonic()
            if action=="preflight":
                request=window._request("history")
                request["action"]="preflight"
                request["target_action"]="history"
                window.jobs.start(request)
                window._update_actions()
            else:
                self.assertTrue(window.start_action(action),window.statusBar().currentMessage())
            job=window.jobs.jobs[-1]
            process=window.jobs.process
            self.assertIsNotNone(process,"ProductWorkbench must use its owned QProcess")
            child_environment=process.processEnvironment()
            child_path=child_environment.value("PYTHONPATH").split(os.pathsep)
            environment_record={
                "job_id":job.get("job_id"),"pid":job.get("pid"),
                "pythonpath":child_path,
                "credential_variables_absent":all(not child_environment.contains(key) for key in
                    ("JQUANTS_API_KEY","KABUFORGE_API_KEY","KABUFORGE_TOKEN")),
                "hostile_pythonpath_absent":str(malicious_path) not in child_path}
            environment_seen.append(environment_record)
            self.assertIn(str(Path(__file__).resolve().parents[2]),child_path)
            self.assertTrue(environment_record["credential_variables_absent"],json.dumps(environment_record))
            self.assertTrue(environment_record["hostile_pythonpath_absent"],json.dumps(environment_record))
            if window.jobs.busy:
                locked_seen.append(not window.factor_cache_panel.toggle.isEnabled())
            self._wait(lambda:not window.jobs.busy and job.get("status") in
                       {"COMPLETED","FAILED","CANCELED"},timeout=timeout)
            job["test_elapsed_seconds"]=round(time.monotonic()-job_started,3)
            jobs_seen.append({key:job.get(key) for key in
                ("job_id","action","status","pid","exit_code","request","input_hash","output_dir","log","manifest","result","test_elapsed_seconds")})
            self.assertEqual(job.get("status"),expected_status,
                json.dumps({"job":job,"log":Path(job.get("log","missing")).read_text(encoding="utf-8",errors="replace") if job.get("log") and Path(job["log"]).is_file() else ""},ensure_ascii=False))
            if expected_status=="COMPLETED":
                log_text=Path(job["log"]).read_text(encoding="utf-8",errors="replace")
                self.assertIn("WORKBENCH_PHASE=",log_text,"worker stage evidence missing from QProcess log")
                request=json.loads(Path(job["request"]).read_text(encoding="utf-8"))
                self.assertEqual(request.get("workspace_path"),str(workspace.resolve()))
                self.assertNotIn("api_key",json.dumps(request).lower())
                self.assertNotIn("token",json.dumps(request).lower())
            (evidence_resolved/"qprocess-progress.json").write_text(json.dumps({
                "jobs":jobs_seen,"sanitized_child_environments":environment_seen,
                "fixture":"create_demo fictional engineering fixture only"},ensure_ascii=False,indent=2),encoding="utf-8")
            return job

        original_env=QProcessEnvironment.systemEnvironment
        window=None; off_window=None; failure=None; cleanup_error=None; completed=False
        try:
            workspace=evidence/"workbench-cache-on"
            workspace_on=workspace
            window=ProductWorkbench(workspace)
            window.load_catalog(demo)
            self.assertTrue(window.load_document(demo/"backtest.json",choice="discard"))
            window.timeline.setText(str(demo/"timeline.json"))
            self.assertFalse(window.factor_cache_panel.is_enabled())
            self.assertTrue(window.factor_cache_panel.toggle.isEnabled())
            window.factor_cache_panel.toggle.setChecked(True)
            self.assertFalse((workspace/"cache"/"history-factors.sqlite").exists())

            def guarded_environment():
                env=original_env()
                env.insert("PYTHONPATH",str(malicious_path))
                env.insert("JQUANTS_API_KEY","test-only-must-be-dropped")
                env.insert("KABUFORGE_API_KEY","test-only-must-be-dropped")
                env.insert("KABUFORGE_TOKEN","test-only-must-be-dropped")
                return env

            with patch("framework_v2.workbench_jobs.QProcessEnvironment.systemEnvironment",
                       side_effect=guarded_environment):
                preflight_job=process_job(window,"preflight")
                self.assertTrue(preflight_job["result"]["result"]["ok"])
                self.assertTrue(preflight_job["result"]["result"]["factor_cache"]["enabled"])
                self.assertFalse((workspace/"cache"/"history-factors.sqlite").exists())
                cold_job=process_job(window,"history")
                cold_report=json.loads(Path(cold_job["result"]["result"]["report"]).read_text(encoding="utf-8"))
                cold_info=cold_report["factor_cache"]
                self.assertEqual((cold_info["hits"],cold_info["misses"],cold_info["lookups"]),(0,2,2))
                cold_summary=cold_job["result"]["result"].get("factor_cache")
                self.assertIsInstance(cold_summary,dict,
                    "history result must carry the report-bound cache summary to the GUI panel")
                self.assertEqual(cold_summary["stats"],{"hits":0,"misses":2,"writes":2,"corrupt":0})
                self.assertEqual(window.factor_cache_panel._summary,cold_summary)
                warm_job=process_job(window,"history")
                warm_report=json.loads(Path(warm_job["result"]["result"]["report"]).read_text(encoding="utf-8"))
                warm_info=warm_report["factor_cache"]
                self.assertEqual((warm_info["hits"],warm_info["misses"],warm_info["lookups"]),(2,0,2))
                warm_summary=warm_job["result"]["result"].get("factor_cache")
                self.assertEqual(warm_summary["stats"],{"hits":2,"misses":0,"writes":0,"corrupt":0})
                self.assertEqual(cold_summary["namespace_identity"],warm_summary["namespace_identity"])
                self.assertEqual(window.factor_cache_panel._summary,warm_summary)

                for field in ("nav","final_state"):
                    self.assertEqual(cold_report[field],warm_report[field])
                for field in ("orders","fills","valuations"):
                    self.assertEqual(cold_report["journal"][field],warm_report["journal"][field])

                # Change a declared factor input, explicitly invalidate the
                # stale preflight, then execute another real Product history job.
                factor_path=demo/"quality.json"
                factor_doc=json.loads(factor_path.read_text(encoding="utf-8"))
                factor_doc["lookback"]+=1
                factor_path.write_text(json.dumps(factor_doc,ensure_ascii=False),encoding="utf-8")
                window.invalidate_preflight()
                changed_preflight=process_job(window,"preflight")
                self.assertTrue(changed_preflight["result"]["result"]["ok"])
                changed_job=process_job(window,"history")
                changed_report=json.loads(Path(changed_job["result"]["result"]["report"]).read_text(encoding="utf-8"))
                changed_summary=changed_job["result"]["result"]["factor_cache"]
                self.assertEqual((changed_summary["stats"]["hits"],changed_summary["stats"]["misses"]),(0,2))
                self.assertNotEqual(changed_summary["namespace_identity"],warm_summary["namespace_identity"])
                self.assertEqual(window.factor_cache_panel._summary,changed_summary)

                # The cache remains opt-in in a fresh GUI-owned workspace.
                off_workspace=evidence/"workbench-cache-off"
                off_window=ProductWorkbench(off_workspace)
                off_window.load_catalog(demo)
                self.assertTrue(off_window.load_document(demo/"backtest.json",choice="discard"))
                off_window.timeline.setText(str(demo/"timeline.json"))
                self.assertFalse(off_window.factor_cache_panel.is_enabled())
                workspace=off_workspace
                off_preflight=process_job(off_window,"preflight")
                self.assertFalse(off_preflight["result"]["result"]["factor_cache"]["enabled"])
                off_job=process_job(off_window,"history")
                off_summary=off_job["result"]["result"]["factor_cache"]
                self.assertFalse(off_summary["enabled"])
                self.assertFalse((off_workspace/"cache"/"history-factors.sqlite").exists())
                self.assertFalse(off_window.factor_cache_panel.is_enabled())
                off_window.close(); self.app.processEvents()
                workspace=workspace_on

                # Corrupt an existing selected cache payload. The owned history
                # job must fail and surface its receipt rather than recompute.
                cache_path=workspace/"cache"/"history-factors.sqlite"
                with closing(sqlite3.connect(cache_path)) as db, db:
                    db.execute("UPDATE factor_cache_v1 SET payload=?",("{tampered",))
                window.invalidate_preflight()
                corrupt_preflight=process_job(window,"preflight")
                self.assertTrue(corrupt_preflight["result"]["result"]["ok"])
                corrupt_job=process_job(window,"history",expected_status="FAILED")
                failure_path=(Path(corrupt_job["output_dir"])/corrupt_job["job_id"]/
                              "factor_cache_failure.json")
                self.assertTrue(failure_path.is_file(),str(failure_path))
                failure_receipt=json.loads(failure_path.read_text(encoding="utf-8"))
                self.assertEqual(failure_receipt["stats"]["corrupt"],1)
                self.assertFalse(failure_receipt["fallback_recompute"])
                self.assertEqual(window.factor_cache_panel._failure_path,str(failure_path))

            self.assertTrue(locked_seen and all(locked_seen),"cache option was not locked during owned jobs")
            self.assertEqual(len(jobs_seen),9)
            self.assertTrue(all(item["credential_variables_absent"] and item["hostile_pythonpath_absent"]
                                for item in environment_seen),json.dumps(environment_seen,ensure_ascii=False))
            history_logs=[Path(job["log"]).read_text(encoding="utf-8",errors="replace")
                          for job in (cold_job,warm_job)]
            self.assertTrue(all('"stage": "workspace.validated"' in text and
                                '"action": "history"' in text and "WORKBENCH_RESULT=" in text
                                for text in history_logs),
                            "owned history worker logs must contain its validation phase and terminal result")
            self.assertTrue((workspace/"cache"/"history-factors.sqlite").is_file())
            self.assertFalse((evidence/"workbench-cache-off"/"cache"/"history-factors.sqlite").exists())
            completed=True
        except BaseException as exc:
            failure={"type":type(exc).__name__,"message":str(exc)}
            raise
        finally:
            if window is not None:
                if window.jobs.busy:
                    window.jobs.cancel()
                    try:
                        self._wait(lambda:not window.jobs.busy,timeout=10)
                    except BaseException as exc:
                        cleanup_error={"type":type(exc).__name__,"message":str(exc),
                                       "job":dict(window.jobs.current or {})}
                window.close(); self.app.processEvents()
            if off_window is not None:
                if off_window.jobs.busy:
                    off_window.jobs.cancel()
                    try:
                        self._wait(lambda:not off_window.jobs.busy,timeout=10)
                    except BaseException as exc:
                        cleanup_error={"type":type(exc).__name__,"message":str(exc),
                                       "job":dict(off_window.jobs.current or {})}
                off_window.close(); self.app.processEvents()
            marker_rows=[]
            receipt={"kind":"product_workbench_factor_cache_qprocess_evidence.v2",
                "status":"COMPLETED" if completed else "FAILED_OR_INCOMPLETE",
                "failure":failure,"cleanup_error":cleanup_error,
                "fixture":"create_demo short fictional synthetic snapshot; engineering test only",
                "workspace_cache_enabled":str(evidence/"workbench-cache-on"/"cache"/"history-factors.sqlite"),
                "jobs":jobs_seen,"sanitized_child_environments":environment_seen,
                "worker_request_is_local_only":True,"network_guard_claim":"not independently injected; history worker uses closed local request/action and no external transport is requested",
                "locked_during_jobs":locked_seen,
                "cache_on_cold":locals().get("cold_info"),"cache_on_warm":locals().get("warm_info"),
                "cache_after_parameter_change":locals().get("changed_summary"),
                "cache_off_summary":locals().get("off_summary"),
                "corruption_receipt":locals().get("failure_receipt"),
                "source_identity":{"run_sha256":hashlib.sha256((demo/"backtest.json").read_bytes()).hexdigest(),
                    "timeline_sha256":hashlib.sha256((demo/"timeline.json").read_bytes()).hexdigest()},
                "limitations":["synthetic engineering workflow; no strategy validation or performance inference","child credential variables and hostile PYTHONPATH were shown absent from the actual QProcess environment; no injected sitecustomize or network-deny shim was used"]}
            (evidence/"qprocess-receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    unittest.main()
