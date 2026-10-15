"""Abruptly stop only disposable child processes at real SQLite boundaries."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest

from framework_v2.store import Store, StoreError
from framework_v2.tests.test_store import fixture


class OwnedCrashBoundaryTests(unittest.TestCase):
    def test_real_before_after_commit_and_uncertain_submission_recovery(self):
        script='''
from pathlib import Path
import sys,time
from framework_v2.store import Store
from framework_v2.tests.test_store import fixture
root=Path(sys.argv[1]); stage=sys.argv[2]; store=Store(root/'journal.sqlite')
account,plan=fixture()
def hook(actual):
    if actual==stage:
        (root/'boundary').write_text(actual)
        time.sleep(60)
if stage=='submission':
    store.register_batch('run',plan,account)
    def submission_hook(actual):
        if actual=='after_commit':
            (root/'boundary').write_text(actual)
            time.sleep(60)
    store.begin_submission(plan.intents[0].intent_id,failure_hook=submission_hook)
else:
    store.register_batch('run',plan,account,failure_hook=hook)
'''
        for stage in ('before_commit','after_commit','submission'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); project=Path(__file__).resolve().parents[2]
                env=os.environ.copy(); env['PYTHONPATH']=str(project)
                process=subprocess.Popen([sys.executable,'-B','-c',script,temp,stage],
                    cwd=project,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    deadline=time.monotonic()+10
                    while not (root/'boundary').exists() and time.monotonic()<deadline and process.poll() is None:
                        time.sleep(.01)
                    self.assertTrue((root/'boundary').exists(),'owned child did not reach boundary')
                    process.kill(); process.wait(timeout=10)
                    self.assertNotEqual(process.returncode,0)
                finally:
                    if process.poll() is None: process.kill(); process.wait(timeout=10)
                    process.stdout.close(); process.stderr.close()
                store=Store(root/'journal.sqlite'); account,plan=fixture()
                view=store.export_view()
                if stage=='before_commit':
                    self.assertEqual(len(view['runs']),0)
                    self.assertEqual(len(view['orders']),0)
                else:
                    self.assertEqual(len(view['runs']),1)
                    self.assertEqual(len(view['orders']),len(plan.intents))
                    self.assertEqual(store.register_batch('run',plan,account),tuple(i.intent_id for i in plan.intents))
                if stage=='submission':
                    self.assertEqual(store.recovery_required(),(plan.intents[0].intent_id,))
                    with self.assertRaises(StoreError): store.begin_submission(plan.intents[0].intent_id)


if __name__ == '__main__': unittest.main()
