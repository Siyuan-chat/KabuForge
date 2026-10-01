import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
from framework_v2.agent import AgentCommandService, AgentResourceService
from framework_v2.agent.mcp import MCPAdapter


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = AgentCommandService(self.root)

    def tearDown(self): self.temp.cleanup()

    def test_default_tools_no_external_or_paper(self):
        names = {x['name'] for x in self.service.tool_catalog()}
        self.assertNotIn('start_paper_simulation',names)
        self.assertNotIn('submit_order',names)
        self.assertTrue(self.service.call('get_capabilities')['ok'])
        self.assertFalse(self.service.call('start_paper_simulation',{})['ok'])

    def test_path_and_schema_rejected_without_secret_echo(self):
        for path in ('../secret.json','C:/secret.json','secrets/key.json'):
            result = self.service.call('inspect_snapshot',{'path':path})
            self.assertFalse(result['ok']); self.assertNotIn(path,json.dumps(result))
        result = self.service.call('get_capabilities',{'token':'do-not-echo'})
        self.assertFalse(result['ok']); self.assertNotIn('do-not-echo',json.dumps(result))

    def test_idempotency_persistent_conflict(self):
        service = AgentCommandService(self.root,enable_paper=True)
        args = {'name':'sample'}
        first = service.call('create_workspace',args,agent_call_id='one',idempotency_key='key')
        self.assertTrue(first['ok'],first)
        reopened = AgentCommandService(self.root,enable_paper=True)
        self.assertEqual(first,reopened.call('create_workspace',args,agent_call_id='two',idempotency_key='key'))
        self.assertFalse(reopened.call('create_workspace',{'name':'different'},agent_call_id='three',idempotency_key='key')['ok'])
        with reopened._db() as db:
            row = db.execute('SELECT result_hash,run_id FROM calls WHERE call_id="one"').fetchone()
        self.assertEqual(len(row[0]),64); self.assertTrue(row[1])

    def test_no_network_demo_and_application_parity(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
            result = self.service.call('run_demo')
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['result']['mode_intent_parity'])
        run_id = result['result']['run_id']
        report = self.service.call('get_run_report',{'run_id':run_id})
        self.assertTrue(report['ok'])
        factor = next(iter(report['result']['report']['factors']))
        diagnostics = self.service.call('analyze_factor',{'run_id':run_id,'factor_id':factor})
        self.assertTrue(diagnostics['ok'],diagnostics)
        self.assertGreater(diagnostics['result']['valid'],0)

    def test_mcp_schema_resources_and_notifications(self):
        adapter = MCPAdapter(self.service)
        self.assertIsNone(adapter.request({'jsonrpc':'2.0','method':'notifications/initialized'}))
        result = adapter.request({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        for tool in result['result']['tools']:
            from jsonschema import Draft202012Validator
            Draft202012Validator.check_schema(tool['inputSchema'])
        resource = AgentResourceService(self.service).read('kabuforge://schemas/run')
        self.assertEqual(resource['type'],'object')

    def test_graph_escape_before_application_read(self):
        (self.root/'run.json').write_text(json.dumps({'kind':'run','strategy':'../outside.json','mode':'backtest'}))
        with patch.object(self.service.application,'validate',side_effect=AssertionError('must not reach application')):
            self.assertFalse(self.service.call('validate_config',{'path':'run.json'})['ok'])

    def test_external_extension_discoverable_but_disabled(self):
        adapter = MCPAdapter(self.service,expose_reserved_external=True)
        response = adapter.request({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        names = {tool['name'] for tool in response['result']['tools']}
        self.assertTrue({'submit_order','cancel_order','request_order_approval'} <= names)
        response = adapter.request({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'submit_order','arguments':{}}})
        self.assertTrue(response['result']['isError'])

    def test_backtest_job_and_read_only_journal(self):
        from framework_v2.demo import create_demo
        create_demo(self.root/'demo')
        result = self.service.call('start_backtest',{'path':'demo/backtest.json','timeline':'demo/timeline.json'})
        self.assertTrue(result['ok'],result)
        job_id = result['result']['job_id']
        deadline = time.monotonic()+60
        while time.monotonic()<deadline:
            job = self.service.call('get_job_status',{'job_id':job_id})['result']
            if job['state'] not in {'QUEUED','RUNNING'}: break
            time.sleep(0.05)
        self.assertEqual(job['state'],'SUCCEEDED',job)
        run_id = job['run_id']
        self.assertTrue(self.service.call('list_fills',{'run_id':run_id})['ok'])
        self.assertTrue(self.service.call('get_job_result',{'job_id':job_id})['ok'])
        factor = next(iter(self.service.call('get_run_report',{'run_id':run_id})['result']['report']['decisions'][0]['factors']))
        self.assertTrue(self.service.call('analyze_factor',{'run_id':run_id,'factor_id':factor})['ok'])

    def test_interrupted_job_fails_closed_after_restart(self):
        job = {'job_id':'f'*32,'state':'RUNNING'}
        self.service._persist_job(job)
        recovered = AgentCommandService(self.root)
        result = recovered.call('get_job_status',{'job_id':'f'*32})['result']
        self.assertEqual(result['state'],'FAILED')
        self.assertEqual(result['error_code'],'KF_JOB_INTERRUPTED')

    def test_second_service_does_not_interrupt_active_job_and_can_cancel(self):
        from framework_v2.demo import create_demo
        import threading
        create_demo(self.root/'demo')
        started = threading.Event(); finished = threading.Event()
        def slow_history(*args, cancel_check, **kwargs):
            started.set()
            try:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    if cancel_check(): raise InterruptedError()
                    time.sleep(.01)
                raise AssertionError('cancel was not observed')
            finally: finished.set()
        with patch('framework_v2.history.run_history',side_effect=slow_history):
            response = self.service.call('start_backtest',{'path':'demo/backtest.json','timeline':'demo/timeline.json'})
            self.assertTrue(response['ok'],response)
            self.assertTrue(started.wait(5))
            other = AgentCommandService(self.root)
            job_id=response['result']['job_id']
            self.assertEqual(other.call('get_job_status',{'job_id':job_id})['result']['state'],'RUNNING')
            stopped=other.call('cancel_job',{'job_id':job_id})
            self.assertEqual(stopped['result']['run_id'],response['result']['run_id'])
            self.assertTrue(finished.wait(5))
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                status=other.call('get_job_status',{'job_id':job_id})['result']['state']
                if status=='CANCELED': break
                time.sleep(.01)
            self.assertEqual(status,'CANCELED')


if __name__ == '__main__': unittest.main()
