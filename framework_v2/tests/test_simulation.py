from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
from framework_v2.execution import AccountState, Quote, Instrument, OrderStatus, ExecutionError
from framework_v2.models import TargetPortfolio
from framework_v2.planner import Planner, FeeModel
from framework_v2.simulation import FakeBroker
from framework_v2.store import Store, StoreError

class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat("2024-05-01T09:00:00+09:00")
        self.account=AccountState("fictional","0",10000,10000,())
        self.broker=FakeBroker(self.account)
        self.quote=Quote("2000",100,100,self.now)
        self.plan=Planner().plan(TargetPortfolio.from_weights({"2000":Decimal(".5")}),self.account,
            {"2000":self.quote},{"2000":Instrument("2000",1,1)},self.broker.capabilities,
            now=self.now,decision_identity="d",strategy_hash="s",turnover_budget=1,fee_model=FeeModel())
        self.intent=self.plan.intents[0]

    def test_lost_response_reconciles_then_partial_cancel_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/"journal.sqlite")
            store.register_batch("demo",self.plan,self.account)
            store.begin_submission(self.intent.intent_id)
            self.broker.submit(self.intent,now=self.now)  # response deliberately discarded
            reopened=Store(Path(temp)/"journal.sqlite")
            self.assertEqual(reopened.recovery_required(),(self.intent.intent_id,))
            with self.assertRaises(StoreError): reopened.begin_submission(self.intent.intent_id)
            events,_=self.broker.reconcile(self.intent.intent_id)
            reopened.reconcile(events[-1],"fake-query-1")
            event,fill=self.broker.match(self.intent.intent_id,self.quote,now=self.now,quantity=20,fee=Decimal(2))
            reopened.record_event(event,fill); reopened.record_event(event,fill)
            canceled=self.broker.cancel(self.intent.intent_id,now=self.now+timedelta(seconds=1))
            reopened.record_event(canceled)
            view=reopened.account_view("fictional")
            self.assertEqual(view["available_cash"],"7998")
            self.assertEqual(view["positions"]["2000"]["quantity"],20)
            self.assertEqual(reopened.order_status(self.intent.intent_id),"CANCELED")
            self.assertEqual(self.broker.account().available_cash,Decimal(7998))

    def test_fill_wins_cancel_race_and_unknown_lookup_never_retries(self):
        accepted=self.broker.submit(self.intent,now=self.now)
        self.assertEqual(self.broker.submit(self.intent,now=self.now),accepted)
        event,fill=self.broker.match(self.intent.intent_id,self.quote,now=self.now)
        self.assertEqual(self.broker.cancel(self.intent.intent_id,now=self.now),event)
        self.assertEqual(event.status,OrderStatus.FILLED)
        with self.assertRaises(ExecutionError): FakeBroker(self.account).reconcile(self.intent.intent_id)
        with self.assertRaises(ExecutionError): self.broker.submit(replace(self.intent,quantity=49),now=self.now)

if __name__=="__main__": unittest.main()
