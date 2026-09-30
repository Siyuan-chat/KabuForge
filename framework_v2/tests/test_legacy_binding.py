import unittest
from framework_v2.legacy_binding import log_facts


class LegacyBindingTests(unittest.TestCase):
    def test_log_dates_do_not_become_available_at(self):
        facts = log_facts('[20:48:11] request_range=2024-01-01..2026-03-31\n'
            '[20:48:11] cache miss listed_info snapshot=20250401; downloading\n'
            '[20:48:12] cache hit listed_info snapshot=20250401\n'
            '[20:48:57] cache write done table=universe path=D:\\cache\\universe.parquet rows=53863')
        self.assertEqual(facts['listed_snapshot_dates'], ['2025-04-01'])
        self.assertEqual(facts['recorded_tables']['universe']['recorded_rows'], 53863)
        self.assertEqual(facts['recorded_tables']['universe']['log_line'], 4)
        self.assertNotIn('available_at', facts)
        self.assertEqual(facts['request_range'], ['2024-01-01', '2026-03-31'])

    def test_missing_facts_are_not_guessed(self):
        self.assertEqual(log_facts('unrelated text')['recorded_tables'], {})
        self.assertIsNone(log_facts('unrelated text')['request_range'])
