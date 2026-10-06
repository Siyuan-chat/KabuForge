"""Artificial engineering fixtures verify the shared, workspace-local research facade."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import framework_v2.factor_research as factor_research_module
import framework_v2.indicator_research_worker as indicator_worker_module
import framework_v2.price_research as price_research_module
import framework_v2.research_application as application_module
from framework_v2.research_application import ResearchApplicationError, ResearchApplicationService


class ResearchApplicationTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (application_module, factor_research_module, price_research_module,
                       indicator_worker_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")

    def test_capabilities_are_conservative_and_indicator_gap_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            service = ResearchApplicationService(temp)
            with patch("framework_v2.research_runtime.resolve_extension_runtime",
                       return_value={"enabled": False, "paths": [], "reason": "isolated runtime test unavailable"}):
                report = service.capabilities()
            self.assertFalse(report["pit_guarantee"])
            self.assertTrue(report["available"]["factor_diagnostics"])
            self.assertTrue(report["available"]["broker_offline_preview"])
            self.assertFalse(report["available"]["indicator_research"])
            self.assertNotIn("ATR seed", report["unavailable_reasons"]["indicator_research"])
            with patch("framework_v2.research_application.ResearchApplicationService._extension_runtime",
                       return_value={"enabled": False, "paths": [], "reason": "isolated runtime test unavailable"}):
                with self.assertRaisesRegex(ResearchApplicationError, "isolated runtime test unavailable"):
                    source = Path(temp) / "manifest.json"
                    source.write_text("{}", encoding="utf-8")
                    service.run_indicator_research(source, "7203")

    def test_indicator_research_uses_fixed_isolated_worker_and_receipt_verified_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page_rows = []
            start = datetime(2022, 1, 3)
            for offset in range(55):
                close = 100.0 + offset * 0.25 + (offset % 4) * 0.1
                page_rows.append({"Date": (start + timedelta(days=offset)).strftime("%Y%m%d"),
                    "Code": "72030", "Open": close - 0.2, "High": close + 1.0,
                    "Low": close - 1.0, "Close": close, "AdjustmentFactor": 1.0})
            page_bytes = json.dumps(page_rows, separators=(",", ":")).encode("utf-8")
            page = root / "page.json"; page.write_bytes(page_bytes)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "kind": "jquants_equities_daily_bars",
                "status": "complete", "request": {"codes": ["72030"], "start": "2022-01-01",
                "end": "2022-12-31"}, "pages": [{"code": "72030", "file": "page.json",
                "sha256": hashlib.sha256(page_bytes).hexdigest(), "row_count": len(page_rows)}]}), encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")
            selected_runtime = service._extension_runtime("indicators", {"provider": "pandas-ta"})
            if not selected_runtime.get("enabled"):
                reason = selected_runtime.get("reason", "selected pandas-ta provider is unavailable")
                self.assertTrue(reason)
                with self.assertRaises(ResearchApplicationError) as raised:
                    service.run_indicator_research(manifest, "7203", sma_period=5,
                        rsi_period=5, atr_period=5)
                self.assertIn(reason, str(raised.exception))
                return
            project_root = Path(__file__).resolve().parents[2]
            workspace = root / "workspace"
            isolated_code = r'''import json, socket, sys
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
manifest = Path(sys.argv[2]).resolve()
workspace = Path(sys.argv[3]).resolve()
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))

def deny_network(*args, **kwargs):
    raise AssertionError("network is forbidden in the offline facade test")

socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
import framework_v2.research_application as application_module
from framework_v2.research_application import ResearchApplicationService

if not Path(application_module.__file__).resolve().is_relative_to(project_root):
    raise AssertionError(f"facade import escaped candidate source: {application_module.__file__}")
if "pandas_ta" in sys.modules:
    raise AssertionError("facade imported pandas-ta before the isolated worker ran")
service = ResearchApplicationService(workspace)
capabilities = service.capabilities()
if not capabilities["available"]["indicator_research"]:
    raise RuntimeError(capabilities["unavailable_reasons"]["indicator_research"])
response = service.run_indicator_research(manifest, "7203", sma_period=5,
    rsi_period=5, atr_period=5)
parent_loaded_provider = "pandas_ta" in sys.modules
print("RESEARCH_APPLICATION_RESULT=" + json.dumps({
    "response": response,
    "pandas_ta_loaded_in_facade_process": parent_loaded_provider,
}, allow_nan=False, separators=(",", ":")))
'''
            allowed_environment = {
                "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "TEMP", "TMP",
                "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
                "PROGRAMDATA",
            }
            isolated_env = {key: value for key, value in os.environ.items()
                if key.upper() in allowed_environment}
            isolated_env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8"})
            process = subprocess.run(
                [sys.executable, "-I", "-B", "-c", isolated_code,
                 str(project_root), str(manifest), str(workspace)],
                cwd=project_root, env=isolated_env, text=True, capture_output=True,
                encoding="utf-8", timeout=180,
            )
            self.assertEqual(process.returncode, 0,
                f"isolated offline facade failed\nstdout={process.stdout[-4000:]}\nstderr={process.stderr[-4000:]}")
            result_lines = [line[len("RESEARCH_APPLICATION_RESULT="):]
                for line in process.stdout.splitlines()
                if line.startswith("RESEARCH_APPLICATION_RESULT=")]
            self.assertEqual(len(result_lines), 1, process.stdout[-4000:])
            isolated_result = json.loads(result_lines[0])
            self.assertFalse(isolated_result["pandas_ta_loaded_in_facade_process"])
            response = isolated_result["response"]
            self.assertEqual(response["status"], "COMPLETED")
            self.assertFalse(response["pit_guarantee"])
            self.assertEqual(response["readiness"], "RESEARCH-ONLY")
            task = Path(response["task_dir"])
            self.assertTrue(task.resolve().is_relative_to(service.workspace))
            launch = json.loads((task / "indicator_worker_launch.json").read_text(encoding="utf-8"))
            self.assertIn("framework_v2.indicator_research_worker", launch["argv"])
            self.assertEqual(launch["source_manifest_sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(launch["credentials"], "not read or resolved")
            self.assertIn("not requested", launch["network"])
            completion = json.loads((task / "indicator_worker_completion.json").read_text(encoding="utf-8"))
            self.assertEqual(completion["exit_code"], 0)
            self.assertFalse(completion["timed_out"])
            artifact = Path(response["result"]["artifact_path"])
            self.assertTrue(artifact.resolve().is_relative_to(service.workspace))
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(payload["engine"]["name"], "pandas-ta")
            self.assertEqual(payload["security_code"], "72030")
            self.assertEqual(len(payload["rows"]), len(page_rows))
            self.assertEqual(response["artifacts"][0]["sha256"], response["result"]["artifact_sha256"])

    def test_indicator_facade_subprocess_protocol_is_static_and_workspace_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / "runtime"; runtime.mkdir()
            manifest = root / "manifest.json"; manifest.write_text("{}", encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")

            class FakeProcess:
                pid = 12345
                def __init__(self, argv, *, cwd, env, stdin, stdout, stderr):
                    self.argv = argv
                    self.cwd = Path(cwd)
                    self.env = env
                    type(self).captured_env = dict(env)
                    self.stdout = stdout
                    self.stderr = stderr
                    self.return_code = 0
                    self.output = Path(argv[argv.index("--output-dir") + 1])
                    self.params = {name: int(argv[argv.index(option) + 1]) for name, option in (
                        ("sma_period", "--sma-period"), ("rsi_period", "--rsi-period"),
                        ("atr_period", "--atr-period"))}
                    payload = {"schema":"kabuforge_indicator_research", "schema_version":2,
                        "readiness":"RESEARCH-ONLY", "pit_guarantee":False,
                        "source_manifest_sha256":hashlib.sha256(manifest.read_bytes()).hexdigest(),
                        "security_code":"72030", "parameters":{**self.params,
                            "macd":{"fast":12,"slow":26,"signal":9}},
                        "engine":{"name":"pandas-ta"}, "rows":[{"date":"2022-01-03"}]}
                    encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
                    artifact = self.output / "indicator-test.json"
                    artifact.write_bytes(encoded)
                    result = {"ok":True, "artifact_path":str(artifact),
                        "artifact_sha256":hashlib.sha256(encoded).hexdigest(),
                        "input_sha256":"a"*64, "engine":"pandas-ta", "version":"test",
                        "row_count":1, "manifest_sha256":payload["source_manifest_sha256"],
                        "pit_guarantee":False}
                    stdout.write(("INDICATOR_RESULT=" + json.dumps(result) + "\n").encode("utf-8"))
                    stdout.flush()
                def wait(self, timeout=None):
                    self.timeout = timeout
                    return self.return_code

            with patch.object(service, "_extension_runtime", return_value={"enabled":True,
                       "paths":[str(runtime)], "versions":{"pandas_ta":"test"}}), \
                 patch("framework_v2.research_application.subprocess.Popen", FakeProcess), \
                 patch.dict(os.environ, {"KABU_TOKEN":"test-secret-never-forwarded"}, clear=False):
                result = service.run_indicator_research(manifest, "7203")
            self.assertNotIn("KABU_TOKEN", FakeProcess.captured_env)
            self.assertEqual(result["status"], "COMPLETED")
            launch = json.loads((Path(result["task_dir"]) / "indicator_worker_launch.json").read_text())
            self.assertEqual(launch["argv"][3], "framework_v2.indicator_research_worker")
            self.assertEqual(launch["argv"][-6:], ["--sma-period","20","--rsi-period","14","--atr-period","14"])
            self.assertEqual(launch["pid"], 12345)
            self.assertEqual(result["result"]["row_count"], 1)
            self.assertTrue(Path(result["result"]["artifact_path"]).resolve().is_relative_to(service.workspace))
            self.assertFalse((Path(result["task_dir"]) / "research-application").exists())

    def test_workspace_output_paths_reject_external_junction_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"; workspace.mkdir()
            external = root / "external"; external.mkdir()
            source = root / "manifest.json"; source.write_text("{}", encoding="utf-8")
            service = ResearchApplicationService(workspace)
            junction = workspace / "factor-research"
            if os.name == "nt":
                pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
                self.assertIsNotNone(pwsh, "PowerShell 7 is required to create a Windows junction fixture")
                env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "TEMP", "TMP") if key in os.environ}
                env.update({"KABU_TEST_JUNCTION":str(junction), "KABU_TEST_TARGET":str(external)})
                script = "New-Item -ItemType Junction -Path $env:KABU_TEST_JUNCTION -Target $env:KABU_TEST_TARGET | Out-Null"
                created = subprocess.run([pwsh, "-NoLogo", "-NoProfile", "-Command", script],
                                         env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(created.returncode, 0, created.stderr)
            else:
                junction.symlink_to(external, target_is_directory=True)
                self.assertTrue(junction.is_symlink(), "the POSIX containment fixture must be a real symlink")
            try:
                with patch("framework_v2.factor_research.run_factor_research") as core:
                    with self.assertRaisesRegex(ResearchApplicationError, "inside the selected workspace"):
                        service.run_factor_diagnostics(source)
                core.assert_not_called()
                self.assertEqual(list(external.iterdir()), [])
                self.assertTrue(list((workspace / "research-tasks").glob("*/failure.json")))
            finally:
                junction.unlink(missing_ok=True)

    def test_returned_artifacts_must_resolve_inside_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = ResearchApplicationService(root / "workspace")
            task = service.workspace / "research-tasks" / "example"
            task.mkdir(parents=True)
            external = root / "external.json"; external.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside the selected workspace"):
                service._artifact_refs([external], task)

    def test_factor_diagnostics_freeze_request_and_write_only_to_new_workspace_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bars-manifest.json"
            source.write_text('{"fixture_provenance":"engineering-only"}', encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")

            def fake_factor(manifest, output, recipe):
                output.mkdir(parents=True)
                artifacts = {}
                for name in ("contract", "report", "feature_rows", "evaluation_panel"):
                    artifact = output / f"{name}.json"
                    artifact.write_text("{}", encoding="utf-8")
                    artifacts[name] = str(artifact)
                return {"status": "COMPLETED", "recipe": recipe, "artifacts": artifacts}

            with patch("framework_v2.factor_research.run_factor_research", side_effect=fake_factor) as core:
                response = service.run_factor_diagnostics_task(source)
            task = Path(response["task_dir"])
            self.assertTrue(task.is_relative_to(service.workspace))
            request = json.loads((task / "application_request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["operation"], "factor_diagnostics")
            self.assertEqual(request["request"]["manifest"]["sha256"],
                             __import__("hashlib").sha256(source.read_bytes()).hexdigest())
            self.assertTrue((task / "completion.json").is_file())
            self.assertEqual(len(response["artifacts"]), 4)
            core.assert_called_once()

    def test_factor_diagnostics_preserves_existing_direct_report_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bars-manifest.json"
            source.write_text("{}", encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")
            def fake_factor(_manifest, output, _recipe):
                output.mkdir(parents=True)
                paths = {}
                for name in ("contract", "report", "feature_rows", "evaluation_panel"):
                    artifact = output / f"{name}.json"
                    artifact.write_text("{}", encoding="utf-8")
                    paths[name] = str(artifact)
                return {"status": "COMPLETED", "artifacts": paths}
            with patch("framework_v2.factor_research.run_factor_research", side_effect=fake_factor):
                returned = service.run_factor_diagnostics(source)
            self.assertEqual(returned["status"], "COMPLETED")
            self.assertTrue(Path(returned["artifacts"]["contract"]).is_file())

    def test_price_service_uses_frozen_public_off_preflight_and_same_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "bars.json"
            manifest.write_text("{}", encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")
            preflight = {"fingerprint": "fp-fixed", "input_hash": "input-fixed",
                         "regime_observer": {"mode": "off", "availability": "not_configured"}}

            def fake_run(_manifest, _recipe, output, *, regime_observer, expected_preflight):
                self.assertEqual(expected_preflight, "fp-fixed")
                output.mkdir(parents=True)
                path = output / "report.json"
                path.write_text('{"readiness":"RESEARCH-ONLY","pit_guarantee":false}', encoding="utf-8")
                (output / "research_inputs.json").write_text("{}", encoding="utf-8")
                return path

            with patch("framework_v2.price_research.preflight_price_research", return_value=preflight), \
                 patch("framework_v2.price_research.run_price_research", side_effect=fake_run) as core:
                response = service.run_price_research(manifest, {"signal_template": "price_momentum"})
            self.assertEqual(response["result"]["preflight_fingerprint"], "fp-fixed")
            self.assertEqual(response["result"]["report"]["readiness"], "RESEARCH-ONLY")
            core.assert_called_once()

    def test_public_price_preflight_none_equals_exact_off_and_rejects_private_fields_before_read(self):
        from framework_v2.price_research import preflight_price_research

        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "input.json"
            manifest.write_text("{}", encoding="utf-8")
            rows = [{"code":"4502","date":day,"open":price,"close":price,
                     "adjustment_factor":1.0}
                    for day,price in (("2024-01-02",10.0),("2024-01-03",11.0),
                                      ("2024-01-04",12.0),("2024-01-05",13.0))]
            recipe = {"signal_template":"price_momentum","lookback":2,"count":1,
                      "frequency":"daily","cash":1000.0,"fee":0.1}
            none = preflight_price_research(manifest, recipe, None, _rows=rows)
            off = preflight_price_research(manifest, recipe, {"mode":"off"}, _rows=rows)
            self.assertEqual(none["fingerprint"], off["fingerprint"])
            self.assertEqual(none["regime_observer"], {"mode":"off","availability":"not_configured"})

            missing = Path(temp) / "must-not-be-read.json"
            invalid_cases = (
                ({"mode":"observe"}, recipe),
                ({"mode":"off","bridge":"private"}, recipe),
                (None, {**recipe,"regime_mode":"observe"}),
                (None, {**recipe,"regime_bridge":{"enabled":True}}),
            )
            with patch("framework_v2.price_research._load_price_research_input",
                       side_effect=AssertionError("input reader must not run before Off validation")) as loader:
                for observer, invalid_recipe in invalid_cases:
                    with self.subTest(observer=observer, recipe=invalid_recipe), \
                         self.assertRaisesRegex(ValueError, "Regime|bridge"):
                        preflight_price_research(missing, invalid_recipe, observer)
                loader.assert_not_called()

    def test_model_operation_builds_closed_static_worker_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"; manifest.write_text("{}", encoding="utf-8")
            factor = root / "factor-run"; factor.mkdir()
            for name in ("contract.json", "report.json", "feature_rows.json", "evaluation_panel.json"):
                (factor / name).write_text("{}", encoding="utf-8")
            service = ResearchApplicationService(root / "workspace")

            class FakeProcess:
                pid = 9876
                def __init__(self, argv, **kwargs):
                    self.argv = argv
                    args = iter(argv)
                    options = {key: next(args, None) for key in ()}
                    job_id = argv[argv.index("--job-id") + 1]
                    workspace = Path(argv[argv.index("--workspace") + 1])
                    job_dir = workspace / "research-studio" / "jobs" / job_id
                    request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
                    self.request = request
                    self.job_dir = job_dir
                def wait(self):
                    (self.job_dir / "result.json").write_text(json.dumps({
                        "schema": "kabuforge.research_studio_result.v1", "status": "COMPLETED",
                        "operation": self.request["operation"], "readiness": "RESEARCH-ONLY",
                        "pit_guarantee": False}), encoding="utf-8")
                    return 0

            # Static worker-protocol tests use a fake capability response. They
            # must not depend on LightGBM/scikit-learn being installed.
            capability = {"enabled": True, "paths": [],
                "versions": {"lightgbm": "fixture-only", "scikit-learn": "fixture-only"},
                "reason": "explicit test capability fixture"}
            with patch.object(service, "_extension_runtime", return_value=capability) as probe, \
                 patch("framework_v2.research_application.subprocess.Popen", FakeProcess):
                response = service.run_model_training(manifest, factor, ["lightgbm"])
            self.assertEqual(probe.call_count, 2)
            probe.assert_any_call("model-training", {"model_names": ["lightgbm"]})
            req = json.loads((Path(response["task_dir"]) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(req["operation"], "model_training")
            self.assertEqual(req["model_names"], ["lightgbm"])
            self.assertEqual(set(req), {"schema", "job_id", "operation", "manifest_path", "manifest_sha256",
                                        "factor_run_dir", "factor_bundle_sha256", "model_names"})
            self.assertEqual(response["status"], "COMPLETED")

    def test_static_worker_rejects_non_allowlisted_operation(self):
        with tempfile.TemporaryDirectory() as temp:
            service = ResearchApplicationService(temp)
            with self.assertRaisesRegex(ValueError, "static worker allowlist"):
                service._run_static_worker("run_arbitrary_code", {}, {})

    def test_paper_mutations_require_double_opt_in_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            off = ResearchApplicationService(root / "disabled")
            with self.assertRaises(PermissionError):
                off.advance_historical_paper("account", expected_cursor=0, enable_paper=True,
                    call_id="c0", idempotency_key="k0")
            self.assertFalse((off.workspace / "research-application").exists())

            service = ResearchApplicationService(root / "enabled", enable_paper=True)
            account = service.workspace / "paper-account"; account.mkdir()
            class Paper:
                calls = 0
                def step_next(self, *, idempotency_key, expected_cursor):
                    self.calls += 1
                    return {"at": "2022-01-04", "cursor": expected_cursor, "idempotency_key": idempotency_key}
                def summary(self):
                    return {"cursor": 1, "total_dates": 2, "status": "IN_PROGRESS"}
            paper = Paper()
            with patch("framework_v2.historical_paper_research.open_historical_paper_research", return_value=paper):
                first = service.advance_historical_paper(account, expected_cursor=0, enable_paper=True,
                    call_id="call-1", idempotency_key="idem-1")
                retry = service.advance_historical_paper(account, expected_cursor=0, enable_paper=True,
                    call_id="call-1", idempotency_key="idem-1")
                self.assertEqual(first, retry)
                with self.assertRaisesRegex(ResearchApplicationError, "idempotency key conflicts"):
                    service.advance_historical_paper(account, expected_cursor=1, enable_paper=True,
                        call_id="call-2", idempotency_key="idem-1")
            self.assertEqual(paper.calls, 1)
            self.assertTrue(list((service.workspace / "research-tasks").glob("*/completion.json")))

    def test_paper_query_is_read_only_and_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = ResearchApplicationService(root / "workspace")
            external = root / "external-account"; external.mkdir()
            with self.assertRaisesRegex(ValueError, "inside the selected workspace"):
                service.query_historical_paper(external)
            account = service.workspace / "account"; account.mkdir()
            class Paper:
                def summary(self): return {"cursor": 0, "total_dates": 1}
                def events(self): return []
                def complete(self): return False
                def cursor(self): return 0
            with patch("framework_v2.historical_paper_research.open_historical_paper_research", return_value=Paper()):
                query = service.query_historical_paper(account, include_events=True)
            self.assertEqual(query["cursor"], 0)
            self.assertFalse(query["complete"])
            self.assertFalse((service.workspace / "research-application").exists())

    def test_broker_config_and_preview_use_pure_local_transport(self):
        from framework_v2.broker_research import BrokerResearchConfig
        from framework_v2.execution import Instrument, OrderIntent

        with tempfile.TemporaryDirectory() as temp:
            service = ResearchApplicationService(Path(temp) / "workspace")
            config = BrokerResearchConfig("test", "http://127.0.0.1:18081", "teach", 2, 9,
                                          "env:KABU_TOKEN")
            created = service.create_broker_workspace(config)
            broker_dir = Path(created["result"]["workspace"])
            now = datetime(2024, 1, 4, 9, 0, tzinfo=timezone(timedelta(hours=9)))
            intent = OrderIntent("intent-1", "order-key-1", "teach", "rev1", "decision1", "strategy1",
                "6758", "buy", 100, "market", None, "DAY", now,
                datetime(2024, 1, 5, 0, 0, tzinfo=now.tzinfo),
                Decimal("1000"), Decimal("1"))
            instrument = Instrument("6758", 100, Decimal("1"))
            response = service.preview_broker_order(broker_dir, intent, instrument, now=now)
            receipt = response["result"]["receipt"]
            self.assertEqual(receipt["network_calls"], 0)
            self.assertFalse(receipt["credential_resolved"])
            self.assertFalse(response["result"]["submitted"])
            self.assertEqual(receipt["credential_ref"], "env:KABU_TOKEN")
            self.assertTrue(Path(response["task_dir"]).is_relative_to(service.workspace))
            self.assertTrue((Path(response["task_dir"]) / "completion.json").is_file())


if __name__ == "__main__":
    unittest.main()
