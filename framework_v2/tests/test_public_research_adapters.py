"""Engineering-fixture tests for the thin public MCP research adapters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from framework_v2.agent.core import AgentCommandService, TOOLS
from framework_v2.agent.external import EXTERNAL_TOOLS
from framework_v2.agent.mcp import MCPAdapter
from framework_v2.version import get_version


class PublicResearchAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "bars").mkdir()
        (self.root / "recipes").mkdir()
        (self.root / "bars" / "manifest.json").write_text("{}", encoding="utf-8")
        (self.root / "recipes" / "price.json").write_text('{"lookback":20}', encoding="utf-8")
        self.service = AgentCommandService(self.root, enable_paper=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_tools_are_closed_and_keep_original_contracts_and_reserved_hooks(self):
        response = MCPAdapter(self.service, expose_reserved_external=True).request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {item["name"]: item for item in response["result"]["tools"]}
        expected_new = {
            "research_price", "research_factor_diagnostics", "research_factor_strategy",
            "research_model_training", "research_engine_comparison", "research_indicator",
            "research_price_sensitivity", "research_paper_create", "research_paper_query",
            "research_paper_step", "research_paper_run_all", "research_broker_workspace_create",
            "research_broker_order_preview", "research_broker_readonly",
        }
        self.assertTrue(expected_new <= set(tools))
        for name, (risk, spec) in TOOLS.items():
            Draft202012Validator.check_schema(tools[name]["inputSchema"])
            self.assertEqual(tools[name]["inputSchema"]["additionalProperties"], False)
            self.assertEqual(tools[name]["annotations"]["destructiveHint"], False)
            self.assertEqual(tools[name]["annotations"]["readOnlyHint"], risk == 0 or name == "research_broker_readonly")
        self.assertEqual({name for name in tools if name in EXTERNAL_TOOLS}, set(EXTERNAL_TOOLS))
        self.assertTrue(all(tools[name]["description"].find("disabled") >= 0 for name in EXTERNAL_TOOLS))
        self.assertEqual(len(TOOLS) - len(expected_new), 31)
        self.assertTrue(tools["research_broker_readonly"]["annotations"]["openWorldHint"])
        self.assertFalse(tools["research_paper_query"]["annotations"]["openWorldHint"])

    def test_stdio_process_exports_research_tools_and_keeps_r3_disabled(self):
        requests = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"fixture","version":"1"}}},
            {"jsonrpc":"2.0","id":2,"method":"tools/list"},
            {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"submit_order","arguments":{}}},
        ]
        process = subprocess.run([sys.executable,"-B","-m","framework_v2.agent.mcp",
            "--workspace",str(self.root / "stdio-agent"),"--expose-reserved-external"],
            input="".join(json.dumps(item)+"\n" for item in requests), text=True,
            capture_output=True,encoding="utf-8",timeout=30,
            env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
        self.assertEqual(process.returncode,0,process.stderr)
        responses=[json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses),3)
        self.assertEqual(responses[0]["result"]["serverInfo"]["version"],get_version())
        tools={item["name"]:item for item in responses[1]["result"]["tools"]}
        self.assertIn("research_price_sensitivity",tools)
        self.assertTrue(tools["research_broker_readonly"]["annotations"]["openWorldHint"])
        self.assertTrue({"request_order_approval","submit_order","cancel_order"} <= set(tools))
        self.assertTrue(responses[2]["result"]["isError"])

    def test_price_dispatch_uses_explicit_workspace_refs_and_shared_service(self):
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.run_price_research.return_value = {
                "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            result = self.service.call("research_price", {
                "manifest_path": "bars/manifest.json", "recipe_path": "recipes/price.json"})
        self.assertTrue(result["ok"], result)
        facade = facade_type.return_value
        facade.run_price_research.assert_called_once_with(
            self.root / "bars" / "manifest.json", {"lookback": 20})
        self.assertFalse(result["result"]["pit_guarantee"])

    def test_path_escape_and_unknown_fields_are_denied_before_service_call(self):
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            escaped = self.service.call("research_price", {
                "manifest_path": "../outside.json", "recipe_path": "recipes/price.json"})
            extra = self.service.call("research_price", {
                "manifest_path": "bars/manifest.json", "recipe_path": "recipes/price.json",
                "python": "import os"})
        self.assertFalse(escaped["ok"])
        self.assertFalse(extra["ok"])
        facade_type.return_value.run_price_research.assert_not_called()

    def test_paper_is_double_opt_in_and_idempotent(self):
        report = self.root / "bars" / "report.json"
        report.write_text("{}", encoding="utf-8")
        mutation = {"manifest_path": "bars/manifest.json", "strategy_report_path": "bars/report.json",
                    "expected_report_sha256": "0" * 64, "confirm_paper": True}
        self.assertFalse(self.service.call("research_paper_create", mutation,
            agent_call_id="disabled", idempotency_key="disabled-key")["ok"])
        enabled = AgentCommandService(self.root, enable_paper=True)
        self.assertFalse(enabled.call("research_paper_create", {**mutation, "confirm_paper": False},
            agent_call_id="missing-confirm", idempotency_key="missing-confirm-key")["ok"])
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.create_historical_paper.return_value = {
                "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            first = enabled.call("research_paper_create", mutation,
                agent_call_id="paper-create-1", idempotency_key="paper-create-key")
            second = enabled.call("research_paper_create", mutation,
                agent_call_id="paper-create-retry", idempotency_key="paper-create-key")
        self.assertTrue(first["ok"], first)
        self.assertEqual(first, second)
        facade_type.return_value.create_historical_paper.assert_called_once()
        call_kwargs = facade_type.return_value.create_historical_paper.call_args.kwargs
        self.assertTrue(call_kwargs["enable_paper"])
        self.assertEqual(call_kwargs["call_id"], "paper-create-1")
        self.assertEqual(call_kwargs["idempotency_key"], "paper-create-key")

    def test_query_and_readonly_are_never_implicit_capability_probes(self):
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            capabilities = self.service.call("get_capabilities")
            facade_type.assert_not_called()
            facade = facade_type.return_value
            facade.query_historical_paper.return_value = {"cursor": 0, "pit_guarantee": False}
            queried = self.service.call("research_paper_query", {"account_dir": "paper/account"})
            self.assertTrue(queried["ok"], queried)
            facade.query_historical_paper.assert_called_once_with(self.root / "paper" / "account", include_events=False)
            # Read-only broker GETs require an explicit confirmation field and are
            # never run as part of get_capabilities/doctor or tool discovery.
            facade.check_broker_read_only.return_value = {"network_calls": 0, "readiness": "NOT_CONNECTED"}
            self.assertFalse(self.service.call("research_broker_readonly", {
                "broker_workspace": "broker", "confirm_read_only": False})["ok"])
            facade.check_broker_read_only.assert_not_called()
            explicit = self.service.call("research_broker_readonly", {
                "broker_workspace": "broker", "confirm_read_only": True})
        self.assertTrue(capabilities["ok"])
        self.assertTrue(explicit["ok"], explicit)
        facade_type.return_value.check_broker_read_only.assert_called_once()
        self.assertEqual(explicit["result"]["network_calls"], 0)

    def test_indicator_default_is_pandas_ta_and_provider_is_static(self):
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.run_indicator_research.return_value = {
                "provider": "pandas-ta", "pit_guarantee": False}
            response = self.service.call("research_indicator", {
                "manifest_path": "bars/manifest.json", "code": "7203"})
            invalid = self.service.call("research_indicator", {
                "manifest_path": "bars/manifest.json", "code": "7203", "provider": "arbitrary.module"})
        self.assertTrue(response["ok"], response)
        self.assertFalse(invalid["ok"])
        kwargs = facade_type.return_value.run_indicator_research.call_args.kwargs
        self.assertEqual(kwargs["provider"], "pandas-ta")
        self.assertEqual(kwargs["sma_period"], 20)

    def test_explicit_missing_broker_env_reference_fails_with_zero_gets(self):
        import os
        import socket
        from unittest.mock import patch
        from framework_v2.broker_research import BrokerResearchConfig, create_broker_workspace
        broker_dir = self.root / "broker-config"
        create_broker_workspace(broker_dir, BrokerResearchConfig(
            environment="test", endpoint="http://127.0.0.1:18081", account_id="fixture",
            account_type=2, exchange=9, credential_ref="env:KABUFORGE_TEST_MISSING_KEY"))
        with patch.dict(os.environ, {"KABUFORGE_TEST_MISSING_KEY": ""}), \
             patch.object(socket.socket, "connect", side_effect=AssertionError("GET must not run")):
            response = self.service.call("research_broker_readonly", {
                "broker_workspace": "broker-config", "confirm_read_only": True})
        self.assertTrue(response["ok"], response)
        check = response["result"]["result"]["check"]
        self.assertEqual(check["failure_code"], "credential_missing")
        self.assertEqual(check["network_calls"], 0)
        self.assertFalse(check["credential_value_persisted"])

    def test_sensitivity_is_a_pinned_service_call_not_a_new_recipe(self):
        run_dir = self.root / "published-run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text("{}", encoding="utf-8")
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.run_price_sensitivity.return_value = {
                "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            response = self.service.call("research_price_sensitivity", {
                "run_directory": "published-run", "expected_report_sha256": "a" * 64})
        self.assertTrue(response["ok"], response)
        facade_type.return_value.run_price_sensitivity.assert_called_once_with(
            run_dir, expected_report_sha256="a" * 64)

    def test_broker_workspace_adapter_rejects_nonlocal_endpoint_before_service_write(self):
        config = {"environment": "test", "endpoint": "https://broker.example.invalid",
            "account_id": "fixture", "account_type": 2, "exchange": 9,
            "credential_ref": "env:KABUFORGE_FIXTURE_KEY"}
        (self.root / "recipes" / "broker.json").write_text(json.dumps(config), encoding="utf-8")
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            response = self.service.call("research_broker_workspace_create", {
                "config_path": "recipes/broker.json"})
        self.assertFalse(response["ok"])
        facade_type.return_value.create_broker_workspace.assert_not_called()

    def test_failed_research_operation_returns_only_workspace_relative_stage_evidence(self):
        from framework_v2.research_application import ResearchApplicationError
        task_dir = self.root / "research-tasks" / "job-fixture"
        task_dir.mkdir(parents=True)
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.run_price_research.side_effect = ResearchApplicationError(
                "price_research", "fixture failure", task_dir=task_dir)
            response = self.service.call("research_price", {
                "manifest_path": "bars/manifest.json", "recipe_path": "recipes/price.json"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["evidence"], {
            "stage": "price_research", "task_ref": "research-tasks/job-fixture"})
        self.assertNotIn(str(self.root), json.dumps(response))


if __name__ == "__main__":
    unittest.main()
