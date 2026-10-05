"""Artificial broker fixtures test mapping and injected GET boundaries only."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import framework_v2.broker_readonly as readonly_module
import framework_v2.broker_research as broker_module
import framework_v2.brokers as mapping_module
import framework_v2.execution as execution_module
from framework_v2.broker_research import (
    BrokerResearchConfig,
    BrokerResearchError,
    NoCallTransport,
    create_broker_workspace,
    load_broker_workspace,
    preview_order,
)
from framework_v2.execution import Instrument, OrderIntent
from framework_v2.broker_readonly import ALLOWED_GET_PATHS, BrokerReadOnlyError, check_read_only


NOW = datetime(2026, 10, 6, 10, 30, tzinfo=timezone(timedelta(hours=9)))


def config(**overrides):
    values = dict(environment="test", endpoint="http://127.0.0.1:18081",
                  account_id="teaching-account", account_type=4, exchange=9,
                  credential_ref="env:KABU_TEACHING_TOKEN")
    values.update(overrides)
    return BrokerResearchConfig(**values)


def order(*, kind="market", price=None, quantity=100, account_id="teaching-account", code="7203"):
    return OrderIntent("intent-1", "idem-1", account_id, "revision-1", "decision-1",
                       "strategy-sha", code, "buy", quantity, kind,
                       None if price is None else Decimal(str(price)), "DAY", NOW,
                       datetime(2026, 10, 7, tzinfo=NOW.tzinfo), Decimal("1000"), Decimal("0"))


class BrokerResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (readonly_module, broker_module, mapping_module, execution_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = create_broker_workspace(Path(self.temp.name) / "new-workspace", config())
        self.instrument = Instrument("7203", 100, Decimal("0.5"))
        self.transport = NoCallTransport()

    def test_config_roundtrip_and_market_preview_are_local(self):
        self.assertEqual(load_broker_workspace(self.workspace), config())
        path = preview_order(self.workspace, order(), self.instrument, now=NOW,
                             transport=self.transport)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "MAPPED_LOCALLY_NOT_CONNECTED_NOT_SUBMITTED")
        self.assertEqual(receipt["network_calls"], 0)
        self.assertFalse(receipt["credential_resolved"])
        self.assertEqual(receipt["mapped_request"]["Symbol"], "7203")
        self.assertEqual(receipt["mapped_request"]["Qty"], 100)
        self.assertEqual(receipt["mapped_request"]["Price"], 0)
        self.assertEqual(receipt["mapped_request"]["ExpireDay"], 20261006)
        self.assertTrue(receipt["input_sha256"])
        self.assertTrue(receipt["mapping_sha256"])
        self.assertTrue(receipt["source_sha256"]["brokers.py"])
        self.assertIn("kabusapi", receipt["spec_reference"])
        from framework_v2.broker_research import _canonical_bytes
        import hashlib
        self.assertEqual(receipt["input_sha256"], hashlib.sha256(_canonical_bytes(receipt["input"])).hexdigest())
        self.assertEqual(self.transport.calls, 0)

    def test_user_controlled_intent_id_cannot_escape_workspace(self):
        hostile = order()
        hostile = OrderIntent("../outside\\nested", hostile.idempotency_key, hostile.account_id,
            hostile.account_revision, hostile.decision_identity, hostile.strategy_hash, hostile.code,
            hostile.side, hostile.quantity, hostile.order_type, hostile.limit_price,
            hostile.time_in_force, hostile.created_at, hostile.valid_until,
            hostile.estimated_price, hostile.estimated_fee)
        path = preview_order(self.workspace, hostile, self.instrument, now=NOW,
                             transport=self.transport)
        self.assertEqual(path.parent.resolve(), self.workspace.resolve())
        self.assertRegex(path.name, r"^preview-[0-9a-f]{64}\.json$")
        self.assertFalse((Path(self.temp.name) / "outside").exists())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["intent_id"], hostile.intent_id)
        self.assertEqual(self.transport.calls, 0)

    def test_limit_order_tick_and_exact_payload(self):
        path = preview_order(self.workspace, order(kind="limit", price="1000.5"),
                             self.instrument, now=NOW)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["mapped_request"]["FrontOrderType"], 20)
        self.assertEqual(receipt["mapped_request"]["Price"], 1000.5)

    def test_rejects_lot_tick_expiry_and_account_without_transport(self):
        cases = [
            (order(quantity=150), self.instrument, NOW, "lot size"),
            (order(kind="limit", price="1000.2"), self.instrument, NOW, "tick size"),
            (order(), Instrument("7203", 100, Decimal("0.5"), NOW), NOW, "expired"),
            (order(account_id="different-account"), self.instrument, NOW, "account_id"),
        ]
        for intent, instrument, now, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(BrokerResearchError, message):
                preview_order(self.workspace, intent, instrument, now=now, transport=self.transport)
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(list(self.workspace.glob("preview-*.json")), [])

    def test_rejects_bad_environment_endpoint_exchange_and_credential_value(self):
        invalid = [
            {"environment": "staging"},
            {"environment": "production", "endpoint": "http://127.0.0.1:18081"},
            {"endpoint": "http://example.com:18081"},
            {"endpoint": "http://user:secret@127.0.0.1:18081"},
            {"exchange": 1},
            {"credential_ref": "super-secret-token-value"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(BrokerResearchError):
                config(**changes)

    def test_environment_proxy_is_never_consulted_and_workspace_never_overwritten(self):
        prior = os.environ.get("HTTP_PROXY")
        os.environ["HTTP_PROXY"] = "http://remote.invalid:8080"
        try:
            preview_order(self.workspace, order(), self.instrument, now=NOW,
                          transport=self.transport)
        finally:
            if prior is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = prior
        self.assertEqual(self.transport.calls, 0)
        with self.assertRaisesRegex(BrokerResearchError, "new"):
            create_broker_workspace(self.workspace, config())

    def test_saved_config_unknown_fields_fail_closed(self):
        path = self.workspace / "broker_config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["config"]["password"] = "should-not-be-accepted"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(BrokerResearchError, "unknown or incomplete"):
            load_broker_workspace(self.workspace)
        with self.assertRaises(BrokerResearchError):
            preview_order(self.workspace, order(), self.instrument, now=NOW,
                          transport=self.transport)
        self.assertEqual(self.transport.calls, 0)

    def test_boolean_schema_version_is_not_integer_version_one(self):
        path = self.workspace / "broker_config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(BrokerResearchError, "unknown broker configuration schema"):
            load_broker_workspace(self.workspace)

    def test_explicit_readonly_missing_environment_reference_performs_zero_gets(self):
        calls = []
        with self.assertRaises(BrokerReadOnlyError) as caught:
            check_read_only(config(), credential_resolver=lambda _reference: None,
                            requester=lambda path: calls.append(path))
        self.assertEqual(caught.exception.code, "credential_missing")
        self.assertEqual(caught.exception.attempted_paths, ())
        self.assertEqual(calls, [])

    def test_explicit_readonly_uses_only_three_injected_gets_and_redacts_values(self):
        calls = []
        bodies = {
            ALLOWED_GET_PATHS[0]: b'{"StockAccountWallet":{}}',
            ALLOWED_GET_PATHS[1]: b'[]',
            ALLOWED_GET_PATHS[2]: b'[]',
        }

        def requester(path):
            calls.append(path)
            return 200, bodies[path]

        result = check_read_only(config(),
            credential_resolver=lambda reference: "fixture-token-not-a-secret"
                if reference == "env:KABU_TEACHING_TOKEN" else None,
            requester=requester)
        self.assertEqual(calls, list(ALLOWED_GET_PATHS))
        self.assertEqual(result["network_calls"], 3)
        self.assertTrue(result["credential_resolved"])
        self.assertFalse(result["credential_value_persisted"])
        self.assertFalse(result["account_values_persisted"])
        self.assertEqual([item["method"] for item in result["requests"]], ["GET"] * 3)
        encoded = json.dumps(result)
        self.assertNotIn("fixture-token-not-a-secret", encoded)
        self.assertNotIn("StockAccountWallet", encoded)


if __name__ == "__main__":
    unittest.main()
