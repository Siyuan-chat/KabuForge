"""Offline kabuStation configuration and cash-order mapping preview.

This module deliberately has no credential lookup and no network transport.
It stores a credential *reference* only and calls the existing pure
``KabuCashBroker.map_order`` mapper. A saved configuration is not a connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .brokers import KABU_REF, BrokerContractError, KabuCashBroker
from .execution import Instrument, OrderIntent, aware


SCHEMA_VERSION = 1
_ENDPOINTS = {"production": "http://127.0.0.1:18080", "test": "http://127.0.0.1:18081"}
_CREDENTIAL_REF = re.compile(r"^(?:env:[A-Z][A-Z0-9_]{1,63}|credential-manager:[A-Za-z0-9._/-]{1,120})$")


class BrokerResearchError(ValueError):
    """Unsafe or incomplete local broker-research configuration/input."""


@dataclass(frozen=True)
class BrokerResearchConfig:
    environment: str
    endpoint: str
    account_id: str
    account_type: int
    exchange: int
    credential_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.environment, str) or self.environment not in _ENDPOINTS:
            raise BrokerResearchError("environment must be production or test")
        if self.endpoint != _ENDPOINTS[self.environment]:
            raise BrokerResearchError("endpoint must match the selected localhost environment and port")
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            raise BrokerResearchError("only an explicit localhost HTTP endpoint is allowed")
        if not isinstance(self.account_id, str) or not self.account_id.strip() or len(self.account_id) > 100:
            raise BrokerResearchError("account_id must be a nonempty local label")
        if type(self.account_type) is not int or self.account_type not in {2, 4}:
            raise BrokerResearchError("account_type must be general(2) or specified(4)")
        if type(self.exchange) is not int or self.exchange not in {9, 27}:
            raise BrokerResearchError("exchange must explicitly select SOR(9) or Tokyo+(27)")
        if not isinstance(self.credential_ref, str) or not _CREDENTIAL_REF.fullmatch(self.credential_ref):
            raise BrokerResearchError("credential_ref must be an env:NAME or credential-manager reference")


class NoCallTransport:
    """Transport sentinel; any accidental request fails immediately and is counted."""

    def __init__(self) -> None:
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise BrokerResearchError("offline mapping preview must never call transport")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default).encode("utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: _sha256_bytes((root / name).read_bytes())
            for name in ("broker_research.py", "brokers.py", "execution.py")}


def create_broker_workspace(workspace: str | Path, config: BrokerResearchConfig) -> Path:
    """Create a new isolated workspace and save only non-secret configuration."""
    if not isinstance(config, BrokerResearchConfig):
        raise BrokerResearchError("BrokerResearchConfig required")
    root = Path(workspace).expanduser().resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise BrokerResearchError("workspace must be a new, empty path") from exc
    payload = {"schema": "kabuforge_broker_research_config", "schema_version": SCHEMA_VERSION,
               "config": asdict(config)}
    try:
        (root / "broker_config.json").write_bytes(_canonical_bytes(payload))
    except Exception:
        # The directory was created by this call. Remove only its own configless
        # directory, and only if it remains empty.
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    return root


def load_broker_workspace(workspace: str | Path) -> BrokerResearchConfig:
    """Read and validate a saved config; never resolve credential_ref."""
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise BrokerResearchError("workspace must be a directory")
    path = root / "broker_config.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BrokerResearchError("saved broker configuration cannot be read") from exc
    if (not isinstance(payload, dict) or payload.get("schema") != "kabuforge_broker_research_config"
            or type(payload.get("schema_version")) is not int or payload.get("schema_version") != SCHEMA_VERSION
            or set(payload) != {"schema", "schema_version", "config"}
            or not isinstance(payload.get("config"), dict)):
        raise BrokerResearchError("unknown broker configuration schema")
    config = payload["config"]
    if set(config) != {"environment", "endpoint", "account_id", "account_type", "exchange", "credential_ref"}:
        raise BrokerResearchError("unknown or incomplete broker configuration fields")
    return BrokerResearchConfig(**config)


def _validate_order(intent: OrderIntent, instrument: Instrument, config: BrokerResearchConfig,
                    now: datetime) -> None:
    if not isinstance(intent, OrderIntent) or not isinstance(instrument, Instrument):
        raise BrokerResearchError("typed OrderIntent and Instrument are required")
    if not isinstance(config, BrokerResearchConfig):
        raise BrokerResearchError("BrokerResearchConfig required")
    try:
        aware(now, "preview now")
    except ValueError as exc:
        raise BrokerResearchError(str(exc)) from exc
    if intent.account_id != config.account_id:
        raise BrokerResearchError("intent account_id does not match the selected local account")
    if intent.code != instrument.code:
        raise BrokerResearchError("intent code does not match the selected instrument")
    if intent.quantity % instrument.lot_size != 0:
        raise BrokerResearchError("quantity must be an exact multiple of the instrument lot size")
    if instrument.expires_at is not None and now >= instrument.expires_at:
        raise BrokerResearchError("instrument has expired")
    if intent.order_type == "limit":
        assert intent.limit_price is not None
        if intent.limit_price % instrument.tick_size != Decimal(0):
            raise BrokerResearchError("limit price must be an exact multiple of the instrument tick size")


def preview_order(workspace: str | Path, intent: OrderIntent, instrument: Instrument, *,
                  now: datetime, transport: NoCallTransport | None = None) -> Path:
    """Write a pure local order mapping preview and evidence receipt.

    The injected transport exists only to make the zero-I/O boundary testable;
    it is never invoked by this function.
    """
    root = Path(workspace).expanduser().resolve(strict=True)
    config = load_broker_workspace(root)
    guard = transport if transport is not None else NoCallTransport()
    if not isinstance(guard, NoCallTransport):
        raise BrokerResearchError("only NoCallTransport is accepted for an offline preview")
    _validate_order(intent, instrument, config, now)
    mapper = KabuCashBroker(guard, exchange=config.exchange, account_type=config.account_type)
    try:
        mapped = mapper.map_order(intent, now=now)
    except BrokerContractError as exc:
        raise BrokerResearchError(str(exc)) from exc

    intent_doc = asdict(intent)
    instrument_doc = asdict(instrument)
    input_doc = {"config": asdict(config), "intent": intent_doc, "instrument": instrument_doc,
                 "now": now.isoformat()}
    input_sha = _sha256_bytes(_canonical_bytes(input_doc))
    mapping_sha = _sha256_bytes(_canonical_bytes(mapped))
    source = _source_identity()
    receipt = {
        "schema": "kabuforge_broker_mapping_preview", "schema_version": SCHEMA_VERSION,
        "status": "MAPPED_LOCALLY_NOT_CONNECTED_NOT_SUBMITTED",
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "environment": config.environment, "endpoint": config.endpoint,
        "account_id": config.account_id, "account_type": config.account_type,
        "exchange": config.exchange, "credential_ref": config.credential_ref,
        "credential_resolved": False, "network_calls": 0,
        "input": input_doc,
        "input_sha256": input_sha, "mapping_sha256": mapping_sha,
        "source_sha256": source, "spec_reference": KABU_REF,
        "intent_id": intent.intent_id, "instrument": instrument.code,
        "mapped_request": mapped,
        "limitations": ["Local field mapping only; no token, connection, validation against terminal, submission, or fill."],
    }
    # Never derive a filesystem component from user-controlled intent IDs.
    dest = root / f"preview-{input_sha}.json"
    if dest.resolve(strict=False).parent != root:
        raise BrokerResearchError("preview receipt path escaped the selected workspace")
    try:
        with dest.open("xb") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False, indent=2,
                                    sort_keys=True, allow_nan=False,
                                    default=_json_default).encode("utf-8"))
    except FileExistsError as exc:
        raise BrokerResearchError("preview receipt already exists; refusing to overwrite") from exc
    if guard.calls != 0:
        raise BrokerResearchError("offline transport boundary violated")
    return dest
