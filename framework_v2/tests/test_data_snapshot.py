import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from framework_v2.config import ConfigError
from framework_v2.data_snapshot import snapshot_frames, snapshot_dependencies
from framework_v2.demo import create_demo
from framework_v2.workbench_service import WorkbenchService


class SnapshotTests(unittest.TestCase):
    def test_manifest_binds_bytes_and_survives_isolated_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = create_demo(Path(temp)/'demo')
            original = json.loads((root/'snapshot.json').read_text())
            manifest = {'format': 'snapshot.parquet.v1', 'datasets': {}}
            for name, data in original['datasets'].items():
                frame = pd.DataFrame(data['rows'], columns=data['columns'])
                path = root / (name+'.parquet')
                frame.to_parquet(path, index=False)
                manifest['datasets'][name] = {'path': path.name, 'rows': len(frame),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            (root/'snapshot.json').write_text(json.dumps(manifest))
            service = WorkbenchService()
            preflight = service.preflight(root/'backtest.json')
            self.assertTrue(preflight['ok'], preflight['issues'])
            self.assertIn(str(root/'prices.parquet'), preflight['file_hashes'])
            copied = service.snapshot_run(root/'backtest.json', Path(temp)/'copy')
            self.assertTrue(service.preflight(copied)['ok'])
            (root/'prices.parquet').write_bytes(b'changed')
            with self.assertRaises(ConfigError):
                snapshot_frames(root/'snapshot.json', manifest)
            self.assertFalse(service.preflight(root/'backtest.json')['ok'])

    def test_escape_rejected(self):
        with self.assertRaises(ConfigError):
            snapshot_dependencies('snapshot.json', {'format':'snapshot.parquet.v1',
                'datasets':{'prices':{'path':'../prices.parquet','sha256':'0'*64,'rows':1}}})
