import json
from pathlib import Path
import tempfile
import unittest

from framework_v2.source_catalog import (compare_caches, identity, inventory_runs,
                                         mapped_path, snapshot_profile, request_profile)


class SourceCatalogTests(unittest.TestCase):
    def test_migration_is_component_scoped(self):
        self.assertEqual(mapped_path(r'D:\codex\quants\data_cache', r'D:\codex\quants',
                                    'new'), Path('new/data_cache'))
        for path in (r'D:\codex\quants_other\data', r'D:\codex\quants\..\secret'):
            with self.assertRaises(ValueError):
                mapped_path(path, r'D:\codex\quants', 'new')

    def test_equal_bytes_do_not_prove_run_version(self):
        a = {'tables': {'prices': {'sha256': 'same'}}}
        result = compare_caches(a, a)[0]
        self.assertEqual(result['status'], 'identical_current_bytes')
        self.assertFalse(result['historical_run_version_proven'])
        self.assertEqual(compare_caches(a, {'tables': {}})[0]['status'], 'missing_side')

    def test_inventory_preserves_missing_and_redacts_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'missing').mkdir()
            (root / 'present').mkdir()
            config = root / 'present/config_used.json'
            config.write_text(json.dumps({'cli': {'data_dir': r'D:\codex\quants\data_cache',
                                                  'api_key': 'MUST_NOT_LEAK'},
                                          'secret': 'MUST_NOT_LEAK'}))
            before = identity(config)
            result = inventory_runs([root])
            self.assertEqual([r['config_status'] for r in result], ['missing', 'read'])
            self.assertNotIn('MUST_NOT_LEAK', json.dumps(result))
            self.assertEqual(before, identity(config))

    def test_snapshot_date_and_creation_time_never_certify_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metadata.json'
            path.write_text(json.dumps({'anchor_date': '2017-06-30',
                'created_at': '2026-04-24T23:01:39',
                'rules': {'universe': 'TOPIX_CURRENT_CONSTITUENTS'}}))
            result = snapshot_profile(path)
            self.assertFalse(result['historical_membership_verified'])
            self.assertIn('CURRENT_CONSTITUENTS', result['blockers'])

    def test_request_timestamp_is_not_publication_and_secrets_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'requests.jsonl'
            path.write_text(json.dumps({'timestamp': '2026-05-05T10:13:04Z',
                'endpoint': '/equities/master', 'status_code': 200,
                'params': {'token': 'SECRET'}, 'error': 'SECRET'}) + '\n' +
                json.dumps({'timestamp': '2026-05-05T10:13:04'}) + '\n')
            result = request_profile(path)
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertEqual(result['invalid_records_or_timestamps'], 1)
            self.assertFalse(result['available_at_verified'])
            self.assertEqual(result['min_acquired_at'], '2026-05-05T10:13:04+00:00')
