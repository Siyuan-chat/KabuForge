"""Explicit, bounded, direct-local GET checks for kabuStation read-only views.

This module is called only from the user's read-only check action. It never
issues token, board, order, cancel, or other requests and does not use proxy or
redirect handlers.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import socket
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .broker_research import BrokerResearchConfig


ALLOWED_GET_PATHS = ("/kabusapi/wallet/cash", "/kabusapi/positions", "/kabusapi/orders")
MAX_RESPONSE_BYTES = 1_000_000
MAX_TIMEOUT_SECONDS = 3.0


class BrokerReadOnlyError(RuntimeError):
    def __init__(self, code: str, *, attempted_paths=()):
        self.code = code
        self.attempted_paths = tuple(attempted_paths)
        super().__init__(code)


def _resolve_environment_reference(reference: str) -> str | None:
    """Resolve only env references, at the explicit call site."""
    if not isinstance(reference, str) or not reference.startswith("env:"):
        raise BrokerReadOnlyError("unsupported_credential_reference")
    name = reference[4:]
    if not name or not name.replace("_", "A").isalnum() or not name[0].isalpha() or name.upper() != name:
        raise BrokerReadOnlyError("invalid_credential_reference")
    return os.environ.get(name)


def _validate_endpoint(config: BrokerResearchConfig) -> tuple[str, int]:
    if not isinstance(config, BrokerResearchConfig):
        raise BrokerReadOnlyError("invalid_saved_configuration")
    expected = {"production": ("127.0.0.1", 18080), "test": ("127.0.0.1", 18081)}
    parsed = urlsplit(config.endpoint)
    host, port = expected[config.environment]
    if (parsed.scheme != "http" or parsed.hostname != host or parsed.port != port
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise BrokerReadOnlyError("endpoint_not_allowlisted")
    return host, port


def _direct_get(host: str, port: int, path: str, token: str, timeout: float) -> tuple[int, bytes]:
    if path not in ALLOWED_GET_PATHS:
        raise BrokerReadOnlyError("request_path_not_allowlisted")
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Accept": "application/json", "X-API-KEY": token})
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise BrokerReadOnlyError("response_too_large")
        if 300 <= response.status < 400:
            raise BrokerReadOnlyError("redirect_blocked")
        return response.status, body
    finally:
        connection.close()


def _shape(path: str, payload) -> tuple[str, int | None]:
    if isinstance(payload, dict) and "Code" in payload and "Message" in payload:
        raise BrokerReadOnlyError("response_error")
    if path == "/kabusapi/wallet/cash":
        if isinstance(payload, dict) and "StockAccountWallet" in payload:
            return "object", None
        raise BrokerReadOnlyError("response_shape_invalid")
    if path in ("/kabusapi/positions", "/kabusapi/orders"):
        if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
            return "array", len(payload)
        raise BrokerReadOnlyError("response_shape_invalid")
    raise BrokerReadOnlyError("request_path_not_allowlisted")


def check_read_only(config: BrokerResearchConfig, *, credential_resolver=None,
                    requester=None, timeout: float = 2.0) -> dict:
    """Perform exactly three allowlisted GETs and return redacted evidence.

    Tests may inject a credential resolver and in-memory requester. Production
    uses direct ``http.client`` to a fixed loopback host/port, without proxies.
    Response payloads and credentials are never included in the returned data.
    """
    host, port = _validate_endpoint(config)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        raise BrokerReadOnlyError("timeout_out_of_range")
    resolve = credential_resolver or _resolve_environment_reference
    try:
        token = resolve(config.credential_ref)
    except BrokerReadOnlyError:
        raise
    except Exception as exc:
        raise BrokerReadOnlyError("credential_resolution_failed") from exc
    if not isinstance(token, str) or not token.strip():
        raise BrokerReadOnlyError("credential_missing")
    if any(ch in token for ch in "\r\n"):
        raise BrokerReadOnlyError("credential_invalid")

    responses = []
    attempted_paths = []
    get = requester or (lambda path: _direct_get(host, port, path, token, float(timeout)))
    for path in ALLOWED_GET_PATHS:
        attempted_paths.append(path)
        try:
            status, body = get(path)
        except BrokerReadOnlyError as exc:
            exc.attempted_paths = tuple(attempted_paths)
            raise
        except socket.timeout as exc:
            raise BrokerReadOnlyError("request_timeout", attempted_paths=attempted_paths) from exc
        except (ConnectionError, OSError, http.client.HTTPException) as exc:
            raise BrokerReadOnlyError("localhost_connection_failed", attempted_paths=attempted_paths) from exc
        if type(status) is not int or status != 200:
            raise BrokerReadOnlyError("http_status_not_ok", attempted_paths=attempted_paths)
        if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
            raise BrokerReadOnlyError("response_too_large_or_invalid", attempted_paths=attempted_paths)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise BrokerReadOnlyError("response_json_invalid", attempted_paths=attempted_paths) from exc
        try:
            shape, count = _shape(path, payload)
        except BrokerReadOnlyError as exc:
            exc.attempted_paths = tuple(attempted_paths)
            raise
        responses.append({"method": "GET", "path": path, "http_status": status,
                          "response_shape": shape, "row_count": count,
                          "response_sha256": hashlib.sha256(body).hexdigest()})

    return {"schema": "kabuforge_broker_read_only_check", "schema_version": 1,
            "status": "CONNECTED_READ_ONLY", "readiness": "READ_ONLY_CONNECTED",
            "pit_guarantee": False, "environment": config.environment,
            "endpoint": config.endpoint, "network_calls": len(ALLOWED_GET_PATHS),
            "credential_resolved": True, "credential_value_persisted": False,
            "redirects_allowed": False, "proxies_used": False,
            "timeout_seconds_per_request": float(timeout),
            "checked_at": datetime.now(timezone.utc).isoformat(), "requests": responses,
            "account_values_persisted": False}
