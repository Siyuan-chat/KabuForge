"""J-Quants connector tests never use a real API key or network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from framework_v2 import data_connection as dc


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payloads.pop(0))


def _bar(day, close):
    return {"Date": day, "Code": "72030", "O": close - 1, "H": close + 1,
            "L": close - 2, "C": close, "Vo": 100, "AdjC": close}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_connection_is_read_only_and_uses_header(self):
        session = _Session([{"data": []}])
        self.assertTrue(dc.test_connection("example-secret", session=session))
        self.assertEqual(session.calls[0][0], dc.BASE_URL + "/equities/master")
        self.assertEqual(session.calls[0][1]["headers"], {"x-api-key": "example-secret"})
        self.assertFalse(list(self.workspace.iterdir()))

    def test_cancel_then_resume_pages_and_integrity(self):
        stop = threading.Event()
        first = _Session([{"data": [_bar("2024-01-04", 10)], "pagination_key": "next-page"}])
        def cancel_after_first(_event):
            stop.set()
        with self.assertRaises(dc.DownloadCancelled):
            dc.download_bars(self.workspace, "example-secret", ["72030"], "2024-01-01", "2024-01-31",
                             session=first, cancel_event=stop, progress=cancel_after_first)
        path = next(self.workspace.glob("jquants_downloads/*/manifest.json"))
        partial = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(partial["status"], "cancelled")
        self.assertEqual(partial["next_pagination_key"]["72030"], "next-page")
        self.assertNotIn("example-secret", path.read_text(encoding="utf-8"))
        second = _Session([{"data": [_bar("2024-01-05", 12)]}])
        self.assertTrue(dc.download_bars(self.workspace, "example-secret", ["72030"], "2024-01-01", "2024-01-31", session=second).samefile(path))
        self.assertEqual(second.calls[0][1]["params"]["pagination_key"], "next-page")
        self.assertEqual([row["close"] for row in dc.load_bars(path)], [10.0, 12.0])
        self.assertFalse(any("available_at" in row for row in dc.load_bars(path)))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pit_guarantee"], False)
        self.assertTrue(dc.download_bars(self.workspace, "example-secret", ["72030"], "2024-01-01", "2024-01-31", session=_Session([])).samefile(path))
        page = next(path.parent.glob("pages/*.json"))
        page.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            dc.load_bars(path)

    def test_rejects_invalid_request_without_network(self):
        session = _Session([])
        with self.assertRaises(ValueError):
            dc.download_bars(self.workspace, "secret", ["7203;evil"], "2024-01-01", "2024-01-31", session=session)
        with self.assertRaises(ValueError):
            dc.download_bars(self.workspace, "secret", ["7203"], "2024-02-01", "2024-01-31", session=session)
        self.assertEqual(session.calls, [])

    def test_resume_rejects_tampered_page_before_network(self):
        stop = threading.Event()
        first = _Session([{"data": [_bar("2024-01-04", 10)], "pagination_key": "p1"}])
        with self.assertRaises(dc.DownloadCancelled):
            dc.download_bars(self.workspace, "secret", ["72030"], "2024-01-01", "2024-01-31",
                             session=first, cancel_event=stop, progress=lambda _: stop.set())
        page = next(self.workspace.glob("jquants_downloads/*/pages/*.json"))
        page.write_text("[]", encoding="utf-8")
        second = _Session([])
        with self.assertRaisesRegex(ValueError, "integrity"):
            dc.download_bars(self.workspace, "secret", ["72030"], "2024-01-01", "2024-01-31", session=second)
        self.assertEqual(second.calls, [])

    def test_rejects_cursor_cycle_and_empty_coverage(self):
        session = _Session([{"data": [_bar("2024-01-04", 10)], "pagination_key": "p1"},
                            {"data": [_bar("2024-01-05", 12)], "pagination_key": "p2"},
                            {"data": [_bar("2024-01-08", 13)], "pagination_key": "p1"}])
        with self.assertRaisesRegex(RuntimeError, "repeated a pagination key"):
            dc.download_bars(self.workspace, "secret", ["72030"], "2024-01-01", "2024-01-31", session=session)
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaisesRegex(RuntimeError, "No daily bars"):
                dc.download_bars(other, "secret", ["72030"], "2024-01-01", "2024-01-31", session=_Session([{"data": []}]))

    def test_single_writer(self):
        root = self.workspace / "same-request"
        with dc._single_writer(root):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with dc._single_writer(root):
                    pass


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    from framework_v2.data_connection_qt import DataConnectionPanel
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 unavailable")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        mock=patch.object(dc,"load_api_key",return_value=None)
        mock.start(); self.addCleanup(mock.stop)

    def test_initialization_and_language_do_not_connect(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(dc, "test_connection") as connect, patch.object(dc, "download_bars") as download:
            panel = DataConnectionPanel(folder)
            panel.set_language("ja_JP")
            self.assertIn("日足", panel.disclaimer_label.text())
            panel.set_language("en_US")
            self.assertIn("local research", panel.disclaimer_label.text())
            self.assertEqual(panel.api_key.echoMode(), panel.api_key.EchoMode.Password)
            panel.show_key.setChecked(True)
            self.assertEqual(panel.api_key.echoMode(), panel.api_key.EchoMode.Normal)
            connect.assert_not_called()
            download.assert_not_called()
            panel.close()

    def test_forget_uses_credential_manager_api(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(dc, "delete_api_key") as delete:
            panel = DataConnectionPanel(folder)
            panel.api_key.setText("example-secret")
            panel.remember.setChecked(True)
            panel.forget_button.click()
            delete.assert_called_once()
            self.assertEqual(panel.api_key.text(), "")
            self.assertFalse(panel.remember.isChecked())
            panel.close()

    def test_download_signal_and_busy_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            expected = str(Path(folder) / "manifest.json")
            with patch.object(dc, "download_bars", return_value=Path(expected)) as download:
                panel = DataConnectionPanel(folder)
                panel.api_key.setText("example-secret")
                panel.codes.setText("7203")
                received = []
                panel.downloaded.connect(received.append)
                panel.download_button.click()
                self.assertTrue(panel.busy)
                deadline = time.monotonic() + 5
                while panel.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.app.processEvents()
                self.assertFalse(panel.busy)
                self.assertEqual(received, [expected])
                download.assert_called_once()
                panel.close()


if __name__ == "__main__":
    unittest.main()
