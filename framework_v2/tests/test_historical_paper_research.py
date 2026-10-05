"""Artificial bars/orders test isolated historical replay, not live-paper performance."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import framework_v2.historical_paper_research as paper_module
import framework_v2.local_cache as local_cache_module
import framework_v2.research_application as application_module
from framework_v2 import local_cache
from framework_v2.historical_paper_research import (
    HistoricalPaperResearchError,
    create_historical_paper_research,
    open_historical_paper_research,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(dates: list[str], opens: dict[str, list[float]] | None = None) -> list[dict]:
    codes = ["4502", "6758", "8306"]
    opens = opens or {code: [10.0] * len(dates) for code in codes}
    result = []
    for code in codes:
        for index, day in enumerate(dates):
            opened = float(opens[code][index])
            close = 10.0
            result.append({"date": day, "code": code, "open": opened,
                "high": max(opened, close) * 1.01, "low": min(opened, close) * .99,
                "close": close, "volume": 1000.0, "adjustment_factor": 1.0,
                "adjustment_close": close})
    return result


def _workspace_inputs(root: Path, dates: list[str], orders: list[dict], *,
                      opens: dict[str, list[float]] | None = None) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.csv"
    bars = _rows(dates, opens)
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(bars[0]))
        writer.writeheader(); writer.writerows(bars)
    loaded = local_cache.load_research_bars(source, codes=["4502", "6758", "8306"],
        start_date=dates[0], end_date=dates[-1], price_basis="raw")
    manifest = loaded.freeze(root / "frozen")
    frozen = local_cache.load_research_bars(manifest, codes=["4502", "6758", "8306"],
        start_date=dates[0], end_date=dates[-1], price_basis="raw")
    input_source = {"kind": "kabuforge_local_research_bars",
        "manifest_sha256": _sha(manifest), "selected_data_sha256": frozen.selected_data_sha256,
        "selection_identity_sha256": frozen.identity_sha256,
        "pinned_identity_sha256": frozen.source["details"]["pinned_identity_sha256"],
        "pinned_selection": frozen.source["details"]["pinned_selection"],
        "price_basis": "raw", "pit_guarantee": False,
        "source_availability": "history visibility unverified"}
    report = {"model": "daily_bar_next_open_research_v1", "status": "COMPLETED",
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False, "submitted": False,
        "price_basis_semantics": {"signals": "selected_price (adjustment_close when adjusted; close when raw)",
            "execution": "original raw open; selected_price never substitutes execution OHLC",
            "valuation": "original raw close; price-only mark, no dividend cash model",
            "pit_guarantee": False},
        "input_source": input_source,
        "recipe": {"signal_template": "test_fixed_schedule", "lookback": 2, "count": 2,
            "frequency": "daily", "cash": 1000.0, "fee": 0.1},
        "initial_equity": 1000.0,
        # Values deliberately unrelated to the replay; the service may use dates only.
        "nav": [{"at": day, "nav": 91.0 + index} for index, day in enumerate(dates)],
        "order_schedule": orders, "trades": [{"future_reference_poison": 999999.0}],
        "strategy_hash": "a" * 64, "input_hash": "b" * 64}
    report["order_schedule_hash"] = hashlib.sha256(json.dumps(report["order_schedule"],
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    report_path = root / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return manifest, report_path


class HistoricalPaperResearchTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (paper_module, local_cache_module, application_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")
        self.tmp = tempfile.TemporaryDirectory(prefix="historical-paper-research-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _orders(self, dates: list[str]) -> list[dict]:
        return [
            {"signal_date": dates[0], "execution_date": dates[1], "code": "8306",
             "side": "sell", "quantity": 3.0, "sizing_price": 10.0},
            {"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
             "side": "buy", "quantity": 10.0, "sizing_price": 10.0},
            {"signal_date": dates[0], "execution_date": dates[1], "code": "6758",
             "side": "buy", "quantity": 9.0, "sizing_price": 10.0},
            {"signal_date": dates[2], "execution_date": dates[3], "code": "4502",
             "side": "sell", "quantity": 4.0, "sizing_price": 10.0},
            {"signal_date": dates[2], "execution_date": dates[3], "code": "6758",
             "side": "buy", "quantity": 8.0, "sizing_price": 10.0},
        ]

    def _create(self, manifest: Path, report: Path, output_name="account"):
        return create_historical_paper_research(manifest, report, _sha(report), self.root / output_name)

    def test_actual_open_fills_sell_first_fixed_quantity_and_resumed_idempotency(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
        opens = {"4502": [10, 20, 10, 12], "6758": [10, 100, 10, 200], "8306": [10, 10, 10, 10]}
        manifest, report = _workspace_inputs(self.root, dates, self._orders(dates), opens=opens)
        account = self._create(manifest, report)
        before = _sha(account.journal_path)
        self.assertEqual(account.summary()["cursor"], 0)
        self.assertEqual(_sha(account.journal_path), before)
        with self.assertRaisesRegex(HistoricalPaperResearchError, "nonnegative integer"):
            account.step_next(idempotency_key="cursor-0", expected_cursor=True)

        first = account.step_next(idempotency_key="cursor-0", expected_cursor=0)
        retry = account.step_next(idempotency_key="cursor-0", expected_cursor=0)
        self.assertEqual(first, retry)
        self.assertEqual(account.cursor(), 1)
        self.assertEqual(len(account.events()), 1)
        account = open_historical_paper_research(account.root)
        resumed_retry = account.step_next(idempotency_key="cursor-0", expected_cursor=0)
        self.assertEqual(first, resumed_retry)
        completed = account.run_all()
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(completed["cursor"], len(dates))

        events = account.events()
        second_day = events[1]
        self.assertEqual([item["side"] for item in second_day["fills"]], ["buy"])
        self.assertAlmostEqual(second_day["fills"][0]["open_price"], 20.0)
        self.assertEqual(second_day["fills"][0]["quantity"], 10.0)
        self.assertIn("long holding", second_day["skips"][0]["reason"])
        self.assertIn("opening gap", second_day["skips"][1]["reason"])
        self.assertAlmostEqual(second_day["equity"], 899.8, places=8)
        fourth_day = events[3]
        self.assertEqual([item["side"] for item in fourth_day["fills"]], ["sell"])
        self.assertAlmostEqual(fourth_day["fills"][0]["open_price"], 12.0)
        self.assertEqual(fourth_day["fills"][0]["quantity"], 4.0)
        self.assertIn("opening gap", fourth_day["skips"][0]["reason"])
        # The source report's NAV and trades are intentionally false/poisoned;
        # neither is used to determine the newly computed account path.
        self.assertNotEqual(second_day["nav"], 92.0)
        journal_hash = _sha(account.journal_path)
        reopened = open_historical_paper_research(account.root)
        self.assertEqual(reopened.summary(), completed)
        self.assertEqual(_sha(reopened.journal_path), journal_hash)
        self.assertIsNone(reopened.step_next())
        self.assertEqual(_sha(reopened.journal_path), journal_hash)

    def test_price_source_identity_and_schedule_hash_are_mandatory(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        manifest, report = _workspace_inputs(self.root, dates, [])
        doc = json.loads(report.read_text(encoding="utf-8"))
        doc["input_source"]["manifest_sha256"] = "0" * 64
        report.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(HistoricalPaperResearchError, "manifest_sha256"):
            self._create(manifest, report, "bad-identity")

        doc["input_source"]["manifest_sha256"] = _sha(manifest)
        doc["order_schedule_hash"] = "0" * 64
        report.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(HistoricalPaperResearchError, "order-schedule hash"):
            self._create(manifest, report, "bad-schedule-hash")

    def test_price_momentum_first_warmup_entry_can_precede_month_boundary_only_once(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
        first = [{"signal_date": dates[2], "execution_date": dates[3], "code": "4502",
                  "side": "buy", "quantity": 1.0, "sizing_price": 10.0}]
        manifest, report = _workspace_inputs(self.root, dates, first)
        doc = json.loads(report.read_text(encoding="utf-8")); doc["recipe"]["frequency"] = "monthly"
        doc["recipe"]["signal_template"] = "price_momentum"
        report.write_text(json.dumps(doc), encoding="utf-8")
        account = self._create(manifest, report, "warmup-entry")
        self.assertEqual(account.reference["schedule_by_date"][dates[3]][0]["code"], "4502")

        later = first + [{"signal_date": dates[3], "execution_date": dates[4], "code": "6758",
                          "side": "buy", "quantity": 1.0, "sizing_price": 10.0}]
        manifest, report = _workspace_inputs(self.root / "later-off-boundary", dates, later)
        doc = json.loads(report.read_text(encoding="utf-8")); doc["recipe"]["frequency"] = "monthly"
        doc["recipe"]["signal_template"] = "price_momentum"
        doc["order_schedule_hash"] = hashlib.sha256(json.dumps(doc["order_schedule"],
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        report.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(HistoricalPaperResearchError, "rebalance boundary"):
            self._create(manifest, report, "later-off-boundary-account")

    def test_strict_d1_sell_first_and_no_forward_label_material(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        bad = [{"signal_date": dates[0], "execution_date": dates[2], "code": "4502",
                "side": "buy", "quantity": 1.0, "sizing_price": 10.0}]
        manifest, report = _workspace_inputs(self.root, dates, bad)
        with self.assertRaisesRegex(HistoricalPaperResearchError, "strict D-1"):
            self._create(manifest, report, "bad-clock")

        valid = [{"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
                  "side": "buy", "quantity": 1.0, "sizing_price": 10.0},
                 {"signal_date": dates[0], "execution_date": dates[1], "code": "6758",
                  "side": "sell", "quantity": 1.0, "sizing_price": 10.0}]
        manifest, report = _workspace_inputs(self.root / "second", dates, valid)
        with self.assertRaisesRegex(HistoricalPaperResearchError, "sell follows a buy"):
            self._create(manifest, report, "bad-ordering")

        poisoned = self.root / "poisoned"
        poisoned.mkdir()
        manifest, report = _workspace_inputs(poisoned, dates, [])
        doc = json.loads(report.read_text(encoding="utf-8")); doc["forward_return"] = 0.25
        report.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(HistoricalPaperResearchError, "future-label"):
            self._create(manifest, report, "bad-label")

    def test_source_change_and_journal_corruption_fail_closed(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        orders = [{"signal_date": dates[0], "execution_date": dates[1], "code": "4502",
            "side": "buy", "quantity": 1.0, "sizing_price": 10.0}]
        manifest, report = _workspace_inputs(self.root, dates, orders)
        frozen_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        for artifact_key in ("canonical_data", "frozen_data"):
            account = self._create(manifest, report, f"source-change-{artifact_key}")
            bars_path = manifest.parent / frozen_manifest[artifact_key]["file"]
            original = bars_path.read_bytes()
            bars_path.write_bytes(original + b" ")
            with self.assertRaisesRegex(HistoricalPaperResearchError, "frozen selected bars changed"):
                account.step_next(idempotency_key=f"source-change-{artifact_key}")
            self.assertTrue((account.root / "failure.json").is_file())
            bars_path.write_bytes(original)

        report_retry = self._create(manifest, report, "report-change-account")
        report_retry.step_next(idempotency_key="same-key")
        original_report = report.read_bytes()
        report.write_bytes(original_report + b" ")
        with self.assertRaisesRegex(HistoricalPaperResearchError, "strategy report changed"):
            report_retry.step_next(idempotency_key="same-key")
        report.write_bytes(original_report)
        self.assertTrue((report_retry.root / "failure.json").is_file())

        account = self._create(manifest, report, "journal-corruption-account")
        account.step_next(idempotency_key="event-0")
        raw = account.journal_path.read_bytes().replace(b'"fees":', b'"fees_broken":', 1)
        account.journal_path.write_bytes(raw)
        with self.assertRaises(HistoricalPaperResearchError):
            open_historical_paper_research(account.root)

    def test_evaluation_panel_file_is_never_opened(self):
        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        manifest, report = _workspace_inputs(self.root, dates, [])
        poison = report.parent / "evaluation_panel.json"
        poison.write_text('{"contains_forward_labels":true}', encoding="utf-8")
        original = Path.read_bytes
        attempts = []
        def guarded_read(path):
            if path.name == "evaluation_panel.json":
                attempts.append(path.name)
                raise AssertionError("evaluation panel was opened")
            return original(path)
        with patch.object(Path, "read_bytes", guarded_read):
            account = self._create(manifest, report, "panel-not-read")
            self.assertEqual(account.cursor(), 0)
        self.assertEqual(attempts, [])

    def test_facade_requires_both_paper_optins_owns_account_and_query_is_read_only(self):
        from framework_v2.research_application import ResearchApplicationService

        dates = ["2021-01-04", "2021-01-05", "2021-01-06"]
        workspace = self.root / "owned-workspace"
        manifest, report = _workspace_inputs(workspace / "inputs", dates, [])
        report_sha = _sha(report)

        disabled = ResearchApplicationService(workspace, enable_paper=False)
        with self.assertRaisesRegex(PermissionError, "service and call-level"):
            disabled.create_historical_paper(manifest, report, report_sha, enable_paper=True,
                call_id="disabled-call", idempotency_key="disabled-key")
        self.assertFalse((workspace / "research-application").exists())

        enabled = ResearchApplicationService(workspace, enable_paper=True)
        with self.assertRaisesRegex(PermissionError, "service and call-level"):
            enabled.create_historical_paper(manifest, report, report_sha, enable_paper=False,
                call_id="missing-call-optin", idempotency_key="missing-optin-key")
        created = enabled.create_historical_paper(manifest, report, report_sha, enable_paper=True,
            call_id="create-call", idempotency_key="create-key")
        account_dir = Path(created["account_dir"]).resolve()
        self.assertTrue(account_dir.is_relative_to(workspace.resolve()))
        paper = open_historical_paper_research(account_dir)
        before_query = _sha(paper.journal_path)
        queried = enabled.query_historical_paper(account_dir)
        self.assertEqual(queried["cursor"], 0)
        self.assertEqual(_sha(paper.journal_path), before_query)

        kwargs = dict(account_dir=account_dir, expected_cursor=0, enable_paper=True,
                      call_id="step-call", idempotency_key="step-key")
        advanced = enabled.advance_historical_paper(**kwargs)
        journal_after_step = _sha(paper.journal_path)
        retried = enabled.advance_historical_paper(**kwargs)
        self.assertEqual(advanced, retried)
        self.assertEqual(_sha(paper.journal_path), journal_after_step)
        self.assertEqual(enabled.query_historical_paper(account_dir)["cursor"], 1)
        outside_account = self.root / "outside-account"
        outside_account.mkdir()
        with self.assertRaisesRegex(ValueError, "stay inside the selected workspace"):
            enabled.query_historical_paper(outside_account)


if __name__ == "__main__":
    unittest.main()
