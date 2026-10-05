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
                self.assertTrue(any(
                    worker_marker["pid"] == item["python_worker_pid"] and
                    worker_marker["ppid"] == item["pid"] for item in all_launches),
                    f"worker guard marker is not bound to an owned QProcess: {worker_marker}")
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
