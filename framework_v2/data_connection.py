"""Explicit, resumable J-Quants v2 daily-bar downloads for local research.

Downloaded rows are a current API view. They have no verified ``available_at``
and must not be passed to the strict point-in-time snapshot engine.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Iterable

import requests

BASE_URL = "https://api.jquants.com/v2"
ENDPOINT = "/equities/bars/daily"
_KEY_TARGET = "KabuForge/JQuantsApiV2"
_CODE_RE = re.compile(r"^[0-9][0-9A-Z]{3}[0-9]?$")


class DownloadCancelled(Exception):
    """Raised after preserving all successfully committed pages."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_text(value: str | date) -> str:
    parsed = date.fromisoformat(str(value))
    return parsed.isoformat()


def _codes(values: Iterable[str]) -> list[str]:
    result = sorted({str(item).strip().upper() for item in values})
    if not result or any(not _CODE_RE.fullmatch(item) for item in result):
        raise ValueError("Enter one or more 4- or 5-character security codes")
    return result


def _request_id(codes: list[str], start: str, end: str) -> str:
    payload = json.dumps([codes, start, end], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _get_json(session, path: str, api_key: str, params: dict) -> dict:
    try:
        response = session.get(BASE_URL + path, headers={"x-api-key": api_key}, params=params, timeout=(10, 45),allow_redirects=False)
        status = response.status_code
        if status != 200:
            # Never expose response text; services sometimes echo credentials.
            raise RuntimeError(f"J-Quants HTTP {status}")
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("J-Quants network request failed") from None
    except ValueError:
        raise RuntimeError("J-Quants returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise RuntimeError("J-Quants returned an unexpected JSON shape")
    return payload


def test_connection(api_key: str, *, session=None) -> bool:
    """Make one read-only, explicit connectivity request; never writes a cache."""
    if not api_key or not api_key.strip():
        raise ValueError("API key is required")
    payload = _get_json(session or requests.Session(), "/equities/master", api_key.strip(), {"code": "86970"})
    if not isinstance(payload.get("data"), list):
        raise RuntimeError("J-Quants returned an unexpected master response")
    return True


def _new_manifest(codes: list[str], start: str, end: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "jquants_equities_daily_bars",
        "source_endpoint": BASE_URL + ENDPOINT,
        "request": {"codes": codes, "start": start, "end": end},
        "status": "in_progress",
        "created_at": _utc_now(), "updated_at": _utc_now(),
        "owner_pid":os.getpid(),"entrypoint":"DataConnectionPanel / download_bars",
        "recovery":"Retry identical codes and dates; verified page checkpoints are reused",
        "exit_method":"Cancel in Data center; pending HTTP requests finish at their timeout",
        "pages": [], "completed_codes": [], "next_pagination_key": {},
        "pit_guarantee": False, "availability": "unverified",
    }


def _read_manifest(path: Path, expected: dict) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("kind") != "jquants_equities_daily_bars" or value.get("request") != expected:
        raise ValueError("Existing download manifest does not match this request")
    return value


@contextmanager
def _single_writer(root: Path):
    """Nonblocking cross-process lock for this request ID."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".download.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("This download is already running in another window") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_pages(path: Path, manifest: dict) -> list[dict]:
    rows = []
    for page in manifest["pages"]:
        source = (path.parent / page["file"]).resolve()
        if not source.is_relative_to(path.parent) or not source.is_file():
            raise ValueError("Manifest page path is invalid")
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest() != page["sha256"]:
            raise ValueError("Downloaded page integrity check failed")
        raw = json.loads(body)
        if not isinstance(raw, list) or len(raw) != page["row_count"]:
            raise ValueError("Downloaded page row count failed")
        for item in raw:
            row = _normalize(item)
            if not _code_matches(page["code"], row["code"]):
                raise ValueError("Downloaded page security code does not match request")
            request = manifest["request"]
            if not request["start"] <= row["date"] <= request["end"]:
                raise ValueError("Downloaded page date is outside requested range")
            rows.append(row)
    return rows


def download_bars(
    workspace: str | Path, api_key: str, codes: Iterable[str], start: str | date, end: str | date,
    *, session=None, cancel_event=None, progress: Callable[[dict], None] | None = None,
) -> Path:
    """Download selected codes, committing each page and cursor atomically.

    Repeating an identical request resumes it. A completed request is reused
    without an HTTP call. The caller must avoid concurrent writers to one ID.
    """
    if not api_key or not api_key.strip():
        raise ValueError("API key is required")
    selected = _codes(codes)
    first, last = _date_text(start), _date_text(end)
    if first > last:
        raise ValueError("Start date must not follow end date")
    root = Path(workspace).resolve() / "jquants_downloads" / _request_id(selected, first, last)
    with _single_writer(root):
        return _download_bars_unlocked(root, api_key, selected, first, last,
                                       session=session, cancel_event=cancel_event, progress=progress)


def _download_bars_unlocked(root, api_key, selected, first, last, *, session, cancel_event, progress):
    manifest_path = root / "manifest.json"
    expected = {"codes": selected, "start": first, "end": last}
    manifest = _read_manifest(manifest_path, expected) if manifest_path.exists() else _new_manifest(selected, first, last)
    if manifest_path.exists():
        _read_pages(manifest_path, manifest)
    if manifest.get("status") == "complete":
        load_bars(manifest_path)  # Verify committed pages before reuse.
        return manifest_path
    root.mkdir(parents=True, exist_ok=True)
    _atomic_json(manifest_path, manifest)
    client = session or requests.Session()
    try:
        for code in selected:
            if code in manifest["completed_codes"]:
                continue
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled; completed pages can be resumed")
                params = {"code": code, "from": first.replace("-", ""), "to": last.replace("-", "")}
                cursor = manifest["next_pagination_key"].get(code)
                if cursor:
                    params["pagination_key"] = cursor
                payload = _get_json(client, ENDPOINT, api_key.strip(), params)
                rows = payload.get("data")
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise RuntimeError("J-Quants response has no data list")
                next_cursor = payload.get("pagination_key")
                if next_cursor is not None and not isinstance(next_cursor, str):
                    raise RuntimeError("J-Quants pagination key is invalid")
                seen = manifest.setdefault("seen_pagination_keys", {}).setdefault(code, [])
                if next_cursor and (next_cursor == cursor or next_cursor in seen):
                    raise RuntimeError("J-Quants repeated a pagination key")
                if not next_cursor and not rows and not any(page["code"] == code and page["row_count"] > 0 for page in manifest["pages"]):
                    raise RuntimeError(f"No daily bars returned for {code} in the selected range")
                index = sum(page["code"] == code for page in manifest["pages"])
                relative = f"pages/{code}-{index:06d}.json"
                body = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                _atomic_bytes(root / relative, body)
                manifest["pages"].append({"code": code, "file": relative, "sha256": hashlib.sha256(body).hexdigest(), "row_count": len(rows)})
                if next_cursor:
                    manifest["next_pagination_key"][code] = next_cursor
                    seen.append(next_cursor)
                else:
                    manifest["next_pagination_key"].pop(code, None)
                    manifest["completed_codes"].append(code)
                manifest["updated_at"] = _utc_now()
                _atomic_json(manifest_path, manifest)
                if progress:
                    progress({"code": code, "page": index + 1, "rows": len(rows), "completed_codes": len(manifest["completed_codes"]), "total_codes": len(selected)})
                if not next_cursor:
                    break
        manifest["status"] = "complete"
        manifest["updated_at"] = _utc_now()
        _atomic_json(manifest_path, manifest)
        return manifest_path
    except DownloadCancelled:
        manifest["status"] = "cancelled"
        manifest["updated_at"] = _utc_now()
        _atomic_json(manifest_path, manifest)
        raise
    except Exception:
        manifest["status"]="failed"
        manifest["updated_at"]=_utc_now()
        _atomic_json(manifest_path,manifest)
        raise


def _number(row: dict, *names: str):
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid numeric bar field {name}") from None
    return None


def _normalize(row: dict) -> dict:
    code = str(row.get("Code", row.get("code", "")))
    if not _CODE_RE.fullmatch(code):
        raise ValueError("Bar has invalid security code")
    raw_date = str(row.get("Date", row.get("date", "")))
    parsed_date = date.fromisoformat(raw_date if "-" in raw_date else f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}")
    return {
        "date": parsed_date.isoformat(), "code": code,
        "open": _number(row, "Open", "O", "open"),
        "high": _number(row, "High", "H", "high"),
        "low": _number(row, "Low", "L", "low"),
        "close": _number(row, "Close", "C", "close"),
        "volume": _number(row, "Volume", "Vo", "volume"),
        "adjustment_factor": _number(row, "AdjustmentFactor", "AdjFactor", "adjustment_factor"),
        "adjustment_close": _number(row, "AdjustmentClose", "AdjC", "adjustment_close"),
    }


def _code_matches(requested: str, actual: str) -> bool:
    return actual == requested or (len(requested) == 4 and len(actual) == 5 and actual.startswith(requested))


def load_bars(manifest_path: str | Path) -> list[dict]:
    """Read only a complete manifest, verify page hashes, return normalized rows."""
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "jquants_equities_daily_bars" or manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        raise ValueError("A complete J-Quants daily-bars manifest is required")
    rows = _read_pages(path, manifest)
    if not rows or any(not any(_code_matches(code, row["code"]) for row in rows) for code in manifest["request"]["codes"]):
        raise ValueError("Downloaded bars have incomplete code coverage")
    return sorted(rows, key=lambda row: (row["date"], row["code"]))


def save_api_key(api_key: str) -> None:
    """Opt-in storage in the current Windows user's Credential Manager."""
    if os.name != "nt":
        raise OSError("Windows Credential Manager is unavailable")
    if not api_key or not api_key.strip():
        raise ValueError("API key is required")
    blob = api_key.strip().encode("utf-16-le")
    if len(blob) > 2560:
        raise ValueError("API key is too long")
    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = CREDENTIAL(Type=1, TargetName=_KEY_TARGET, CredentialBlobSize=len(blob),
                            CredentialBlob=buffer, Persist=2, UserName="KabuForge")
    fn = ctypes.WinDLL("Advapi32", use_last_error=True).CredWriteW
    fn.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(credential), 0):
        raise OSError(ctypes.get_last_error(), "Credential Manager write failed")


def load_api_key() -> str | None:
    if os.name != "nt":
        return None
    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    pointer = ctypes.POINTER(CREDENTIAL)()
    dll = ctypes.WinDLL("Advapi32", use_last_error=True)
    read = dll.CredReadW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    read.restype = wintypes.BOOL
    if not read(_KEY_TARGET, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise OSError(ctypes.get_last_error(), "Credential Manager read failed")
    try:
        value = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
        return value.decode("utf-16-le")
    finally:
        free = dll.CredFree
        free.argtypes = [ctypes.c_void_p]
        free(pointer)


def delete_api_key() -> None:
    """Remove only this app's saved J-Quants API key."""
    if os.name != "nt":
        return
    fn = ctypes.WinDLL("Advapi32", use_last_error=True).CredDeleteW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if not fn(_KEY_TARGET, 1, 0) and ctypes.get_last_error() != 1168:
        raise OSError(ctypes.get_last_error(), "Credential Manager delete failed")
