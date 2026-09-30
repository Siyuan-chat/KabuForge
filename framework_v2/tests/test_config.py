"""Configuration contract tests; all fixtures live in temporary directories."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from framework_v2.config import ConfigError, ImplementationRegistry, load_config, resolve_run


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = ImplementationRegistry()
        self.registry.register("momentum", "1", lambda *_: None)
        self.factor = {
            "schema_version": "1.0", "kind": "factor", "id": "mom", "version": "1",
            "implementation": {"id": "momentum", "version": "1", "parameters": {}},
            "data_requirements": [{"dataset": "prices", "fields": ["close"]}],
            "lookback": 20, "output": {"name": "momentum", "description": "return"},
        }
        self.strategy = {
            "schema_version": "1.0", "kind": "strategy", "id": "simple", "version": "1",
            "universe": {"snapshot": "TOPIX 500 at run snapshot"},
            "factors": ["../factors/mom.json"], "scoring": {"formula": "mom * 2"},
            "portfolio": {"construction": "rank", "parameters": {"count": 20}},
            "risk": {"max_position_weight": 0.1, "max_gross_exposure": 1},
            "rebalance": {"frequency": "daily"},
        }
        self.run = {
            "schema_version": "1.0", "kind": "run", "id": "r1", "version": "1",
            "strategy": "../strategies/simple.json", "data_snapshot": "../data/snapshot.json",
            "clock": {"start": "2025-01-01", "end": "2025-02-01", "timezone": "Asia/Tokyo"},
            "mode": "backtest", "fees": {"commission_rate": 0.001, "minimum_fee": 0},
            "account_ref": "../accounts/account.json", "output_dir": "../results/r1",
        }
        self.factor_file = self._write("factors/mom.json", self.factor)
        self.strategy_file = self._write("strategies/simple.json", self.strategy)
        self.run_file = self._write("runs/run.json", self.run)
        self._write("data/snapshot.json", {"asof": "2025-01-01"})
        self._write("accounts/account.json", {"account_id": "paper-1"})

    def _write(self, relative: str, value: object) -> Path:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")
        return target

    def test_resolve_relative_paths_and_hashes_without_output_side_effect(self) -> None:
        resolved = resolve_run(self.run_file, self.registry)
        self.assertEqual(resolved.factors[0]["id"], "mom")
        self.assertIn(str(self.factor_file.resolve()), resolved.file_hashes)
        self.assertEqual(resolved.implementation_versions["mom"], "1")
        self.assertEqual(len(resolved.account_hash), 64)
        self.assertFalse(resolved.output_dir.exists())
        with self.assertRaises(TypeError):
            resolved.strategy["scoring"]["formula"] = "other"
        with self.assertRaises(TypeError):
            resolved.file_hashes[str(self.factor_file.resolve())] = "changed"
        self.strategy["scoring"]["formula"] = "other"
        self.assertEqual(resolved.strategy["scoring"]["formula"], "mom * 2")

    def test_unknown_schema_version_and_extra_field(self) -> None:
        self.factor["schema_version"] = "2.0"
        self._write("factors/mom.json", self.factor)
        with self.assertRaises(ConfigError):
            load_config(self.factor_file)
        self.factor["schema_version"] = "1.0"
        self.factor["kind"] = []
        self._write("factors/mom.json", self.factor)
        with self.assertRaises(ConfigError):
            load_config(self.factor_file)
        self.factor["kind"] = "factor"
        self.factor["import_path"] = "module:danger"
        self._write("factors/mom.json", self.factor)
        with self.assertRaises(ConfigError):
            load_config(self.factor_file)

    def test_missing_reference(self) -> None:
        self.strategy["factors"] = ["../factors/missing.json"]
        self._write("strategies/simple.json", self.strategy)
        with self.assertRaisesRegex(ConfigError, "missing referenced file"):
            resolve_run(self.run_file, self.registry)

    def test_duplicate_identity_at_different_paths(self) -> None:
        self._write("factors/copy.json", self.factor)
        self.strategy["factors"] = ["../factors/mom.json", "../factors/copy.json"]
        self._write("strategies/simple.json", self.strategy)
        with self.assertRaisesRegex(ConfigError, "duplicate config identity"):
            resolve_run(self.run_file, self.registry)

    def test_cycle(self) -> None:
        self.run["strategy"] = "run.json"
        self._write("runs/run.json", self.run)
        with self.assertRaisesRegex(ConfigError, "cyclic"):
            resolve_run(self.run_file, self.registry)

    def test_invalid_formula_and_unknown_factor_name(self) -> None:
        for formula in ("__import__('os')", "mom ** 2", "other + 1", "mom + " + "1" * 2050, "mom + 1" + "0" * 200):
            with self.subTest(formula=formula):
                self.strategy["scoring"]["formula"] = formula
                self._write("strategies/simple.json", self.strategy)
                with self.assertRaises(ConfigError):
                    resolve_run(self.run_file, self.registry)

    def test_strategy_hash_does_not_depend_on_run_mode(self) -> None:
        first = resolve_run(self.run_file, self.registry)
        self.run["mode"] = "paper"
        self._write("runs/run.json", self.run)
        second = resolve_run(self.run_file, self.registry)
        self.assertEqual(first.strategy_hash, second.strategy_hash)
        self.assertNotEqual(first.file_hashes[str(self.run_file.resolve())], second.file_hashes[str(self.run_file.resolve())])

    def test_credentials_in_external_json_or_metadata(self) -> None:
        self._write("accounts/account.json", {"api_key": "should-never-be-here"})
        with self.assertRaisesRegex(ConfigError, "credential-like"):
            resolve_run(self.run_file, self.registry)
        self._write("accounts/account.json", {"account_id": "paper-1"})
        self.factor["metadata"] = {"nested": {"password": "bad"}}
        self._write("factors/mom.json", self.factor)
        with self.assertRaisesRegex(ConfigError, "credential-like"):
            resolve_run(self.run_file, self.registry)

    def test_unknown_implementation_and_duplicate_json_key(self) -> None:
        self.factor["implementation"]["version"] = "unknown"
        self._write("factors/mom.json", self.factor)
        with self.assertRaisesRegex(ConfigError, "unknown implementation"):
            resolve_run(self.run_file, self.registry)
        self.factor_file.write_text('{"kind":"factor","kind":"factor"}', encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "duplicate JSON key"):
            load_config(self.factor_file)

    def test_dynamic_import_key_inside_parameters(self) -> None:
        self.factor["implementation"]["parameters"] = {"module": "os"}
        self._write("factors/mom.json", self.factor)
        with self.assertRaisesRegex(ConfigError, "dynamic code-loading"):
            resolve_run(self.run_file, self.registry)

    def test_nan_and_absolute_path(self) -> None:
        self.factor_file.write_text('{"kind":"factor","x":NaN}', encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "non-finite"):
            load_config(self.factor_file)
        self.strategy["factors"] = [str(self.factor_file)]
        self._write("strategies/simple.json", self.strategy)
        with self.assertRaisesRegex(ConfigError, "relative file path"):
            resolve_run(self.run_file, self.registry)


if __name__ == "__main__":
    unittest.main()
