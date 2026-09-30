import unittest

import pandas as pd

from framework_v2.financial_events import (AmbiguousFinancialEventOrderError,
                                            canonicalize_financial_events,
                                            latest_visible_financial_events)


class FinancialEventTests(unittest.TestCase):
    def test_same_day_events_are_preserved_and_latest_is_time_based(self):
        clean, quarantine, stats = canonicalize_financial_events(pd.DataFrame([
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "A", "Code": "1111", "x": 1},
            {"DiscDate": "2025-01-10", "DiscTime": "15:30", "DiscNo": "B", "Code": "1111", "x": 2},
        ]))
        self.assertEqual((len(clean), len(quarantine), stats["clean_rows"]), (2, 0, 2))
        result = latest_visible_financial_events(clean, "2025-01-10T16:00:00+09:00")
        self.assertEqual(result.iloc[0]["disc_no"], "B")

    def test_future_event_is_excluded(self):
        clean, _, _ = canonicalize_financial_events(pd.DataFrame([
            {"disclosed_date": "2025-01-10", "disclosed_time": "09:00:00", "disc_no": "A", "code": "1111"},
            {"disclosed_date": "2025-01-11", "disclosed_time": "09:00:00", "disc_no": "B", "code": "2222"},
        ]))
        result = latest_visible_financial_events(clean, "2025-01-10T12:00:00+09:00")
        self.assertEqual(result["code"].tolist(), ["1111"])

    def test_missing_time_is_quarantined_without_inference(self):
        clean, quarantine, stats = canonicalize_financial_events(pd.DataFrame([
            {"DiscDate": "2025-01-10", "DiscTime": None, "DiscNo": "A", "Code": "1111"},
        ]))
        self.assertTrue(clean.empty)
        self.assertEqual(quarantine.iloc[0]["quarantine_reason"], "invalid_or_missing_disclosed_time")
        self.assertEqual(stats["invalid_time_rows"], 1)

    def test_duplicate_dataframe_indexes_do_not_merge_distinct_events(self):
        frame = pd.DataFrame([
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "A", "Code": "1111"},
            {"DiscDate": "2025-01-10", "DiscTime": "10:00", "DiscNo": "B", "Code": "1111"},
        ], index=[7, 7])
        clean, quarantine, _ = canonicalize_financial_events(frame)
        self.assertEqual(clean["disc_no"].tolist(), ["A", "B"])
        self.assertTrue(quarantine.empty)

    def test_conflicting_natural_key_is_quarantined_and_exact_duplicates_merge(self):
        clean, quarantine, stats = canonicalize_financial_events(pd.DataFrame([
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "A", "Code": "1111", "value": 1},
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "A", "Code": "1111", "value": 2},
            {"DiscDate": "2025-01-10", "DiscTime": "10:00", "DiscNo": "B", "Code": "1111", "value": 3},
            {"DiscDate": "2025-01-10", "DiscTime": "10:00", "DiscNo": "B", "Code": "1111", "value": 3},
        ]))
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(quarantine), 2)
        self.assertEqual(stats["conflict_rows"], 2)
        self.assertEqual(stats["duplicate_rows_merged"], 1)

    def test_timezone_rules_and_same_timestamp_ordering_are_strict(self):
        clean, _, _ = canonicalize_financial_events(pd.DataFrame([
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "Z", "Code": "1111"},
            {"DiscDate": "2025-01-10", "DiscTime": "09:00", "DiscNo": "A", "Code": "1111"},
        ]))
        self.assertEqual(str(clean.iloc[0]["source_disclosed_at"].tz), "Asia/Tokyo")
        with self.assertRaises(ValueError):
            latest_visible_financial_events(clean.iloc[:1], "2025-01-10 10:00:00")
        with self.assertRaises(AmbiguousFinancialEventOrderError):
            latest_visible_financial_events(clean, "2025-01-10T10:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
