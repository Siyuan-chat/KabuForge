"""Offline GUI integration for the explicit local-cache research path."""
from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd
from PySide6.QtWidgets import QApplication

from framework_v2.product_ui import ProductWorkbench


class LocalCacheGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        import framework_v2.local_cache_panel as panel_module
        candidate=Path(__file__).resolve().parents[2]
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),
                        panel_module.__file__)

    def _wait(self, predicate, timeout=60):
        import time
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertTrue(predicate(), "GUI worker did not complete before the bounded test timeout")

    def _fixture(self, path: Path):
        rows = []
        start = date(2024, 1, 2)
        for offset in range(42):
            day = (start + timedelta(days=offset)).isoformat()
            close = 100 + offset * .35 + (offset % 5) * .2
            rows.append({"date": day, "code": "72030", "open": close * .999,
                         "high": close * 1.01, "low": close * .99, "close": close,
                         "volume": 10000 + offset, "adjustment_factor": 1.0,
                         "adjustment_close": close * 1.02})
        frame = pd.DataFrame(rows)
        if path.suffix == ".csv":
            frame.to_csv(path, index=False)
        else:
            frame.to_parquet(path, index=False)
        return rows

    def test_csv_and_parquet_freeze_feed_indicator_and_native_backtest(self):
        with tempfile.TemporaryDirectory() as temp, patch("framework_v2.data_connection.load_api_key", return_value=None):
            root = Path(temp)
            for suffix in (".csv", ".parquet"):
                source = root / f"bars{suffix}"
                self._fixture(source)
                workspace = root / ("gui-" + suffix.lstrip("."))
                window = ProductWorkbench(workspace)
                try:
                    cache = window.local_cache_panel
                    cache.set_source_path(source)
                    cache.set_selection(["7203"], "2024-01-02", "2024-02-12", "raw")
                    self.assertTrue(cache.start_freeze())
                    self.assertFalse(cache.codes.isEnabled())
                    self.assertFalse(cache.price_basis.isEnabled())
                    self._wait(lambda: cache._task is None)
                    self.assertTrue(cache.codes.isEnabled())
                    self.assertTrue(Path(window.market_manifest).is_file())
                    frozen = json.loads(Path(window.market_manifest).read_text(encoding="utf-8"))
                    self.assertEqual(frozen["kind"], "kabuforge_local_research_bars")
                    self.assertEqual(frozen["canonical_data"]["rows"], 42)
                    self.assertIn("selected_data_sha256", frozen)

                    indicator = window.indicator_panel
                    indicator.code.setText("7203")
                    if indicator.dependency_ready:
                        self.assertTrue(indicator.run(),indicator.status.text())
                        self._wait(lambda: not indicator._is_busy())
                        self.assertEqual(len(indicator.table.rows), 42,
                            f"indicator did not render all 42 selected 7203 rows: {indicator.status.text()} "
                            f"job={indicator._job_dir}")
                        indicator_artifact = Path(indicator._last_payload["artifact_path"])
                        indicator_doc = json.loads(indicator_artifact.read_text(encoding="utf-8"))
                        self.assertEqual(indicator_doc["source_identity"]["price_basis"], "raw")
                        self.assertEqual(indicator_doc["source_identity"]["selected_data_sha256"],
                                         frozen["selected_data_sha256"])
                    else:
                        self.assertFalse(indicator.run(),"missing provider must not report a completed calculation")
                        self.assertIn("dependency",indicator.status.text().lower())

                    window.template.setCurrentIndex(window.template.findData("market"))
                    window.strategy_name.setText("Offline local momentum")
                    window.holding_count.setValue(1)
                    window.frequency.setCurrentIndex(window.frequency.findData("daily"))
                    window.lookback.setValue(3)
                    window.signal_template.setCurrentIndex(window.signal_template.findData("price_momentum"))
                    self.assertTrue(window.create_strategy(), window.guide_summary.text())
                    recipe = window.guide_recipe
                    from framework_v2.workbench_service import WorkbenchService
                    from framework_v2.workbench_worker import run_request
                    preflight = WorkbenchService().preflight_price_research(
                        window.market_manifest, recipe, {"mode": "off"})
                    self.assertTrue(preflight["ok"], json.dumps(preflight.get("issues"), ensure_ascii=False))
                    job_id = "offline-" + suffix.lstrip(".")
                    job_root = workspace / "jobs" / job_id / "output"
                    job_root.mkdir(parents=True)
                    request = {"job_id": job_id,
                        "action": "price_research", "mode": "backtest",
                        "output_dir": str(job_root), "market_manifest": str(window.market_manifest),
                        "workspace_path": str(workspace.resolve()),
                        "recipe": recipe, "regime_observer": {"mode": "off"},
                        "expected_fingerprint": preflight["fingerprint"]}
                    import requests
                    import urllib.request
                    with patch("framework_v2.data_connection.load_api_key",
                               side_effect=AssertionError("offline worker attempted to read credentials")), \
                         patch.object(requests.Session, "request",
                                      side_effect=AssertionError("offline worker attempted network access")), \
                         patch("urllib.request.urlopen",
                               side_effect=AssertionError("offline worker attempted network access")):
                        result = run_request(request)
                    self.assertTrue(result["ok"], json.dumps(result.get("errors"), ensure_ascii=False))
                    report_path = Path(result["result"]["report"])
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["input_source"]["kind"], "kabuforge_local_research_bars")
                    self.assertEqual(report["input_source"]["price_basis"], "raw")
                    self.assertEqual(report["signal_price_basis"], "raw")
                    self.assertIn("raw source open/close OHLC", report["execution_price_basis"])
                    self.assertTrue(report["nav"])
                    window.set_language("ja_JP")
                    self.assertIn("ローカル", cache.title())
                    cache.details_button.setChecked(True)
                    self.assertIn("固定ID", cache.details.text())
                    window.set_language("en_US")
                    self.assertIn("Local market cache", cache.title())
                    self.assertIn("Source SHA-256", cache.details.text())
                finally:
                    window.close(); self.app.processEvents()

    def test_gui_discloses_adjustment_and_warmup_rejections(self):
        from framework_v2.local_cache_panel import LocalCachePanel
        from framework_v2.workbench_service import WorkbenchService
        import requests
        import urllib.request
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); panel = LocalCachePanel(root)
            recipe = {"name": "Short local fixture", "template": "market", "count": 1,
                "lookback": 2, "cash": 100000, "fee": .1, "frequency": "daily",
                "signal_template": "price_momentum", "signal_provider": "native"}
            rows = []
            for offset in range(4):
                close = 100 + offset
                rows.append({"date": (date(2024, 1, 2) + timedelta(days=offset)).isoformat(),
                    "code": "72030", "open": close, "high": close + 1, "low": close - 1,
                    "close": close, "volume": 1000})
            source = root / "plain_ohlcv.csv"; pd.DataFrame(rows).to_csv(source, index=False)
            panel.set_source_path(source); panel.set_selection(["7203"], "2024-01-02", "2024-01-05")
            self.assertTrue(panel.start_freeze()); self._wait(lambda: panel._task is None)
            self.assertFalse(panel._last_result["native_backtest_compatible"])
            self.assertIn("adjustment_factor is missing", panel.status.text())
            with patch("framework_v2.data_connection.load_api_key",
                       side_effect=AssertionError("offline preflight attempted to read credentials")), \
                 patch.object(requests.Session, "request",
                              side_effect=AssertionError("offline preflight attempted network access")), \
                 patch("urllib.request.urlopen",
                       side_effect=AssertionError("offline preflight attempted network access")):
                missing_factor = WorkbenchService().preflight_price_research(
                    panel._last_result["manifest_path"], recipe, {"mode": "off"})
            self.assertFalse(missing_factor["ok"])
            self.assertIn("Adjustment-factor evidence missing",
                          missing_factor["issues"][0]["message"])

            # Add factors but keep the history too short for the configured lookback.
            recipe["lookback"] = 20
            enough_schema = pd.DataFrame(rows).assign(adjustment_factor=1.0)
            short_source = root / "short.csv"; enough_schema.to_csv(short_source, index=False)
            panel.set_source_path(short_source); panel.set_selection(["7203"], "2024-01-02", "2024-01-05")
            self.assertTrue(panel.start_freeze()); self._wait(lambda: panel._task is None)
            self.assertTrue(panel._last_result["native_backtest_compatible"])
            short_history = WorkbenchService().preflight_price_research(
                panel._last_result["manifest_path"], recipe, {"mode": "off"})
            self.assertFalse(short_history["ok"])
            self.assertIn("Not enough sessions", short_history["issues"][0]["message"])
            panel.close(); self.app.processEvents()

    def test_gui_requires_explicit_identical_dedup_and_localizes_frozen_counts(self):
        from framework_v2.local_cache_panel import LocalCachePanel

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "duplicate-bars.parquet"
            rows = self._fixture(source)
            frame = pd.DataFrame(rows)
            frame = pd.concat([frame, frame.iloc[[8]]], ignore_index=True)
            frame.to_parquet(source, index=False, row_group_size=10)
            panel = LocalCachePanel(root / "workspace")
            try:
                panel.set_source_path(source)
                panel.set_selection(["7203"], "2024-01-02", "2024-02-12")
                self.assertEqual(panel.duplicate_policy.currentData(), "reject")
                self.assertTrue(panel.start_freeze())
                self._wait(lambda: panel._task is None)
                self.assertIsNone(panel._last_result)
                self.assertIn("duplicate", panel._status_error)

                panel.set_selection(["7203"], "2024-01-02", "2024-02-12",
                                    "raw", "drop_identical")
                self.assertTrue(panel.start_freeze())
                self._wait(lambda: panel._task is None)
                self.assertIsNotNone(panel._last_result)
                self.assertEqual(panel._last_result["duplicate_rows_removed"], 1)
                self.assertEqual(panel._last_result["duplicate_policy"], "drop_identical")
                manifest = json.loads(Path(panel._last_result["manifest_path"]).read_text(encoding="utf-8"))
                self.assertEqual(manifest["coverage"]["duplicate_rows_removed"], 1)
                self.assertEqual(manifest["selection"]["duplicate_policy"], "drop_identical")
                self.assertIn("删除完全相同重复行 1 条", panel.status.text())
                for language, text_fragment in (("zh_CN", "删除完全相同重复行 1 条"),
                                                 ("ja_JP", "削除した完全一致行 1 行"),
                                                 ("en_US", "removed 1 identical rows")):
                    panel.set_language(language)
                    self.assertIn(text_fragment, panel.status.text())
                panel.set_language("zh_CN")
            finally:
                panel.close(); self.app.processEvents()

    def test_gui_verified_halt_exclusion_is_explicit_frozen_and_trilingual(self):
        from framework_v2.local_cache_panel import LocalCachePanel

        rows = []
        for code, base in (("4502", 100), ("6758", 200)):
            rows.append({"date": "2020-09-30", "code": code, "open": base,
                "high": base + 2, "low": base - 2, "close": base + 1, "volume": 1000,
                "adjustment_factor": 1.0})
            halt = {"date": "2020-10-01", "code": code, "open": None, "high": None,
                "low": None, "close": None, "volume": None, "adjustment_factor": 1.0}
            rows.extend([halt.copy(), halt.copy()])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "verified-halt-fixture.parquet"
            pd.DataFrame(rows).to_parquet(source, index=False, row_group_size=2)
            panel = LocalCachePanel(root / "workspace")
            try:
                self.assertFalse(panel.known_halt_exclusion.isChecked())
                panel.set_source_path(source)
                panel.set_selection(["4502", "6758"], "2020-09-30", "2020-10-01",
                    "raw", "drop_identical", "exclude_verified_tse_halt_20201001")
                self.assertTrue(panel.known_halt_exclusion.isChecked())
                self.assertTrue(panel.start_freeze())
                self._wait(lambda: panel._task is None)
                result = panel._last_result
                self.assertIsNotNone(result, panel.status.text())
                self.assertEqual(result["rows"], 2)
                self.assertEqual(result["rows_before_dedup"], 6)
                self.assertEqual(result["duplicate_rows_removed"], 2)
                self.assertEqual(result["verified_halt_exclusion"]["rows"], 2)
                self.assertEqual(result["verified_halt_exclusion"]["date"], "2020-10-01")
                manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
                exclusion = manifest["selection"]["verified_halt_exclusion"]
                self.assertEqual(exclusion["input_source_sha256"], manifest["source"]["source_sha256"])
                self.assertIn("20201001-03.html", exclusion["source_url"])
                self.assertEqual(manifest["selection"]["known_halt_policy"],
                                 "exclude_verified_tse_halt_20201001")
                self.assertIn("排除 2 行（2020-10-01）", panel.status.text())
                for language, fragment in (("ja_JP", "2020-10-01 の 2 行を除外"),
                                            ("en_US", "Excluded 2 rows on 2020-10-01"),
                                            ("zh_CN", "排除 2 行（2020-10-01）")):
                    panel.set_language(language)
                    self.assertIn(fragment, panel.status.text())
                panel.set_language("zh_CN")
            finally:
                panel.close(); self.app.processEvents()

    def test_editing_or_failing_new_local_input_invalidates_old_market_source(self):
        from framework_v2.local_cache_panel import LocalCachePanel

        with tempfile.TemporaryDirectory() as temp, patch("framework_v2.data_connection.load_api_key", return_value=None):
            root = Path(temp); window = ProductWorkbench(root / "workbench")
            try:
                panel = window.local_cache_panel
                first = root / "first.csv"; self._fixture(first)
                panel.set_source_path(first)
                panel.set_selection(["7203"], "2024-01-02", "2024-02-12", "raw")
                self.assertTrue(panel.start_freeze()); self._wait(lambda: panel._task is None)
                self.assertIsNotNone(window.market_manifest)
                first_manifest = str(window.market_manifest)
                self.assertTrue(Path(first_manifest).is_file())
                self.assertTrue(panel._last_result)

                # Editing any new selection invalidates the old active manifest immediately.
                second = root / "broken.csv"; second.write_text("not,a,daily-bar-schema\n1,2,3\n", encoding="utf-8")
                panel.set_source_path(second)
                self.assertIsNone(window.market_manifest)
                self.assertEqual(panel._last_result, None)
                self.assertEqual(window.indicator_panel.manifest.text(), "")
                self.assertFalse(window.run_guided())

                panel.set_selection(["7203"], "2024-01-02", "2024-02-12", "raw")
                self.assertTrue(panel.start_freeze()); self._wait(lambda: panel._task is None)
                failure_text = panel.status.text()
                self.assertIn("未完成", failure_text)
                self.assertTrue(failure_text.strip())
                self.assertFalse(panel._last_result)
                error_detail = panel._status_error
                self.assertTrue(error_detail)
                for language, title_fragment in (("ja_JP", "ローカル"), ("en_US", "Local market cache"),
                                                  ("zh_CN", "本地行情缓存")):
                    window.set_language(language)
                    self.assertIn(title_fragment, panel.title())
                    self.assertIn("未完了" if language == "ja_JP" else
                                  "Not completed" if language == "en_US" else "未完成", panel.status.text())
                    self.assertIn(error_detail, panel.status.text())
                self.assertFalse(Path(first_manifest).resolve() == Path(window.market_manifest or "__none__").resolve())
            finally:
                window.close(); self.app.processEvents()

    def test_csv_runs_through_owned_qprocess_with_sanitized_environment(self):
        """Exercise the real QProcess chain on an explicit fictional calendar fixture."""
        import hashlib
        import uuid
        from PySide6.QtCore import QProcessEnvironment

        evidence_root = Path(os.environ.get("KABUFORGE_TEST_EVIDENCE_ROOT",tempfile.gettempdir()))
        evidence = (evidence_root / "local-cache-gui-qprocess"
                    / (time.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]))
        evidence.mkdir(parents=True, exist_ok=False)
        source = evidence / "fictional_consecutive_calendar_days.csv"
        self._fixture(source)
        malicious_path=evidence/"must-not-be-inherited"
        malicious_path.mkdir()
        original_system_environment=QProcessEnvironment.systemEnvironment
        environment_by_job={}
        workspace = evidence / "workbench"
        window = ProductWorkbench(workspace)
        started = time.monotonic()
        try:
            cache = window.local_cache_panel
            cache.set_source_path(source)
            cache.set_selection(["7203"], "2024-01-02", "2024-02-12", "raw")
            self.assertTrue(cache.start_freeze())
            self._wait(lambda: cache._task is None)
            window.template.setCurrentIndex(window.template.findData("market"))
            window.strategy_name.setText("Offline QProcess momentum")
            window.holding_count.setValue(1)
            window.frequency.setCurrentIndex(window.frequency.findData("daily"))
            window.lookback.setValue(3)
            window.signal_template.setCurrentIndex(window.signal_template.findData("price_momentum"))
            self.assertTrue(window.create_strategy(), window.guide_summary.text())

            def guarded_process_environment():
                environment = original_system_environment()
                environment.insert("PYTHONPATH", str(malicious_path))
                environment.insert("JQUANTS_API_KEY","test-only-must-be-dropped")
                environment.insert("KABUFORGE_API_KEY","test-only-must-be-dropped")
                environment.insert("KABUFORGE_TOKEN","test-only-must-be-dropped")
                return environment

            deadline = time.monotonic() + 150
            status_history = []
            last_snapshot = None
            last_recorded_at = 0.0
            with patch("framework_v2.workbench_jobs.QProcessEnvironment.systemEnvironment",
                       side_effect=guarded_process_environment):
                self.assertTrue(window.run_guided(), window.statusBar().currentMessage())
                while time.monotonic() < deadline:
                    self.app.processEvents()
                    jobs = [dict(job) for job in window.jobs.jobs]
                    process=window.jobs.process
                    if process is not None:
                        current=window.jobs.current or {}
                        job_id=current.get("job_id")
                        if job_id and job_id not in environment_by_job:
                            child_env=process.processEnvironment()
                            child_path=child_env.value("PYTHONPATH").split(os.pathsep)
                            environment_by_job[job_id]={
                                "job_id":job_id,"pid":current.get("pid"),"pythonpath":child_path,
                                "credential_variables_absent":all(not child_env.contains(name) for name in
                                    ("JQUANTS_API_KEY","KABUFORGE_API_KEY","KABUFORGE_TOKEN")),
                                "hostile_pythonpath_absent":str(malicious_path) not in child_path}
                    snapshot = [{"job_id": job.get("job_id"), "action": job.get("action"),
                                 "status": job.get("status"), "pid": job.get("pid"),
                                 "exit_code": job.get("exit_code"), "manifest": job.get("manifest"),
                                 "log": job.get("log")} for job in jobs]
                    now = time.monotonic()
                    if snapshot != last_snapshot or now - last_recorded_at >= 2:
                        status_history.append({"elapsed_seconds": round(now - started, 3), "jobs": snapshot})
                        last_snapshot, last_recorded_at = snapshot, now
                    research = [job for job in jobs if job.get("action") == "price_research"]
                    if research and research[-1].get("status") in {"COMPLETED", "FAILED", "CANCELED"}:
                        break
                    time.sleep(.05)
            jobs = [dict(job) for job in window.jobs.jobs]
            research = [job for job in jobs if job.get("action") == "price_research"]
            if window.jobs.busy:
                # The controller owns this exact worker. Preserve its request/log/manifest before cancelling.
                window.jobs.cancel()
                cancel_deadline = time.monotonic() + 8
                while window.jobs.busy and time.monotonic() < cancel_deadline:
                    self.app.processEvents(); time.sleep(.05)
                jobs = [dict(job) for job in window.jobs.jobs]
                research = [job for job in jobs if job.get("action") == "price_research"]
            serial_jobs = [{key: job.get(key) for key in
                ("job_id", "action", "status", "pid", "exit_code", "started_at", "finished_at",
                 "request", "input_hash", "output_dir", "log", "manifest", "error", "result")}
                for job in jobs]
            receipt = {"test": "actual ProductWorkbench QProcess offline chain",
                "fixture": "42 fictional consecutive calendar dates; not a Japan exchange calendar",
                "worker_boundary": "fixed workbench request/action protocol; the actual child environment drops injected credentials and hostile PYTHONPATH; no injected sitecustomize or network-deny shim",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "jobs": serial_jobs, "observed_states": status_history,
                "child_environment_by_job":environment_by_job,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "report": None, "limitations": ["synthetic engineering fixture only; no market performance inference"]}
            if research and research[-1].get("status") == "COMPLETED":
                report_path = (research[-1].get("result") or {}).get("result", {}).get("report")
                receipt["report"] = report_path
            receipt_path = evidence / "qprocess-receipt.json"
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            worker_jobs = [job for job in jobs if job.get("action") in {"preflight", "price_research"}]
            receipt["environment_verified"] = len(worker_jobs) == 2 and all(
                job.get("job_id") in environment_by_job and
                environment_by_job[job.get("job_id")]["credential_variables_absent"] and
                environment_by_job[job.get("job_id")]["hostile_pythonpath_absent"]
                for job in worker_jobs)
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertTrue(receipt["environment_verified"],
                f"worker environment allowlist was not verified for each owned worker; receipt: {receipt_path}")
            self.assertTrue(research, f"run_guided did not reach price_research; receipt: {receipt_path}")
            self.assertEqual(research[-1].get("status"), "COMPLETED",
                f"QProcess research status {research[-1].get('status')}; receipt: {receipt_path}")
            report_path = Path(receipt["report"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["input_source"]["kind"], "kabuforge_local_research_bars")
            self.assertTrue(report.get("nav"))
        finally:
            if window.jobs.busy:
                window.jobs.cancel()
                cancel_deadline = time.monotonic() + 8
                while window.jobs.busy and time.monotonic() < cancel_deadline:
                    self.app.processEvents(); time.sleep(.05)
            window.close(); self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
