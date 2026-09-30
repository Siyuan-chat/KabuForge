"""Config identities must not rename or silently substitute legacy algorithms."""
import unittest
import pandas as pd
from framework_v2.factors import FactorSpec, FactorContext, FactorContractError
from framework_v2.legacy_factors import LegacyFactorRegistry, LegacyFactorAdapter
from framework_v2.strategy import CompositeFactorStrategy
from framework_v2.models import StrategyState, StrategyError

def spec(alias, implementation, window=1):
    return FactorSpec.from_config({"kind":"factor","schema_version":"1.0","id":alias,"version":"1",
        "implementation":{"id":implementation,"version":"1","parameters":{"window":window}},
        "data_requirements":[],"lookback":window,"output":{"name":"score","description":"synthetic"}})

def runner(name):
    def compute(*,universe,rebalance_date,config):
        frame=pd.DataFrame({"code":universe["code"],"factor_name":name,
            "factor_value":[config["window"]*2,config["window"]],"signal_date":"2024-04-30",
            "data_end_date":"2024-04-30","rebalance_date":rebalance_date})
        return {"minimal":frame,"detail":frame.copy(),"summary":{"algorithm":name}}
    return compute

class AliasTests(unittest.TestCase):
    def setUp(self):
        self.context=FactorContext(decision_at="2024-05-01T09:00:00+09:00",data_snapshot_hash="synthetic",
            datasets={"universe":pd.DataFrame({"code":["1300","1301"],"in_universe":True,
                "asof_date":"2024-04-30","available_at":"2024-04-30T16:00:00+09:00"})})

    def test_two_aliases_one_algorithm_preserve_legacy_names(self):
        registry=LegacyFactorRegistry()
        registry.register_runner("quality","1",runner("quality"))
        registry.register_loader("fundamental_loader",lambda ctx:lambda:pd.DataFrame())
        adapter=LegacyFactorAdapter(registry)
        results={name:adapter.run(spec(name,"private.quality",window),self.context)
                 for name,window in [("fast",1),("slow",2)]}
        self.assertEqual(results["fast"].minimal.factor_name.tolist(),["quality","quality"])
        self.assertEqual(results["slow"].binding_id,"slow")
        strategy=CompositeFactorStrategy({"kind":"strategy","scoring":{"formula":"slow-fast"},
            "portfolio":{"construction":"equal_weight","parameters":{"top_n":1}}},factor_ids=("fast","slow"))
        decision=strategy.decide_with_audit(results=results,context=self.context,state=StrategyState(),decision_identity="d")
        self.assertEqual(list(decision.target.weights()),["1300"])
        results["fast"],results["slow"]=results["slow"],results["fast"]
        with self.assertRaisesRegex(StrategyError,"binding"):
            strategy.decide(results=results,context=self.context,state=StrategyState(),decision_identity="d2")

    def test_explicit_public_and_private_momentum_are_distinct(self):
        registry=LegacyFactorRegistry()
        registry.register_runner("residual_momentum","1",runner("residual_momentum"))
        registry.register_loader("close_loader",lambda ctx:lambda:pd.DataFrame())
        public=spec("momentum","public.momentum_12_1")
        with self.assertRaises(FactorContractError): registry.bind(public,self.context)
        registry.register_public_runner("residual_momentum","1",runner("momentum_12_1"))
        adapter=LegacyFactorAdapter(registry)
        result=adapter.run(public,self.context)
        self.assertEqual(result.minimal.factor_name.tolist(),["momentum_12_1"]*2)
        private=adapter.run(spec("residual","private.residual_momentum"),self.context)
        self.assertEqual(private.minimal.factor_name.tolist(),["residual_momentum"]*2)
        self.assertNotEqual(public.cache_key(data_snapshot_hash="x",universe_identity="u",decision_at=self.context.decision_at),
                            spec("momentum","private.residual_momentum").cache_key(data_snapshot_hash="x",universe_identity="u",decision_at=self.context.decision_at))

if __name__=="__main__": unittest.main()
