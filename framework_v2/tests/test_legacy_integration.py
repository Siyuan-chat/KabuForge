"""Exercise the actual installed public algorithms on fictional PIT data."""
import socket
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from framework_v2.synthetic import datasets
from framework_v2.factors import FactorSpec, FactorContext
from framework_v2.legacy_provider import BuiltinFactors, REQUIRED_DATASETS, PITLegacyProvider
from framework_v2.factors import FactorContractError

class LegacyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=datasets()
        cls.builtins=BuiltinFactors()

    def compute(self, frames, name):
        ctx=FactorContext(decision_at="2024-05-01T09:00:00+09:00",datasets=frames,data_snapshot_hash="fictional")
        implementation=("public.momentum_12_1" if name == "residual_momentum" else "public."+name)
        spec=FactorSpec.from_config({"schema_version":"1.0","kind":"factor","id":name,"version":"1",
            "implementation":{"id":implementation,"version":self.builtins.versions[implementation],"parameters":{}},
            "data_requirements":[{"dataset":d,"fields":list(frames[d].columns)} for d in REQUIRED_DATASETS[name]],
            "lookback":800,"output":{"name":name,"description":"synthetic integration"}})
        with patch.object(socket.socket,"connect",side_effect=AssertionError("network prohibited")), patch.object(socket,"getaddrinfo",side_effect=AssertionError("network prohibited")):
            return self.builtins.compute(spec,ctx)

    def test_all_seven_have_values_and_future_perturbations_do_not_change_minimal(self):
        changed={k:v.copy(deep=True) for k,v in self.frames.items()}
        boundary=pd.Timestamp("2024-05-01T09:00:00+09:00")
        for frame in changed.values():
            future=frame.available_at>boundary
            for column in frame.select_dtypes(include="number"):
                frame.loc[future,column] *= 37
            if "in_universe" in frame: frame.loc[future,"in_universe"]=False
        # Late disclosed financial revision must also stay invisible.
        later=changed["financial_summary"].iloc[:1].copy()
        later["available_at"]=pd.Timestamp("2024-06-01T16:00:00+09:00")
        later["net_income"]=-999999999999
        changed["financial_summary"]=pd.concat([changed["financial_summary"],later],ignore_index=True)
        for name in REQUIRED_DATASETS:
            with self.subTest(name=name):
                original=self.compute(self.frames,name)
                self.assertEqual(len(original.minimal),20)
                self.assertGreater(original.minimal.factor_value.notna().sum(),0)
                pd.testing.assert_frame_equal(original.minimal,self.compute(changed,name).minimal)
                from framework_v2.cache import FactorCache
                with tempfile.TemporaryDirectory() as temp:
                    cache=FactorCache(Path(temp)/"factor.sqlite")
                    cache.put("a"*64,original)
                    restored=cache.get("a"*64)
                    pd.testing.assert_frame_equal(original.minimal,restored.minimal,check_exact=True)
                    pd.testing.assert_frame_equal(original.detail,restored.detail,check_exact=True)

    def test_financial_csv_dtype_conversion_is_explicit(self):
        frames={k:v.copy(deep=True) for k,v in self.frames.items()}
        for name in ("financial_summary","market_cap"):
            for col in frames[name].select_dtypes(include="number"):
                frames[name][col]=frames[name][col].astype(str)
        pd.testing.assert_frame_equal(self.compute(self.frames,"value").minimal,self.compute(frames,"value").minimal)

    def test_independent_typed_legacy_calls_match_all_minimal_outputs(self):
        from runtime.historical_data import JpxHistoricalProvider, LocalDataPaths
        # Reference input is independently cut at the declared decision time.
        # Legacy date-only providers otherwise include the same day's future close.
        cutoff=pd.Timestamp("2024-05-01T09:00:00+09:00")
        frames={k:v.loc[v.available_at<=cutoff].copy() for k,v in self.frames.items()}
        class ReferenceProvider(JpxHistoricalProvider):
            def table(self,name,**kwargs):
                result=frames[name].drop(columns="available_at").copy()
                for column in ("date","asof_date","disclosed_date"):
                    if column in result: result[column]=pd.to_datetime(result[column])
                return result
        provider=ReferenceProvider(LocalDataPaths(data_dir="<never-resolved>"))
        universe=frames["universe"].loc[frames["universe"].asof_date.eq("2024-04-30")].drop(columns="available_at")
        date=pd.Timestamp("2024-05-01")
        loaders={"fundamental_loader":provider.load_fundamental_panel,"close_loader":provider.load_close_prices,
            "price_loader":provider.load_price_history,"panel_price_loader":provider.load_price_history,
            "attention_loader":provider.load_attention_inputs,"behaviour_loader":provider.load_behaviour_inputs}
        for name,runner in self.builtins.runners.items():
            with self.subTest(name=name), patch.object(socket.socket,"connect",side_effect=AssertionError("network prohibited")):
                config={**loaders,"asof_date":date,"allow_yfinance_fallback":False,"save_minimal_path":None,"save_detail_path":None}
                expected=runner(universe=universe,rebalance_date=date,config=config)["minimal"]
                pd.testing.assert_frame_equal(expected.reset_index(drop=True),self.compute(frames,name).minimal.reset_index(drop=True),check_exact=True)

    def test_implementation_parameters_are_not_silently_ignored(self):
        from framework_v2.legacy_provider import validate_parameters
        runner=self.builtins.runners["quality"]
        with self.assertRaises(FactorContractError): validate_parameters(runner,{"winsor_lwer_q":0.1})
        with self.assertRaises(FactorContractError): validate_parameters(runner,{"winsor_lower_q":0.99})
        with self.assertRaises(FactorContractError): validate_parameters(runner,{"save_detail_path":"unexpected.csv"})

if __name__=="__main__": unittest.main()
