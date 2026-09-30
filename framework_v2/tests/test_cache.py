from pathlib import Path
import tempfile
import unittest
import pandas as pd
from framework_v2.cache import FactorCache
from framework_v2.factors import FactorResult, FactorContractError

class CacheTests(unittest.TestCase):
    def test_exact_float_roundtrip_detachment_and_collision(self):
        minimal=pd.DataFrame({"code":["2000","2001"],"factor_name":"f",
            "factor_value":[0.12345678901234567,float("nan")],"signal_date":pd.Timestamp("2024-01-01"),
            "data_end_date":pd.Timestamp("2024-01-01"),"rebalance_date":pd.Timestamp("2024-01-02")})
        result=FactorResult(minimal,minimal,{"observed":pd.Timestamp("2024-01-01"),"nested":[1,None]},binding_id="alias")
        with tempfile.TemporaryDirectory() as temp:
            cache=FactorCache(Path(temp)/"cache.sqlite"); key="a"*64
            self.assertIsNone(cache.get(key)); cache.put(key,result); cache.put(key,result)
            restored=cache.get(key)
            pd.testing.assert_frame_equal(result.minimal,restored.minimal,check_exact=True)
            self.assertEqual(restored.summary,result.summary); self.assertEqual(restored.binding_id,"alias")
            changed=minimal.copy(); changed.loc[0,"factor_value"]=42
            with self.assertRaises(FactorContractError): cache.put(key,FactorResult(changed,changed,{}))
            self.assertIsNone(cache.get("b"*64))

if __name__=="__main__": unittest.main()
