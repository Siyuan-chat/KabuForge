"""Artificial cache fixtures test byte identity and selection rules, not market data."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import framework_v2.local_cache as local_cache_module
from framework_v2.local_cache import LocalCacheError, _date_text, load_research_bars


def _bars() -> pd.DataFrame:
    return pd.DataFrame([
        {"Date": "20240103", "Code": "01230", "Open": 11, "High": 12,
         "Low": 10, "Close": 11.5, "Volume": 1200,
         "AdjustmentFactor": 1.0, "AdjustmentClose": 11.5},
        {"Date": "20240102", "Code": "01230", "Open": 10, "High": 11,
         "Low": 9, "Close": 10.5, "Volume": 1000,
         "AdjustmentFactor": 0.95, "AdjustmentClose": 9.975},
    ])


class LocalResearchCacheTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        self.assertTrue(Path(local_cache_module.__file__).resolve().is_relative_to(project_root),
                        f"test imported non-candidate implementation: {local_cache_module.__file__}")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _csv(self, frame=None) -> Path:
        path = self.root / "bars.csv"
        (frame if frame is not None else _bars()).to_csv(path, index=False)
        return path

    def _load(self, path, **kwargs):
        return load_research_bars(path, codes=["0123"], start_date="2024-01-01",
                                  end_date="2024-01-31", **kwargs)

    def test_csv_keeps_leading_zero_sorts_and_hashes_selected_basis(self):
        result = self._load(self._csv(), price_basis="adjusted")
        self.assertEqual(result.bars["code"].tolist(), ["01230", "01230"])
        self.assertEqual(result.bars["date"].tolist(), ["2024-01-02", "2024-01-03"])
        self.assertEqual(result.selection["matched_codes"], {"0123": "01230"})
        self.assertEqual(result.bars["selected_price"].tolist(), [9.975, 11.5])
        self.assertEqual(len(result.source["source_sha256"]), 64)
        self.assertEqual(len(result.selected_data_sha256), 64)
        self.assertFalse(result.source["details"]["pit_guarantee"])

    def test_date_parser_accepts_only_exact_calendar_forms_and_valid_iso_datetimes(self):
        valid = {
            "20240102": "2024-01-02",
            "2024-01-02": "2024-01-02",
            "2024-01-02T23:59:59+09:00": "2024-01-02",
            "2024-01-02T00:15Z": "2024-01-02",
            "2024-01-02T12:30:00.123456-05:00": "2024-01-02",
            datetime.fromisoformat("2024-01-02T23:59:59+09:00"): "2024-01-02",
        }
        for value, expected in valid.items():
            with self.subTest(value=value):
                self.assertEqual(_date_text(value), expected)

        invalid = [
            "2024-01-02garbage", "2024-01-02T12:30:00Ztail", "2024-01-02 12:30:00junk",
            "2024-1-2", "2024-02-30", "2024-01-02T25:00:00", "2024-01-02T12:61:00",
            "2024-01-02T12:30:00+25:00", "2024-01-02T12", "2024010x", "20241301",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(LocalCacheError, "complete ISO datetime"):
                _date_text(value)

        malformed_source = _bars(); malformed_source.loc[0, "Date"] = "2024-01-02junk"
        with self.assertRaisesRegex(LocalCacheError, "complete ISO datetime"):
            self._load(self._csv(malformed_source))

    def test_datetime_daily_dates_keep_written_calendar_day_and_freeze_hash_roundtrips(self):
        source = self.root / "timestamp-bars.csv"
        frame = _bars()
        frame["Date"] = ["2024-01-03T00:15:00Z", "2024-01-02T23:59:59-05:00"]
        frame.to_csv(source, index=False)
        raw_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        result = load_research_bars(source, codes=["0123"], start_date="20240101",
                                    end_date="2024-01-31T23:59:59+09:00", price_basis="raw")
        self.assertEqual(result.bars["date"].tolist(), ["2024-01-02", "2024-01-03"])
        self.assertEqual(result.source["source_sha256"], raw_source_hash)
        frozen = result.freeze(self.root / "datetime-freeze")
        frozen_doc = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertEqual(frozen_doc["source"]["source_sha256"], raw_source_hash)
        roundtrip = load_research_bars(frozen, codes=["0123"], start_date="20240101",
                                       end_date="2024-01-31")
        self.assertEqual(roundtrip.selected_data_sha256, result.selected_data_sha256)
        self.assertNotEqual(roundtrip.source["source_sha256"], raw_source_hash)
        self.assertEqual(roundtrip.source["details"]["original_source"]["source_sha256"], raw_source_hash)

    def test_4_digit_code_must_resolve_uniquely(self):
        frame = pd.concat([_bars(), _bars().assign(Code="01231")], ignore_index=True)
        path = self._csv(frame)
        with self.assertRaisesRegex(LocalCacheError, "multiple 5-character"):
            self._load(path)

    def test_venue_suffix_and_original_code_are_preserved(self):
        suffixed = _bars().assign(Code="7203.T")
        path = self._csv(suffixed)
        result = load_research_bars(path, codes=["7203"], start_date="2024-01-01",
                                    end_date="2024-01-31")
        self.assertEqual(result.bars["code"].tolist(), ["7203", "7203"])
        self.assertEqual(result.bars["source_code"].tolist(), ["7203.T", "7203.T"])
        frozen = result.freeze(self.root / "venue-suffix-freeze")
        roundtrip = load_research_bars(frozen, codes=["7203"], start_date="2024-01-01",
                                       end_date="2024-01-31")
        self.assertEqual(roundtrip.bars["source_code"].tolist(), ["7203.T", "7203.T"])

    def test_duplicate_nonfinite_empty_bad_ohlc_and_missing_adjustment_rejected(self):
        duplicate = pd.concat([_bars(), _bars().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(LocalCacheError, "duplicate"):
            self._load(self._csv(duplicate))
        nonfinite = _bars(); nonfinite.loc[0, "Close"] = float("inf")
        with self.assertRaisesRegex(LocalCacheError, "non-finite"):
            self._load(self._csv(nonfinite))
        bad_ohlc = _bars(); bad_ohlc.loc[0, "High"] = 10
        with self.assertRaisesRegex(LocalCacheError, "high must"):
            self._load(self._csv(bad_ohlc))
        with self.assertRaisesRegex(LocalCacheError, "empty"):
            self._load(self._csv(_bars().iloc[0:0]))
        missing = _bars().drop(columns=["AdjustmentClose"])
        with self.assertRaisesRegex(LocalCacheError, "adjustment_close is absent"):
            load_research_bars(self._csv(missing), codes=["0123"],
                               start_date="2024-01-01", end_date="2024-01-31",
                               price_basis="adjusted")

    def test_parquet_load_and_missing_engine_message(self):
        path = self.root / "bars.parquet"
        _bars().to_parquet(path, index=False)
        result = self._load(path)
        self.assertEqual(len(result.bars), 2)
        self.assertEqual(result.source["kind"], "local_parquet")
        with patch.dict("sys.modules", {"pyarrow": None, "pyarrow.compute": None,
                                         "pyarrow.parquet": None}):
            with self.assertRaisesRegex(LocalCacheError, "requires an installed"):
                self._load(path)

    def test_parquet_selects_projected_rows_with_streaming_identity_and_freeze_roundtrip(self):
        path = self.root / "local-cache.parquet"
        rows = [
            {"date": "2017-01-03", "code": "7203.T", "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100, "adjustment_factor": 1.0,
             "adjustment_open": 10, "adjustment_high": 12, "adjustment_low": 9,
             "adjustment_close": 11, "adjustment_volume": 100},
            {"date": "2017-01-03", "code": "4502", "open": 20, "high": 22,
             "low": 19, "close": 21, "volume": 200, "adjustment_factor": 1.0,
             "adjustment_open": 20, "adjustment_high": 22, "adjustment_low": 19,
             "adjustment_close": 21, "adjustment_volume": 200},
            {"date": "2018-06-01", "code": "7203.T", "open": 12, "high": 14,
             "low": 11, "close": 13, "volume": 120, "adjustment_factor": 1.0,
             "adjustment_open": 12, "adjustment_high": 14, "adjustment_low": 11,
             "adjustment_close": 13, "adjustment_volume": 120},
            {"date": "2017-01-03", "code": "8306", "open": 30, "high": 32,
             "low": 29, "close": 31, "volume": 300, "adjustment_factor": 1.0,
             "adjustment_open": 30, "adjustment_high": 32, "adjustment_low": 29,
             "adjustment_close": 31, "adjustment_volume": 300},
        ]
        pd.DataFrame(rows).to_parquet(path, index=False, row_group_size=1)
        raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        original_read_bytes = Path.read_bytes

        def forbid_whole_file_read(candidate):
            if candidate.resolve() == path.resolve():
                raise AssertionError("Parquet selection attempted an unbounded whole-file read")
            return original_read_bytes(candidate)

        with patch.object(Path, "read_bytes", forbid_whole_file_read):
            selected = load_research_bars(path, codes=["7203"], start_date="2017-01-01",
                                          end_date="2017-12-31", price_basis="raw")
        self.assertEqual(selected.bars["code"].tolist(), ["7203"])
        self.assertEqual(selected.bars["source_code"].tolist(), ["7203.T"])
        self.assertEqual(selected.bars["date"].tolist(), ["2017-01-03"])
        self.assertEqual(selected.source["source_sha256"], raw_hash)
        pq_details = selected.source["details"]["parquet_selection"]
        self.assertEqual(pq_details["file_rows"], 4)
        self.assertEqual(pq_details["row_groups_scanned"], 4)
        self.assertEqual(pq_details["candidate_rows_for_codes"], 2)
        self.assertEqual(pq_details["rows_after_arrow_date_filter"], 1)
        self.assertIn("code filter before pandas normalization", pq_details["selection_method"])

        frozen = selected.freeze(self.root / "fixture-frozen-bars")
        manifest = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"]["source_sha256"], raw_hash)
        self.assertEqual(manifest["selection"]["duplicate_policy"], "reject")
        roundtrip = load_research_bars(frozen, codes=["7203"], start_date="2017-01-01",
                                       end_date="2017-12-31", duplicate_policy="reject")
        self.assertEqual(roundtrip.selected_data_sha256, selected.selected_data_sha256)
        self.assertEqual(roundtrip.bars["source_code"].tolist(), ["7203.T"])

    def test_identical_duplicate_policy_is_explicit_and_conflicts_always_reject(self):
        row = _bars().iloc[[0]]
        duplicate = pd.concat([row, row], ignore_index=True)
        path = self._csv(duplicate)
        with self.assertRaisesRegex(LocalCacheError, "policy=reject"):
            self._load(path)
        selected = self._load(path, duplicate_policy="drop_identical")
        self.assertEqual(len(selected.bars), 1)
        self.assertEqual(selected.coverage["duplicate_rows_removed"], 1)
        self.assertEqual(selected.coverage["duplicate_policy"], "drop_identical")
        frozen = selected.freeze(self.root / "deduplicated-frozen")
        manifest = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertEqual(manifest["selection"]["duplicate_policy"], "drop_identical")
        self.assertEqual(manifest["coverage"]["duplicate_rows_removed"], 1)
        replay = load_research_bars(frozen, codes=["0123"], start_date="2024-01-01",
                                    end_date="2024-01-31", duplicate_policy="drop_identical")
        self.assertEqual(replay.selected_data_sha256, selected.selected_data_sha256)
        with self.assertRaisesRegex(LocalCacheError, "must match the frozen"):
            load_research_bars(frozen, codes=["0123"], start_date="2024-01-01",
                               end_date="2024-01-31", duplicate_policy="reject")

        conflict = duplicate.copy(); conflict.loc[1, "Close"] += 0.5
        with self.assertRaisesRegex(LocalCacheError, "conflicting duplicate"):
            self._load(self._csv(conflict), duplicate_policy="drop_identical")

    def test_only_verified_all_day_tse_halt_placeholders_can_be_excluded_and_roundtrip(self):
        rows = []
        for code, base in (("4502", 100), ("6758", 200)):
            rows.append({"date": "2020-09-30", "code": code, "open": base,
                "high": base + 2, "low": base - 2, "close": base + 1, "volume": 1000,
                "adjustment_factor": 1.0})
            halt = {"date": "2020-10-01", "code": code, "open": None,
                "high": None, "low": None, "close": None, "volume": None,
                "adjustment_factor": 1.0}
            rows.extend([halt.copy(), halt.copy()])
        source = self._csv(pd.DataFrame(rows))
        kwargs = {"codes": ["4502", "6758"], "start_date": "2020-09-30",
                  "end_date": "2020-10-01", "duplicate_policy": "drop_identical"}
        with self.assertRaisesRegex(LocalCacheError, "missing open"):
            load_research_bars(source, **kwargs)
        selected = load_research_bars(source, **kwargs,
            known_halt_policy="exclude_verified_tse_halt_20201001")
        self.assertEqual(selected.bars["date"].tolist(), ["2020-09-30", "2020-09-30"])
        self.assertEqual(selected.coverage["rows_before_dedup"], 6)
        self.assertEqual(selected.coverage["duplicate_rows_removed"], 2)
        self.assertEqual(selected.coverage["rows_before_halt_exclusion"], 4)
        exclusion = selected.selection["verified_halt_exclusion"]
        self.assertEqual(exclusion["date"], "2020-10-01")
        self.assertEqual(exclusion["rows"], 2)
        self.assertEqual(exclusion["codes"], ["4502", "6758"])
        self.assertEqual(exclusion["input_source_sha256"], selected.source["source_sha256"])
        self.assertIn("20201001-03.html", exclusion["source_url"])
        frozen = selected.freeze(self.root / "known-halt-freeze")
        doc = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertEqual(doc["selection"]["verified_halt_exclusion"], exclusion)
        replay = load_research_bars(frozen, **kwargs,
            known_halt_policy="exclude_verified_tse_halt_20201001")
        self.assertEqual(replay.selected_data_sha256, selected.selected_data_sha256)
        self.assertEqual(replay.source["details"]["pinned_identity_sha256"], selected.identity_sha256)
        with self.assertRaisesRegex(LocalCacheError, "must match the frozen"):
            load_research_bars(frozen, **kwargs)

    def test_known_halt_rule_rejects_partial_or_valid_quotes_and_other_dates(self):
        option = "exclude_verified_tse_halt_20201001"
        base = {"date": "2020-10-01", "code": "4502", "open": None, "high": None,
                "low": None, "close": None, "volume": None, "adjustment_factor": 1.0}
        for field, value, expected in (("open", 100, "requires one 2020-10-01 row"),
                                       ("open", None, "missing open")):
            with self.subTest(field=field, value=value):
                row = base.copy(); row[field] = value
                rows = [row]
                if value is None:
                    rows.append({"date": "2020-10-02", "code": "4502", "open": None,
                        "high": None, "low": None, "close": None, "volume": None,
                        "adjustment_factor": 1.0})
                source = self._csv(pd.DataFrame(rows))
                with self.assertRaisesRegex(LocalCacheError, expected):
                    load_research_bars(source, codes=["4502"], start_date="2020-10-01",
                        end_date="2020-10-02", known_halt_policy=option)

    def test_inline_snapshot_and_hash_bound_parquet_snapshot(self):
        inline = self.root / "snapshot.json"
        data = _bars().rename(columns={"Date": "date", "Code": "code"})
        inline.write_text(json.dumps({"format": "snapshot.inline.v1", "datasets": {
            "prices": {"columns": list(data.columns), "rows": data.where(pd.notna(data), None).values.tolist()}
        }}), encoding="utf-8")
        self.assertEqual(self._load(inline).source["kind"], "snapshot.inline.v1")

        parquet_root = self.root / "snapshot-pq"; parquet_root.mkdir()
        pq = parquet_root / "prices.parquet"; data.to_parquet(pq, index=False)
        digest = hashlib.sha256(pq.read_bytes()).hexdigest()
        extra = parquet_root / "extra.parquet"; extra.write_bytes(b"synthetic optional dependency")
        extra_digest = hashlib.sha256(extra.read_bytes()).hexdigest()
        manifest = parquet_root / "snapshot.json"
        manifest.write_text(json.dumps({"format": "snapshot.parquet.v1", "datasets": {
            "extra": {"path": "extra.parquet", "sha256": extra_digest, "rows": len(data)},
            "prices": {"path": "prices.parquet", "sha256": digest, "rows": len(data)}
        }}), encoding="utf-8")
        self.assertEqual(self._load(manifest).source["kind"], "snapshot.parquet.v1")
        pq.write_bytes(pq.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(LocalCacheError, "verification failed"):
            self._load(manifest)

    def test_complete_jquants_manifest_is_read_only_and_pages_hash_checked(self):
        root = self.root / "jq"; (root / "pages").mkdir(parents=True)
        page = root / "pages" / "01230-000000.json"
        body = json.dumps([{
            "Date": "20240102", "Code": "01230", "Open": "10", "High": "11",
            "Low": "9", "Close": "10.5", "Volume": "1000",
            "AdjustmentFactor": "0.95", "AdjustmentClose": "9.975",
        }, {
            "Date": "20240103", "Code": "01230", "Open": "11", "High": "12",
            "Low": "10", "Close": "11.5", "Volume": "1200",
            "AdjustmentFactor": None, "AdjustmentClose": None,
        }], separators=(",", ":")).encode("utf-8")
        page.write_bytes(body)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": 1,
            "kind": "jquants_equities_daily_bars", "status": "complete",
            "request": {"codes": ["01230"], "start": "2024-01-02", "end": "2024-01-03"},
            "pages": [{"code": "01230", "file": "pages/01230-000000.json",
                       "sha256": hashlib.sha256(body).hexdigest(), "row_count": 2}],
            "availability": "unverified", "pit_guarantee": False,
        }), encoding="utf-8")
        result = load_research_bars(manifest, codes=["0123"], start_date="2024-01-02",
                                    end_date="2024-01-03")
        self.assertEqual(result.source["kind"], "jquants_manifest")
        self.assertFalse(result.source["details"]["pit_guarantee"])
        self.assertEqual(result.bars.iloc[0]["code"], "01230")
        self.assertTrue(pd.isna(result.bars.iloc[1]["adjustment_close"]))
        page.write_bytes(body + b" ")
        with self.assertRaisesRegex(LocalCacheError, "manifest/page verification failed"):
            load_research_bars(manifest, codes=["0123"], start_date="2024-01-02",
                               end_date="2024-01-03")

    def test_freeze_writes_only_new_package_and_refuses_changes_or_existing_output(self):
        source = self._csv(); original = source.read_bytes()
        result = self._load(source)
        frozen = result.freeze(self.root / "new-freeze")
        self.assertTrue(frozen.is_file())
        self.assertEqual(source.read_bytes(), original)
        receipt = json.loads(frozen.read_text(encoding="utf-8"))
        self.assertEqual(receipt["frozen_data"]["rows"], 2)
        self.assertFalse(receipt["availability"]["pit_guarantee"])
        roundtrip = load_research_bars(frozen, codes=["0123"], start_date="2024-01-01",
                                       end_date="2024-01-31", price_basis="raw")
        self.assertEqual(roundtrip.selected_data_sha256, result.selected_data_sha256)
        self.assertEqual(roundtrip.source["details"]["pinned_identity_sha256"], result.identity_sha256)
        self.assertEqual(roundtrip.source["details"]["original_source"]["kind"], "local_csv")
        self.assertNotEqual(roundtrip.source["source_sha256"], result.source["source_sha256"])
        with self.assertRaises(FileExistsError):
            result.freeze(frozen.parent)
        changed_source = self._csv()
        changed = self._load(changed_source)
        changed_source.write_text(changed_source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(LocalCacheError, "changed or disappeared after inspection"):
            changed.freeze(self.root / "should-not-exist")
        self.assertFalse((self.root / "should-not-exist").exists())

    def test_frozen_artifact_rejects_escaped_paths_tampering_and_price_basis_changes(self):
        result = load_research_bars(self._csv(), codes=["0123"], start_date="2024-01-01",
                                    end_date="2024-01-31", price_basis="adjusted")
        manifest_path = result.freeze(self.root / "frozen-adjusted")
        with self.assertRaisesRegex(LocalCacheError, "price basis"):
            load_research_bars(manifest_path, codes=["0123"], start_date="2024-01-01",
                               end_date="2024-01-31", price_basis="raw")
        adjusted_roundtrip = load_research_bars(manifest_path, codes=["0123"],
                                                start_date="2024-01-01", end_date="2024-01-31",
                                                price_basis="adjusted")
        self.assertEqual(adjusted_roundtrip.selected_data_sha256, result.selected_data_sha256)
        copied = self.root / "frozen-copy"
        shutil.copytree(manifest_path.parent, copied)
        copied_manifest = copied / "manifest.json"
        manifest = json.loads(copied_manifest.read_text(encoding="utf-8"))
        manifest["canonical_data"]["file"] = "../outside.json"
        copied_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LocalCacheError, "escapes"):
            load_research_bars(copied_manifest, codes=["0123"], start_date="2024-01-01",
                               end_date="2024-01-31", price_basis="adjusted")

    def test_generator_codes_are_supported_and_outside_coverage_is_reported_as_error(self):
        path = self._csv()
        result = load_research_bars(path, codes=(code for code in ["0123"]),
                                    start_date="2024-01-02", end_date="2024-01-03")
        self.assertEqual(result.selection["requested_codes"], ["0123"])
        with self.assertRaisesRegex(LocalCacheError, "no bars match"):
            load_research_bars(path, codes=["0123"], start_date="2025-01-01", end_date="2025-01-03")


if __name__ == "__main__":
    unittest.main()
