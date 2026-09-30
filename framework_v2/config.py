"""Strict, local-only configuration loading for framework v2.

``load_config`` validates one versioned configuration file. ``resolve_run``
validates its complete dependency graph before returning immutable evidence.
Neither function connects to a broker or creates an output directory.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_DIR = Path(__file__).with_name("schemas")
KINDS = frozenset({"factor", "strategy", "run"})
_SECRET_KEYS = frozenset({
    "password", "passwd", "secret", "token", "apikey", "privatekey",
    "accesskey", "clientsecret", "credential", "credentials", "authorization",
})
_CODE_KEYS = frozenset({
    "import", "module", "modulepath", "pythonmodule", "classpath",
    "entrypoint", "callable", "functionpath",
})


class ConfigError(ValueError):
    """Configuration is malformed, unsafe, or has unresolved dependencies."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ConfigError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ConfigError(f"non-finite JSON number: {value}")


def _read_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                           parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"JSON root must be an object: {path}")
    _check_secrets(value, path)
    return value, hashlib.sha256(raw).hexdigest()


def _check_secrets(value: Any, path: Path) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in _SECRET_KEYS or normalized.endswith((
                "password", "secret", "token", "apikey", "privatekey",
                "accesskey", "credential", "credentials",
            )):
                raise ConfigError(f"credential-like key {key!r} is forbidden in {path}")
            if normalized in _CODE_KEYS:
                raise ConfigError(f"dynamic code-loading key {key!r} is forbidden in {path}")
            _check_secrets(item, path)
    elif isinstance(value, list):
        for item in value:
            _check_secrets(item, path)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ConfigError(f"non-finite number in {path}")


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _relative(base_file: Path, reference: str) -> Path:
    windows = PureWindowsPath(reference)
    if (not reference or Path(reference).is_absolute() or windows.is_absolute()
            or bool(windows.drive) or "://" in reference):
        raise ConfigError(f"reference must be a relative file path: {reference!r}")
    target = (base_file.parent / reference).resolve()
    if not target.is_file():
        raise ConfigError(f"missing referenced file: {target}")
    return target


def _relative_output(base_file: Path, reference: str) -> Path:
    windows = PureWindowsPath(reference)
    if (not reference or Path(reference).is_absolute() or windows.is_absolute()
            or bool(windows.drive) or "://" in reference):
        raise ConfigError(f"output_dir must be relative: {reference!r}")
    return (base_file.parent / reference).resolve()


def _validate_formula(formula: str, factor_ids: set[str]) -> None:
    if len(formula) > 2048:
        raise ConfigError("scoring formula exceeds 2048 characters")
    try:
        tree = ast.parse(formula, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ConfigError(f"invalid scoring formula: {exc}") from exc
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise ConfigError("scoring formula exceeds 256 AST nodes")
    names: set[str] = set()

    def visit(node: ast.AST, depth: int = 0) -> None:
        if depth > 32:
            raise ConfigError("scoring formula exceeds 32 AST levels")
        if isinstance(node, ast.Expression):
            visit(node.body, depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            visit(node.left, depth + 1)
            visit(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            visit(node.operand, depth + 1)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in factor_ids:
                raise ConfigError(f"unknown factor in scoring formula: {node.id}")
            names.add(node.id)
        elif isinstance(node, ast.Constant) and type(node.value) is int and node.value.bit_length() <= 128:
            pass
        elif isinstance(node, ast.Constant) and type(node.value) is float and math.isfinite(node.value):
            pass
        else:
            raise ConfigError(f"forbidden scoring formula syntax: {type(node).__name__}")

    visit(tree)
    if not names:
        raise ConfigError("scoring formula must reference a factor")


def _load_config_snapshot(
    source: Path, snapshot: tuple[dict[str, Any], str] | None = None,
) -> tuple[dict[str, Any], str]:
    value, digest = snapshot if snapshot is not None else _read_json_snapshot(source)
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ConfigError(f"unknown configuration kind: {kind!r}")
    schema = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda err: (list(map(str, err.path)), err.message))
    if errors:
        first = errors[0]
        raise ConfigError(f"invalid {kind} config {source} at {list(first.path)}: {first.message}")
    return value, digest


def load_config(path: str | Path) -> dict[str, Any]:
    """Read one local JSON config, reject secrets/duplicate keys, and validate its kind."""
    value, _ = _load_config_snapshot(Path(path).resolve())
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class ImplementationRegistry:
    """Explicit map of approved (implementation id, version) to a callable."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Callable[..., Any]] = {}

    def register(self, implementation_id: str, version: str, function: Callable[..., Any]) -> None:
        if not implementation_id or not version or not callable(function):
            raise ConfigError("registry requires an id, version, and callable")
        key = (implementation_id, version)
        if key in self._items:
            raise ConfigError(f"implementation already registered: {key}")
        self._items[key] = function

    def require(self, implementation_id: str, version: str) -> Callable[..., Any]:
        key = (implementation_id, version)
        try:
            return self._items[key]
        except KeyError as exc:
            raise ConfigError(f"unknown implementation: {key}") from exc


@dataclass(frozen=True)
class ResolvedRun:
    """Validated effective configuration and content evidence; no execution occurs."""

    run: Mapping[str, Any]
    strategy: Mapping[str, Any]
    factors: tuple[Mapping[str, Any], ...]
    implementation_bindings: Mapping[tuple[str, str], Callable[..., Any]]
    file_hashes: Mapping[str, str]
    implementation_versions: Mapping[str, str]
    strategy_hash: str
    data_snapshot_hash: str
    account_hash: str
    output_dir: Path


def resolve_run(path: str | Path, registry: ImplementationRegistry) -> ResolvedRun:
    """Resolve a run's local graph, rejecting cycles, duplicate identities and unknown code.

    Relative paths are interpreted from the file containing each reference.
    External snapshot/account/universe JSON is validated for syntax and secrets,
    then hashed; it is never connected to a broker or otherwise executed.
    """
    if not isinstance(registry, ImplementationRegistry):
        raise TypeError("registry must be an ImplementationRegistry")
    root = Path(path).resolve()
    active: set[Path] = set()
    loaded: dict[Path, dict[str, Any]] = {}
    identities: dict[tuple[str, str, str], Path] = {}
    hashes: dict[str, str] = {}
    bindings: dict[tuple[str, str], Callable[..., Any]] = {}
    versions: dict[str, str] = {}
    read_cache: dict[Path, tuple[dict[str, Any], str]] = {}

    def snapshot(source: Path) -> tuple[dict[str, Any], str]:
        if source not in read_cache:
            read_cache[source] = _read_json_snapshot(source)
        return read_cache[source]

    def external(base: Path, reference: str) -> tuple[Path, str]:
        target = _relative(base, reference)
        _, digest = snapshot(target)
        hashes[str(target)] = digest
        return target, digest

    def visit(source: Path, expected_kind: str) -> dict[str, Any]:
        if source in active:
            raise ConfigError(f"cyclic configuration reference: {source}")
        if source in loaded:
            value = loaded[source]
            if value["kind"] != expected_kind:
                raise ConfigError(f"expected {expected_kind}, got {value['kind']}: {source}")
            return value
        active.add(source)
        try:
            value, digest = _load_config_snapshot(source, snapshot(source))
            if value["kind"] != expected_kind:
                raise ConfigError(f"expected {expected_kind}, got {value['kind']}: {source}")
            identity = (value["kind"], value["id"], value["version"])
            previous = identities.get(identity)
            if previous is not None and previous != source:
                raise ConfigError(f"duplicate config identity {identity}: {previous} and {source}")
            identities[identity] = source
            hashes[str(source)] = digest
            if expected_kind == "run":
                clock = value["clock"]
                if dt.date.fromisoformat(clock["start"]) > dt.date.fromisoformat(clock["end"]):
                    raise ConfigError("clock.start must be on or before clock.end")
                visit(_relative(source, value["strategy"]), "strategy")
                snapshot_path, _ = external(source, value["data_snapshot"])
                snapshot_value, _ = snapshot(snapshot_path)
                if snapshot_value.get("format") == "snapshot.parquet.v1":
                    from .data_snapshot import snapshot_dependencies
                    hashes.update(snapshot_dependencies(snapshot_path, snapshot_value))
                external(source, value["account_ref"])
                _relative_output(source, value["output_dir"])
            elif expected_kind == "strategy":
                if "path" in value["universe"]:
                    external(source, value["universe"]["path"])
                for reference in value["factors"]:
                    visit(_relative(source, reference), "factor")
            else:
                impl = value["implementation"]
                key = (impl["id"], impl["version"])
                bindings[key] = registry.require(*key)
                versions[value["id"]] = impl["version"]
            loaded[source] = value
            return value
        finally:
            active.remove(source)

    run = visit(root, "run")
    strategy_path = _relative(root, run["strategy"])
    strategy = loaded[strategy_path]
    factor_paths = [_relative(strategy_path, ref) for ref in strategy["factors"]]
    factors = tuple(loaded[item] for item in factor_paths)
    factor_ids = [item["id"] for item in factors]
    if len(set(factor_ids)) != len(factor_ids):
        raise ConfigError("duplicate factor id in one strategy")
    _validate_formula(strategy["scoring"]["formula"], set(factor_ids))
    strategy_evidence: dict[str, Any] = {
        "config": strategy,
        "factors": [{"config": loaded[item], "sha256": hashes[str(item)]} for item in factor_paths],
        "implementations": versions,
    }
    if "path" in strategy["universe"]:
        universe_path = _relative(strategy_path, strategy["universe"]["path"])
        strategy_evidence["universe_sha256"] = hashes[str(universe_path)]
    snapshot_path = _relative(root, run["data_snapshot"])
    account_path = _relative(root, run["account_ref"])
    return ResolvedRun(
        run=_freeze(run), strategy=_freeze(strategy), factors=_freeze(list(factors)),
        implementation_bindings=_freeze(bindings), file_hashes=_freeze(hashes),
        implementation_versions=_freeze(versions),
        strategy_hash=_canonical_hash(strategy_evidence),
        data_snapshot_hash=hashes[str(snapshot_path)],
        account_hash=hashes[str(account_path)],
        output_dir=_relative_output(root, run["output_dir"]),
    )
