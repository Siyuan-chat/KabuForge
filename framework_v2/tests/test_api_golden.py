"""Same inputs retain the pre-registry composite decision and public type identity."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from framework_v2.application import ApplicationService
from framework_v2.demo import create_demo
from framework_v2.local_io import context_from_file, account_from_file, execution_from_file, research_marks
from framework_v2.strategy import CompositeFactorStrategy
from framework_v2.models import StrategyState


class GoldenAPITests(unittest.TestCase):
    def test_registry_decision_matches_original_composite(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=create_demo(Path(temp)/'demo'); service=ApplicationService()
            resolved=service.validate(folder/'backtest.json')
            stamp='2024-05-01T09:00:00+09:00'
            context=context_from_file(folder/'snapshot.json',expected_hash=resolved.data_snapshot_hash,decision_at=stamp)
            account=account_from_file(folder/'account.json',expected_hash=resolved.account_hash)
            quotes,instruments,_=execution_from_file(folder/'execution.json')
            result=service.plan(resolved,context=context,account=account,research_marks=research_marks(context),quotes=quotes,instruments=instruments,now=datetime.fromisoformat(stamp))
            original=CompositeFactorStrategy(resolved.strategy,factor_ids=tuple(result.factors)).decide_with_audit(results=result.factors,context=context,state=StrategyState(),decision_identity=result.decision_identity)
            self.assertEqual(result.decision,original)
            self.assertEqual(result.strategy_implementation_id,'composite_factor')

    def test_implementation_identity_is_checked_during_validation(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            folder=create_demo(Path(temp)/'demo')
            config=json.loads((folder/'strategy.json').read_text())
            config['implementation']={'id':'unknown','version':'1'}
            (folder/'strategy.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'unknown strategy'):
                ApplicationService().validate(folder/'backtest.json')
