"""Engineering-fixture tests for the public CLI facade adapter.

These tests verify routing, parsing and safety boundaries; they are not a
financial validation or a production-data demonstration.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from kabuforge import cli  # noqa: E402


class PublicResearchCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / "bars").mkdir()
        (self.workspace / "recipes").mkdir()
        (self.workspace / "bars" / "manifest.json").write_text("{}", encoding="utf-8")
        (self.workspace / "recipes" / "price.json").write_text('{"lookback":20}', encoding="utf-8")
        (self.workspace / "broker").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, tail):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli._main(["research", "--workspace", str(self.workspace), *tail])
        return json.loads(output.getvalue())

    def test_fixed_operation_catalog_and_cli_routes_to_shared_facade(self):
        expected = {
            "price", "factor", "strategy", "models", "engines", "indicator", "sensitivity",
            "paper-create", "paper-query", "paper-step", "paper-run-all", "broker-create",
            "broker-preview", "broker-readonly",
        }
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade = facade_type.return_value
            facade.run_price_research.return_value = {"readiness": "RESEARCH-ONLY", "pit_guarantee": False}
            result = self._run(["price", "--manifest", "bars/manifest.json", "--recipe", "recipes/price.json"])
        self.assertEqual(set(cli._research_command_names()), expected)
        self.assertFalse(result["pit_guarantee"])
        args = facade.run_price_research.call_args.args
        self.assertEqual(args[0], self.workspace / "bars" / "manifest.json")
        self.assertEqual(args[1], {"lookback": 20})
        self.assertEqual(facade_type.call_args.args[0], self.workspace)

    def test_paths_cannot_escape_workspace(self):
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            with self.assertRaises(ValueError):
                self._run(["price", "--manifest", "..\\outside.json", "--recipe", "recipes/price.json"])
        facade_type.return_value.run_price_research.assert_not_called()

    def test_paper_mutation_requires_both_optins_and_fixed_ids(self):
        report = self.workspace / "bars" / "strategy.json"
        report.write_text("{}", encoding="utf-8")
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade = facade_type.return_value
            facade.create_historical_paper.return_value = {"status": "COMPLETED", "pit_guarantee": False}
            with self.assertRaises(PermissionError):
                self._run(["paper-create", "--confirm-paper", "--manifest", "bars/manifest.json",
                           "--strategy-report", "bars/strategy.json", "--report-sha", "0" * 64,
                           "--call-id", "cli-call", "--idempotency-key", "cli-idem"])
            result = self._run(["--enable-paper", "paper-create", "--confirm-paper", "--manifest",
                                "bars/manifest.json", "--strategy-report", "bars/strategy.json",
                                "--report-sha", "0" * 64, "--call-id", "cli-call",
                                "--idempotency-key", "cli-idem"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(facade.create_historical_paper.call_args.kwargs["enable_paper"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli._main(["research", "--workspace", str(self.workspace), "paper-run-all",
                       "--account-dir", "account", "--call-id", "x", "--idempotency-key", "y"])

    def test_broker_readonly_requires_an_explicit_cli_confirmation(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli._main(["research", "--workspace", str(self.workspace), "broker-readonly",
                       "--broker-workspace", "broker"])
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.check_broker_read_only.return_value = {
                "network_calls": 0, "credential_value_persisted": False}
            result = self._run(["broker-readonly", "--broker-workspace", "broker",
                                "--confirm-read-only"])
        self.assertEqual(result["network_calls"], 0)
        self.assertFalse(facade_type.return_value.check_broker_read_only.call_args.kwargs.get("submit", False))

    def test_cli_reports_failure_stage_and_owned_task_directory(self):
        from framework_v2.research_application import ResearchApplicationError
        task_dir=self.workspace/'research-tasks'/'failed-fixture'
        task_dir.mkdir(parents=True)
        stderr=io.StringIO()
        with patch("framework_v2.research_application.ResearchApplicationService") as facade_type:
            facade_type.return_value.run_price_research.side_effect=ResearchApplicationError(
                "price_research", "fixture failure", task_dir=task_dir)
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                cli.main(["research", "--workspace", str(self.workspace), "price",
                          "--manifest", "bars/manifest.json", "--recipe", "recipes/price.json"])
        failure=json.loads(stderr.getvalue())
        self.assertEqual(failure["stage"], "price_research")
        self.assertEqual(failure["task_dir"], str(task_dir))


if __name__ == "__main__":
    unittest.main()
