import unittest
from decimal import Decimal
import pandas as pd
from framework_v2.factors import FactorContext
from framework_v2.local_io import research_marks

class ResearchMarksTests(unittest.TestCase):
    def test_missing_close_uses_visible_last_valid_without_changing_factor_rows(self):
        rows=[('A','2025-04-01',100),('A','2025-04-02',None),
              ('A','2025-04-03',999),('B','2025-04-01',float('inf')),
              ('C','2025-04-01',0),('D','2025-04-01',-1)]
        frame=pd.DataFrame(rows,columns=['code','date','close'])
        frame['available_at']=frame['date']+'T23:59:00+09:00'
        context=FactorContext(decision_at='2025-04-02T23:59:00+09:00',
            datasets={'prices':frame},data_snapshot_hash='test')
        self.assertEqual(research_marks(context),{'A':Decimal('100')})
        self.assertTrue(context.read('prices').loc[lambda x:x.date.eq('2025-04-02'),'close'].isna().all())
