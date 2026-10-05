"""Operation-specific discovery for optional public research dependencies.

The public package uses the currently selected Python environment. A valid
installed-extras runtime therefore has no extra import paths (``paths=[]``).
Discovery reads package metadata and module specs only; it never imports heavy
optional libraries during GUI startup.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
import platform
import re
import sysconfig
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PackageRequirement:
    distribution: str
    module: str
    minimum: str | None = None
    maximum_exclusive: str | None = None


def _req(distribution: str, module: str, minimum: str | None = None,
         maximum_exclusive: str | None = None) -> PackageRequirement:
    return PackageRequirement(distribution, module, minimum, maximum_exclusive)


_NUMPY = _req("numpy", "numpy", "2.2", "2.3")
_PANDAS = _req("pandas", "pandas", "2.2", "3")
_PLOTLY = _req("plotly", "plotly", "6.1.1", "7")
_JQS = _req("jquantstats", "jquantstats", "0.12", "0.13")
_POLARS = _req("polars", "polars", "1.43")
_SCIPY = _req("scipy", "scipy", "1.14.1")
_TALIB = _req("TA-Lib", "talib", "0.6.5")
_PANDAS_TA = _req("pandas-ta", "pandas_ta", "0.4.71")
_LIGHTGBM = _req("lightgbm", "lightgbm", "4.7", "5")
_SCIKIT_LEARN = _req("scikit-learn", "sklearn", "1.9", "2")
_CATBOOST = _req("catboost", "catboost", "1.2.10", "1.3")
_VECTORBT = _req("vectorbt", "vectorbt", "1.0", "1.1")
_BACKTRADER = _req("backtrader", "backtrader", "1.9.78.123", "2")

_ANALYTICS = (_JQS, _POLARS, _PLOTLY, _NUMPY, _PANDAS, _SCIPY)
_INDICATOR_TALIB = (_TALIB, _NUMPY)
_INDICATOR_PANDAS_TA = (_PANDAS_TA, _PANDAS, _NUMPY)
_MODEL_LIGHTGBM = (_LIGHTGBM, _SCIKIT_LEARN, _PANDAS, _NUMPY)
_MODEL_CATBOOST = (_CATBOOST, _PANDAS, _NUMPY)
_ENGINE_VECTORBT = (_VECTORBT, _PANDAS, _NUMPY, _PLOTLY)
_ENGINE_BACKTRADER = (_BACKTRADER, _PANDAS, _NUMPY)

_ALIASES = {
    "analytics_dashboard": "analytics",
    "talib": "indicator-talib",
    "pandas-ta": "indicator-pandas-ta",
    "indicator_ta_lib": "indicator-talib",
    "indicator_pandas_ta": "indicator_pandas-ta",
    "model_lightgbm": "model-lightgbm",
    "model_catboost": "model-catboost",
    "engine_vectorbt": "engine-vectorbt",
    "engine_backtrader": "engine-backtrader",
    "lightgbm": "model-lightgbm",
    "catboost": "model-catboost",
    "vectorbt": "engine-vectorbt",
    "backtrader": "engine-backtrader",
}


def _version_tuple(value: str | None) -> tuple[int, ...] | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", value)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _compare_versions(left: str, right: str) -> int | None:
    a, b = _version_tuple(left), _version_tuple(right)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def _discover(requirement: PackageRequirement) -> dict[str, object]:
    version = None
    metadata_error = None
    try:
        version = metadata.version(requirement.distribution)
    except metadata.PackageNotFoundError:
        pass
    except (OSError, PermissionError, ValueError) as exc:
        metadata_error = type(exc).__name__

    discoverable = False
    discovery_error = None
    try:
        discoverable = util.find_spec(requirement.module) is not None
    except (ImportError, ModuleNotFoundError, ValueError, OSError, PermissionError) as exc:
        discovery_error = type(exc).__name__

    reasons = []
    if version is None:
        if metadata_error:
            reasons.append(f"{requirement.distribution} metadata unavailable ({metadata_error})")
        else:
            reasons.append(f"{requirement.distribution} distribution not installed")
    else:
        if requirement.minimum is not None:
            compared = _compare_versions(version, requirement.minimum)
            if compared is None or compared < 0:
                reasons.append(f"{requirement.distribution} {version} is below required {requirement.minimum}")
        if requirement.maximum_exclusive is not None:
            compared = _compare_versions(version, requirement.maximum_exclusive)
            if compared is None or compared >= 0:
                reasons.append(f"{requirement.distribution} {version} is outside the supported range <{requirement.maximum_exclusive}")
    if discovery_error:
        reasons.append(f"module discovery failed: {discovery_error}")
    elif not discoverable:
        reasons.append("module is not discoverable in this Python environment")

    return {
        "distribution": requirement.distribution,
        "module": requirement.module,
        "version": version,
        "package_discoverable": discoverable,
        "import_status": "not_probed",
        "metadata_error": metadata_error,
        "discovery_error": discovery_error,
        "ready": not reasons,
        "reason": "; ".join(reasons) if reasons else None,
    }


def operation_requirements(operation: str | None = None,
                           choices: Mapping[str, object] | None = None) -> tuple[PackageRequirement, ...]:
    """Return the exact optional distributions needed by one workflow.

    Native data, price and factor research, local-file workflows, and offline
    broker previews use only the public package's base dependencies.
    Composite model/engine jobs must state the selected model or backends.
    """
    name = _ALIASES.get(str(operation or "native"), str(operation or "native"))
    choices = choices or {}
    fixed: dict[str, tuple[PackageRequirement, ...]] = {
        "native": (),
        "jquants-download": (),
        "local-cache": (),
        "broker-preview": (),
        "analytics": _ANALYTICS,
        "indicator-talib": _INDICATOR_TALIB,
        "indicator-pandas-ta": _INDICATOR_PANDAS_TA,
        "model-lightgbm": _MODEL_LIGHTGBM,
        "model-catboost": _MODEL_CATBOOST,
        "engine-vectorbt": _ENGINE_VECTORBT,
        "engine-backtrader": _ENGINE_BACKTRADER,
    }
    if name in fixed:
        return fixed[name]
    if name == "indicators":
        provider = choices.get("provider", "native")
        mapping = {"native": (), "talib": _INDICATOR_TALIB, "pandas-ta": _INDICATOR_PANDAS_TA}
        if provider not in mapping:
            raise ValueError("unsupported indicator provider")
        return mapping[provider]
    if name == "model-training":
        selected = choices.get("model_names")
        if not isinstance(selected, (list, tuple)) or not selected:
            raise ValueError("model-training requires selected model_names")
        mapping = {"lightgbm": _MODEL_LIGHTGBM, "catboost": _MODEL_CATBOOST}
        if any(item not in mapping for item in selected) or len(set(selected)) != len(selected):
            raise ValueError("unsupported or duplicate model name")
        return _unique_requirements(req for item in selected for req in mapping[item])
    if name == "engine-comparison":
        selected = choices.get("backends")
        if not isinstance(selected, (list, tuple)) or not selected:
            raise ValueError("engine-comparison requires selected backends")
        mapping = {"native": (), "vectorbt": _ENGINE_VECTORBT, "backtrader": _ENGINE_BACKTRADER}
        if any(item not in mapping for item in selected) or len(set(selected)) != len(selected):
            raise ValueError("unsupported or duplicate engine backend")
        return _unique_requirements(req for item in selected for req in mapping[item])
    raise ValueError("unknown research operation: " + name)


def _unique_requirements(requirements: Iterable[PackageRequirement]) -> tuple[PackageRequirement, ...]:
    result = {}
    for item in requirements:
        prior = result.get(item.distribution.lower())
        if prior is not None and prior != item:
            raise ValueError("conflicting requirements for " + item.distribution)
        result[item.distribution.lower()] = item
    return tuple(result.values())


def _operation_status(operation: str | None, choices: Mapping[str, object] | None) -> dict[str, object]:
    try:
        requirements = operation_requirements(operation, choices)
    except (TypeError, ValueError) as exc:
        return {"name": operation or "native", "enabled": False,
                "dependencies_available": False, "runtime_launchable": None, "mode": "installed",
                "paths": [], "required_distributions": [], "packages": [],
                "reason": str(exc), "import_status": "not_probed"}
    packages = [_discover(item) for item in requirements]
    reasons = [str(item["reason"]) for item in packages if item["reason"]]
    return {"name": operation or "native", "enabled": not reasons,
            "dependencies_available": not reasons, "runtime_launchable": None, "mode": "installed",
            "paths": [], "required_distributions": [item.distribution for item in requirements],
            "packages": packages, "reason": "; ".join(reasons) if reasons else None,
            "import_status": "not_probed"}


def resolve_research_runtime(project_root=None, python_version=None, python_platform=None, *,
                             operation: str | None = None,
                             choices: Mapping[str, object] | None = None) -> dict[str, object]:
    """Inspect the active installed runtime without importing optional packages.

    ``project_root`` remains accepted for compatibility but is not searched.
    The no-argument operation is Native, so missing extras do not disable the
    base application. ``paths`` is retained for worker compatibility and is
    empty for a valid installed-extras runtime.
    """
    if python_version is None:
        python_version = platform.python_version()
    if python_platform is None:
        python_platform = sysconfig.get_platform()
    operation_state = _operation_status(operation, choices)
    target_specs = {
        "analytics": operation_requirements("analytics"),
        "talib": _INDICATOR_TALIB,
    }
    targets = {}
    for target, requirements in target_specs.items():
        packages = [_discover(item) for item in requirements]
        reasons = [str(item["reason"]) for item in packages if item["reason"]]
        targets[target] = {"enabled": not reasons, "mode": "installed", "paths": [],
                           "versions": {str(item["distribution"]): item["version"] for item in packages},
                           "packages": packages, "reason": "; ".join(reasons) if reasons else None,
                           "import_status": "not_probed", "runtime_launchable": None}
    return {
        "enabled": bool(operation_state["enabled"]),
        "dependencies_available": bool(operation_state["dependencies_available"]),
        "runtime_launchable": operation_state["runtime_launchable"],
        "python_version": str(python_version),
        "python_platform": str(python_platform),
        "mode": "installed",
        "operation": operation_state,
        "paths": [],
        "targets": targets,
        "versions": {str(package["distribution"]): package["version"]
                      for package in operation_state["packages"]},
        "reason": operation_state["reason"],
        "import_receipt_verified": False,
        "startup_probe": "distribution metadata and module specs only; optional libraries are not imported",
    }


def resolve_extension_runtime(project_root=None, python_version=None, python_platform=None, *,
                              operation: str | None = None,
                              choices: Mapping[str, object] | None = None) -> dict[str, object]:
    """Backward-compatible alias for the same operation-scoped runtime check.

    Callers must pass the selected model/backend/provider for optional work.
    With no operation requested, the public Native core remains available.
    """
    return resolve_research_runtime(project_root, python_version, python_platform,
                                    operation=operation, choices=choices)
