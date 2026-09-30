"""One lossless JSON document for both form and source editors."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .config import (ConfigError, KINDS, SCHEMA_DIR, _check_secrets,
                     _reject_constant, _unique_pairs)


class ConfigDocument:
    """Editable in-memory config; validation never mutates it or writes a file."""

    def __init__(self, path: str | Path | None = None):
        self.path: Path | None = None
        self._data: Any = {}
        self._dirty = False
        self._revision = 0
        if path is not None:
            self.load(path)

    @property
    def data(self) -> Any:
        return copy.deepcopy(self._data)

    @property
    def text(self) -> str:
        return json.dumps(self._data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def revision(self) -> int:
        return self._revision

    def load(self, path: str | Path) -> "ConfigDocument":
        source = Path(path).resolve()
        self.set_json(source.read_text(encoding="utf-8"))
        self.path = source
        self._dirty = False
        return self

    def set_json(self, text: str) -> None:
        if not isinstance(text, str):
            raise ConfigError("JSON source must be text")
        try:
            value = json.loads(text, object_pairs_hook=_unique_pairs,
                               parse_constant=_reject_constant)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ConfigError("configuration root must be an object")
        self._data = value
        self._revision += 1
        self._dirty = True

    def set_field(self, dot_path: str, value: Any) -> None:
        if not isinstance(dot_path, str) or not dot_path or any(not part for part in dot_path.split(".")):
            raise ConfigError("field path must be a nonempty dotted object path")
        next_data = copy.deepcopy(self._data)
        cursor = next_data
        parts = dot_path.split(".")
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor or not isinstance(cursor[part], dict):
                raise ConfigError(f"field path has no object: {part}")
            cursor = cursor[part]
        if not isinstance(cursor, dict):
            raise ConfigError("field parent is not an object")
        cursor[parts[-1]] = copy.deepcopy(value)
        try:
            json.dumps(next_data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"field must be finite JSON: {exc}") from exc
        self._data = next_data
        self._revision += 1
        self._dirty = True

    def validate(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        kind = self._data.get("kind") if isinstance(self._data, dict) else None
        if not isinstance(kind, str) or kind not in KINDS:
            return [{"field": "kind", "message": "legacy or unknown kind; explicit conversion required"}]
        try:
            _check_secrets(self._data, self.path or Path("<unsaved>"))
        except ConfigError as exc:
            issues.append({"field": "configuration", "message": str(exc)})
        schema = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for error in sorted(validator.iter_errors(self._data), key=lambda e: (str(list(e.path)), e.message)):
            issues.append({"field": ".".join(map(str, error.path)) or "$", "message": error.message})
        return issues

    def save_as(self, path: str | Path) -> Path:
        issues = self.validate()
        if issues:
            raise ConfigError(f"cannot save invalid configuration: {issues}")
        destination = Path(path).resolve()
        saved = copy.deepcopy(self._data)
        if self.path is not None and self.path.parent != destination.parent:
            def rebase(reference: str) -> str:
                if not isinstance(reference, str) or not reference or Path(reference).is_absolute() or "://" in reference:
                    raise ConfigError("cannot rebase an invalid relative reference")
                original_target = (self.path.parent / reference).resolve()
                try:
                    return Path(os.path.relpath(original_target, destination.parent)).as_posix()
                except ValueError as exc:
                    raise ConfigError("cannot rebase reference across filesystem drives") from exc

            if saved["kind"] == "run":
                for field in ("strategy", "data_snapshot", "account_ref", "output_dir"):
                    saved[field] = rebase(saved[field])
            elif saved["kind"] == "strategy":
                saved["factors"] = [rebase(ref) for ref in saved["factors"]]
                if "path" in saved["universe"]:
                    saved["universe"]["path"] = rebase(saved["universe"]["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        self._data = saved
        self.path = destination
        self._dirty = False
        return destination
