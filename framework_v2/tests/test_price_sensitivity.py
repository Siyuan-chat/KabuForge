"""Artificial fixed bars exercise sensitivity replay contracts, not market outcomes."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import contextlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import framework_v2.price_research as price_research_module
import framework_v2.price_sensitivity as sensitivity_module
import framework_v2.price_sensitivity_worker as sensitivity_worker_module
from framework_v2.price_research import research_bars
from framework_v2.price_sensitivity import run_price_sensitivity, SCENARIOS
from framework_v2.price_sensitivity_worker import REQUEST_SCHEMA, _install_offline_guards, _read_request, main


def _write_source_run(folder: Path, *, fee=0.1):
    folder.mkdir(parents=True, exist_ok=True)
    days=[]; current=date(2024,1,2)
    while len(days)<4:
        if current.weekday()<5: days.append(current.isoformat())
        current += timedelta(days=1)
    closes=[10.0,11.0,12.0,13.0]
    opens=[10.0,10.0,11.0,12.0]
    bars=[{"code":"4502","date":day,"open":opens[i],"close":closes[i],
           "adjustment_factor":1.0} for i,day in enumerate(days)]
    recipe={"count":1,"lookback":2,"cash":1000.0,"fee":fee,"frequency":"daily",
            "signal_template":"price_momentum"}
    input_bytes=json.dumps({"bars":bars,"recipe":recipe},sort_keys=True,ensure_ascii=False,allow_nan=False).encode("utf-8")
    (folder/"research_inputs.json").write_bytes(input_bytes)
    report=research_bars(bars,recipe)
    report["input_hash"]=hashlib.sha256(input_bytes).hexdigest()
    report["order_schedule_hash"]=hashlib.sha256(json.dumps(report["order_schedule"],sort_keys=True,
        separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    report_path=folder/"report.json"
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    return report, bars, recipe, hashlib.sha256(report_path.read_bytes()).hexdigest()


class PriceSensitivityTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (price_research_module, sensitivity_module, sensitivity_worker_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")

    def test_preregistered_cases_replay_baseline_rerun_higher_fee_and_shift_terminal_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/"source"
            original,bars,recipe,report_sha=_write_source_run(source)
            output=run_price_sensitivity(source,root/"result",expected_report_sha256=report_sha)
            result=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([row["scenario"]["id"] for row in result["scenarios"]],
                [row["id"] for row in SCENARIOS])
            baseline,higher,delay=result["scenarios"]
            self.assertEqual(baseline["financial_path"],{key:original.get(key) for key in (
                "nav","account_path","order_schedule","delayed_order_plan","trades","skipped_orders","fees","daily_turnover")})
            self.assertEqual(baseline["scenario_kind"],"strategy_rerun_with_fee_parameter")
            self.assertEqual(higher["scenario_recipe"]["fee"],0.2)
            self.assertEqual(higher["quantity_policy"],"recalculated_by_the_same_strategy_and_fee_reserve")
            independently_rerun=research_bars(bars,{**recipe,"fee":0.2})
            for key in ("nav","account_path","order_schedule","skipped_orders","trades","fees"):
                self.assertEqual(higher["financial_path"][key],independently_rerun[key])
            self.assertGreater(higher["fees"],baseline["fees"])
            self.assertEqual(delay["scenario_kind"],"fixed_baseline_quantity_execution_diagnostic")
            self.assertEqual(delay["quantity_policy"],"baseline_order_quantities_are_frozen_without_resizing")
            self.assertEqual(delay["skips"],1)
            self.assertEqual(delay["financial_path"]["skipped_orders"][0]["reason"],"no_next_observed_open")
            self.assertEqual(delay["fills"],0)
            self.assertTrue(all(row["nav"]==1.0 for row in delay["financial_path"]["nav"]))
            self.assertIn("no signal or security selection was regenerated",delay["execution_diagnostic"])
            self.assertEqual(original["fees"],baseline["fees"])
            self.assertFalse(result["pit_guarantee"])
            self.assertIn("no scenario is selected",result["selection"])
            self.assertEqual(hashlib.sha256((source/"report.json").read_bytes()).hexdigest(),report_sha)

    def test_rejects_source_changes_and_requires_exact_baseline_finance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/"source"
            report,_,_,report_sha=_write_source_run(source)
            with self.assertRaisesRegex(ValueError,"changed after sensitivity selection"):
                run_price_sensitivity(source,root/"wrong-hash",expected_report_sha256="0"*64)
            report["nav"][0]["nav"]=1.001
            (source/"report.json").write_text(json.dumps(report,allow_nan=False),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"baseline replay does not reproduce source nav"):
                run_price_sensitivity(source,root/"mismatch")
            with self.assertRaisesRegex(ValueError,"outside the immutable source run"):
                run_price_sensitivity(source,source/"derived-output")

    def test_worker_is_static_offline_and_binds_the_selected_report_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/"source"; _,_,_,report_sha=_write_source_run(source)
            job_id="0"*32; job_dir=root/"workspace"/"price-sensitivity"/"jobs"/job_id
            job_dir.mkdir(parents=True)
            request={"schema":REQUEST_SCHEMA,"job_id":job_id,"operation":"price_sensitivity",
                     "run_directory":str(source),"report_sha256":report_sha}
            (job_dir/"request.json").write_text(json.dumps(request),encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--workspace",str(root/"workspace"),"--job-id",job_id]),0)
            result=json.loads((job_dir/"result.json").read_text(encoding="utf-8"))
            result_bytes=(job_dir/"result.json").read_bytes()
            self.assertEqual(result["status"],"COMPLETED")
            self.assertEqual(result["source_report_sha256"],report_sha)
            self.assertEqual(result["offline_guards"]["socket_connect"],"blocked")
            self.assertEqual(result["offline_guards"]["credential_loader"],
                             "data_connection.load_api_key denied")
            restore=_install_offline_guards()
            try:
                with self.assertRaisesRegex(RuntimeError,"blocks network"):
                    socket.create_connection(("127.0.0.1",1),timeout=.01)
            finally:
                restore()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--workspace",str(root/"workspace"),"--job-id",job_id]),1)
            self.assertEqual((job_dir/"result.json").read_bytes(),result_bytes)
            self.assertFalse((job_dir/"failure.json").exists())
            bad_id="1"*32; bad_dir=root/"workspace"/"price-sensitivity"/"jobs"/bad_id
            bad_dir.mkdir(parents=True)
            request.update(job_id=bad_id,operation="price_sensitivity",report_sha256="0"*64)
            (bad_dir/"request.json").write_text(json.dumps(request),encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--workspace",str(root/"workspace"),"--job-id",bad_id]),1)
            failure=json.loads((bad_dir/"failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["status"],"FAILED")
            self.assertIn("source report hash",failure["reason"])

    def test_worker_rejects_escaped_jobs_and_output_junctions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); workspace=root/"workspace"; workspace.mkdir()
            escaped=root/"escaped"; escaped.mkdir()
            jobs=workspace/"price-sensitivity"/"jobs"; jobs.parent.mkdir(parents=True)
            original_resolve=Path.resolve
            def escaped_jobs(path,*args,**kwargs):
                return escaped if path.name=="jobs" and path.parent.name=="price-sensitivity" else original_resolve(path,*args,**kwargs)
            with patch.object(Path,"resolve",escaped_jobs):
                with self.assertRaisesRegex(ValueError,"job root escapes"):
                    _read_request(workspace,"2"*32)

        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); workspace=root/"workspace"; jobs=workspace/"price-sensitivity"/"jobs"
            job_id="3"*32; job=jobs/job_id; job.mkdir(parents=True)
            external=root/"outside"; external.mkdir()
            request={"schema":REQUEST_SCHEMA,"job_id":job_id,"operation":"price_sensitivity",
                     "run_directory":str(root),"report_sha256":"0"*64}
            (job/"request.json").write_text(json.dumps(request),encoding="utf-8")
            outputs=job/"outputs"; original_resolve=Path.resolve
            def escaped_outputs(path,*args,**kwargs):
                return external if path.name=="outputs" else original_resolve(path,*args,**kwargs)
            with patch.object(Path,"resolve",escaped_outputs):
                with self.assertRaisesRegex(ValueError,"output directory escapes"):
                    _read_request(workspace,job_id)
            self.assertEqual(list(external.iterdir()),[])


if __name__ == "__main__":
    unittest.main()
