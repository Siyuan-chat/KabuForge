"""Artificial in-memory plan/cache checks; not market or strategy evidence."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import framework_v2.application as application_module
import framework_v2.cache as cache_module
import framework_v2.config as config_module
import framework_v2.demo as demo_module
import framework_v2.factors as factors_module
import framework_v2.legacy_provider as provider_module
import framework_v2.local_io as local_io_module
from framework_v2.application import ApplicationService
from framework_v2.cache import FactorCache, FactorCacheCorruptionError
from framework_v2.demo import create_demo
from framework_v2.factors import FactorResult, FactorSpec
from framework_v2.local_io import account_from_file, context_from_file, execution_from_file, research_marks


class FactorCacheIntegrationTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[2]
        for module in (application_module, cache_module, config_module, demo_module,
                       factors_module, provider_module, local_io_module):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(project_root),
                            f"test imported non-candidate implementation: {module.__file__}")

    def test_application_plan_reads_cache_and_reuses_factor_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = create_demo(Path(temp) / "fictional-demo")
            cache = FactorCache(Path(temp) / "isolated-cache.sqlite",
                                namespace={"implementation_source": "engineering-fixture-v1"})
            service = ApplicationService(factor_cache=cache)
            resolved = service.validate(root / "backtest.json")
            context = context_from_file(root / "snapshot.json",
                expected_hash=resolved.data_snapshot_hash,
                decision_at="2024-05-01T09:00:00+09:00")
            account = account_from_file(root / "account.json", expected_hash=resolved.account_hash)
            quotes, instruments, _ = execution_from_file(root / "execution.json")

            calls = []
            counted_bindings = {}
            for key, implementation in resolved.implementation_bindings.items():
                def counted(spec, factor_context, _implementation=implementation):
                    calls.append(spec.implementation_id)
                    return _implementation(spec, factor_context)
                counted_bindings[key] = counted
            resolved = replace(resolved, implementation_bindings=counted_bindings)

            first = service.plan(resolved, context=context, account=account,
                research_marks=research_marks(context), quotes=quotes, instruments=instruments,
                now=datetime.fromisoformat("2024-05-01T09:00:00+09:00"))
            first_call_count = len(calls)
            self.assertGreater(first_call_count, 0)
            second = service.plan(resolved, context=context, account=account,
                research_marks=research_marks(context), quotes=quotes, instruments=instruments,
                now=datetime.fromisoformat("2024-05-01T09:00:00+09:00"))

            self.assertEqual(len(calls), first_call_count, "warm cache should avoid recomputing factors")
            self.assertEqual(first.decision, second.decision)
            self.assertEqual(first.risk, second.risk)
            self.assertEqual(first.plan, second.plan)

    def test_factor_identity_and_namespace_dimensions_do_not_alias(self):
        config = {"schema_version":"1.0", "id":"quality", "kind":"factor", "version":"1",
            "implementation":{"id":"public.quality", "version":"1", "parameters":{"window":20}},
            "lookback":20, "data_requirements":[], "output":{"name":"quality"}}
        spec = FactorSpec.from_config(config)
        args = {"data_snapshot_hash":"snapshot-a", "universe_identity":"universe-a",
                "decision_at":"2024-05-01T09:00:00+09:00"}
        base = spec.cache_key(**args)
        variants = []
        changed = json.loads(json.dumps(config)); changed["implementation"]["parameters"]["window"] = 21
        variants.append(FactorSpec.from_config(changed).cache_key(**args))
        for name, value in (("data_snapshot_hash", "snapshot-b"), ("universe_identity", "universe-b"),
                            ("decision_at", "2024-05-02T09:00:00+09:00")):
            changed_args = dict(args); changed_args[name] = value
            variants.append(spec.cache_key(**changed_args))
        changed_version = json.loads(json.dumps(config)); changed_version["implementation"]["version"] = "2"
        variants.append(FactorSpec.from_config(changed_version).cache_key(**args))
        self.assertEqual(len(set([base, *variants])), len(variants) + 1)

        with tempfile.TemporaryDirectory() as temp:
            first = FactorCache(Path(temp) / "cache.sqlite", namespace={"source":"v1"})
            second = FactorCache(Path(temp) / "cache.sqlite", namespace={"source":"v2"})
            self.assertIsNone(first.get(base))
            frame = pd.DataFrame({"code":["4502"], "factor_name":["quality"],
                "factor_value":[0.25], "signal_date":[pd.Timestamp("2024-05-01")],
                "data_end_date":[pd.Timestamp("2024-05-01")],
                "rebalance_date":[pd.Timestamp("2024-05-02")]})
            result = FactorResult(frame, frame, {"fixture":"engineering-only"}, binding_id="quality")
            first.put(base, result)
            self.assertIsNotNone(first.get(base))
            self.assertIsNone(second.get(base), "different implementation namespace must miss")
            for key in variants:
                self.assertIsNone(first.get(key))

    def test_corrupt_factor_cache_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "isolated-cache.sqlite"
            cache = FactorCache(path, namespace={"source":"engineering-fixture-v1"})
            frame = pd.DataFrame({"code":["4502"], "factor_name":["quality"],
                "factor_value":[0.25], "signal_date":[pd.Timestamp("2024-05-01")],
                "data_end_date":[pd.Timestamp("2024-05-01")],
                "rebalance_date":[pd.Timestamp("2024-05-02")]})
            cache.put("a" * 64, FactorResult(frame, frame, {}, binding_id="quality"))
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE factor_cache_v1 SET payload=?", ("{tampered",))
            with self.assertRaises(FactorCacheCorruptionError):
                cache.get("a" * 64)


if __name__ == "__main__":
    unittest.main()
