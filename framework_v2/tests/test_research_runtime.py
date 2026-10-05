"""Public optional-runtime and integration readiness contract tests."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

from framework_v2.integrations import DEFAULT_INTEGRATIONS, inspect_integrations
from framework_v2.research_runtime import (
    operation_requirements,
    resolve_extension_runtime,
    resolve_research_runtime,
)


ROOT = Path(__file__).resolve().parents[2]


def _available(requirement):
    version = {
        "jquantstats": "0.12.0", "polars": "1.44.2", "plotly": "6.9.0",
        "numpy": "2.2.6", "pandas": "2.3.3", "scipy": "1.18.1",
        "TA-Lib": "0.8.1", "pandas-ta": "0.4.71b0", "lightgbm": "4.7.0",
        "scikit-learn": "1.9.1", "catboost": "1.2.10", "vectorbt": "1.0.0",
        "backtrader": "1.9.78.123",
    }[requirement.distribution]
    return {"distribution": requirement.distribution, "module": requirement.module,
            "version": version, "package_discoverable": True,
            "import_status": "not_probed", "metadata_error": None,
            "discovery_error": None, "ready": True, "reason": None}


class ResearchRuntimeTests(unittest.TestCase):
    def test_native_default_is_ready_without_optional_dependencies_and_keeps_legacy_shape(self):
        with patch("framework_v2.research_runtime._discover",
                   side_effect=lambda req: {**_available(req), "ready": False,
                       "package_discoverable": False, "version": None,
                       "reason": "distribution not installed"}):
            state = resolve_research_runtime()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["mode"], "installed")
        self.assertEqual(state["paths"], [])
        self.assertEqual(state["operation"]["required_distributions"], [])
        self.assertEqual(set(state["targets"]), {"analytics", "talib"})
        self.assertIn("startup_probe", state)
        extension_alias = resolve_extension_runtime(operation="native")
        self.assertTrue(extension_alias["enabled"])
        self.assertEqual(extension_alias["paths"], [])

    def test_model_and_engine_choices_require_only_selected_optional_libraries(self):
        lightgbm = operation_requirements("model-training", {"model_names": ["lightgbm"]})
        self.assertEqual({item.distribution for item in lightgbm},
                         {"lightgbm", "scikit-learn", "pandas", "numpy"})
        catboost = operation_requirements("model-training", {"model_names": ["catboost"]})
        self.assertEqual({item.distribution for item in catboost}, {"catboost", "pandas", "numpy"})
        vectorbt = operation_requirements("engine-comparison", {"backends": ["vectorbt", "native"]})
        self.assertEqual({item.distribution for item in vectorbt}, {"vectorbt", "pandas", "numpy", "plotly"})
        self.assertNotIn("backtrader", {item.distribution for item in vectorbt})
        with patch("framework_v2.research_runtime._discover", side_effect=_available):
            state = resolve_extension_runtime(operation="model-training", choices={"model_names": ["lightgbm"]})
        self.assertTrue(state["enabled"])
        self.assertEqual(state["paths"], [])
        self.assertNotIn("catboost", state["versions"])

    def test_missing_or_incompatible_dependency_blocks_only_selected_operation(self):
        def available_except_catboost(requirement):
            item = _available(requirement)
            if requirement.distribution == "catboost":
                item.update(ready=False, package_discoverable=False, version=None,
                            reason="catboost distribution not installed")
            return item

        with patch("framework_v2.research_runtime._discover", side_effect=available_except_catboost):
            lightgbm = resolve_research_runtime(operation="model-training", choices={"model_names": ["lightgbm"]})
            catboost = resolve_research_runtime(operation="model-training", choices={"model_names": ["catboost"]})
        self.assertTrue(lightgbm["enabled"])
        self.assertFalse(catboost["enabled"])
        self.assertIn("catboost", catboost["reason"].lower())
        from framework_v2 import research_runtime
        requirement = operation_requirements("model-catboost")[0]
        with patch.object(research_runtime.metadata, "version", return_value="1.0.0"), \
             patch.object(research_runtime.util, "find_spec", return_value=object()):
            incompatible = research_runtime._discover(requirement)
        self.assertFalse(incompatible["ready"])
        self.assertIn("below required", incompatible["reason"])

    def test_missing_sklearn_blocks_lightgbm_but_not_catboost(self):
        def without_sklearn(requirement):
            item = _available(requirement)
            if requirement.distribution == "scikit-learn":
                item.update(ready=False, package_discoverable=False, version=None,
                            reason="scikit-learn distribution not installed")
            return item

        with patch("framework_v2.research_runtime._discover", side_effect=without_sklearn):
            lightgbm = resolve_research_runtime(
                operation="model-training", choices={"model_names": ["lightgbm"]})
            catboost = resolve_research_runtime(
                operation="model-training", choices={"model_names": ["catboost"]})
        self.assertFalse(lightgbm["enabled"])
        self.assertIn("scikit-learn", lightgbm["reason"])
        self.assertTrue(catboost["enabled"])
        self.assertNotIn("scikit-learn", catboost["operation"]["required_distributions"])
        self.assertEqual(catboost["paths"], [])

    def test_active_python_metadata_matrix_matches_each_selected_operation(self):
        cases = (
            ("native", None), ("jquants-download", None), ("local-cache", None),
            ("broker-preview", None), ("analytics", None), ("indicator-talib", None),
            ("indicator-pandas-ta", None),
            ("model-training", {"model_names": ["lightgbm"]}),
            ("model-training", {"model_names": ["catboost"]}),
            ("engine-comparison", {"backends": ["vectorbt"]}),
            ("engine-comparison", {"backends": ["backtrader"]}),
        )
        for operation, choices in cases:
            with self.subTest(operation=operation, choices=choices):
                state = resolve_research_runtime(operation=operation, choices=choices)
                packages = state["operation"]["packages"]
                self.assertEqual(state["paths"], [])
                self.assertEqual(state["mode"], "installed")
                self.assertEqual(state["operation"]["import_status"], "not_probed")
                self.assertEqual(state["enabled"], all(item["ready"] for item in packages))
                self.assertIsNone(state["runtime_launchable"])
                self.assertEqual(state["python_version"], platform.python_version())
                self.assertTrue(all(item["import_status"] == "not_probed" for item in packages))

    def test_every_optional_requirement_can_block_its_operation_independently(self):
        cases = (
            ("analytics", None), ("indicator-talib", None), ("indicator-pandas-ta", None),
            ("model-training", {"model_names": ["lightgbm"]}),
            ("model-training", {"model_names": ["catboost"]}),
            ("engine-comparison", {"backends": ["vectorbt"]}),
            ("engine-comparison", {"backends": ["backtrader"]}),
        )
        for operation, choices in cases:
            requirements = operation_requirements(operation, choices)
            for missing in requirements:
                def discover(item, missing_name=missing.distribution):
                    value = _available(item)
                    if item.distribution == missing_name:
                        value.update(ready=False, package_discoverable=False, version=None,
                                     reason=f"{missing_name} distribution not installed")
                    return value
                with self.subTest(operation=operation, missing=missing.distribution), \
                     patch("framework_v2.research_runtime._discover", side_effect=discover):
                    state = resolve_research_runtime(operation=operation, choices=choices)
                self.assertFalse(state["enabled"])
                self.assertIn(missing.distribution.lower(), state["reason"].lower())

    def test_unknown_operations_and_invalid_choices_fail_closed(self):
        self.assertFalse(resolve_research_runtime(operation="arbitrary-module")["enabled"])
        self.assertFalse(resolve_research_runtime(operation="model-training")["enabled"])
        with self.assertRaises(ValueError):
            operation_requirements("engine-comparison", {"backends": ["unknown"]})
        with self.assertRaises(ValueError):
            operation_requirements("indicators", {"provider": "unknown"})

    def test_discovery_never_claims_import_success_or_imports_a_package(self):
        from framework_v2 import research_runtime

        with patch.object(research_runtime.metadata, "version", return_value="1.0.0"), \
             patch.object(research_runtime.util, "find_spec", return_value=object()) as find_spec:
            result = research_runtime._discover(research_runtime.PackageRequirement("demo", "demo"))
        find_spec.assert_called_once_with("demo")
        self.assertTrue(result["package_discoverable"])
        self.assertEqual(result["import_status"], "not_probed")

    def test_registry_separates_implemented_workflows_from_dependency_and_import_state(self):
        specs = {item.id: item for item in DEFAULT_INTEGRATIONS}
        self.assertTrue(specs["native"].workflow_implemented)
        self.assertTrue(specs["jquants"].workflow_implemented)
        implemented_ids = {"local-cache", "talib", "pandas-ta", "analytics", "lightgbm",
                           "catboost", "vectorbt", "backtrader", "broker-readonly"}
        self.assertTrue(all(specs[item].workflow_implemented for item in implemented_ids))
        profiles = {}
        for integration_id in implemented_ids:
            spec = specs[integration_id]
            requirements = operation_requirements(spec.operation, dict(spec.choices))
            profiles[integration_id] = {"enabled": True, "dependencies_available": True,
                "runtime_launchable": None,
                "operation": {"packages": [_available(req) for req in requirements],
                              "required_distributions": [req.distribution for req in requirements],
                              "import_status": "not_probed"}}
        with patch("framework_v2.integrations.resolve_research_runtime", side_effect=AssertionError("profile expected")):
            statuses = {item.spec.id: item for item in inspect_integrations(
                tuple(specs[item] for item in implemented_ids), runtime_profiles=profiles)}
        for integration_id, status in statuses.items():
            self.assertTrue(status.spec.workflow_implemented, integration_id)
            self.assertTrue(status.dependencies_available, integration_id)
            self.assertTrue(status.workflow_ready, integration_id)
            self.assertEqual(status.lifecycle, "available", integration_id)
            self.assertIsNone(status.runtime_launchable)
            self.assertEqual(status.import_status, "not_probed")
            self.assertTrue(all(item["import_status"] == "not_probed" for item in status.packages))
        self.assertIn("terminal connection not verified", specs["broker-readonly"].capabilities)
        self.assertIn("no token/submit/cancel", specs["broker-readonly"].capabilities)

    def test_candidate_extras_version_aliases_and_migration_hashes(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], "0.2.0rc1")
        extras = project["project"]["optional-dependencies"]
        for name in ("gui", "analytics", "indicators", "models", "backends", "ml", "backtest", "event-backtest"):
            self.assertIn(name, extras)
        self.assertEqual(set(extras["ml"]), set(extras["models"]))
        for requirement in ("lightgbm[scikit-learn]>=4.7,<5", "scikit-learn>=1.9,<2"):
            self.assertIn(requirement, extras["models"])
            self.assertIn(requirement, extras["ml"])
        self.assertEqual(set(extras["backtest"]), {
            "vectorbt>=1.0,<1.1", "numpy>=2.2,<2.3", "pandas>=2.2,<3", "plotly>=6.1.1,<7"})
        self.assertTrue(any(value == "plotly>=6.1.1,<7" for value in extras["analytics"]))
        self.assertTrue(any(value == "pandas>=2.2,<3" for value in extras["backends"]))
        package_data = project["tool"]["setuptools"]["package-data"]["framework_v2"]
        self.assertIn("docs/demos/research-20261006/*/*.png", package_data)
        self.assertIn("docs/demos/research-20261006/*.json", package_data)
        self.assertIn("docs/demos/research-20261006/*.md", package_data)

        manifest = json.loads((ROOT / "framework_v2/public_source_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["baseline_commit"], "a329d3632b83c6e4f2d0145d572013f3537e6515")
        migration = manifest["migration_metadata"]
        self.assertEqual(migration["candidate_version"], "0.2.0rc1")
        self.assertEqual(migration["migration_id"], "public-runtime-final-dependency-batch-root-20261006")
        hashes = migration["file_hashes"]
        self.assertGreater(len(hashes), 25)
        self.assertNotIn("framework_v2/public_source_manifest.json", hashes)
        self.assertTrue({"pyproject.toml", "framework_v2/research_runtime.py",
            "framework_v2/integrations.py", "framework_v2/tests/test_research_runtime.py"}.issubset(hashes))
        production_prefixes = ("framework_v2/", "src/kabuforge/", "tools/", "factors/", "runtime/")
        for relative in hashes:
            self.assertTrue(relative == "pyproject.toml" or relative.startswith(production_prefixes), relative)
            self.assertTrue("/tests/" not in relative or relative == "framework_v2/tests/test_research_runtime.py", relative)
        for relative, expected in migration["file_hashes"].items():
            normalized = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected, relative)


if __name__ == "__main__":
    unittest.main()
