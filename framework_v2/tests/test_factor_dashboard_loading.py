"""Dashboard navigation regressions, including the unchanged real GUI workflow."""
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from framework_v2.tests import test_factor_research_gui as original_tests
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from framework_v2.factor_research_panel import FactorResearchPanel
from framework_v2.tests.qt_widget_cleanup import dispose_closed_widget


class FactorDashboardLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_workflow_without_load_finished_slot(self):
        original_init = FactorResearchPanel.__init__

        def without_completion_slot(panel, *args, **kwargs):
            original_init(panel, *args, **kwargs)
            panel.view.loadFinished.disconnect(panel._load_finished)

        case_type = original_tests.FactorResearchGuiTests
        method = 'test_user_workbench_mounts_factor_panel_and_locale_switch_preserves_inputs'
        case = case_type(method)
        case_type.setUpClass()
        try:
            case.setUp()
            try:
                with patch.object(FactorResearchPanel, '__init__', without_completion_slot):
                    getattr(case, method)()
            finally:
                try:
                    case.tearDown()
                finally:
                    case.doCleanups()
        finally:
            try:
                case_type.tearDownClass()
            finally:
                case_type.doClassCleanups()

    @contextmanager
    def controlled_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel = FactorResearchPanel(root, language='en_US')
            callbacks = []
            current_url = [QUrl()]
            page = panel.view.page()
            try:
                with ExitStack() as stack:
                    stack.enter_context(patch.object(panel.view, 'load', side_effect=lambda url: current_url.__setitem__(0, QUrl(url))))
                    stack.enter_context(patch.object(panel.view, 'url', side_effect=lambda: QUrl(current_url[0])))
                    stack.enter_context(patch.object(page, 'isLoading', return_value=False))
                    stack.enter_context(patch.object(page, 'runJavaScript', side_effect=lambda script, callback: callbacks.append(callback)))
                    panel.dashboard_paths = {lang: str(root / (lang + '.html')) for lang in ('en_US', 'ja_JP')}
                    yield panel, callbacks, current_url, root
            finally:
                panel.close()
                dispose_closed_widget(panel)

    @staticmethod
    def document(url, language='en_US', plots=6, ready='object'):
        return json.dumps(dict(url=url.toString(), language=language, plots=plots, ready=ready))

    def test_old_navigation_callback_cannot_ready_new_language(self):
        with self.controlled_panel() as (panel, callbacks, current_url, root):
            panel._load_dashboard('en_US')
            panel._poll_dom()
            old_callback, old_url = callbacks[-1], QUrl(current_url[0])
            panel.set_language('ja_JP')
            panel._load_dashboard('ja_JP')
            panel._poll_dom()
            # Even a forged current-document result cannot rescue a stale generation.
            old_callback(self.document(current_url[0], 'ja_JP'))
            self.assertFalse(panel._dashboard_ready)
            callbacks[-1](self.document(old_url, 'en_US'))
            self.assertFalse(panel._dashboard_ready)
            callbacks[-1](self.document(current_url[0], 'ja_JP'))
            self.assertTrue(panel._dashboard_ready)

    def test_clear_manifest_invalidates_pending_dom_callback(self):
        with self.controlled_panel() as (panel, callbacks, current_url, root):
            manifest = root / 'manifest.json'
            manifest.write_text('{}', encoding='utf-8')
            panel.set_manifest(manifest)
            panel.dashboard_paths = {'en_US': str(root / 'en_US.html')}
            panel._load_dashboard('en_US')
            panel._poll_dom()
            callback, url = callbacks[-1], QUrl(current_url[0])
            panel.clear_manifest()
            callback(self.document(url))
            self.assertFalse(panel._dashboard_ready)
            self.assertFalse(panel._dom_timer.isActive())
            self.assertIsNone(panel.manifest_path)

    def test_document_identity_six_charts_and_polling_budget(self):
        with self.controlled_panel() as (panel, callbacks, current_url, root):
            panel._load_dashboard('en_US')
            self.assertEqual(panel._dom_timer.interval(), 250)
            self.assertTrue(panel._dom_timer.isActive())
            expected_url = QUrl(current_url[0])
            with patch.object(panel.view.page(), 'isLoading', return_value=True):
                panel._poll_dom()
                panel._load_finished(False)
                self.assertEqual(callbacks, [])
                self.assertEqual(panel._dom_attempts, 0)
                self.assertTrue(panel._dom_timer.isActive())
            current_url[0] = QUrl.fromLocalFile(str(root / 'other.html'))
            panel._poll_dom()
            self.assertEqual(callbacks, [])
            self.assertEqual(panel._dom_attempts, 0)
            current_url[0] = expected_url
            panel._poll_dom()
            callback, url = callbacks[-1], QUrl(current_url[0])
            for result in (self.document(QUrl.fromLocalFile(str(root / 'other.html'))),
                           self.document(url, 'ja_JP'), self.document(url, plots=5),
                           self.document(url, ready='undefined')):
                callback(result)
                self.assertFalse(panel._dashboard_ready)
            current_url[0] = QUrl.fromLocalFile(str(root / 'other.html'))
            callback(self.document(url))
            self.assertFalse(panel._dashboard_ready)
            current_url[0] = url
            callback(self.document(url))
            self.assertTrue(panel._dashboard_ready)
            panel._load_dashboard('en_US')
            for _ in range(40):
                panel._poll_dom()
                panel._load_finished(True)
            self.assertEqual(panel._dom_attempts, 40)
            self.assertTrue(panel._dom_timer.isActive())
            panel._poll_dom()
            self.assertEqual(panel._dom_attempts, 41)
            self.assertFalse(panel._dom_timer.isActive())
            self.assertIn('charts are unavailable', panel.status.text())
            self.assertIn('Chart DOM did not become ready', panel.status.text())
