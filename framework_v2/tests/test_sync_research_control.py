"""Real stdio cancellation with unchanged final-response and paper boundaries."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
import sqlite3

from framework_v2.request_control import cancellation_scope, check_cancelled, RequestCancelled
from framework_v2.stdio_transport import serve


def _pid_exists(pid):
    """Query without signals on Windows; uncertainty must fail the assertion."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87: return False  # Invalid PID, not access denied.
        raise ctypes.WinError(error)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259  # STILL_ACTIVE
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class SyncResearchControlTests(unittest.TestCase):
    def test_context_is_reset_and_paper_does_not_receive_cancel_token(self):
        class Service:
            def shutdown(self): pass
        class Adapter:
            service = Service()
            def request(self, value):
                check_cancelled()
                return {'jsonrpc':'2.0','id':value['id'],'result':{'paper_boundary_retained':True}}
        messages = [ {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'research_paper_step'}},
                     {'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':1}} ]
        out = io.StringIO()
        serve(Adapter(), io.StringIO(''.join(json.dumps(x)+'\n' for x in messages)), out)
        self.assertTrue(json.loads(out.getvalue())['result']['paper_boundary_retained'])
        event = threading.Event(); event.set()
        with cancellation_scope(event):
            with self.assertRaises(RequestCancelled): check_cancelled()
        check_cancelled()

    def test_oversize_invalid_and_normal_frames_keep_original_errors(self):
        class Service:
            def shutdown(self): pass
        class Adapter:
            service = Service()
            def request(self, value):
                return {'jsonrpc':'2.0','id':value['id'],'result':{}}
        out = io.StringIO()
        text = 'x'*(1024*1024+2)+'\ninvalid\n[]\n'+json.dumps({'id':1})+'\n'
        serve(Adapter(), io.StringIO(text), out)
        frames = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([x['error']['code'] for x in frames[:3]], [-32600,-32700,-32600])
        self.assertEqual(frames[3]['id'], 1)

    def test_queued_requests_do_not_starve_control_eof(self):
        class Service:
            def shutdown(self): pass
        class Adapter:
            service=Service()
            def request(self,value):
                if value['id']==1:
                    # EOF must still reach this active operation when more
                    # than the former queue window is pending.
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        try: check_cancelled()
                        except RequestCancelled:
                            return {'id':1,'result':{'canceled':True}}
                        time.sleep(.001)
                    raise AssertionError('control reader starved behind business requests')
                return {'id':value['id'],'result':{}}
        first={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'research_factor_diagnostics'}}
        pending=[{'jsonrpc':'2.0','id':i,'method':'ping'} for i in range(2,66)]
        output=io.StringIO()
        serve(Adapter(),io.StringIO(''.join(json.dumps(v)+'\n' for v in [first]+pending)),output)
        results=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(results[0]['result']['canceled'])
        self.assertEqual([r['id'] for r in results],list(range(1,66)))

    def test_real_sync_worker_eof_and_notification(self):
        self.assertTrue(_pid_exists(os.getpid()))
        for reason in ('eof', 'notification'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                script = '''
import sys,subprocess
from pathlib import Path
from unittest.mock import patch
from framework_v2.agent.core import AgentCommandService
from framework_v2.research_application import ResearchApplicationService
from framework_v2.agent.mcp import main
root=Path(sys.argv[1]); original=subprocess.Popen
def start(argv,**kwargs):
    if not isinstance(argv,list) or 'framework_v2.research_studio_worker' not in argv:
        return original(argv,**kwargs)
    child=original([sys.executable,'-B','-c','import time;time.sleep(60)'],**kwargs)
    (root/'child.pid').write_text(str(child.pid))
    return child
def dispatch(self,tool,a,**kwargs):
    return ResearchApplicationService(root)._run_static_worker('factor_strategy',{}, {'manifest_sha256':'a'*64})
with patch('framework_v2.research_application.subprocess.Popen',start), patch.object(AgentCommandService,'_dispatch',dispatch):
    main(['--workspace',str(root)])
'''
                request = {'jsonrpc':'2.0','id':7,'method':'tools/call','params':{
                    'name':'research_factor_diagnostics','arguments':{'manifest_ref':'fixture.json'}}}
                # Public uses its existing recipe/file schema instead.
                from framework_v2.agent.core import TOOLS
                properties = TOOLS['research_factor_diagnostics'][1]['properties']
                if 'manifest_path' in properties:
                    request['params']['arguments'] = {'manifest_path':'fixture.json'}
                project = Path(__file__).resolve().parents[2]
                env = os.environ.copy(); env['PYTHONPATH'] = str(project)
                process = subprocess.Popen([sys.executable,'-B','-c',script,temp], cwd=project,
                    env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    text=True,encoding='utf-8')
                try:
                    process.stdin.write(json.dumps(request)+'\n'); process.stdin.flush()
                    deadline=time.monotonic()+10
                    while not (root/'child.pid').exists() and time.monotonic()<deadline and process.poll() is None:
                        time.sleep(.01)
                    self.assertTrue((root/'child.pid').exists(), 'research worker did not start')
                    if reason == 'notification':
                        process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/cancelled',
                            'params':{'requestId':7}})+'\n'); process.stdin.flush()
                        # Keep stdin open until the final response: notification
                        # cancellation must work independently of EOF.
                        line = process.stdout.readline()
                        response = json.loads(line)
                        process.stdin.close(); process.stdin=None
                        _, stderr=process.communicate(timeout=10)
                    else:
                        process.stdin.close(); process.stdin=None
                        stdout,stderr=process.communicate(timeout=10)
                        response=json.loads(stdout)
                    self.assertEqual(process.returncode,0,stderr)
                    self.assertEqual(response['id'],7)
                    self.assertTrue(response['result']['isError'])
                    result=json.loads(response['result']['content'][0]['text'])
                    self.assertFalse(result['ok'])
                    if 'error_type' in result['error']:
                        self.assertEqual(result['error']['error_type'],'RequestCancelled')
                    else:
                        self.assertEqual(result['error']['code'],'KF_AGENT_REJECTED')
                        self.assertEqual(result['evidence']['stage'],'static_worker')
                    failure=json.loads(next(root.glob('research-studio/jobs/*/facade_failure.json')).read_text())
                    self.assertEqual(failure['status'],'CANCELED')
                    self.assertFalse(list(root.glob('research-studio/jobs/*/completion.json')))
                    with closing(sqlite3.connect(root/'agent_audit.sqlite')) as db:
                        link=db.execute('SELECT task_id,job_id FROM call_task_links').fetchone()
                        self.assertEqual(link,(failure['task_id'],failure['task_id']))
                    self.assertFalse(_pid_exists(int((root/'child.pid').read_text())))
                finally:
                    if process.poll() is None: process.kill(); process.wait(timeout=10)
                    for stream in (process.stdin,process.stdout,process.stderr):
                        if stream is not None: stream.close()

    def test_in_process_price_and_factor_checks_cancel_without_paper_mutation(self):
        from framework_v2.price_research import research_bars
        from framework_v2.tests.test_price_research_account_path import bars, recipe
        from framework_v2.factor_research import run_factor_research
        from framework_v2.tests.test_factor_research import FactorResearchTests
        event=threading.Event(); event.set()
        with cancellation_scope(event):
            with self.assertRaises(RequestCancelled): research_bars(bars(),recipe())
        fixture=FactorResearchTests(); fixture.setUp()
        try:
            frozen=fixture._frozen_manifest()
            manifest=frozen[0] if isinstance(frozen,tuple) else frozen
            with cancellation_scope(event):
                with self.assertRaises(RequestCancelled):
                    run_factor_research(manifest,fixture.root/'canceled-factor')
            self.assertFalse((fixture.root/'canceled-factor/report.json').exists())
        finally:
            fixture.tearDown()


if __name__ == '__main__': unittest.main()
