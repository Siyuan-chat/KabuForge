"""Synthetic-only checks for local cash-equity order planning."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from framework_v2.execution import (AccountState, BrokerCapabilities, ExecutionError,
                                    Instrument, OrderEvent, OrderStatus, Position, Quote)
from framework_v2.models import TargetPortfolio, TargetPosition
from framework_v2.planner import FeeModel, Planner


NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone(timedelta(hours=9)))


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.account = AccountState("synthetic", "rev-1", "10000", "1000",
                                    (Position("A", 10, "90"),))
        self.quotes = {code: Quote(code, "100", "100", NOW)
                       for code in ("A", "B", "C")}
        self.instruments = {"A": Instrument("A", 1, "1"),
                            "B": Instrument("B", 10, "1"),
                            "C": Instrument("C", 100, "1")}
        self.cap = BrokerCapabilities(frozenset({"market", "limit"}), frozenset({"DAY"}))
        self.fees = FeeModel(0, 0)

    def plan(self, target, **kw):
        args = dict(target=target, account=self.account, quotes=self.quotes,
                    instruments=self.instruments, capabilities=self.cap,
                    now=NOW, decision_identity="decision-1", strategy_hash="strategy-1",
                    turnover_budget=Decimal(1), fee_model=self.fees)
        args.update(kw)
        return Planner().plan(**args)

    def test_none_vs_empty_and_sell_before_buy_without_sale_proceeds(self):
        self.assertEqual(self.plan(None).intents, ())
        empty = self.plan(TargetPortfolio(()))
        self.assertEqual([(o.side, o.code, o.quantity) for o in empty.intents],
                         [("sell", "A", 10)])
        target = TargetPortfolio.from_weights({"B": ".5", "C": ".5"})
        plan = self.plan(target)
        self.assertEqual([(o.side, o.code, o.quantity) for o in plan.intents],
                         [("sell", "A", 10), ("buy", "B", 10)])
        self.assertEqual(plan.remaining_cash, Decimal(0))
        self.assertNotIn("C", [o.code for o in plan.intents])

    def test_mixed_lot_one_ten_hundred(self):
        account = AccountState("a", "r", "30000", "30000")
        target = TargetPortfolio.from_weights({"A": ".1", "B": ".1", "C": ".8"})
        result = self.plan(target, account=account)
        self.assertEqual({o.code: o.quantity for o in result.intents},
                         {"A": 30, "B": 30, "C": 200})
        self.assertTrue(all(o.quantity % self.instruments[o.code].lot_size == 0 for o in result.intents))

    def test_explicit_amount_target_and_total_budget(self):
        account = AccountState("a", "r", "10000", "10000")
        target = TargetPortfolio((TargetPosition("B", Decimal(".1"), Decimal("2000")),))
        result = self.plan(target, account=account)
        self.assertEqual(result.intents[0].quantity, 20)
        excessive = TargetPortfolio((TargetPosition("B", Decimal(".1"), Decimal("11000")),))
        with self.assertRaisesRegex(ExecutionError, "notional exceeds equity"):
            self.plan(excessive, account=account)

    def test_missing_stale_future_and_expired_skip(self):
        target = TargetPortfolio.from_weights({"B": ".1", "C": ".1"})
        account = AccountState("a", "r", "10000", "10000")
        quotes = dict(self.quotes)
        del quotes["B"]
        quotes["C"] = Quote("C", 100, 100, NOW - timedelta(minutes=2))
        result = self.plan(target, account=account, quotes=quotes)
        self.assertIn("missing_quote", result.skipped["B"])
        self.assertIn("stale_quote", result.skipped["C"])
        self.assertFalse(result.intents)
        quotes["B"] = Quote("B", 100, 100, NOW + timedelta(seconds=1))
        instruments = dict(self.instruments)
        instruments["C"] = Instrument("C", 100, 1, NOW)
        result = self.plan(target, account=account, quotes=quotes, instruments=instruments)
        self.assertIn("future_quote", result.skipped["B"])
        self.assertIn("stale_quote", result.skipped["C"])

    def test_expired_instrument_and_no_reselection(self):
        target = TargetPortfolio.from_weights({"B": ".5", "C": ".5"})
        account = AccountState("a", "r", "10000", "10000")
        instruments = dict(self.instruments)
        instruments["B"] = Instrument("B", 10, 1, NOW)
        result = self.plan(target, account=account, instruments=instruments)
        self.assertIn("expired_instrument", result.skipped["B"])
        self.assertFalse(result.intents)

    def test_unsupported_type_tif_and_short(self):
        target = TargetPortfolio.from_weights({"B": ".1"})
        with self.assertRaisesRegex(ExecutionError, "order type"):
            self.plan(target, capabilities=BrokerCapabilities(frozenset({"limit"}), frozenset({"DAY"})))
        with self.assertRaisesRegex(ExecutionError, "time-in-force"):
            self.plan(target, capabilities=BrokerCapabilities(frozenset({"market"}), frozenset()))
        with self.assertRaisesRegex(ExecutionError, "short"):
            self.plan(TargetPortfolio.from_weights({"B": "-.1"}))

    def test_limit_tick_and_identity_payload(self):
        target = TargetPortfolio.from_weights({"B": ".2"})
        account = AccountState("a", "r", "10000", "10000")
        instruments = dict(self.instruments)
        instruments["B"] = Instrument("B", 10, Decimal("0.5"))
        bad = self.plan(target, account=account, instruments=instruments, order_type="limit", limit_prices={"B": "100.1"})
        self.assertIn("invalid_limit_tick", bad.skipped["B"])
        first = self.plan(target, account=account, instruments=instruments, order_type="limit", limit_prices={"B": "100.5"})
        again = self.plan(target, account=account, instruments=instruments, order_type="limit", limit_prices={"B": "100.5"})
        changed = self.plan(target, account=account, instruments=instruments, order_type="limit", limit_prices={"B": "101"})
        self.assertEqual(first.intents[0].intent_id, again.intents[0].intent_id)
        self.assertNotEqual(first.intents[0].intent_id, changed.intents[0].intent_id)
        self.assertEqual(first.intents[0].intent_id, first.intents[0].idempotency_key)
        self.assertEqual(first.intents[0].time_in_force, "DAY")
        # A higher limit cannot size beyond the requested target notional.
        high = self.plan(target, account=account, instruments=instruments,
                         order_type="limit", limit_prices={"B": "200"})
        self.assertEqual(high.intents[0].quantity, 10)

    def test_fees_cash_boundary_and_sell_fee(self):
        target = TargetPortfolio.from_weights({"B": ".5"})
        result = self.plan(target, fee_model=FeeModel(0, 1))
        self.assertFalse(any(o.side == "buy" for o in result.intents))
        self.assertIn("insufficient_cash_including_fee", result.skipped["B"])
        no_cash = AccountState("a", "r", "10000", 0, (Position("A", 10, 90),))
        empty = self.plan(TargetPortfolio(()), account=no_cash, fee_model=FeeModel(0, 1))
        self.assertEqual([(o.side, o.code) for o in empty.intents], [("sell", "A")])
        self.assertEqual(empty.remaining_cash, 0)
        replacement = self.plan(TargetPortfolio.from_weights({"B": ".1"}),
                                account=no_cash, fee_model=FeeModel(0, 1))
        self.assertEqual([(o.side, o.code) for o in replacement.intents], [("sell", "A")])
        self.assertIn("insufficient_cash_including_fee", replacement.skipped["B"])

    def test_odd_lot_liquidation_records_residual(self):
        account = AccountState("a", "r", "20000", 0, (Position("C", 105, 90),))
        result = self.plan(TargetPortfolio(()), account=account)
        self.assertEqual(result.intents[0].quantity, 100)
        self.assertIn("odd_lot_residual", result.skipped["C"])

    def test_turnover_exact_after_lot_rounding(self):
        target = TargetPortfolio.from_weights({"B": ".5", "C": ".5"})
        account = AccountState("a", "r", "10000", "10000")
        result = self.plan(target, account=account, turnover_budget=Decimal(".099999"))
        self.assertEqual(result.intents, ())
        self.assertEqual(result.estimated_turnover, 0)
        result = self.plan(target, account=account, turnover_budget=Decimal(".1"))
        self.assertEqual([(o.side, o.quantity) for o in result.intents], [("buy", 10)])
        self.assertEqual(result.estimated_turnover, Decimal(".1"))

    def test_inputs_and_results_immutable(self):
        target = TargetPortfolio.from_weights({"B": ".1"})
        result = self.plan(target)
        with self.assertRaises(FrozenInstanceError):
            result.intents[0].quantity = 20
        with self.assertRaises(TypeError):
            result.skipped["x"] = ("changed",)
        with self.assertRaises(FrozenInstanceError):
            self.account.positions[0].quantity = 20
        self.assertEqual(target.weights(), {"B": Decimal(".1")})

    def test_contract_validation(self):
        for value in (True, 1.2, -1):
            with self.assertRaises(ExecutionError):
                Position("X", value, 10)
        for value in ("NaN", "Infinity"):
            with self.assertRaises(ExecutionError):
                AccountState("a", "r", 1, value)
        with self.assertRaises(ExecutionError):
            AccountState("a", "r", 100, 100, (Position("X", 1, 1), Position("X", 2, 1)))
        with self.assertRaises(ExecutionError):
            Quote("X", 1, 1, datetime(2026, 9, 30))
        with self.assertRaises(ExecutionError):
            OrderEvent("x", OrderStatus.UNKNOWN, datetime(2026, 9, 30))
        with self.assertRaises(ExecutionError):
            self.plan(TargetPortfolio(()), now=datetime(2026, 9, 30))


if __name__ == "__main__":
    unittest.main()
