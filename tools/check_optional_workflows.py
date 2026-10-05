"""Run real, bounded tests for one fully installed public optional extra.

This is an acceptance helper for dependency-resolution CI. Import success is
checked for each declared provider before a representative unittest suite runs;
metadata-only discovery does not count as a successful workflow.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
import unittest


GROUPS = {
    "analytics": {
        "providers": {
            "jquantstats": "jquantstats",
            "numpy": "numpy",
            "pandas": "pandas",
            "polars": "polars",
            "plotly": "plotly",
            "scipy": "scipy",
        },
        "tests": (
            "framework_v2.tests.test_report_analysis",
            "framework_v2.tests.test_report_account_analysis",
        ),
    },
    "indicators": {
        "providers": {
            "TA-Lib": "talib",
            "pandas-ta": "pandas_ta",
            "numpy": "numpy",
            "pandas": "pandas",
        },
        "tests": ("framework_v2.tests.test_indicator_research",),
    },
    "models": {
        "providers": {
            "lightgbm": "lightgbm",
            "catboost": "catboost",
            "scikit-learn": "sklearn",
            "numpy": "numpy",
            "pandas": "pandas",
        },
        "tests": ("framework_v2.tests.test_model_research",),
    },
    "backends": {
        "providers": {
            "vectorbt": "vectorbt",
            "backtrader": "backtrader",
            "numpy": "numpy",
            "pandas": "pandas",
            "plotly": "plotly",
        },
        "tests": ("framework_v2.tests.test_engine_research",),
    },
}


class RecordingResult(unittest.TestResult):
    """Collect concise per-test evidence while retaining unittest counters."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, str]] = []

    def startTest(self, test: unittest.case.TestCase) -> None:
        self._current_test = test.id()
        super().startTest(test)

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        self.events.append({"test": test.id(), "status": "passed"})
        super().addSuccess(test)

    def addFailure(self, test: unittest.case.TestCase, err: tuple[object, object, object]) -> None:
        self.events.append({"test": test.id(), "status": "failed"})
        super().addFailure(test, err)

    def addError(self, test: unittest.case.TestCase, err: tuple[object, object, object]) -> None:
        self.events.append({"test": test.id(), "status": "error"})
        super().addError(test, err)

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:
        self.events.append({"test": test.id(), "status": "skipped", "reason": reason})
        super().addSkip(test, reason)


def _check_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if Path.cwd().resolve() != root:
        raise RuntimeError("run this checker from the project root")
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError("project pyproject.toml is missing")
    return root


def run(extra: str) -> dict[str, object]:
    if extra not in GROUPS:
        raise ValueError("unsupported optional extra")
    root = _check_root()
    if sys.version_info < (3, 12):
        raise RuntimeError("optional workflow checks require Python 3.12 or later")
    # Script execution puts tools/ at sys.path[0]; explicitly bind test imports
    # to the audited checkout instead of an installed package from elsewhere.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    imported: dict[str, str] = {}
    import_errors: dict[str, str] = {}
    for distribution, module_name in GROUPS[extra]["providers"].items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            import_errors[distribution] = f"{type(exc).__name__}: {exc}"
        else:
            imported[distribution] = str(getattr(module, "__version__", "imported"))

    if import_errors:
        summary = {
            "extra": extra,
            "project_root": str(root),
            "python": sys.version.split()[0],
            "provider_imports": imported,
            "provider_import_errors": import_errors,
            "tests_run": 0,
            "failures": 0,
            "errors": len(import_errors),
            "skips": 0,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        raise RuntimeError("required operation provider import failed")

    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(GROUPS[extra]["tests"])
    result = RecordingResult()
    suite.run(result)
    summary: dict[str, object] = {
        "extra": extra,
        "project_root": str(root),
        "python": sys.version.split()[0],
        "provider_imports": imported,
        "test_modules": list(GROUPS[extra]["tests"]),
        "evidence_scope": "existing artificial engineering fixtures only; not market or strategy evidence",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skips": len(result.skipped),
        "test_events": result.events,
    }
    if result.failures:
        summary["failure_details"] = [text for _, text in result.failures]
    if result.errors:
        summary["error_details"] = [text for _, text in result.errors]
    if result.skipped:
        summary["skip_details"] = [reason for _, reason in result.skipped]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if result.testsRun == 0:
        raise RuntimeError("selected optional workflow suite ran zero tests")
    if result.failures or result.errors or result.skipped:
        raise RuntimeError("optional workflow suite must pass with zero failures, errors, and skips")
    if len(result.events) != result.testsRun:
        raise RuntimeError("unclassified unittest outcomes detected")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extra", choices=tuple(GROUPS))
    args = parser.parse_args(argv)
    run(args.extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
