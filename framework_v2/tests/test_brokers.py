"""Mock-only broker mapping and Excel bridge tests; no terminal or account."""

import tempfile
import threading
import time
from dataclasses import replace
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from framework_v2.brokers import (BrokerContractError, ExcelCommand, HttpResponse,
                                  KabuCashBroker, NeoTradeMapper, RakutenMapper)
from framework_v2.excel_bridge import BridgeError, ExcelBridge
from framework_v2.execution import OrderIntent


NOW = datetime(2026, 9, 30, 10, tzinfo=timezone(timedelta(hours=9)))


def intent(side="buy", order_type="market", limit=None):
    return OrderIntent("intent-1", "idem-1", "account", "rev", "decision", "strategy",
                       "7203", side, 100, order_type, limit, "DAY", NOW,
                       datetime(2026, 10, 1, tzinfo=NOW.tzinfo), 100, 0)


class HttpMock:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, *, json_body=None, params=None):
        self.calls.append((method, path, json_body, params))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class BlockingHttpMock:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, path, *, json_body=None, params=None):
        with self.lock:
            self.calls.append((method, path, json_body, params))
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError("mock was not released")
        return HttpResponse(200, {"Result": 0, "OrderId": "B123"})


class KabuTests(unittest.TestCase):
    def test_cash_market_limit_and_explicit_day(self):
        broker = KabuCashBroker(HttpMock(), exchange=9, account_type=4)
        buy = broker.map_order(intent(), now=NOW)
        self.assertEqual((buy["Side"], buy["CashMargin"], buy["DelivType"],
                          buy["FundType"], buy["FrontOrderType"], buy["Price"]),
                         ("2", 1, 2, "02", 10, 0))
        self.assertEqual(buy["ExpireDay"], 20260930)
        self.assertNotEqual(buy["ExpireDay"], 0)
        sell = broker.map_order(intent("sell", "limit", Decimal("100.5")), now=NOW)
        self.assertEqual((sell["Side"], sell["DelivType"], sell["FundType"],
                          sell["FrontOrderType"], sell["Price"]),
                         ("1", 0, "  ", 20, 100.5))
        with self.assertRaises(BrokerContractError):
            KabuCashBroker(HttpMock(), exchange=1, account_type=4)
        with self.assertRaises(BrokerContractError):
            broker.map_order(intent(), now=NOW + timedelta(days=1))
        with self.assertRaises(BrokerContractError):
            broker.map_order(intent(), now=NOW - timedelta(seconds=1))
        with self.assertRaises(BrokerContractError):
            broker.map_order(replace(intent(), valid_until=datetime(2026, 10, 1, 0, 0, 1,
                                                                    tzinfo=NOW.tzinfo)), now=NOW)

    def test_submit_unknown_never_retries_and_queries(self):
        mock = HttpMock([TimeoutError("lost"), HttpResponse(200, {"Result": 0, "OrderId": "B123"}),
                         HttpResponse(200, [{"ID": "B123", "State": 3, "Details": []}]),
                         HttpResponse(200, {"StockAccountWallet": 1000}),
                         HttpResponse(200, [])])
        broker = KabuCashBroker(mock, exchange=27, account_type=2)
        result = broker.submit(intent(), now=NOW)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(broker.submit(intent(), now=NOW).status, "UNKNOWN")
        self.assertEqual(len(mock.calls), 1)
        # A fresh broker object can only be used under the external store gate.
        broker2 = KabuCashBroker(mock, exchange=27, account_type=2)
        accepted = broker2.submit(intent(), now=NOW)
        self.assertEqual((accepted.status, accepted.broker_order_id), ("ACCEPTED", "B123"))
        self.assertEqual(broker2.reconcile("B123").status, "UNKNOWN")
        self.assertEqual(broker2.account()["wallet"]["StockAccountWallet"], 1000)
        self.assertEqual(mock.calls[2][3], {"product": "1", "id": "B123"})

    def test_cancel_broker_id_and_incomplete_result(self):
        mock = HttpMock([HttpResponse(200, {"Result": 0, "OrderId": "C1"}),
                         HttpResponse(200, {"Result": 0})])
        broker = KabuCashBroker(mock, exchange=9, account_type=4)
        self.assertEqual(broker.cancel("B123").status, "ACCEPTED")
        self.assertEqual(mock.calls[0][2], {"OrderId": "B123"})
        self.assertEqual(broker.submit(intent(), now=NOW).status, "UNKNOWN")
        with self.assertRaises(BrokerContractError):
            broker.cancel("")

    def test_kabu_full_payload_and_key_collision_and_bool_result(self):
        mock = HttpMock([HttpResponse(200, {"Result": False, "OrderId": "fake"})])
        broker = KabuCashBroker(mock, exchange=9, account_type=4)
        self.assertEqual(broker.submit(intent(), now=NOW).status, "UNKNOWN")
        with self.assertRaisesRegex(BrokerContractError, "different payload"):
            broker.submit(replace(intent(), quantity=200), now=NOW)
        with self.assertRaisesRegex(BrokerContractError, "idempotency key"):
            broker.submit(replace(intent(), intent_id="other"), now=NOW)
        self.assertEqual(len(mock.calls), 1)

    def test_concurrent_duplicate_submit_and_cancel_send_once(self):
        for operation in ("submit", "cancel"):
            with self.subTest(operation=operation):
                mock = BlockingHttpMock()
                broker = KabuCashBroker(mock, exchange=9, account_type=4)
                results = []
                errors = []
                second_started = threading.Event()

                def call(started=None):
                    if started is not None:
                        started.set()
                    try:
                        result = (broker.submit(intent(), now=NOW) if operation == "submit"
                                  else broker.cancel("B123"))
                        results.append(result)
                    except Exception as exc:
                        errors.append(exc)

                first = threading.Thread(target=call)
                second = threading.Thread(target=call, args=(second_started,))
                first.start()
                try:
                    self.assertTrue(mock.entered.wait(1), "first request did not enter transport")
                    second.start()
                    self.assertTrue(second_started.wait(1))
                    # The first HTTP call is still in flight while the second
                    # caller attempts the same operation.
                    time.sleep(0.05)
                    self.assertEqual(len(mock.calls), 1)
                finally:
                    mock.release.set()
                    first.join(2)
                    if second.ident is not None:
                        second.join(2)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(mock.calls), 1)
                self.assertEqual(len(results), 2)
                self.assertEqual(results[0], results[1])


class MapperTests(unittest.TestCase):
    def test_rakuten_all_nineteen_positions(self):
        mapper = RakutenMapper("excel-gen-1", account_type="0")
        command = mapper.submit(intent("sell", "limit", Decimal(101)), 17, now=NOW)
        self.assertEqual(command.name, "RssStockOrder_V")
        self.assertEqual(len(command.args), 19)
        self.assertEqual(command.args[:11], (17, "7203.T", "1", "0", "0", 100,
                                              "1", 101.0, "1", "", "0"))
        self.assertEqual(command.args[15], "0")
        cancel = mapper.cancel(18, "broker-order-7")
        self.assertEqual(cancel.args, (18, "broker-order-7"))
        with self.assertRaises(BrokerContractError):
            mapper.submit(intent(), 2147483648, now=NOW)

    def test_neotrade_correct_day_positions_and_cancel_id(self):
        mapper = NeoTradeMapper("excel-gen-1")
        command = mapper.submit(intent(), 100_000_000_000_000, now=NOW)
        self.assertEqual(command.name, "SntExecEqtyOrder")
        self.assertEqual(command.args, (100_000_000_000_000, "7203.T", "3", "0",
                                        "100", "0", "", "1", "1", "", "1"))
        self.assertEqual(mapper.cancel(19, "987654321").args, (19, "2", "987654321"))
        with self.assertRaises(BrokerContractError):
            mapper.submit(intent(), 100_000_000_000_001, now=NOW)


class MockWorkbook:
    def __init__(self, path, *, generation="gen", mode="UNKNOWN"):
        self.path = path
        self.full_name = str(path)
        self.mode = mode
        self.names = {"BridgeProtocolVersion": "1.0", "BridgeGeneration": generation}
        self.calls = []
        self.threads = []
        self.closed = False

    def read_named(self, name):
        self.threads.append(threading.get_ident())
        return self.names.get(name)

    def write_named(self, name, value):
        self.threads.append(threading.get_ident())
        self.names[name] = value

    def run_macro(self, name):
        self.threads.append(threading.get_ident())
        self.calls.append(name)
        if self.mode == "raise":
            raise ConnectionError("disconnected")
        if self.mode == "hang":
            time.sleep(0.06)
        if self.mode == "hard_hang":
            time.sleep(2.5)
        if self.mode == "incomplete":
            return
        self.names["BridgeResponseRequestID"] = self.names["BridgeRequestID"]
        self.names["BridgeResponseStatus"] = self.mode
        self.names["BridgeResponseValue"] = "broker-1"

    def close(self):
        self.closed = True


class Guard:
    def __init__(self):
        self.used = {}

    def __call__(self, broker, generation, request_id, digest):
        key = (broker, generation if broker == "rakuten" else "global", request_id)
        if key in self.used:
            if self.used[key] != digest:
                raise BridgeError("request ID payload collision")
            return False
        self.used[key] = digest
        return True


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "dedicated.xlsm"
        self.path.write_bytes(b"mock only")

    def test_single_worker_unknown_and_idempotent_no_resend(self):
        book = MockWorkbook(self.path)
        guard = Guard()
        command = RakutenMapper("gen").submit(intent(), 1, now=NOW)
        with ExcelBridge(self.path, "gen", lambda path: book, guard) as bridge:
            first = bridge.execute(command)
            second = bridge.execute(command)
            self.assertEqual(first.status, "UNKNOWN")
            self.assertEqual(first, second)
            self.assertEqual(len(book.calls), 1)
            self.assertEqual(len(set(book.threads)), 1)
            self.assertNotEqual(book.threads[0], threading.get_ident())
            with self.assertRaisesRegex(BridgeError, "generation mismatch"):
                bridge.execute(RakutenMapper("other").submit(intent(), 2, now=NOW))
            with self.assertRaisesRegex(BridgeError, "uncertain"):
                bridge.execute(RakutenMapper("gen").submit(intent(), 2, now=NOW))
        self.assertTrue(book.closed)
        # Durable guard prevents resend even after constructing a new bridge.
        book2 = MockWorkbook(self.path)
        with ExcelBridge(self.path, "gen", lambda path: book2, guard) as bridge:
            self.assertEqual(bridge.execute(command).status, "UNKNOWN")
            self.assertEqual(book2.calls, [])

    def test_busy_disconnect_and_incomplete_response_are_unknown(self):
        for mode in ("BUSY", "raise", "incomplete"):
            book = MockWorkbook(self.path, mode=mode)
            with ExcelBridge(self.path, "gen", lambda path: book, Guard()) as bridge:
                outcome = bridge.execute(RakutenMapper("gen").submit(intent(), 7, now=NOW))
                self.assertEqual(outcome.status, "UNKNOWN")
                self.assertIn("uncertainty", outcome.reason)
                with self.assertRaisesRegex(BridgeError, "uncertain"):
                    bridge.execute(RakutenMapper("gen").submit(intent(), 8, now=NOW))
        book = MockWorkbook(self.path, mode="ACCEPTED")
        with ExcelBridge(self.path, "gen", lambda path: book, Guard()) as bridge:
            self.assertEqual(bridge.execute(RakutenMapper("gen").submit(intent(), 9, now=NOW)).status,
                             "UNKNOWN")

    def test_com_timeout_poison_and_no_retry(self):
        book = MockWorkbook(self.path, mode="hang")
        command = RakutenMapper("gen").submit(intent(), 11, now=NOW)
        with ExcelBridge(self.path, "gen", lambda path: book, Guard()) as bridge:
            result = bridge.execute(command, timeout=0.01)
            self.assertEqual(result.status, "UNKNOWN")
            self.assertEqual(bridge.execute(command), result)
            with self.assertRaisesRegex(BridgeError, "uncertain"):
                bridge.execute(RakutenMapper("gen").submit(intent(), 12, now=NOW))
        self.assertEqual(len(book.calls), 1)

    def test_close_reports_live_com_worker(self):
        book = MockWorkbook(self.path, mode="hard_hang")
        bridge = ExcelBridge(self.path, "gen", lambda path: book, Guard())
        command = RakutenMapper("gen").submit(intent(), 15, now=NOW)
        self.assertEqual(bridge.execute(command, timeout=0.01).status, "UNKNOWN")
        with self.assertRaisesRegex(BridgeError, "still active"):
            bridge.close()
        time.sleep(0.6)
        bridge.close()
        self.assertTrue(book.closed)

    def test_neo_global_request_id_guard_and_wrong_workbook(self):
        guard = Guard()
        command = NeoTradeMapper("gen").submit(intent(), 9, now=NOW)
        with ExcelBridge(self.path, "gen", lambda path: MockWorkbook(path), guard) as bridge:
            self.assertEqual(bridge.execute(command).status, "UNKNOWN")
        same_id_new_generation = NeoTradeMapper("next").submit(intent(), 9, now=NOW)
        with ExcelBridge(self.path, "next", lambda path: MockWorkbook(path, generation="next"), guard) as bridge:
            with self.assertRaisesRegex(BridgeError, "collision"):
                bridge.execute(same_id_new_generation)
        with self.assertRaisesRegex(BridgeError, "generation mismatch"):
            ExcelBridge(self.path, "different", lambda path: MockWorkbook(path), Guard())
        wrong = self.path.parent / "unrelated.xlsm"
        wrong.write_bytes(b"mock only")
        with self.assertRaisesRegex(BridgeError, "different workbook"):
            ExcelBridge(self.path, "gen", lambda path: MockWorkbook(wrong), Guard())

    def test_vba_static_allowlist_and_no_auto_order(self):
        source = (Path(__file__).resolve().parents[1] / "bridge" / "PrivateEngineBridge.bas").read_text(encoding="utf-8")
        self.assertIn("ThisWorkbook.Names", source)
        self.assertIn("Select Case broker &", source)
        self.assertNotIn("Workbook_Open", source.replace("' No Workbook_Open", ""))
        self.assertNotIn("Auto_Open", source)
        self.assertNotIn("Security", source)


if __name__ == "__main__":
    unittest.main()
