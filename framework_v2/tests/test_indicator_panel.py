"""Indicator panel isolation/lifecycle tests; fixtures are fictional calendar data."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import time
import unittest
import shutil
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from framework_v2.indicator_panel import IndicatorChart, IndicatorResearchPanel


def _argv_option(argv, name):
    matches = [index for index, value in enumerate(argv) if value == name]
    if len(matches) != 1 or matches[0] + 1 >= len(argv):
        return None
    return argv[matches[0] + 1]


def _same_path_entity(first, second):
    if not isinstance(first, (str, os.PathLike)) or not isinstance(second, (str, os.PathLike)):
        return False
    if not os.fspath(first) or not os.fspath(second):
        return False
    try:
        if os.path.samefile(first, second):
            return True
    except (OSError, TypeError, ValueError):
        pass
    try:
        return Path(first).resolve(strict=True) == Path(second).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _worker_is_bound_to_launch(worker, launch, gui_pid):
    qprocess_pid = launch.get("pid")
    worker_pid = worker.get("pid")
    if not isinstance(qprocess_pid, int) or not isinstance(worker_pid, int):
        return False
    if worker_pid != launch.get("python_worker_pid"):
        return False
    if worker.get("ppid") != launch.get("python_worker_ppid"):
        return False
    if not _same_path_entity(worker.get("executable", ""), launch.get("python_worker_executable", "")):
        return False

    worker_argv = worker.get("orig_argv") or worker.get("argv")
    if worker_argv != launch.get("python_worker_argv"):
        return False
    if "framework_v2.indicator_research_worker" not in worker_argv:
        return False
    manifest_arg = _argv_option(worker_argv, "--manifest")
    output_arg = _argv_option(worker_argv, "--output-dir")
    expected_manifest = (launch.get("request") or {}).get("manifest")
    expected_output = launch.get("output_dir")
    if not manifest_arg or not expected_manifest or not _same_path_entity(manifest_arg, expected_manifest):
        return False
    if not output_arg or not expected_output or not _same_path_entity(output_arg, expected_output):
        return False

    if worker_pid == qprocess_pid:
        # Native python.exe is the QProcess itself; its parent is the GUI.
        return worker.get("ppid") == gui_pid and _same_path_entity(
            launch.get("program", ""), worker.get("executable", ""))
    # A Windows redirector is the QProcess and starts the base interpreter.
    return worker.get("ppid") == qprocess_pid


def _short_windows_path(path):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    get_short_path = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_short_path.restype = wintypes.DWORD
    needed = get_short_path(str(path), None, 0)
    if not needed:
        return None
    buffer = ctypes.create_unicode_buffer(needed)
    written = get_short_path(str(path), buffer, needed)
    return buffer.value if written else None


def _long_windows_temp_path(path):
    if os.name != "nt":
        return None
    profile = os.environ.get("USERPROFILE")
    if not profile:
        return None
    try:
        relative = os.path.relpath(path, tempfile.gettempdir())
        candidate = Path(profile) / "AppData" / "Local" / "Temp" / relative
        if candidate.exists() and os.path.samefile(candidate, path):
            return candidate
    except (OSError, RuntimeError, ValueError):
        return None
    return None


class _PreserveOnFailure:
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="indicator-qprocess-"))
        return str(self.path)

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            shutil.rmtree(self.path)
        else:
            print(f"INDICATOR_QPROCESS_FAILURE_EVIDENCE={self.path}")
        return False


class IndicatorPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_imported_panel_comes_from_this_candidate_checkout(self):
        import framework_v2.indicator_panel as panel_module
        candidate=Path(__file__).resolve().parents[2]
        self.assertTrue(Path(panel_module.__file__).resolve().is_relative_to(candidate),
                        panel_module.__file__)

    def _fixture(self, root: Path, *, adjusted=False) -> Path:
        start = date(2021, 1, 4)
        rows = []
        for index in range(70):
            close = 100.0 + index * 0.35 + (index % 5) * 0.12
            item = {"Date": (start + timedelta(days=index)).strftime("%Y%m%d"),
                "Code": "45020", "Open": close - 0.15, "High": close + 0.8,
                "Low": close - 0.7, "Close": close, "Volume": 10000 + index,
                "AdjustmentFactor": 1.0}
            if adjusted:
                item.update({"AdjustmentOpen": close * 1.1 - 0.15,
                    "AdjustmentHigh": close * 1.1 + 0.8, "AdjustmentLow": close * 1.1 - 0.7,
                    "AdjustmentClose": close * 1.1})
            rows.append(item)
        page_bytes = json.dumps(rows, separators=(",", ":")).encode("utf-8")
        (root / "bars.json").write_bytes(page_bytes)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1, "kind": "jquants_equities_daily_bars",
            "status": "complete", "request": {"codes": ["45020"], "start": "2021-01-04", "end": "2021-12-31"},
            "fixture_provenance": "fictional synthetic consecutive calendar dates for engineering tests; not market data",
            "pages": [{"code": "45020", "file": "bars.json",
                "sha256": hashlib.sha256(page_bytes).hexdigest(), "row_count": len(rows)}]},
            ensure_ascii=False), encoding="utf-8")
        return manifest

    def test_chart_preserves_all_dates_and_breaks_at_null_warmup(self):
        chart = IndicatorChart("test", "JPY/share")
        dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
        values = [None, 10.0, None, 12.0]
        chart.set_series(dates, [("SMA", values)])
        self.assertEqual(chart.dates, dates)
        self.assertEqual(chart.series[0][1], values)
        self.assertEqual(len(chart.series[0][1]), len(dates))

    def test_rsi_chart_uses_fixed_zero_to_one_hundred_axis(self):
        chart = IndicatorChart("RSI", "0–100")
        self.assertEqual(chart._y_range([49.0, 50.0, 51.0]), (0.0, 100.0))
        self.assertEqual(chart._y_range([0.0, 100.0]), (0.0, 100.0))

    def _synthetic_binding(self, root: Path, *, direct: bool, manifest_arg=None, output_arg=None,
                           expected_manifest=None, expected_output=None):
        manifest = root / "manifest with spaces.json"
        manifest.write_text("{}", encoding="utf-8")
        output = root / "worker output"
        output.mkdir(exist_ok=True)
        qprocess_pid = 12001 if direct else 12002
        worker_pid = qprocess_pid if direct else 12003
        worker_ppid = os.getpid() if direct else qprocess_pid
        args = ["-B", "-m", "framework_v2.indicator_research_worker", "--manifest",
                str(manifest_arg or manifest), "--output-dir", str(output_arg or output)]
        marker = {"pid": worker_pid, "ppid": worker_ppid, "executable": sys.executable,
                  "argv": args[2:], "orig_argv": [sys.executable, *args]}
        launch = {"pid": qprocess_pid, "program": sys.executable,
                  "python_worker_pid": worker_pid, "python_worker_ppid": worker_ppid,
                  "python_worker_executable": sys.executable,
                  "python_worker_argv": marker["orig_argv"],
                  "request": {"manifest": str(expected_manifest or manifest)},
                  "output_dir": str(expected_output or output)}
        return marker, launch

    def test_direct_qprocess_topology_binding_accepts_and_rejects_wrong_parent(self):
        with tempfile.TemporaryDirectory(prefix="indicator-direct-binding-") as tmp:
            marker, launch = self._synthetic_binding(Path(tmp), direct=True)
            self.assertTrue(_worker_is_bound_to_launch(marker, launch, os.getpid()))
            wrong_parent = {**marker, "ppid": launch["pid"]}
            wrong_parent_launch = {**launch, "python_worker_ppid": launch["pid"]}
            self.assertFalse(_worker_is_bound_to_launch(
                wrong_parent, wrong_parent_launch, os.getpid()))

    def test_redirector_qprocess_topology_binding_accepts_and_rejects_wrong_parent(self):
        with tempfile.TemporaryDirectory(prefix="indicator-redirector-binding-") as tmp:
            marker, launch = self._synthetic_binding(Path(tmp), direct=False)
            self.assertTrue(_worker_is_bound_to_launch(marker, launch, os.getpid()))
            wrong_parent = {**marker, "ppid": os.getpid()}
            wrong_parent_launch = {**launch, "python_worker_ppid": os.getpid()}
            self.assertFalse(_worker_is_bound_to_launch(
                wrong_parent, wrong_parent_launch, os.getpid()))

    def test_worker_args_bind_manifest_and_output_by_path_identity(self):
        with tempfile.TemporaryDirectory(prefix="indicator-qprocess-path-identity-") as tmp:
            root = Path(tmp)
            long_manifest = root / "manifest with spaces.json"
            long_output = root / "worker output"
            long_root = _long_windows_temp_path(root)
            if long_root and os.path.normcase(str(long_root)) != os.path.normcase(str(root)):
                short_root = _short_windows_path(long_root)
                self.assertTrue(short_root, "expected an available short-path spelling for the temp fixture")
                self.assertTrue(os.path.samefile(long_root, short_root))
                short_manifest = Path(short_root) / long_manifest.name
                short_output = Path(short_root) / long_output.name
                marker, launch = self._synthetic_binding(
                    root, direct=True, manifest_arg=short_manifest, output_arg=short_output,
                    expected_manifest=long_manifest, expected_output=long_output)
                self.assertNotEqual(os.path.normcase(short_manifest), os.path.normcase(long_manifest))
            else:
                marker, launch = self._synthetic_binding(root, direct=True)
            self.assertTrue(_worker_is_bound_to_launch(marker, launch, os.getpid()))
            wrong_manifest = list(marker["orig_argv"])
            wrong_manifest[wrong_manifest.index("--manifest") + 1] = str(root / "missing.json")
            wrong_manifest_launch = {**launch, "python_worker_argv": wrong_manifest}
            self.assertFalse(_worker_is_bound_to_launch(
                {**marker, "orig_argv": wrong_manifest}, wrong_manifest_launch, os.getpid()))
            wrong_output = list(marker["orig_argv"])
            wrong_output[wrong_output.index("--output-dir") + 1] = str(root / "different-output")
            wrong_output_launch = {**launch, "python_worker_argv": wrong_output}
            self.assertFalse(_worker_is_bound_to_launch(
                {**marker, "orig_argv": wrong_output}, wrong_output_launch, os.getpid()))

    @unittest.skipUnless(os.name == "nt", "isolated extension runtime is validated for win_amd64")
    def test_real_pandas_ta_qprocess_has_dual_guards_and_restarts_after_failure(self):
        import platform
        import sysconfig
        from framework_v2.research_runtime import resolve_extension_runtime

        project_root = Path(__file__).resolve().parents[2]
        runtime = resolve_extension_runtime(project_root, platform.python_version(), sysconfig.get_platform(),
                                            operation="indicator-pandas-ta")
        self.assertTrue(runtime["enabled"], runtime.get("reason"))
        self.assertEqual(runtime["versions"].get("pandas-ta"), "0.4.71b0")
        with _PreserveOnFailure() as tmp:
            evidence = Path(tmp)
            valid_manifest = self._fixture(evidence)
            # A second manifest has adjusted close but lacks normalized adjusted OHLC;
            # fail closed, retain the failed task receipt, then restart raw successfully.
            bad_root = evidence / "bad-adjusted"
            bad_root.mkdir()
            bad_manifest = self._fixture(bad_root, adjusted=False)
            page = json.loads((bad_root / "bars.json").read_text(encoding="utf-8"))
            for row in page:
                row["AdjC"] = float(row["Close"]) * 1.1
            page_bytes = json.dumps(page, separators=(",", ":")).encode("utf-8")
            (bad_root / "bars.json").write_bytes(page_bytes)
            data = json.loads(bad_manifest.read_text(encoding="utf-8"))
            data["pages"][0]["sha256"] = hashlib.sha256(page_bytes).hexdigest()
            bad_manifest.write_text(json.dumps(data), encoding="utf-8")

            guard_dir = evidence / "child_guard"
            guard_dir.mkdir()
            marker = evidence / "guard-marker.jsonl"
            guard_code = (
                "import json, os, socket, sys, urllib.request\n"
                f"sys.path.insert(0, {str(project_root)!r})\n"
                "def _blocked(*args, **kwargs): raise AssertionError('network or credential access denied by test guard')\n"
                "socket.socket.connect = _blocked\n"
                "socket.socket.connect_ex = _blocked\n"
                "socket.create_connection = _blocked\n"
                "urllib.request.urlopen = _blocked\n"
                "from framework_v2 import data_connection\n"
                "data_connection.load_api_key = _blocked\n"
                f"open({str(marker)!r}, 'a', encoding='utf-8').write(json.dumps({{'pid':os.getpid(),'ppid':os.getppid(),'executable':sys.executable,'argv':sys.argv,'orig_argv':getattr(sys,'orig_argv',[]),'network_guard':'ready','credential_guard':'ready'}})+'\\n')\n"
            )
            (guard_dir / "sitecustomize.py").write_text(guard_code, encoding="utf-8")
            panel = IndicatorResearchPanel(evidence / "workspace", language="zh_CN")
            panel.provider.setCurrentIndex(panel.provider.findData("pandas_ta"))
            panel.code.setText("4502")
            self.assertTrue(panel.set_manifest(bad_manifest))
            # Inject the guard as a resolver-approved extension overlay. The
            # production QProcess environment builder still applies its normal
            # allowlist; this does not mutate the parent process environment.
            guarded_runtime = {**runtime, "paths": [str(guard_dir), *runtime["paths"]]}
            with patch("framework_v2.indicator_panel.resolve_extension_runtime",
                       return_value=guarded_runtime):
                self.assertTrue(panel.run(), panel.status.text())
            self._wait(panel, expect="failed", timeout=45)
            first_job = panel._job_dir
            self.assertIsNotNone(first_job)
            failed_receipt = json.loads((first_job / "completion.json").read_text(encoding="utf-8"))
            self.assertNotEqual(failed_receipt["exit_code"], 0)
            self.assertIn("same-basis adjusted OHLC", failed_receipt["result"]["error"])
            self.assertTrue(panel.run_button.isEnabled(), "failed worker left the form disabled")
            self.assertTrue(panel.set_manifest(valid_manifest))
            panel.code.setText("4502")
            with patch("framework_v2.indicator_panel.resolve_extension_runtime",
                       return_value=guarded_runtime):
                self.assertTrue(panel.run(), panel.status.text())
            self.assertFalse(panel.set_manifest(bad_manifest), "running request must freeze its source")
            self.assertFalse(panel.browse.isEnabled())
            self._wait(panel, expect="completed", timeout=90)

            result = panel._last_payload["result"]
            artifact = json.loads(Path(panel._last_payload["artifact_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result.engine_name, "pandas-ta")
            self.assertEqual(result.price_field, "close")
            self.assertEqual(result.atr_price_field, "original raw OHLC")
            self.assertEqual(len(result.rows), 70)
            self.assertEqual(artifact["readiness"], "RESEARCH-ONLY")
            self.assertIs(artifact["pit_guarantee"], False)
            self.assertIn("not market data", artifact["source_identity"]["fixture_provenance"])
            self.assertIn("RMA/Wilder", artifact["engine"]["seed_semantics"]["rsi"])
            self.assertIn("original raw OHLC", artifact["engine"]["seed_semantics"]["atr"])
            self.assertIn("presma=True", artifact["engine"]["seed_semantics"]["atr"])
            self.assertIn("simple-average true-range seed", artifact["engine"]["seed_semantics"]["atr"])
            self.assertNotIn("without SMA seed", artifact["engine"]["seed_semantics"]["atr"])
            self.assertEqual(panel.chart.dates, [row["date"] for row in result.rows])
            self.assertEqual(panel.rsi_chart.dates, panel.chart.dates)
            self.assertEqual(panel.macd_chart.dates, panel.chart.dates)
            self.assertEqual(panel.atr_chart.dates, panel.chart.dates)
            self.assertIsNone(result.rows[0]["sma"])
            self.assertIsNone(result.rows[0]["rsi"])
            self.assertIsNone(result.rows[0]["atr"])
            self.assertTrue(all(value is None or math.isfinite(value)
                for row in result.rows for key, value in row.items()
                if key in {"close", "sma", "rsi", "macd", "macd_signal", "macd_histogram", "atr"}))

            job_dirs = sorted((panel.output_dir / "jobs").iterdir())
            self.assertEqual(len(job_dirs), 2)
            completed_job = Path(panel._last_payload["worker_log"]).parent
            launch = json.loads((completed_job / "launch.json").read_text(encoding="utf-8"))
            completion = json.loads((completed_job / "completion.json").read_text(encoding="utf-8"))
            self.assertTrue(launch["pid"])
            self.assertTrue(launch["python_worker_pid"])
            self.assertTrue(launch["request_sha256"])
            self.assertTrue(launch["process_started_at_utc"])
            self.assertEqual(completion["exit_code"], 0)
            self.assertTrue(completion["ended_at_utc"])
            self.assertEqual(completion["input_sha256"], result.input_sha256)
            self.assertTrue(completion["log_sha256"])
            self.assertTrue(marker.is_file(), "QProcess did not load the injected guard")
            markers = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(markers), 2, "each worker child must load the guard before it starts")
            worker_markers = [record for record in markers
                              if "framework_v2.indicator_research_worker" in record["orig_argv"]]
            self.assertEqual(len(worker_markers), 2)
            all_launches = [json.loads((job / "launch.json").read_text(encoding="utf-8")) for job in job_dirs]
            for worker_marker in worker_markers:
                self.assertEqual(worker_marker["network_guard"], "ready")
                self.assertEqual(worker_marker["credential_guard"], "ready")
                bound_launches = [item for item in all_launches
                                  if worker_marker["pid"] == item["python_worker_pid"]]
                self.assertEqual(len(bound_launches), 1,
                    f"worker PID must bind to exactly one owned QProcess receipt: {worker_marker}")
                self.assertTrue(_worker_is_bound_to_launch(worker_marker, bound_launches[0], os.getpid()),
                    f"worker marker, input/output paths or process topology do not bind to launch receipt: {worker_marker}")
            self.assertNotIn("token", (completed_job / "worker.log").read_text(encoding="utf-8").lower())
            panel.close(); self.app.processEvents()

    def _wait(self, panel, *, expect: str, timeout: float):
        deadline = time.monotonic() + timeout
        while panel._is_busy() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.025)
        self.app.processEvents()
        if panel._is_busy():
            panel.cancel_worker()
            cleanup_deadline = time.monotonic() + 5
            while panel._is_busy() and time.monotonic() < cleanup_deadline:
                self.app.processEvents(); time.sleep(.025)
            self.fail(f"indicator worker timed out; job={panel._job_dir}; log={panel._process_log}")
        self.assertEqual(panel._status_key, expect,
            f"status={panel.status.text()}, job={panel._job_dir}, log={panel._process_log}")


if __name__ == "__main__":
    unittest.main()
