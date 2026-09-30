"""Qt integration tests use only temporary synthetic inputs and owned workers."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import importlib.util
if importlib.util.find_spec('PySide6') is None:
    raise unittest.SkipTest('GUI tests require framework_v2/requirements-gui.txt')
from PySide6.QtCore import QTimer
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from framework_v2.demo import create_demo
from framework_v2.cli import plan_file
from framework_v2.workbench_qt import WorkbenchWindow


class QtTests(unittest.TestCase):
    def test_report_reader_verifies_binary_snapshots_without_json_decoding(self):
        import hashlib
        inputs=self.root/'job'/'inputs'; inputs.mkdir(parents=True)
        binary=inputs/'prices.parquet'; binary.write_bytes(b'PAR1-binary-test-fixture')
        manifest={'copied_hashes':{str(binary):hashlib.sha256(binary.read_bytes()).hexdigest()}}
        (inputs/'workbench_snapshot.json').write_text(json.dumps(manifest))
        report=self.root/'job'/'report.json'; report.write_text(json.dumps({'decisions':[],'nav':[]}))
        self.assertEqual(self.window._read_report(report)['workbench_configs'],{})
        binary.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.window._read_report(report)

    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.demo=create_demo(self.root/'demo')
        self.window=WorkbenchWindow(self.root/'ui'); self.window.show()
        self.assertTrue(self.window.load_document(self.demo/'backtest.json'))
        self.app.processEvents()

    def tearDown(self):
        if self.window.jobs.busy:
            self.window.jobs.cancel(); self.wait_job()
        self.window.document.load(self.demo/'backtest.json')
        self.window.json_invalid=False; self.window.form_errors={}
        self.window.close(); self.app.processEvents(); self.temp.cleanup()

    def wait_job(self):
        deadline=time.monotonic()+90
        while self.window.jobs.busy and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.005)
        self.assertFalse(self.window.jobs.busy,'worker timeout')
        self.app.processEvents()
        return self.window.jobs.jobs[-1]

    def preflight(self):
        self.assertTrue(self.window.start_action('preflight'))
        job=self.wait_job(); self.assertEqual(job['status'],'COMPLETED',job.get('error'))

    def test_edit_roundtrip_unsaved_and_invalidates(self):
        self.preflight()
        edit=self.window.fields['fees.commission_rate']; edit.setText('0.002')
        edit.editingFinished.emit()
        self.assertEqual(json.loads(self.window.json_edit.toPlainText())['fees']['commission_rate'],.002)
        self.assertTrue(self.window.document.dirty); self.assertIsNone(self.window.preflight_result)
        self.assertFalse(self.window.history_button.isEnabled())
        self.assertFalse(self.window.load_document(self.demo/'paper.json',choice='cancel'))
        self.assertEqual(self.window.run_path,self.demo/'backtest.json')
        self.window.json_edit.setPlainText('{')
        self.assertTrue(self.window.json_invalid); self.assertFalse(self.window.form_widget.isEnabled())
        self.assertTrue(self.window.load_document(self.demo/'paper.json',choice='discard'))
        self.assertFalse(self.window.document.dirty)
        self.assertEqual(self.window.mode.currentData(),'paper')

    def test_process_responsive_lock_duplicate_and_cli_equal(self):
        ticks=[]; timer=QTimer(); timer.setInterval(5); timer.timeout.connect(lambda:ticks.append(1)); timer.start()
        self.preflight()
        self.assertTrue(self.window.start_action('plan'))
        self.assertFalse(self.window.start_action('plan'))
        self.assertFalse(self.window.mode.isEnabled()); self.assertFalse(self.window.editor_tabs.isEnabled())
        job=self.wait_job(); timer.stop()
        self.assertEqual(job['status'],'COMPLETED',job.get('error')); self.assertGreater(len(ticks),3)
        actual=json.loads(Path(job['result']['result']['report']).read_text(encoding='utf-8'))
        expected=plan_file(self.demo/'backtest.json',self.demo/'execution.json',self.window.decision_at.text(),self.window.now.text())
        for key in ('strategy_hash','decision','risk','plan'):
            self.assertEqual(actual.get(key),expected.get(key),key)
        self.assertTrue(self.window.mode.isEnabled())
        self.window.mode.setCurrentIndex(self.window.mode.findData('paper'))
        self.assertIsNone(self.window.preflight_result)
        self.assertFalse(self.window.jobs.busy)

    def test_history_render_and_unknown_gate(self):
        self.preflight(); self.assertTrue(self.window.start_action('history'))
        job=self.wait_job(); self.assertEqual(job['status'],'COMPLETED',job.get('error'))
        self.assertIsNotNone(self.window.report)
        self.assertGreater(len(self.window.report['nav']),0)
        self.assertGreater(len(self.window.target_table.rows),0)
        self.window.show_journal({'accounts':[],'positions':[],'orders':[{'status':'UNKNOWN'}],
            'events':[],'fills':[],'blockers':[{'reason':'do not resend'}]})
        self.assertTrue(self.window.paper_blocked); self.assertFalse(self.window.simulate_button.isEnabled())
        self.assertFalse(self.window.recovery_button.isEnabled())
        self.assertFalse(self.window.grab().isNull())

    def test_failed_and_cancel_are_truthful(self):
        self.window.jobs.start({'action':'journal','journal_path':str(self.root/'absent.sqlite')})
        job=self.wait_job(); self.assertEqual(job['status'],'FAILED'); self.assertNotEqual(job['exit_code'],0)
        self.assertFalse((self.root/'absent.sqlite').exists())
        self.window.jobs.start({'action':'demo'})
        process=self.window.jobs.process
        deadline=time.monotonic()+5
        while not self.window.jobs.current.get('pid') and time.monotonic()<deadline: self.app.processEvents()
        self.assertTrue(self.window.jobs.cancel()); job=self.wait_job()
        self.assertEqual(job['status'],'CANCELED'); self.assertIsNone(self.window.jobs.process)
        self.window.jobs._kill_owned(process)  # stale ownership cannot affect another process

    def test_table_filter_numeric_sort_copy_export_and_font(self):
        self.assertTrue(QFontDatabase.families())
        table=self.window.trades_table
        table.set_rows([{'code':'A','quantity':100},{'code':'B','quantity':20}])
        table.proxy.sort(1,Qt.SortOrder.AscendingOrder)
        self.assertEqual(table.visible_rows()[0],['B','20'])
        table.search.setText('A'); self.assertEqual(table.proxy.rowCount(),1)
        table.view.selectRow(0); table.copy_selected()
        self.assertEqual(self.app.clipboard().text(),'A\t100')
        path=self.root/'table.csv'
        with patch('framework_v2.workbench_widgets.QFileDialog.getSaveFileName',return_value=(str(path),'CSV')):
            table.export_csv()
        self.assertIn('A,100',path.read_text(encoding='utf-8-sig'))
        table.view.setColumnWidth(0,215); table.persist(); table.set_rows([{'code':'A','quantity':1}])
        self.assertEqual(table.view.columnWidth(0),215)

    def test_legacy_block_and_saved_button_dispatch(self):
        old=self.root/'legacy.json'; old.write_text('{"legacy":true}')
        self.assertTrue(self.window.load_document(old))
        self.assertIsNone(self.window.run_path); self.assertFalse(self.window.preflight_button.isEnabled())
        self.assertIn('显式转换',self.window.issues.toPlainText())
        self.window.load_document(self.demo/'backtest.json')
        dest=self.demo/'copy.json'
        with patch('framework_v2.workbench_qt.QFileDialog.getSaveFileName',return_value=(str(dest),'JSON')):
            self.window.save_button.click()
        self.assertTrue(dest.is_file())


if __name__=='__main__': unittest.main()
