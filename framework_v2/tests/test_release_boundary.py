"""Public-release boundary regressions; all inputs are local synthetic fixtures."""
from __future__ import annotations

from pathlib import Path
import hashlib
import io
import json
import tarfile
import tempfile
import unittest

from framework_v2.factors import FactorContractError, FactorSpec
from framework_v2.legacy_provider import BuiltinFactors
from tools.check_public_distribution import inspect_distribution


class ReleaseBoundaryTests(unittest.TestCase):
    def test_only_public_factor_identities_and_no_private_family(self):
        builtins = BuiltinFactors()
        self.assertTrue(builtins.versions)
        self.assertTrue(all(item.startswith("public.") for item in builtins.versions))
        with self.assertRaises(FactorContractError):
            BuiltinFactors(family="private")

    def test_private_factor_config_is_not_accepted(self):
        builtins = BuiltinFactors()
        private_spec = FactorSpec.from_config({
            "schema_version": "1.0", "kind": "factor", "id": "private_quality", "version": "1",
            "implementation": {"id": "private.quality", "version": "1", "parameters": {}},
            "data_requirements": [{"dataset": "financial_summary", "fields": ["code"]}],
            "lookback": 1, "output": {"name": "private_quality", "description": "fixture"},
        })
        with self.assertRaises(FactorContractError):
            builtins.validate_spec(private_spec)

    def test_agent_has_no_real_broker_capability_and_r3_stub_is_disabled(self):
        from framework_v2.agent.core import AgentCommandService, AgentError
        from framework_v2.agent.external import ReservedExternalActions

        with tempfile.TemporaryDirectory() as temp:
            service = AgentCommandService(Path(temp))
            capabilities = service.call("inspect_broker_capabilities")
        self.assertTrue(capabilities["ok"])
        self.assertFalse(capabilities["result"]["submit_enabled"])
        self.assertFalse(capabilities["result"]["cancel_enabled"])
        with self.assertRaises(AgentError) as raised:
            ReservedExternalActions().execute("submit_order", {})
        self.assertEqual(raised.exception.code, "KF_AGENT_DISABLED")

    def test_checker_rejects_private_runtime_and_credential_literal_by_path_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text("[project]\nname='kabuforge'\n")
            (root / "public_source_manifest.json").write_text(
                '{"baseline_commit":"a329d363","source_hashes":{}}'
            )
            (root / "historical_data.py").write_text("x = 1\n")
            findings = inspect_distribution(root)
        self.assertIn({"category": "private_runtime", "path": "historical_data.py"}, findings)

    def test_checker_normalizes_explicit_lf_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = b"line one\r\nline two\r\n"
            normalized = raw.replace(b"\r\n", b"\n")
            (root / "public.py").write_bytes(raw)
            (root / "pyproject.toml").write_text("[project]\nname='kabuforge'\n")
            (root / "public_source_manifest.json").write_text(
                '{"baseline_commit":"a329d363","hash_normalization":"LF","source_hashes":{"public.py":"'
                + hashlib.sha256(normalized).hexdigest() + '"}}'
            )
            findings = inspect_distribution(root)
        self.assertFalse(findings)

    def test_checker_strips_sdist_root_before_manifest_and_private_runtime_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "kabuforge-0.1.0rc1.tar.gz"
            manifest = b'{"baseline_commit":"a329d363","source_hashes":{}}'
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, payload in {
                    "kabuforge-0.1.0rc1/pyproject.toml": b"[project]\nname='kabuforge'\n",
                    "kabuforge-0.1.0rc1/public_source_manifest.json": manifest,
                    "kabuforge-0.1.0rc1/framework_v2/public_source_manifest.json": manifest,
                    "kabuforge-0.1.0rc1/historical_data.py": b"x = 1\n",
                }.items():
                    info = tarfile.TarInfo(name); info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            findings = inspect_distribution(archive_path)
        self.assertEqual(findings, [{"category": "private_runtime", "path": "historical_data.py"}])


if __name__ == "__main__":
    unittest.main()
