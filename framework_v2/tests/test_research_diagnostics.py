import unittest
import pandas as pd
from framework_v2.research_diagnostics import analyze_frame, check_visibility


class ResearchDiagnosticsTests(unittest.TestCase):
    def test_ties_and_cross_sections(self):
        frame = pd.DataFrame({'code':['A','B','C','A','B'], 'signal_date':['2024-01-01']*3+['2024-02-01']*2,
                              'factor_value':[1,1,float('inf'),10,20]})
        result = analyze_frame(frame)
        self.assertEqual(result['valid'],4)
        ranks = result['cross_sectional_ranks']
        self.assertEqual(ranks[0]['rank'],ranks[1]['rank'])
        self.assertEqual(ranks[2]['rank'],None)
        self.assertEqual(ranks[3]['rank'],0.5)

    def test_unknown_availability_fails_closed(self):
        frame = pd.DataFrame({'available_at':['2024-01-01','2024-01-01T00:00:00Z','2025-01-01T00:00:00Z']})
        result = check_visibility({'prices':frame},'2024-02-01T00:00:00Z')
        self.assertFalse(result['availability_valid'])
        self.assertEqual(result['future_rows_require_gate'],1)
        self.assertEqual(result['datasets']['prices']['missing_available_at'],1)
