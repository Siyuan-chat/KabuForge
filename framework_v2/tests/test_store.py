"""Temporary SQLite only; no broker, real account, or network access."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from framework_v2.execution import (AccountState, BrokerCapabilities, ExecutionError, Fill,
                                    OrderEvent, OrderPlan, OrderStatus, Position, Quote, Instrument)
from framework_v2.models import TargetPortfolio
from framework_v2.planner import FeeModel, Planner
from framework_v2.store import Store, StoreError


NOW = datetime(2026, 9, 30, 10, tzinfo=timezone(timedelta(hours=9)))


def fixture(account=None, target=None, decision="d1"):
    account = account or AccountState("synthetic", "r0", 10000, 1000, (Position("A", 10, 90),))
    target = target if target is not None else TargetPortfolio.from_weights({"B": ".1"})
    plan = Planner().plan(target, account,
                          {c: Quote(c, 100, 100, NOW) for c in ("A", "B")},
                          {c: Instrument(c, 1, 1) for c in ("A", "B")},
                          BrokerCapabilities(frozenset({"market"}), frozenset({"DAY"})),
                          now=NOW, decision_identity=decision, strategy_hash="s1",
                          turnover_budget=Decimal(1), fee_model=FeeModel())
    return account, plan


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.store = Store(self.path)

    def test_batch_reservations_and_idempotent_replay(self):
        account, plan = fixture()
        ids = self.store.register_batch("run", plan, account,
                                        raw_target=TargetPortfolio(()),
                                        allowed_target=TargetPortfolio.from_weights({"B": ".1"}))
        self.assertEqual(ids, tuple(i.intent_id for i in plan.intents))
        self.assertEqual(self.store.register_batch("run", plan, account,
                         raw_target=TargetPortfolio(()),
                         allowed_target=TargetPortfolio.from_weights({"B": ".1"})), ids)
        self.assertEqual(len(self.store.export_view()["orders"]), 2)
        self.assertEqual(self.store.order_status(ids[0]), "PLANNED")
        with self.assertRaisesRegex(StoreError, "audit payload"):
            self.store.register_batch("run", OrderPlan((plan.intents[0],), {}, 0, 1000),
                                      account, raw_target=TargetPortfolio(()),
                                      allowed_target=TargetPortfolio.from_weights({"B": ".1"}))
        with self.assertRaisesRegex(StoreError, "audit payload"):
            self.store.register_batch("run", OrderPlan((), {}, 0, 1000), account,
                                      raw_target=TargetPortfolio(()),
                                      allowed_target=TargetPortfolio.from_weights({"B": ".1"}),
                                      decision_identity="d1", strategy_hash="s1")
        # A different run cannot reserve the same held shares or cash.
        other = Store(self.path)
        _, other_plan = fixture(account, decision="d2")
        with self.assertRaisesRegex(StoreError, "unreserved"):
            other.register_batch("run2", other_plan, account)
        self.assertEqual(len(other.export_view()["runs"]), 1)

    def test_submit_unknown_recovery_and_reconciliation(self):
        account, plan = fixture()
        sell = plan.intents[0]
        self.store.register_batch("run", plan, account)
        self.store.begin_submission(sell.intent_id)
        self.assertEqual(self.store.recovery_required(), (sell.intent_id,))
        with self.assertRaisesRegex(StoreError, "reconcile"):
            Store(self.path).begin_submission(sell.intent_id)
        unknown = OrderEvent(sell.intent_id, OrderStatus.UNKNOWN, NOW, event_id="e-unknown")
        self.store.record_event(unknown)
        self.assertEqual(self.store.order_status(sell.intent_id), "UNKNOWN")
        with self.assertRaises(StoreError):
            self.store.begin_submission(sell.intent_id)
        accepted = OrderEvent(sell.intent_id, OrderStatus.ACCEPTED, NOW + timedelta(seconds=1),
                              broker_order_id="broker-1", event_id="e-accepted")
        with self.assertRaisesRegex(StoreError, "reconciliation evidence"):
            self.store.record_event(OrderEvent(sell.intent_id, OrderStatus.ACCEPTED,
                                               NOW + timedelta(seconds=1), event_id="no-proof"))
        self.store.reconcile(accepted, "broker-query-1")
        self.assertEqual(self.store.recovery_required(), ())
        self.store.record_event(unknown)
        self.assertEqual(self.store.order_status(sell.intent_id), "ACCEPTED")

    def test_same_broker_event_adds_multiple_query_evidence_without_collision(self):
        account, plan = fixture()
        sell = plan.intents[0]
        self.store.register_batch("run", plan, account)
        self.store.begin_submission(sell.intent_id)
        accepted = OrderEvent(sell.intent_id, OrderStatus.ACCEPTED, NOW,
                              broker_order_id="broker-1", event_id="stable-event")
        self.store.record_event(accepted)
        self.store.reconcile(accepted, "query-one")
        self.store.reconcile(accepted, "query-two")
        view = self.store.export_view()
        self.assertEqual(len(view["events"]), 1)
        self.assertEqual(len(view["reconciliations"]), 2)
        with self.assertRaisesRegex(StoreError, "evidence reference collision"):
            self.store.reconcile(OrderEvent(sell.intent_id, OrderStatus.ACCEPTED,
                                            NOW + timedelta(seconds=1), event_id="other-event"),
                                 "query-one")

    def test_late_fill_after_cancel_is_booked_once_and_revision_advances(self):
        account, plan = fixture()
        sell = plan.intents[0]
        self.store.register_batch("run", plan, account)
        self.store.record_event(OrderEvent(sell.intent_id, OrderStatus.CANCELED, NOW,
                                           event_id="cancel"))
        fill = Fill(sell.intent_id, "trade-1", "A", "sell", 3, 99, 1, NOW + timedelta(seconds=2))
        event = OrderEvent(sell.intent_id, OrderStatus.PARTIAL, NOW + timedelta(seconds=2),
                           event_id="late-partial")
        self.store.record_event(event, fill)
        view = self.store.account_view("synthetic")
        self.assertEqual(view["revision"], "r0#1")
        self.assertEqual(view["available_cash"], "1296")
        self.assertEqual(view["positions"]["A"]["quantity"], 7)
        self.assertEqual(self.store.order_status(sell.intent_id), "CANCELED")
        self.store.record_event(event, fill)
        self.assertEqual(self.store.account_view("synthetic"), view)
        self.assertEqual(len(self.store.export_view()["fills"]), 1)

    def test_buy_fill_and_old_revision_rejected(self):
        account, plan = fixture()
        buy = next(i for i in plan.intents if i.side == "buy")
        self.store.register_batch("run", plan, account)
        fill = Fill(buy.intent_id, "b-trade", "B", "buy", 10, 100, 0, NOW)
        self.store.record_event(OrderEvent(buy.intent_id, OrderStatus.FILLED, NOW,
                                           event_id="b-filled"), fill)
        view = self.store.account_view("synthetic")
        self.assertEqual(view["available_cash"], "0")
        self.assertEqual(view["positions"]["B"]["quantity"], 10)
        self.assertEqual(self.store.order_status(buy.intent_id), "FILLED")
        # An old snapshot cannot seed a different order batch after a fill.
        _, other_plan = fixture(account, decision="d2")
        with self.assertRaisesRegex(StoreError, "stale account revision"):
            self.store.register_batch("new-run", other_plan, account)

    def test_reported_filled_without_trade_detail_stays_unknown(self):
        account, plan = fixture()
        buy = next(i for i in plan.intents if i.side == "buy")
        self.store.register_batch("run", plan, account)
        self.store.record_event(OrderEvent(buy.intent_id, OrderStatus.FILLED, NOW,
                                           event_id="reported-filled"))
        self.assertEqual(self.store.order_status(buy.intent_id), "UNKNOWN")
        self.assertIn(buy.intent_id, self.store.recovery_required())

    def test_empty_plan_still_records_account_and_identity(self):
        account, _ = fixture()
        empty = OrderPlan((), {}, 0, account.available_cash)
        with self.assertRaisesRegex(StoreError, "empty plan requires"):
            self.store.register_batch("empty", empty, account)
        self.assertEqual(self.store.register_batch("empty", empty, account,
                         decision_identity="d-empty", strategy_hash="s-empty"), ())
        self.assertEqual(self.store.account_view("synthetic")["revision"], "r0")
        self.assertEqual(self.store.export_view()["runs"][0]["intent_ids"], "[]")

    def test_uncertain_order_blocks_other_plan_and_submission(self):
        account, plan = fixture()
        self.store.register_batch("run", plan, account)
        sell, buy = plan.intents
        self.store.begin_submission(sell.intent_id)
        with self.assertRaisesRegex(StoreError, "uncertain orders"):
            self.store.begin_submission(buy.intent_id)
        _, other_plan = fixture(account, decision="d2")
        with self.assertRaisesRegex(StoreError, "uncertain orders"):
            self.store.register_batch("run2", other_plan, account)

    def test_later_unknown_gates_and_older_acceptance_cannot_clear(self):
        account, plan = fixture()
        sell, buy = plan.intents
        self.store.register_batch("run", plan, account)
        self.store.begin_submission(sell.intent_id)
        self.store.reconcile(OrderEvent(sell.intent_id, OrderStatus.ACCEPTED, NOW,
                                        event_id="accepted"), "query-a")
        self.store.record_event(OrderEvent(sell.intent_id, OrderStatus.UNKNOWN,
                                           NOW + timedelta(seconds=2), event_id="unknown-new"))
        self.store.reconcile(OrderEvent(sell.intent_id, OrderStatus.ACCEPTED,
                                        NOW + timedelta(seconds=1), event_id="accepted-old"), "query-old")
        self.assertEqual(self.store.order_status(sell.intent_id), "UNKNOWN")
        with self.assertRaises(StoreError):
            self.store.begin_submission(buy.intent_id)

    def test_unexpected_price_books_negative_cash_and_gates_account(self):
        account, plan = fixture()
        sell, buy = plan.intents
        self.store.register_batch("run", plan, account)
        self.store.record_event(OrderEvent(buy.intent_id, OrderStatus.FILLED, NOW,
                                           event_id="overfill-price"),
                                Fill(buy.intent_id, "expensive-trade", "B", "buy", 10, 200, 0, NOW))
        view = self.store.account_view("synthetic")
        self.assertEqual(view["available_cash"], "-1000")
        self.assertTrue(view["reconciliation_required"])
        with self.assertRaisesRegex(StoreError, "account requires reconciliation"):
            self.store.begin_submission(sell.intent_id)

    def test_mark_account_revision_identity_and_exact_coverage(self):
        account, plan = fixture()
        self.store.register_batch("run", plan, account)
        before = self.store.account_view("synthetic")
        revision = self.store.mark_account("synthetic", "r0", {"A": Decimal(150)},
                                           "valuation-1", NOW)
        after = self.store.account_view("synthetic")
        self.assertEqual(revision, "r0#1")
        self.assertEqual(after["equity"], "2500")
        self.assertEqual(after["available_cash"], before["available_cash"])
        self.assertEqual(after["positions"], before["positions"])
        self.assertEqual(self.store.mark_account("synthetic", "r0", {"A": 150},
                                                  "valuation-1", NOW), revision)
        with self.assertRaisesRegex(StoreError, "different payload"):
            self.store.mark_account("synthetic", "r0", {"A": 151}, "valuation-1", NOW)
        with self.assertRaisesRegex(StoreError, "stale account revision"):
            self.store.mark_account("synthetic", "r0", {"A": 150}, "valuation-2", NOW)
        with self.assertRaisesRegex(StoreError, "cover exactly"):
            self.store.mark_account("synthetic", revision, {}, "valuation-2", NOW)
        for invalid in (0, -1, Decimal("NaN"), Decimal("Infinity")):
            with self.assertRaises(ExecutionError):
                self.store.mark_account("synthetic", revision, {"A": invalid},
                                        "valuation-bad", NOW)

    def test_mark_does_not_unlock_unknown_submission(self):
        account, plan = fixture()
        sell, buy = plan.intents
        self.store.register_batch("run", plan, account)
        self.store.begin_submission(sell.intent_id)
        self.store.mark_account("synthetic", "r0", {"A": 100}, "mark-while-unknown", NOW)
        self.assertEqual(self.store.recovery_required(), (sell.intent_id,))
        with self.assertRaisesRegex(StoreError, "uncertain orders"):
            self.store.begin_submission(buy.intent_id)


if __name__ == "__main__":
    unittest.main()
