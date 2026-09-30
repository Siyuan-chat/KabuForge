"""Crash-boundary and competing-connection tests on disposable SQLite files."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from framework_v2.execution import AccountState, ExecutionError, Fill, OrderEvent, OrderStatus, Quote
from framework_v2.store import Store, StoreError
from framework_v2.tests.test_store import NOW, fixture


def fail_at(stage):
    def hook(actual):
        if actual == stage:
            raise RuntimeError(stage)
    return hook


class FailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.sqlite"
        self.store = Store(self.path)

    def test_crossed_quote_rejected(self):
        with self.assertRaisesRegex(ExecutionError, "crossed quote"):
            Quote("X", 101, 100, NOW)

    def test_batch_before_and_after_commit_recovery(self):
        account, plan = fixture()
        with self.assertRaisesRegex(RuntimeError, "before_commit"):
            self.store.register_batch("run", plan, account,
                                      failure_hook=fail_at("before_commit"))
        self.assertEqual(self.store.export_view()["orders"], [])
        self.assertEqual(self.store.export_view()["runs"], [])
        with self.assertRaisesRegex(RuntimeError, "after_commit"):
            self.store.register_batch("run", plan, account,
                                      failure_hook=fail_at("after_commit"))
        self.assertEqual(len(self.store.export_view()["orders"]), 2)
        self.assertEqual(self.store.register_batch("run", plan, account),
                         tuple(i.intent_id for i in plan.intents))
        self.assertEqual(len(self.store.export_view()["orders"]), 2)

    def test_fill_crash_boundaries_and_export_failure(self):
        account, plan = fixture()
        buy = next(i for i in plan.intents if i.side == "buy")
        self.store.register_batch("run", plan, account)
        event = OrderEvent(buy.intent_id, OrderStatus.FILLED, NOW,
                           event_id="fill-event")
        fill = Fill(buy.intent_id, "trade", "B", "buy", 10, 100, 0, NOW)
        with self.assertRaisesRegex(RuntimeError, "before_commit"):
            self.store.record_event(event, fill, failure_hook=fail_at("before_commit"))
        self.assertEqual(self.store.account_view("synthetic")["revision"], "r0")
        self.assertEqual(self.store.export_view()["fills"], [])
        with self.assertRaisesRegex(RuntimeError, "after_commit"):
            self.store.record_event(event, fill, failure_hook=fail_at("after_commit"))
        saved = self.store.account_view("synthetic")
        self.assertEqual(saved["revision"], "r0#1")
        self.store.record_event(event, fill)
        self.assertEqual(self.store.account_view("synthetic"), saved)
        with self.assertRaisesRegex(RuntimeError, "after_read"):
            self.store.export_view(failure_hook=fail_at("after_read"))
        self.assertEqual(len(Store(self.path).export_view()["fills"]), 1)

    def test_event_and_trade_id_collision_rejected_atomically(self):
        account, plan = fixture()
        buy = next(i for i in plan.intents if i.side == "buy")
        self.store.register_batch("run", plan, account)
        first = OrderEvent(buy.intent_id, OrderStatus.PARTIAL, NOW, event_id="event-1")
        fill = Fill(buy.intent_id, "trade-1", "B", "buy", 3, 100, 0, NOW)
        self.store.record_event(first, fill)
        with self.assertRaisesRegex(StoreError, "trade_id collision"):
            self.store.record_event(first, Fill(buy.intent_id, "trade-1", "B", "buy", 3, 101, 0, NOW))
        with self.assertRaisesRegex(StoreError, "event_id collision"):
            self.store.record_event(OrderEvent(buy.intent_id, OrderStatus.REJECTED, NOW,
                                               event_id="event-1"))
        with self.assertRaisesRegex(StoreError, "trade_id collision"):
            self.store.record_event(OrderEvent(buy.intent_id, OrderStatus.PARTIAL, NOW,
                                               event_id="event-2"),
                                    Fill(buy.intent_id, "trade-1", "B", "buy", 3, 101, 0, NOW))
        view = self.store.export_view()
        self.assertEqual(len(view["events"]), 1)
        self.assertEqual(len(view["fills"]), 1)
        self.assertEqual(self.store.account_view("synthetic")["revision"], "r0#1")

    def test_two_connections_cannot_reserve_same_cash(self):
        account = AccountState("synthetic", "r0", 10000, 1000)
        _, plan1 = fixture(account, decision="one")
        _, plan2 = fixture(account, decision="two")
        barrier = threading.Barrier(2)

        def worker(run, plan):
            local = Store(self.path)
            barrier.wait(timeout=5)
            try:
                local.register_batch(run, plan, account)
                return "saved"
            except StoreError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(worker, "run-one", plan1)
            right = pool.submit(worker, "run-two", plan2)
            results = [left.result(timeout=10), right.result(timeout=10)]
        self.assertEqual(results.count("saved"), 1)
        self.assertTrue(any("unreserved cash" in result for result in results))
        self.assertEqual(len(self.store.export_view()["orders"]), 1)


if __name__ == "__main__":
    unittest.main()
