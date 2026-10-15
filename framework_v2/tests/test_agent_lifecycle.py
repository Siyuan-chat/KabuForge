"""Owned shutdown, real stdio EOF and additive task lineage regressions."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from framework_v2.agent.core import AgentCommandService
from framework_v2.demo import create_demo


class AgentLifecycleTests(unittest.TestCase):
    def test_shutdown_does_not_cancel_another_service_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_demo(root / 'demo')
            owner = AgentCommandService(root)
            began = threading.Event()

            def history(*args, cancel_check, **kwargs):
                began.set()
                while not cancel_check():
                    threading.Event().wait(.01)
                raise InterruptedError()

            with patch('framework_v2.history.run_history', history):
                response = owner.call('start_backtest', {'path': 'demo/backtest.json', 'timeline': 'demo/timeline.json'})
                self.assertTrue(response['ok'], response)
                job_id = response['result']['job_id']
                try:
                    self.assertTrue(began.wait(5))
                    other = AgentCommandService(root)
                    other.shutdown()
                    self.assertFalse(owner.cancellations[job_id].is_set())
                finally:
                    owner.shutdown()
                self.assertEqual(owner.jobs[job_id]['state'], 'CANCELED')
                self.assertFalse(owner._threads[job_id].is_alive())
                lineage = json.loads((owner._run(response['result']['run_id'])/'task_lineage.json').read_text())
                self.assertEqual(lineage['task_id'], job_id)
                self.assertEqual(lineage['run_id'], response['result']['run_id'])
                owner.shutdown()
                self.assertFalse(owner.call('start_backtest', {'path': 'demo/backtest.json', 'timeline': 'demo/timeline.json'})['ok'])

    def test_explicit_cancel_after_compute_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_demo(root / 'demo')
            service = AgentCommandService(root)
            began, release = threading.Event(), threading.Event()

            def history(*args, **kwargs):
                began.set()
                if not release.wait(5):
                    raise RuntimeError('test worker not released')
                return {'decisions': []}

            with patch('framework_v2.history.run_history', history):
                response = service.call('start_backtest', {'path': 'demo/backtest.json', 'timeline': 'demo/timeline.json'})
                self.assertTrue(response['ok'], response)
                job_id = response['result']['job_id']
                try:
                    self.assertTrue(began.wait(5))
                    canceled = service.call('cancel_job', {'job_id': job_id})
                    self.assertTrue(canceled['result']['cancel_requested'])
                finally:
                    release.set()
                    service._threads[job_id].join(10)
                    service.shutdown()
                self.assertEqual(service.jobs[job_id]['state'], 'CANCELED')
                self.assertFalse((service._run(response['result']['run_id'])/'report.json').exists())

    def test_research_task_link_is_durable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            service = AgentCommandService(temp)
            task = Path(temp) / 'research-tasks/task'; task.mkdir(parents=True)
            result = {'task_id': 'task', 'task_dir': str(task), 'status': 'PARTIAL'}
            with patch.object(service, '_dispatch', return_value=result) as dispatch:
                first = service.call('run_demo', agent_call_id='call', idempotency_key='key')
                self.assertTrue(first['ok'], first)
                reopened = AgentCommandService(temp)
                self.assertEqual(first, reopened.call('run_demo', agent_call_id='retry', idempotency_key='key'))
                self.assertEqual(dispatch.call_count, 1)
            with closing(sqlite3.connect(service.db_path)) as db:
                row = db.execute('SELECT call_id,task_id,task_dir FROM call_task_links').fetchone()
                self.assertEqual(row, ('call', 'task', str(Path('research-tasks/task'))))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM call_task_links').fetchone()[0], 1)

    def test_success_before_cancel_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); create_demo(root/'demo')
            service = AgentCommandService(root)
            with patch('framework_v2.history.run_history', return_value={'decisions': []}):
                response = service.call('start_backtest', {'path':'demo/backtest.json','timeline':'demo/timeline.json'})
                self.assertTrue(response['ok'], response)
                job_id = response['result']['job_id']
                service._threads[job_id].join(10)
                self.assertFalse(service._threads[job_id].is_alive())
                canceled = service.call('cancel_job', {'job_id':job_id})
                self.assertFalse(canceled['result']['cancel_requested'])
                service.shutdown()
                self.assertEqual(service.jobs[job_id]['state'], 'SUCCEEDED')
                self.assertEqual(json.loads((service._run(response['result']['run_id'])/'report.json').read_text()), {'decisions': []})

    def test_real_stdio_eof_cancels_and_persists_owned_job(self):
        with tempfile.TemporaryDirectory() as temp:
            script = '''
import sys,time
from pathlib import Path
from unittest.mock import patch
from framework_v2.demo import create_demo
from framework_v2.agent.mcp import main
root=Path(sys.argv[1]); create_demo(root/'demo')
def history(*args,cancel_check,**kwargs):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if cancel_check(): raise InterruptedError()
        time.sleep(.01)
    raise RuntimeError('EOF did not cancel')
with patch('framework_v2.history.run_history',history):
    main(['--workspace',str(root)])
'''
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'start_backtest', 'arguments': {'path': 'demo/backtest.json', 'timeline': 'demo/timeline.json'}}}
            project = Path(__file__).resolve().parents[2]
            env = os.environ.copy(); env['PYTHONPATH'] = str(project)
            with subprocess.Popen([sys.executable, '-B', '-c', script, temp], cwd=project,
                                  env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8') as process:
                try:
                    stdout, stderr = process.communicate(json.dumps(request) + '\n', timeout=25)
                except subprocess.TimeoutExpired:
                    process.kill(); process.communicate(); raise
                self.assertEqual(process.returncode, 0, stderr)
            response = json.loads(stdout)
            value = json.loads(response['result']['content'][0]['text'])
            self.assertTrue(value['ok'], value)
            job = json.loads(next((Path(temp) / 'agent_jobs').glob('*.json')).read_text())
            self.assertEqual(job['state'], 'CANCELED')
            self.assertIsNotNone(job['finished_at'])
            with closing(sqlite3.connect(Path(temp) / 'agent_audit.sqlite')) as db:
                self.assertEqual(db.execute('SELECT job_id,run_id FROM call_task_links').fetchone(),
                                 (job['job_id'], job['run_id']))

    def test_research_and_gui_lineage_preserve_original_requests(self):
        from framework_v2.research_application import ResearchApplicationService
        from framework_v2.workbench_jobs import JobController
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_id, folder = ResearchApplicationService(root)._new_task('factor_diagnostics', {'fixture': True})
            lineage = json.loads((folder/'task_lineage.json').read_text())
            self.assertEqual(lineage['task_id'], task_id)
            self.assertEqual(lineage['request_ref'], 'application_request.json')
            self.assertEqual(json.loads((folder/'application_request.json').read_text())['request'], {'fixture': True})
            # Do not launch a worker: inspect the owned pre-start artifacts.
            class Process:
                def start(self, *args): pass
            controller = JobController(root)
            with patch('PySide6.QtCore.QProcess.start', lambda *args: None):
                job_id = controller.start({'action': 'demo'})
            path = root/'jobs'/job_id
            gui = json.loads((path/'task_lineage.json').read_text())
            self.assertEqual(gui['task_id'], job_id)
            self.assertEqual(gui['input_sha256'], controller.current['input_hash'])
            self.assertEqual(json.loads((path/'request.json').read_text())['action'], 'demo')
            controller.process.deleteLater(); controller.process = None
            app.processEvents()

    def test_real_pipe_disconnect_retains_canceled_terminal(self):
        with tempfile.TemporaryDirectory() as temp:
            script = '''
import sys,time
from pathlib import Path
from unittest.mock import patch
from framework_v2.demo import create_demo
from framework_v2.agent.mcp import main
root=Path(sys.argv[1]); create_demo(root/'demo')
def history(*args,cancel_check,**kwargs):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if cancel_check(): raise InterruptedError()
        time.sleep(.01)
    raise RuntimeError('disconnect did not cancel')
with patch('framework_v2.history.run_history',history):
    main(['--workspace',str(root)])
'''
            request = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{
                'name':'start_backtest','arguments':{'path':'demo/backtest.json','timeline':'demo/timeline.json'}}}
            project = Path(__file__).resolve().parents[2]
            env = os.environ.copy(); env['PYTHONPATH'] = str(project)
            with subprocess.Popen([sys.executable,'-B','-c',script,temp], cwd=project,
                                  env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,text=True,encoding='utf-8') as process:
                try:
                    process.stdout.close()
                    process.stdin.write(json.dumps(request)+'\n'); process.stdin.flush(); process.stdin.close()
                    process.wait(timeout=25)
                    stderr = process.stderr.read()
                except Exception:
                    if process.poll() is None: process.kill(); process.wait(timeout=10)
                    raise
            self.assertNotEqual(process.returncode, 0)
            # Windows CRT reports a closed redirected stdout as EINVAL;
            # POSIX commonly reports EPIPE/BrokenPipeError. Both lose delivery.
            self.assertRegex(stderr, r'(BrokenPipeError|OSError: \[Errno (22|32)\])')
            job = json.loads(next((Path(temp)/'agent_jobs').glob('*.json')).read_text())
            self.assertEqual(job['state'], 'CANCELED')
            self.assertIsNotNone(job['finished_at'])


if __name__ == '__main__':
    unittest.main()
