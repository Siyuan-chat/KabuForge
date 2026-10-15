"""Failure-boundary regressions; no optional backend or broker required."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from framework_v2 import research_application as module


class ResearchLifecycleTests(unittest.TestCase):
    def test_launch_receipt_failure_reaps_real_owned_child(self):
        with tempfile.TemporaryDirectory() as temp:
            service = module.ResearchApplicationService(temp)
            children = []
            original_popen = subprocess.Popen
            original_write = module._write_new

            def start(argv, **kwargs):
                if not isinstance(argv, list) or 'framework_v2.research_studio_worker' not in argv:
                    return original_popen(argv, **kwargs)
                child = original_popen([sys.executable, '-B', '-c', 'import time; time.sleep(60)'], **kwargs)
                children.append(child)
                return child

            def write(path, value):
                if '.pending-' in path.name:
                    raise OSError('injected launch receipt failure')
                return original_write(path, value)

            try:
                with patch.object(module.subprocess, 'Popen', start), patch.object(module, '_write_new', write):
                    with self.assertRaises(module.ResearchApplicationError):
                        service._run_static_worker('factor_strategy', {}, {'manifest_sha256': 'a' * 64})
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                job = next((Path(temp) / 'research-studio/jobs').iterdir())
                self.assertTrue((job / 'application_launch.json').is_file())
                self.assertTrue((job / 'facade_failure.json').is_file())
                self.assertFalse((job / 'completion.json').exists())
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=10)

    def test_terminal_identity_and_external_artifact_fail_closed(self):
        for invalid in ('job_id', 'operation', 'schema', 'manifest_sha256', 'pit_guarantee', 'artifact'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                service = module.ResearchApplicationService(Path(temp) / 'workspace')
                outside = Path(temp) / 'outside.json'
                outside.write_text('{}', encoding='utf-8')

                class Process:
                    pid = 1
                    def __init__(self, argv, **kwargs):
                        self.job = service.workspace / 'research-studio/jobs' / argv[-1]
                    def wait(self):
                        value = {'schema': 'kabuforge.research_studio_result.v1',
                                 'job_id': self.job.name, 'operation': 'factor_strategy',
                                 'manifest_sha256': 'a' * 64, 'status': 'COMPLETED',
                                 'readiness': 'RESEARCH-ONLY', 'pit_guarantee': False}
                        if invalid == 'artifact':
                            value['artifacts'] = {'report': str(outside)}
                        else:
                            value[invalid] = True if invalid == 'pit_guarantee' else 'wrong'
                        (self.job / 'result.json').write_text(json.dumps(value), encoding='utf-8')
                        return 0
                    def poll(self):
                        return 0

                with patch.object(module.subprocess, 'Popen', Process):
                    with self.assertRaises(module.ResearchApplicationError):
                        service._run_static_worker('factor_strategy', {}, {'manifest_sha256': 'a' * 64})
                self.assertFalse(list(service.workspace.glob('research-studio/jobs/*/completion.json')))

    def test_post_mutation_failure_blocks_replay_after_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            service = module.ResearchApplicationService(temp, enable_paper=True)
            marker = Path(temp) / 'business-effect.json'

            def action():
                marker.write_text('{"committed":true}', encoding='utf-8')
                raise OSError('injected failure after business persistence')

            with self.assertRaises(OSError):
                service._paper_mutation('test', {}, 'call', 'key', action)
            reopened = module.ResearchApplicationService(temp, enable_paper=True)
            with self.assertRaises(module.ResearchApplicationError):
                reopened._paper_mutation('test', {}, 'retry', 'key', lambda: self.fail('replayed'))
            self.assertTrue(marker.exists())
            with closing(sqlite3.connect(service._paper_db())) as db:
                self.assertEqual(db.execute('SELECT state FROM paper_calls').fetchone()[0], 'FAILED')


if __name__ == '__main__':
    unittest.main()
