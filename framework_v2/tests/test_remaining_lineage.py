"""Remaining adapter receipts exercised through their existing real fixtures."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from framework_v2.demo import create_demo
from framework_v2.cli import main


class RemainingLineageTests(unittest.TestCase):
    def test_legacy_demo_plan_and_simulate_have_distinct_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); demo=root/'demo'
            with redirect_stdout(io.StringIO()): main(['demo','--out',str(demo)])
            self.assertEqual(json.loads((demo/'task_lineage.json').read_text())['operation'],'demo')
            for op in ('plan','simulate'):
                output=root/(op+'.json')
                argv=[op,str(demo/'fake.json'),'--execution',str(demo/'execution.json'),
                    '--decision-at','2024-05-01T09:00:00+09:00','--now','2024-05-01T09:00:00+09:00',
                    '--out',str(output)]
                if op=='simulate': argv.extend(['--journal',str(root/'journal.sqlite')])
                with redirect_stdout(io.StringIO()): main(argv)
                lineage=json.loads((root/(output.name+'.task_lineage.json')).read_text())
                self.assertEqual(lineage['operation'],op)
                self.assertEqual(lineage['input_sha256'],hashlib.sha256((root/lineage['request_ref']).read_bytes()).hexdigest())
                self.assertTrue(output.is_file())

    def test_legacy_history_cli_retains_stdout_and_records_entry_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); demo=create_demo(root/'demo'); out=root/'history'
            stdout=io.StringIO()
            with redirect_stdout(stdout):
                main(['history',str(demo/'backtest.json'),'--timeline',str(demo/'timeline.json'),'--out',str(out)])
            value=json.loads(stdout.getvalue())
            self.assertEqual(set(value), {'output','decisions','nav_rows','external_submission'})
            self.assertFalse(value['external_submission'])
            report=json.loads((out/'report.json').read_text())
            self.assertEqual(value['decisions'],len(report['decisions']))
            self.assertEqual(value['nav_rows'],len(report['nav']))
            self.assertGreater(value['nav_rows'],0)
            lineage=json.loads((out/'task_lineage.json').read_text())
            self.assertEqual(lineage['execution_host'],'framework_v2.cli')
            self.assertEqual(lineage['input_identity_kind'],'explicit_entry_files')
            inputs=json.loads((out/'lineage_inputs.json').read_text())
            self.assertEqual(inputs['run']['sha256'],hashlib.sha256((demo/'backtest.json').read_bytes()).hexdigest())
            self.assertEqual(inputs['timeline']['sha256'],hashlib.sha256((demo/'timeline.json').read_bytes()).hexdigest())

    def _panel_receipt(self, case_class, method, host):
        from framework_v2 import task_lineage
        from framework_v2.historical_paper_panel import HistoricalPaperPanel
        captures=[]
        original=task_lineage.write_lineage
        paper_original=HistoricalPaperPanel._write_operation
        def record(directory,value):
            request=Path(directory)/value['request_ref']
            self.assertTrue(request.is_file())
            if value['input_identity_kind']=='request_bytes':
                self.assertEqual(value['input_sha256'],hashlib.sha256(request.read_bytes()).hexdigest())
            elif value['input_identity_kind']=='canonical_embedded_request':
                embedded=json.loads(request.read_text())['request']
                raw=json.dumps(embedded,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
                self.assertEqual(value['input_sha256'],hashlib.sha256(raw).hexdigest())
            captures.append(value)
        def write(directory,**kwargs):
            value=original(directory,**kwargs); record(directory,value); return value
        def paper_write(panel,name,value):
            paper_original(panel,name,value)
            if name=='task_lineage.json': record(panel._operation_dir,value)
        case_class.setUpClass()
        case=case_class(method); case.setUp()
        try:
            with patch.object(task_lineage,'write_lineage',write), patch.object(HistoricalPaperPanel,'_write_operation',paper_write):
                getattr(case,method)()
            selected=[v for v in captures if v['execution_host']==host]
            self.assertTrue(selected, host+' did not record lineage')
            for value in selected:
                self.assertEqual(value['schema'],'kabuforge.task_lineage.v1')
                self.assertTrue(value['task_id'])
                self.assertTrue(value['input_sha256'])
        finally:
            case.tearDown()

    def test_historical_paper_panel_lineage_with_real_replay(self):
        from framework_v2.tests.test_paper_broker_gui import PaperBrokerGuiTests
        self._panel_receipt(PaperBrokerGuiTests,
            'test_historical_panel_creates_steps_queries_reopens_and_completes','HistoricalPaperPanel')

    def test_sensitivity_panel_lineage_with_real_three_case_worker(self):
        from framework_v2.tests.test_price_sensitivity_gui import PriceSensitivityGuiTests
        self._panel_receipt(PriceSensitivityGuiTests,
            'test_explicit_source_locale_and_actual_three_case_worker','PriceSensitivityPanel')

    def test_indicator_panel_lineage_with_existing_runtime_guards(self):
        from framework_v2.tests.test_indicator_panel import IndicatorPanelTests
        self._panel_receipt(IndicatorPanelTests,
            'test_real_pandas_ta_qprocess_has_dual_guards_and_restarts_after_failure','IndicatorPanel')


if __name__ == '__main__': unittest.main()
