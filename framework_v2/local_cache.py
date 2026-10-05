"""Explicit, offline reader for local daily-bar inputs.

This module never searches for caches or calls a network service.  Callers
select one file/manifest, symbols, a date window, and a raw/adjusted price
basis.  Historical availability is preserved when present, never inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

import pandas as pd

from . import data_connection
from .config import ConfigError
from .data_snapshot import parquet_entries, snapshot_frames, verified_bytes


class LocalCacheError(ValueError):
    """An explicit local market-data input is incomplete or invalid."""


_CODE_RE = re.compile(r"^[0-9][0-9A-Z]{3}[0-9]?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?$"
)
_COLUMN_ALIASES = {
    "date": "date", "tradingdate": "date",
    "code": "code", "securitycode": "code", "stockcode": "code",
    "localcode": "code", "local_code": "code",
    "open": "open", "o": "open", "high": "high", "h": "high",
    "low": "low", "l": "low", "close": "close", "c": "close",
    "volume": "volume", "vo": "volume",
    "adjustmentfactor": "adjustment_factor", "adjfactor": "adjustment_factor",
    "adjustment_factor": "adjustment_factor",
    "adjustmentclose": "adjustment_close", "adjc": "adjustment_close",
    "adjustedclose": "adjustment_close", "adjustment_close": "adjustment_close",
    "availableat": "available_at", "available_at": "available_at",
}
_REQUIRED_COLUMNS = ("date", "code", "open", "high", "low", "close", "volume")
_KNOWN_HALT_DATE = "2020-10-01"
_KNOWN_HALT_REASON = "Tokyo Stock Exchange all-day trading halt caused by a system failure"
_KNOWN_HALT_SOURCE = "https://www.jpx.co.jp/english/news/1030/20201001-03.html"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    """Hash a selected file with bounded memory and detect concurrent edits."""
    try:
        before = path.stat()
        digest = sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
    except OSError:
        raise LocalCacheError("cannot read the selected local input") from None
    identity = lambda stat: (stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", None))
    if identity(before) != identity(after):
        raise LocalCacheError("selected local input changed while its identity was being read")
    return {"sha256": digest.hexdigest(), "size_bytes": after.st_size,
            "mtime_ns": after.st_mtime_ns, "file_identity": identity(after)}


def _verify_files(files: Iterable[tuple[Path, str]], message: str) -> None:
    for file_path, expected in files:
        try:
            actual = _file_identity(file_path)["sha256"]
        except (OSError, LocalCacheError):
            raise LocalCacheError(message) from None
        if actual != expected:
            raise LocalCacheError(message)


def _contained_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise LocalCacheError("frozen artifact path must be a non-empty relative path")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise LocalCacheError("frozen artifact path escapes its manifest directory")
    if not candidate.is_file():
        raise LocalCacheError("frozen artifact file is missing")
    return candidate


def _date_text(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        if _ISO_DATE_RE.fullmatch(text):
            return date.fromisoformat(text).isoformat()
        if _ISO_DATETIME_RE.fullmatch(text):
            # Daily-bar dates retain the calendar date written in the input.
            # A timezone offset does not imply a PIT timestamp or UTC date shift.
            return datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00")).date().isoformat()
        raise ValueError("unsupported date text")
    except (TypeError, ValueError):
        raise LocalCacheError("date must be YYYYMMDD, an ISO date, or a complete ISO datetime") from None


def _code_text(value: Any) -> str:
    if value is None or value is pd.NA:
        raise LocalCacheError("security code is missing")
    if isinstance(value, bool):
        raise LocalCacheError("security code is invalid")
    if isinstance(value, int):
        text = str(value).zfill(4) if 0 <= value <= 9999 else str(value)
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise LocalCacheError("security code is not an integer")
        integer = int(value)
        text = str(integer).zfill(4) if 0 <= integer <= 9999 else str(integer)
    else:
        text = str(value).strip().upper()
        # Strip only an explicit venue suffix. Numeric five-character codes
        # remain intact (for example 72030 is not collapsed to 7203).
        match = re.fullmatch(r"([0-9A-Z]{4,5})(?:[._-][A-Z][A-Z0-9]*)?", text)
        if match:
            text = match.group(1)
    if not _CODE_RE.fullmatch(text):
        raise LocalCacheError("security code must be a 4- or 5-character code")
    return text


def _column_key(value: Any) -> str:
    text = str(value).strip().lower()
    return re.sub(r"[\s-]+", "_", text)


def _canonical_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed: dict[Any, str] = {}
    seen: dict[str, Any] = {}
    for column in frame.columns:
        key = _column_key(column)
        compact = key.replace("_", "")
        target = _COLUMN_ALIASES.get(key, _COLUMN_ALIASES.get(compact, key))
        if target in seen:
            raise LocalCacheError(f"ambiguous source columns for {target}")
        seen[target] = column
        renamed[column] = target
    out = frame.rename(columns=renamed).copy()
    if "code" in out:
        if "source_code" not in out:
            out["source_code"] = out["code"].copy()
        out["code"] = out["code"].map(_code_text)
    if "date" in out:
        out["date"] = out["date"].map(_date_text)
    missing = sorted(set(_REQUIRED_COLUMNS) - set(out.columns))
    if missing:
        raise LocalCacheError(f"daily-bar input is missing required fields: {missing}")
    return out


def _number(value: Any, field: str, *, required: bool, row: int) -> float | None:
    if value is None or value is pd.NA or (isinstance(value, str) and not value.strip()):
        if required:
            raise LocalCacheError(f"missing {field} at row {row}")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LocalCacheError(f"invalid {field} at row {row}") from None
    if not math.isfinite(number):
        raise LocalCacheError(f"non-finite {field} at row {row}")
    return number


def _values_equal(left: Any, right: Any) -> bool:
    left_missing = left is None or left is pd.NA or left is pd.NaT
    right_missing = right is None or right is pd.NA or right is pd.NaT
    if left_missing or right_missing:
        return left_missing and right_missing
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _validate_and_sort(frame: pd.DataFrame, duplicate_policy: str = "reject",
                       known_halt_policy: str = "reject",
                       selected_codes: set[str] | None = None) -> tuple[pd.DataFrame, int, dict | None]:
    if frame.empty:
        raise LocalCacheError("daily-bar input is empty")
    if duplicate_policy not in {"reject", "drop_identical"}:
        raise LocalCacheError("duplicate_policy must be 'reject' or 'drop_identical'")
    if known_halt_policy not in {"reject", "exclude_verified_tse_halt_20201001"}:
        raise LocalCacheError("unsupported known-halt exclusion policy")
    out = frame.copy()
    duplicate_mask = out.duplicated(["code", "date"], keep=False)
    removed = 0
    if duplicate_mask.any():
        if duplicate_policy == "reject":
            raise LocalCacheError("duplicate security-code/date bars are not allowed (policy=reject)")
        columns = list(out.columns)
        keep_indices: list[int] = []
        for _key, group in out.loc[duplicate_mask].groupby(["code", "date"], sort=False, dropna=False):
            first = group.iloc[0]
            if any(any(not _values_equal(first[column], candidate[column]) for column in columns)
                   for _, candidate in group.iloc[1:].iterrows()):
                raise LocalCacheError("conflicting duplicate security-code/date bars are never allowed")
            keep_indices.append(int(group.index[0]))
            removed += len(group) - 1
        validated = out
        out = pd.concat([validated.loc[~duplicate_mask], validated.loc[keep_indices]], axis=0)
    halt_exclusion = None
    halt_mask = out["date"].eq(_KNOWN_HALT_DATE)
    if halt_mask.any() and known_halt_policy == "exclude_verified_tse_halt_20201001":
        halt_rows = out.loc[halt_mask]
        required_prices = ("open", "high", "low", "close", "volume")
        def source_null(value: Any) -> bool:
            return value is None or value is pd.NA or value is pd.NaT or (isinstance(value, str) and not value.strip())
        covered_codes = set(halt_rows["code"].astype(str))
        all_empty = all(all(source_null(value) for value in halt_rows[field]) for field in required_prices)
        if (selected_codes is None or covered_codes != selected_codes or len(halt_rows) != len(selected_codes)
                or not all_empty):
            raise LocalCacheError("verified TSE halt exclusion requires one 2020-10-01 row for every selected security, with all raw OHLCV fields null")
        out = out.loc[~halt_mask].copy()
        halt_exclusion = {"date": _KNOWN_HALT_DATE, "rows": len(halt_rows),
                          "codes": sorted(covered_codes), "reason": _KNOWN_HALT_REASON,
                          "source_url": _KNOWN_HALT_SOURCE}
    # All other missing bars, and any non-finite numeric values, remain hard errors.
    for field in ("open", "high", "low", "close"):
        out[field] = [_number(value, field, required=True, row=index)
                      for index, value in enumerate(out[field])]
        if any(value <= 0 for value in out[field]):
            raise LocalCacheError(f"{field} must be positive")
    out["volume"] = [_number(value, "volume", required=True, row=index)
                     for index, value in enumerate(out["volume"])]
    if any(value < 0 for value in out["volume"]):
        raise LocalCacheError("volume must be nonnegative")
    for field in ("adjustment_factor", "adjustment_close"):
        if field in out:
            values = [_number(value, field, required=False, row=index)
                      for index, value in enumerate(out[field])]
            if field == "adjustment_factor" and any(value is not None and value <= 0 for value in values):
                raise LocalCacheError("adjustment_factor must be positive when present")
            out[field] = pd.Series(values, index=out.index, dtype=object)
    for field in out.columns:
        for value in out[field]:
            numeric = value.item() if hasattr(value, "item") and not isinstance(value, (str, bytes)) else value
            if isinstance(numeric, float) and not math.isfinite(numeric):
                raise LocalCacheError(f"non-finite {field} is not a source null")
    if not (out["high"] >= out[["open", "close"]].max(axis=1)).all():
        raise LocalCacheError("high must be at least max(open, close)")
    if not (out["low"] <= out[["open", "close"]].min(axis=1)).all():
        raise LocalCacheError("low must be at most min(open, close)")
    if not (out["high"] >= out["low"]).all():
        raise LocalCacheError("high must be at least low")
    return out.sort_values(["date", "code"], kind="stable").reset_index(drop=True), removed, halt_exclusion


def _read_snapshot(path: Path, raw: bytes, manifest: dict) -> tuple[pd.DataFrame, list[dict], list[tuple[Path, str]], str]:
    snapshot_format = manifest.get("format")
    dependency_info: list[dict] = []
    verified_files: list[tuple[Path, str]] = [(path, _digest(raw))]
    if snapshot_format == "snapshot.inline.v1":
        frames = snapshot_frames(path, manifest)
        if "prices" not in frames:
            raise LocalCacheError("snapshot does not contain a prices dataset")
        info = [{"name": "snapshot.json", "sha256": _digest(raw)}]
        return frames["prices"], info, verified_files, snapshot_format
    if snapshot_format != "snapshot.parquet.v1":
        raise LocalCacheError("unsupported snapshot format")
    try:
        entries = parquet_entries(path, manifest)
    except ConfigError as exc:
        raise LocalCacheError(str(exc)) from None
    if "prices" not in entries:
        raise LocalCacheError("snapshot does not contain a prices dataset")
    prices_frame = None
    for name, (file_path, item) in entries.items():
        try:
            body = verified_bytes(file_path, item["sha256"])
        except (OSError, ConfigError) as exc:
            raise LocalCacheError(f"snapshot dataset verification failed: {name}") from None
        verified_files.append((file_path, item["sha256"]))
        dependency_info.append({"name": f"{name}.parquet", "sha256": item["sha256"],
                                "rows": item["rows"]})
        if name == "prices":
            try:
                prices_frame = pd.read_parquet(BytesIO(body))
            except ImportError:
                raise LocalCacheError("Parquet input requires an installed pyarrow or fastparquet engine") from None
            except Exception as exc:
                raise LocalCacheError(f"prices Parquet could not be read: {type(exc).__name__}") from None
            if len(prices_frame) != item["rows"]:
                raise LocalCacheError("snapshot prices row count mismatch")
    if prices_frame is None:
        raise LocalCacheError("snapshot does not contain a prices dataset")
    _verify_files(verified_files, "snapshot input changed while it was being read")
    return prices_frame, dependency_info, verified_files, snapshot_format


def _parquet_subset(path: Path, requested_codes: Iterable[str], start: str, end: str
                    ) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read only requested daily-bar rows from explicitly selected Parquet.

    One code column pass resolves aliases/leading zeroes. A second pass reads
    one row group at a time and projects its declared fields before applying
    the code predicate, keeping memory bounded by a row group.
    """
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError:
        raise LocalCacheError("Parquet input requires an installed pyarrow engine for bounded selection") from None
    try:
        parquet = pq.ParquetFile(path)
        schema_names = list(parquet.schema_arrow.names)
    except Exception as exc:
        raise LocalCacheError(f"Parquet could not be opened: {type(exc).__name__}") from None

    normalized: dict[str, str] = {}
    for name in schema_names:
        key = _column_key(name)
        compact = key.replace("_", "")
        target = _COLUMN_ALIASES.get(key, _COLUMN_ALIASES.get(compact, key))
        if target in normalized:
            raise LocalCacheError(f"ambiguous Parquet source columns for {target}")
        normalized[target] = name
    if "code" not in normalized or "date" not in normalized:
        raise LocalCacheError("Parquet daily bars require unambiguous code and date columns")
    code_column, date_column = normalized["code"], normalized["date"]

    canonical_to_raw: dict[str, set[Any]] = {}
    try:
        for index in range(parquet.metadata.num_row_groups):
            code_values = parquet.read_row_group(index, columns=[code_column])[code_column].unique().to_pylist()
            for raw_code in code_values:
                if raw_code is None:
                    continue
                canonical_to_raw.setdefault(_code_text(raw_code), set()).add(raw_code)
    except LocalCacheError:
        raise
    except Exception as exc:
        raise LocalCacheError(f"Parquet security-code index scan failed: {type(exc).__name__}") from None
    mapping, matched = _resolve_codes(set(canonical_to_raw), requested_codes)
    raw_selected = set().union(*(canonical_to_raw[code] for code in matched))
    field_type = parquet.schema_arrow.field(code_column).type
    try:
        raw_values = pa.array(list(raw_selected), type=field_type)
    except (TypeError, ValueError, pa.ArrowException):
        raise LocalCacheError("Parquet security-code field has an unsupported type") from None

    frames: list[pd.DataFrame] = []
    candidate_rows = 0
    date_filtered_rows = 0
    scanned = 0
    try:
        for index in range(parquet.metadata.num_row_groups):
            table = parquet.read_row_group(index, columns=schema_names)
            scanned += 1
            mask = pc.is_in(table[code_column], value_set=raw_values)
            selected_table = table.filter(mask)
            if not selected_table.num_rows:
                continue
            candidate_rows += selected_table.num_rows
            selected_dates = selected_table[date_column]
            if selected_dates.null_count:
                raise LocalCacheError("Parquet selected securities contain missing date values")
            date_type = parquet.schema_arrow.field(date_column).type
            if pa.types.is_string(date_type) or pa.types.is_large_string(date_type):
                raw_dates = selected_dates
                if pc.sum(pc.cast(pc.equal(raw_dates, ""), pa.int64())).as_py():
                    raise LocalCacheError("Parquet selected securities contain empty date values")
                prefix10 = pc.utf8_slice_codeunits(raw_dates, start=0, stop=10)
                iso_mask = pc.and_(pc.greater_equal(prefix10, start), pc.less_equal(prefix10, end))
                prefix8 = pc.utf8_slice_codeunits(raw_dates, start=0, stop=8)
                compact_mask = pc.and_(
                    pc.equal(pc.utf8_length(raw_dates), 8),
                    pc.and_(pc.greater_equal(prefix8, start.replace("-", "")),
                            pc.less_equal(prefix8, end.replace("-", ""))))
                selected_table = selected_table.filter(pc.or_(iso_mask, compact_mask))
            date_filtered_rows += selected_table.num_rows
            if not selected_table.num_rows:
                continue
            # Arrow-backed conversion preserves nulls as pd.NA instead of
            # turning them into indistinguishable IEEE NaNs.
            try:
                frame = selected_table.to_pandas(types_mapper=pd.ArrowDtype)
            except TypeError:
                frame = selected_table.to_pandas()
            frame = _canonical_columns(frame)
            frame = frame.loc[frame["code"].isin(matched) & frame["date"].between(start, end)]
            if not frame.empty:
                frames.append(frame)
    except LocalCacheError:
        raise
    except Exception as exc:
        raise LocalCacheError(f"Parquet selected-row read failed: {type(exc).__name__}") from None
    if not frames:
        raise LocalCacheError("no bars match the selected symbols and date window")
    frame = pd.concat(frames, ignore_index=True)
    observed = set(frame["code"].astype(str))
    if observed != matched:
        raise LocalCacheError(f"selected symbols have no bars in the date window: {sorted(matched - observed)}")
    return frame, {"schema_fields": schema_names,
                   "file_rows": parquet.metadata.num_rows,
                   "row_groups": parquet.metadata.num_row_groups,
                   "row_groups_scanned": scanned,
                   "candidate_rows_for_codes": candidate_rows,
                   "rows_after_arrow_date_filter": date_filtered_rows,
                   "selected_rows_before_dedup": len(frame),
                   "requested_codes": list(requested_codes),
                   "matched_codes": mapping,
                   "selection_method": "projected row-group read; code filter before pandas normalization; observed-date filter"}


def _read_frozen_manifest(path: Path, raw: bytes, manifest: dict) -> tuple[pd.DataFrame, dict, list[tuple[Path, str]]]:
    if manifest.get("schema_version") != 1:
        raise LocalCacheError("unsupported local research artifact schema version")
    selection = manifest.get("selection")
    basis = manifest.get("price_basis")
    if not isinstance(selection, dict) or basis not in {"raw", "adjusted"}:
        raise LocalCacheError("frozen artifact selection or price basis is invalid")
    if selection.get("price_basis") != basis:
        raise LocalCacheError("frozen artifact price basis does not match its selection")
    root = path.parent.resolve()
    typed = manifest.get("canonical_data")
    convenience = manifest.get("frozen_data")
    if not isinstance(typed, dict) or not isinstance(convenience, dict):
        raise LocalCacheError("frozen artifact data entries are missing")
    typed_path = _contained_file(root, typed.get("file"))
    csv_path = _contained_file(root, convenience.get("file"))
    expected_hash = manifest.get("selected_data_sha256")
    if (not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
            or typed.get("sha256") != expected_hash):
        raise LocalCacheError("frozen artifact canonical-data hash identity is invalid")
    try:
        typed_bytes = typed_path.read_bytes()
        csv_bytes = csv_path.read_bytes()
    except OSError:
        raise LocalCacheError("frozen artifact data file could not be read") from None
    if _digest(typed_bytes) != typed.get("sha256"):
        raise LocalCacheError("frozen artifact canonical-data hash mismatch")
    try:
        records = json.loads(typed_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise LocalCacheError("frozen artifact canonical data is invalid JSON") from None
    if not isinstance(records, list) or not records or any(not isinstance(row, dict) for row in records):
        raise LocalCacheError("frozen artifact canonical rows are invalid")
    if typed_bytes != _canonical_json(records) or _digest(_canonical_json(records)) != expected_hash:
        raise LocalCacheError("frozen artifact selected-data identity does not match its canonical rows")
    canonical_columns = list(records[0])
    if any(list(row) != canonical_columns for row in records):
        raise LocalCacheError("frozen artifact canonical row columns are inconsistent")
    csv_columns = convenience.get("columns")
    if (typed.get("rows") != len(records) or typed.get("columns") != canonical_columns
            or convenience.get("rows") != len(records) or not isinstance(csv_columns, list)
            or set(csv_columns) != set(canonical_columns) or len(csv_columns) != len(canonical_columns)):
        raise LocalCacheError("frozen artifact row or column metadata mismatch")
    availability = manifest.get("availability")
    if not isinstance(availability, dict) or availability.get("pit_guarantee") is not False:
        raise LocalCacheError("frozen artifact cannot claim a PIT guarantee")
    if any(row.get("selected_price_basis") != basis for row in records):
        raise LocalCacheError("frozen artifact rows mix or contradict the declared price basis")
    original_source = manifest.get("source")
    original_identity = manifest.get("identity_sha256")
    expected_identity = _digest(_canonical_json({
        "source_sha256": (original_source or {}).get("source_sha256"),
        "dependencies": (original_source or {}).get("dependencies"),
        "selection": selection, "selected_data_sha256": expected_hash,
    }))
    if original_identity != expected_identity:
        raise LocalCacheError("frozen artifact pinned source identity mismatch")
    try:
        csv_frame = pd.read_csv(BytesIO(csv_bytes), dtype=str, low_memory=False)
    except Exception as exc:
        raise LocalCacheError(f"frozen artifact convenience CSV is invalid: {type(exc).__name__}") from None
    if len(csv_frame) != len(records) or list(csv_frame.columns) != csv_columns:
        raise LocalCacheError("frozen artifact convenience CSV row or column mismatch")
    if (not isinstance(convenience.get("sha256"), str)
            or _digest(csv_bytes) != convenience["sha256"]):
        raise LocalCacheError("frozen artifact convenience CSV hash mismatch")
    files = [(path, _digest(raw)), (typed_path, typed.get("sha256")),
             (csv_path, convenience["sha256"])]
    _verify_files(files, "frozen artifact changed while it was being read")
    frame = pd.DataFrame(records, dtype=object)
    source = {
        "kind": "kabuforge_local_research_bars", "schema_version": 1,
        "source_sha256": _digest(raw),
        "details": {
            "pit_guarantee": False, "availability_field_present": "available_at" in frame,
            "pinned_identity_sha256": manifest.get("identity_sha256"),
            "pinned_selected_data_sha256": expected_hash,
            "pinned_selection": selection, "original_source": original_source,
        },
        "dependencies": [
            {"name": typed_path.name, "sha256": typed.get("sha256"), "rows": len(records)},
            {"name": csv_path.name, "sha256": convenience.get("sha256"), "rows": len(records)},
        ],
    }
    return frame, source, files


def _read_explicit_source(path: Path, *, requested_codes: Iterable[str] | None = None,
                          start: str | None = None, end: str | None = None
                          ) -> tuple[pd.DataFrame, dict, list[tuple[Path, str]]]:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        if requested_codes is None or start is None or end is None:
            raise LocalCacheError("Parquet source needs an explicit code and date selection")
        identity_before = _file_identity(path)
        frame, parquet_details = _parquet_subset(path, requested_codes, start, end)
        identity_after = _file_identity(path)
        if identity_before != identity_after:
            raise LocalCacheError("Parquet input changed while selected rows were being read")
        source = {"kind": "local_parquet", "schema_version": "external-local-bars.v1",
                  "source_sha256": identity_before["sha256"],
                  "details": {"pit_guarantee": False,
                              "availability_field_present": "available_at" in frame.columns,
                              "file_size_bytes": identity_before["size_bytes"],
                              "input_file_identity_sha256": _digest(_canonical_json({
                                  "sha256": identity_before["sha256"],
                                  "size_bytes": identity_before["size_bytes"]})),
                              "parquet_selection": parquet_details},
                  "dependencies": []}
        return frame, source, [(path, identity_before["sha256"])]
    try:
        raw = path.read_bytes()
    except OSError:
        raise LocalCacheError("cannot read the selected local input") from None
    source_hash = _digest(raw)
    dependencies: list[tuple[Path, str]] = []
    if suffix in {".csv", ".txt"}:
        try:
            # Preserve empty cells as empty source values so the validator can
            # distinguish an explicit null from IEEE NaN in numeric cells.
            frame = pd.read_csv(BytesIO(raw), dtype=str, low_memory=False, keep_default_na=False)
        except Exception as exc:
            raise LocalCacheError(f"CSV could not be read: {type(exc).__name__}") from None
        kind = "local_csv"
        details = {"schema_version": "external-local-bars.v1"}
    elif suffix == ".json":
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise LocalCacheError("selected JSON file is not a supported manifest") from None
        if not isinstance(manifest, dict):
            raise LocalCacheError("selected JSON manifest must be an object")
        if manifest.get("kind") == "jquants_equities_daily_bars":
            if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
                raise LocalCacheError("a complete J-Quants daily-bars manifest is required")
            before = _digest(path.read_bytes())
            try:
                rows = data_connection.load_bars(path)
            except Exception as exc:
                raise LocalCacheError(f"J-Quants manifest/page verification failed: {type(exc).__name__}") from None
            if _digest(path.read_bytes()) != before or before != source_hash:
                raise LocalCacheError("J-Quants manifest changed while it was being read")
            # Keep upstream nulls as object None values; otherwise pandas may
            # turn optional adjustment fields into float NaN and misclassify
            # a source null as a non-finite numeric observation.
            frame = pd.DataFrame(rows, dtype=object)
            kind = "jquants_manifest"
            request = manifest.get("request") or {}
            details = {"schema_version": manifest.get("schema_version"),
                       "request": request, "pit_guarantee": False,
                       "availability": manifest.get("availability", "unverified")}
            for page in manifest.get("pages", []):
                page_path = (path.parent / str(page.get("file", ""))).resolve()
                dependencies.append((page_path, str(page.get("sha256", ""))))
            for page_path, expected_hash in dependencies:
                try:
                    actual_hash = _digest(page_path.read_bytes())
                except OSError:
                    raise LocalCacheError("J-Quants page disappeared while being read") from None
                if actual_hash != expected_hash:
                    raise LocalCacheError("J-Quants page changed while being read")
            dependency_info = [{"name": file.name, "sha256": digest}
                               for file, digest in dependencies]
            return frame, {"kind": kind, "schema_version": details["schema_version"],
                           "source_sha256": source_hash, "details": details,
                           "dependencies": dependency_info}, [(path, source_hash), *dependencies]
        if manifest.get("kind") == "kabuforge_local_research_bars":
            return _read_frozen_manifest(path, raw, manifest)
        if manifest.get("format") in {"snapshot.inline.v1", "snapshot.parquet.v1"}:
            frame, dependency_info, verified_files, snapshot_format = _read_snapshot(path, raw, manifest)
            return frame, {"kind": snapshot_format, "schema_version": snapshot_format,
                           "source_sha256": source_hash, "details": {"pit_guarantee": False,
                           "availability_field_present": "available_at" in frame.columns},
                           "dependencies": dependency_info}, verified_files
        raise LocalCacheError("JSON input must be a supported completed J-Quants manifest or data snapshot")
    else:
        raise LocalCacheError("select one CSV, Parquet, or supported JSON manifest file")
    return frame, {"kind": kind, "schema_version": details["schema_version"],
                   "source_sha256": source_hash,
                   "details": {"pit_guarantee": False,
                               "availability_field_present": "available_at" in frame.columns},
                   "dependencies": dependencies}, [(path, source_hash)]


def _resolve_codes(available: set[str], requested: Iterable[str]) -> tuple[dict[str, str], set[str]]:
    selected = [_code_text(item) for item in requested]
    if not selected or len(selected) != len(set(selected)):
        raise LocalCacheError("choose one or more unique 4- or 5-character security codes")
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for code in selected:
        if code in available:
            match = code
        elif len(code) == 4:
            matches = sorted(item for item in available if len(item) == 5 and item.startswith(code))
            if len(matches) > 1:
                raise LocalCacheError(f"4-character code {code} matches multiple 5-character securities")
            if not matches:
                raise LocalCacheError(f"security code not found: {code}")
            match = matches[0]
        else:
            raise LocalCacheError(f"security code not found: {code}")
        if match in used:
            raise LocalCacheError("requested codes resolve to the same local security")
        mapping[code] = match
        used.add(match)
    return mapping, used


def _frame_records(frame: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for row in frame.to_dict(orient="records"):
        clean = {}
        for key, value in row.items():
            if value is None or value is pd.NA:
                clean[key] = None
            elif isinstance(value, (pd.Timestamp, datetime, date)):
                clean[key] = value.isoformat()
            elif hasattr(value, "item"):
                value = value.item()
                clean[key] = value if not isinstance(value, float) or math.isfinite(value) else None
            elif isinstance(value, float) and not math.isfinite(value):
                clean[key] = None
            else:
                clean[key] = value
        records.append(clean)
    return records


@dataclass
class LocalResearchBars:
    """Verified selected bars plus source, coverage, and price-basis identity."""

    bars: pd.DataFrame
    source: dict
    selection: dict
    coverage: dict
    selected_data_sha256: str
    identity_sha256: str
    _verified_files: tuple[tuple[Path, str], ...]

    def freeze(self, output_dir: str | Path) -> Path:
        """Write a new immutable CSV+manifest package to a caller-owned path."""
        output = Path(output_dir).resolve()
        if output.exists():
            raise FileExistsError(output)
        _verify_files(self._verified_files,
                      "a source input changed or disappeared after inspection; reload before freezing")
        current_hash = _digest(_canonical_json(_frame_records(self.bars)))
        if current_hash != self.selected_data_sha256:
            raise LocalCacheError("selected bars were modified after inspection")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=False, exist_ok=False)
        bars_path = output / "prices.csv"
        with bars_path.open("x", encoding="utf-8-sig", newline="") as stream:
            self.bars.to_csv(stream, index=False, lineterminator="\n")
        bars_hash = _digest(bars_path.read_bytes())
        canonical_path = output / "selected_rows.json"
        canonical_bytes = _canonical_json(_frame_records(self.bars))
        with canonical_path.open("xb") as stream:
            stream.write(canonical_bytes)
        canonical_hash = _digest(canonical_bytes)
        manifest = {
            "schema_version": 1,
            "kind": "kabuforge_local_research_bars",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": self.source,
            "selection": self.selection,
            "coverage": self.coverage,
            "selected_data_sha256": self.selected_data_sha256,
            "identity_sha256": self.identity_sha256,
            "frozen_data": {"file": "prices.csv", "sha256": bars_hash,
                            "rows": len(self.bars), "columns": list(self.bars.columns)},
            "canonical_data": {"file": "selected_rows.json", "sha256": canonical_hash,
                                "rows": len(self.bars), "columns": sorted(self.bars.columns),
                                "encoding": "canonical-json-rows.v1"},
            "price_basis": self.selection["price_basis"],
            "availability": {"field_present": "available_at" in self.bars.columns,
                              "semantics": "preserved input only; not certified or inferred",
                              "pit_guarantee": False},
            "readiness": "RESEARCH-ONLY; source history visibility is unverified",
        }
        with (output / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        return output / "manifest.json"


def load_research_bars(
    source_path: str | Path,
    *,
    codes: Iterable[str],
    start_date: str | date,
    end_date: str | date,
    price_basis: str = "raw",
    duplicate_policy: str = "reject",
    known_halt_policy: str = "reject",
) -> LocalResearchBars:
    """Load one explicitly selected CSV, Parquet, J-Quants manifest or snapshot.

    This operation is read-only. It never scans a directory or creates a
    network client. Call ``result.freeze(new_workspace_path)`` to write an
    independently selected, hash-bound research input package.
    """
    if price_basis not in {"raw", "adjusted"}:
        raise LocalCacheError("price_basis must be explicitly 'raw' or 'adjusted'")
    if duplicate_policy not in {"reject", "drop_identical"}:
        raise LocalCacheError("duplicate_policy must be 'reject' or 'drop_identical'")
    if known_halt_policy not in {"reject", "exclude_verified_tse_halt_20201001"}:
        raise LocalCacheError("unsupported known-halt exclusion policy")
    requested_codes = [_code_text(code) for code in codes]
    if not requested_codes:
        raise LocalCacheError("choose one or more unique 4- or 5-character security codes")
    start = _date_text(start_date); end = _date_text(end_date)
    if start > end:
        raise LocalCacheError("start_date must not follow end_date")
    path = Path(source_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise LocalCacheError("selected input must be a file")
    frame, source, verified_files = _read_explicit_source(
        path, requested_codes=requested_codes, start=start, end=end)
    source = {**source, "source_fields": [str(column) for column in frame.columns]}
    pinned_selection = source.get("details", {}).get("pinned_selection")
    if source.get("kind") == "kabuforge_local_research_bars":
        if price_basis != pinned_selection.get("price_basis"):
            raise LocalCacheError("requested price basis must match the frozen artifact")
        if start < pinned_selection.get("start_date", "") or end > pinned_selection.get("end_date", ""):
            raise LocalCacheError("requested date window exceeds the frozen artifact selection")
        if duplicate_policy != pinned_selection.get("duplicate_policy", "reject"):
            raise LocalCacheError("duplicate policy must match the frozen artifact selection")
        if known_halt_policy != pinned_selection.get("known_halt_policy", "reject"):
            raise LocalCacheError("known-halt policy must match the frozen artifact selection")
    frame = _canonical_columns(frame)
    if frame.empty:
        raise LocalCacheError("daily-bar input is empty")
    mapping, matched = _resolve_codes(set(frame["code"].astype(str)), requested_codes)
    if pinned_selection is not None:
        pinned_codes = set((pinned_selection.get("matched_codes") or {}).values())
        if not matched.issubset(pinned_codes):
            raise LocalCacheError("requested securities exceed the frozen artifact selection")
    selected = frame.loc[frame["code"].isin(matched) & frame["date"].between(start, end)].copy()
    if selected.empty:
        raise LocalCacheError("no bars match the selected symbols and date window")
    rows_before_dedup = len(selected)
    selected, duplicates_removed, halt_exclusion = _validate_and_sort(
        selected, duplicate_policy, known_halt_policy, matched)
    rows_before_halt_exclusion = len(selected) + (halt_exclusion["rows"] if halt_exclusion else 0)
    if selected.empty:
        raise LocalCacheError("no bars match the selected symbols and date window")
    observed = set(selected["code"].astype(str))
    if observed != matched:
        absent = sorted(matched - observed)
        raise LocalCacheError(f"selected symbols have no bars in the date window: {absent}")
    if halt_exclusion is None and pinned_selection is not None:
        halt_exclusion = pinned_selection.get("verified_halt_exclusion")
    if halt_exclusion is not None and not halt_exclusion.get("input_source_sha256"):
        halt_exclusion = {**halt_exclusion, "input_source_sha256": source["source_sha256"]}
    if price_basis == "adjusted":
        if "adjustment_close" not in selected:
            raise LocalCacheError("adjusted price basis requested but adjustment_close is absent")
        chosen = [_number(value, "adjustment_close", required=True, row=index)
                  for index, value in enumerate(selected["adjustment_close"])]
        if any(value <= 0 for value in chosen):
            raise LocalCacheError("adjustment_close must be positive")
        selected["adjustment_close"] = chosen
        selected["selected_price"] = chosen
    else:
        selected["selected_price"] = selected["close"].astype(float)
    selected["selected_price_basis"] = price_basis
    selected = selected.sort_values(["date", "code"], kind="stable").reset_index(drop=True)
    selected_records = _frame_records(selected)
    selected_hash = _digest(_canonical_json(selected_records))
    selection = {"requested_codes": requested_codes, "matched_codes": mapping,
                 "start_date": start, "end_date": end, "price_basis": price_basis,
                 "duplicate_policy": duplicate_policy, "known_halt_policy": known_halt_policy,
                 "verified_halt_exclusion": halt_exclusion}
    identity = _digest(_canonical_json({"source_sha256": source["source_sha256"],
        "dependencies": source["dependencies"], "selection": selection,
        "selected_data_sha256": selected_hash}))
    per_code = []
    for requested_code, matched_code in mapping.items():
        group = selected.loc[selected["code"].eq(matched_code)]
        per_code.append({"requested_code": requested_code, "matched_code": matched_code,
            "rows": len(group), "first_observed_date": group["date"].min(),
            "last_observed_date": group["date"].max(),
            "distinct_observed_dates": int(group["date"].nunique())})
    coverage = {"requested_start": start, "requested_end": end,
                "rows": len(selected), "symbols": per_code,
                "duplicate_policy": duplicate_policy,
                "rows_before_dedup": rows_before_dedup,
                "duplicate_rows_removed": duplicates_removed,
                "rows_before_halt_exclusion": rows_before_halt_exclusion,
                "verified_halt_exclusion": halt_exclusion,
                "calendar_note": "observed dates only; no exchange calendar was inferred",
                "missing_expected_sessions": None}
    source = {**source, "selected_file_name": path.name}
    return LocalResearchBars(selected.copy(deep=True), source, selection, coverage,
                             selected_hash, identity, tuple(verified_files))
