import unittest
import pandas as pd
from framework_v2.universe_repair import canonicalize


class UniverseRepairTests(unittest.TestCase):
    def test_mixed_date_duplicates_collapse_without_timestamp_invention(self):
        frame = pd.DataFrame({'asof_date': ['2025-04-01', '2025-04-01 00:00:00'],
                              'code': ['1301', '1301'], 'in_universe': [True, True]})
        clean, quarantine, stats = canonicalize(frame)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean.iloc[0].source_row_count, 2)
        self.assertTrue(quarantine.empty)
        self.assertNotIn('available_at', clean.columns)
        self.assertFalse(stats['pit_executable'])

    def test_conflicts_are_quarantined_not_last_write_wins(self):
        frame = pd.DataFrame({'asof_date': ['2025-04-01'] * 3,
            'code': ['1301', '1301', '1302'], 'in_universe': [True, False, True]})
        clean, quarantine, stats = canonicalize(frame)
        self.assertEqual(clean.code.tolist(), ['1302'])
        self.assertEqual(len(quarantine), 2)
        self.assertEqual(stats['conflicting_keys'], 1)

    def test_non_midnight_dates_and_string_bools_are_rejected(self):
        frame = pd.DataFrame({'asof_date': ['2025-04-01 12:00', '2025-04-01'],
            'code': ['1301', '1302'], 'in_universe': [True, 'False']})
        clean, quarantine, stats = canonicalize(frame)
        self.assertTrue(clean.empty)
        self.assertEqual(stats['invalid_rows'], 2)
