"""Point-in-time factor contracts; no filesystem, network, or cache writes.

Legacy calendar columns (``date``, ``asof_date``, ``disclosed_date``) retain
their original values. ``available_at`` is a separate, mandatory timestamp
that says when each row became knowable to this framework.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


class FactorContractError(ValueError):
    """A factor, result, or point-in-time input violated its contract."""


def _aware(value: Any, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FactorContractError(f"invalid {label}: {value!r}") from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise FactorContractError(f"{label} must have an explicit timezone")
    return stamp.tz_convert("UTC")


def _clone_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy both pandas buffers and mutable Python objects inside cells."""
    owned = frame.copy(deep=True)
    for column in owned.columns:
        if pd.api.types.is_object_dtype(owned[column].dtype):
            owned[column] = owned[column].map(copy.deepcopy)
    return owned


def _calendar_stamp(value: Any, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FactorContractError(f"invalid {label}: {value!r}") from exc
    if pd.isna(stamp):
        raise FactorContractError(f"unknown {label} cannot pass the PIT gate")
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("Asia/Tokyo")
    return stamp.tz_convert("UTC")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _json_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FactorContractError(f"cache identity must be finite JSON: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class FactorSpec:
    """Immutable identity and JSON parameters for a registered factor version."""

    id: str
    version: str
    implementation_id: str
    implementation_version: str
    schema_version: str
    _config: Mapping[str, Any]

    def __post_init__(self) -> None:
        for item in (self.id, self.version, self.implementation_id,
                     self.implementation_version, self.schema_version):
            if not isinstance(item, str) or not item:
                raise FactorContractError("factor identities and versions must be nonempty strings")
        if not isinstance(self._config, Mapping):
            raise FactorContractError("factor config must be a mapping")
        plain = _plain(self._config)
        _json_hash(plain)
        object.__setattr__(self, "_config", _freeze(plain))

    @classmethod
    def from_config(cls, value: Mapping[str, Any]) -> "FactorSpec":
        if value.get("kind") != "factor" or value.get("schema_version") != "1.0":
            raise FactorContractError("expected a validated factor schema v1.0 config")
        impl = value.get("implementation")
        if not isinstance(impl, Mapping):
            raise FactorContractError("factor implementation is required")
        for item in (value.get("id"), value.get("version"), impl.get("id"), impl.get("version")):
            if not isinstance(item, str) or not item:
                raise FactorContractError("factor and implementation identities must be nonempty strings")
        config = _plain(value)
        _json_hash(config)
        return cls(value["id"], value["version"], impl["id"], impl["version"],
                   value["schema_version"], _freeze(config))

    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    def cache_key(self, *, data_snapshot_hash: str, universe_identity: str,
                  decision_at: Any) -> str:
        """Compute a versioned identity only; this does not read/write a cache."""
        if not data_snapshot_hash or not universe_identity:
            raise FactorContractError("snapshot hash and universe identity are required")
        stamp = _aware(decision_at, "decision_at")
        return _json_hash({
            "factor_id": self.id, "factor_version": self.version,
            "implementation_id": self.implementation_id,
            "implementation_version": self.implementation_version,
            "schema_version": self.schema_version, "config": _plain(self._config),
            "data_snapshot_hash": data_snapshot_hash,
            "universe_identity": universe_identity,
            "decision_at": stamp.isoformat(),
        })


class FactorContext:
    """Read-only, as-of view over caller-supplied dataset snapshots.

    Every row requires a timezone-aware ``available_at``. Future rows are
    filtered; missing or naive availability timestamps fail closed. A caller
    can ask for an earlier as-of, never a later one. Each read is a deep copy.
    """

    def __init__(self, *, decision_at: Any, datasets: Mapping[str, pd.DataFrame],
                 data_snapshot_hash: str) -> None:
        self._decision_at = _aware(decision_at, "decision_at")
        if not isinstance(data_snapshot_hash, str) or not data_snapshot_hash:
            raise FactorContractError("data_snapshot_hash is required")
        self._data_snapshot_hash = data_snapshot_hash
        self._datasets: dict[str, pd.DataFrame] = {}
        for name, frame in datasets.items():
            if not isinstance(name, str) or not name or not isinstance(frame, pd.DataFrame):
                raise FactorContractError("datasets must map names to DataFrames")
            if "available_at" not in frame.columns:
                raise FactorContractError(f"{name} lacks available_at")
            owned = _clone_frame(frame)
            timestamps = [_aware(item, f"{name}.available_at") for item in owned["available_at"]]
            owned["available_at"] = pd.Series(timestamps, index=owned.index, dtype="datetime64[ns, UTC]")
            self._datasets[name] = owned

    @property
    def decision_at(self) -> pd.Timestamp:
        return self._decision_at

    @property
    def data_snapshot_hash(self) -> str:
        return self._data_snapshot_hash

    def read(self, dataset: str, *, asof: Any | None = None,
             fields: tuple[str, ...] | None = None) -> pd.DataFrame:
        """Return rows known by as-of, preserving legacy date column values."""
        if dataset not in self._datasets:
            raise FactorContractError(f"unregistered dataset: {dataset}")
        cutoff = self._decision_at if asof is None else _aware(asof, "asof")
        if cutoff > self._decision_at:
            raise FactorContractError("asof cannot exceed decision_at")
        frame = self._datasets[dataset]
        work = _clone_frame(frame.loc[frame["available_at"] <= cutoff])
        # A calendar-date row from a later local day is never historical,
        # even if its availability field was accidentally backdated.
        for date_col in ("date", "asof_date", "disclosed_date", "data_end_date"):
            if work.empty:
                break
            if date_col in work.columns:
                parsed = work[date_col].map(lambda item: _calendar_stamp(item, f"{dataset}.{date_col}"))
                work = _clone_frame(work.loc[parsed <= cutoff])
        if fields is not None:
            selected = list(dict.fromkeys((*fields, "available_at")))
            missing = set(selected) - set(work.columns)
            if missing:
                raise FactorContractError(f"missing fields in {dataset}: {sorted(missing)}")
            work = _clone_frame(work.loc[:, selected])
        return _clone_frame(work.reset_index(drop=True))

    def universe(self, *, asof: Any | None = None) -> pd.DataFrame:
        """Return the latest known global universe snapshot using the same PIT gate."""
        rows = self.read("universe", asof=asof)
        required = {"asof_date", "code", "in_universe"}
        if not required.issubset(rows.columns):
            raise FactorContractError(f"universe lacks {sorted(required - set(rows.columns))}")
        if rows.empty:
            return rows
        parsed = pd.to_datetime(rows["asof_date"], errors="raise")
        latest = parsed.max()
        rows = _clone_frame(rows.loc[parsed.eq(latest) & rows["in_universe"].eq(True)])
        if rows["code"].astype(str).duplicated().any():
            raise FactorContractError("duplicate code in latest universe snapshot")
        return _clone_frame(rows.reset_index(drop=True))


class FactorResult:
    """Validated legacy-compatible ``minimal/detail/summary`` result.

    Missing factor values (NaN/NA) are preserved for explicit strategy policy;
    positive or negative infinity and duplicate codes are rejected.
    """

    REQUIRED_MINIMAL = frozenset({
        "code", "factor_name", "factor_value", "signal_date",
        "data_end_date", "rebalance_date",
    })

    def __init__(self, minimal: pd.DataFrame, detail: pd.DataFrame,
                 summary: Mapping[str, Any], *, factor_id: str | None = None,
                 extras: Mapping[str, Any] | None = None,
                 binding_id: str | None = None) -> None:
        if binding_id is not None and (not isinstance(binding_id, str) or not binding_id):
            raise FactorContractError("binding_id must be a nonempty config factor id")
        self._binding_id = binding_id
        if not isinstance(minimal, pd.DataFrame) or not isinstance(detail, pd.DataFrame):
            raise FactorContractError("minimal and detail must be DataFrames")
        if not isinstance(summary, Mapping):
            raise FactorContractError("summary must be a mapping")
        missing = self.REQUIRED_MINIMAL - set(minimal.columns)
        if missing:
            raise FactorContractError(f"minimal lacks columns: {sorted(missing)}")
        if minimal["code"].isna().any() or minimal["code"].astype(str).duplicated().any():
            raise FactorContractError("minimal code must be nonmissing and unique")
        if minimal["factor_name"].isna().any():
            raise FactorContractError("minimal factor_name must be present")
        if factor_id is not None and not minimal["factor_name"].eq(factor_id).all():
            raise FactorContractError("minimal factor_name differs from factor id")
        values = pd.to_numeric(minimal["factor_value"], errors="coerce")
        invalid_text = minimal["factor_value"].notna() & values.isna()
        if invalid_text.any() or values.map(lambda item: not math.isfinite(item) if pd.notna(item) else False).any():
            raise FactorContractError("factor_value must be finite or missing")
        for col in ("signal_date", "data_end_date", "rebalance_date"):
            series = minimal[col]
            parsed = pd.to_datetime(series, errors="coerce")
            if (series.notna() & parsed.isna()).any():
                raise FactorContractError(f"invalid minimal {col}")
        self._minimal = _clone_frame(minimal)
        self._detail = _clone_frame(detail)
        self._summary = copy.deepcopy(dict(summary))
        if extras and {"minimal", "detail", "summary"} & set(extras):
            raise FactorContractError("extra legacy keys collide with core result")
        self._extras = copy.deepcopy(dict(extras or {}))

    @classmethod
    def from_legacy_dict(cls, value: Mapping[str, Any], *, factor_id: str | None = None,
                         binding_id: str | None = None) -> "FactorResult":
        if not isinstance(value, Mapping) or not {"minimal", "detail", "summary"}.issubset(value):
            raise FactorContractError("legacy result needs minimal/detail/summary")
        extras = {key: item for key, item in value.items() if key not in {"minimal", "detail", "summary"}}
        return cls(value["minimal"], value["detail"], value["summary"],
                   factor_id=factor_id, extras=extras, binding_id=binding_id)

    @property
    def binding_id(self) -> str | None:
        """Config identity, separate from the unchanged legacy factor_name column."""
        return self._binding_id

    @property
    def minimal(self) -> pd.DataFrame:
        return _clone_frame(self._minimal)

    @property
    def detail(self) -> pd.DataFrame:
        return _clone_frame(self._detail)

    @property
    def summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)

    @property
    def extras(self) -> dict[str, Any]:
        return copy.deepcopy(self._extras)

    def to_legacy_dict(self) -> dict[str, Any]:
        return {"minimal": self.minimal, "detail": self.detail,
                "summary": self.summary, **self.extras}
