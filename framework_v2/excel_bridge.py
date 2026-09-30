"""Dedicated-workbook, single-worker Excel bridge with injected COM factory.

This module does not instantiate Excel, alter macro security, or discover open
workbooks.  A caller-supplied factory must open exactly the reviewed workbook
inside the worker's STA and expose read_named/write_named/run_macro/close.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .brokers import BrokerContractError, BrokerOutcome, ExcelCommand

PROTOCOL_VERSION = "1.0"
MACRO = "PrivateEngineBridge.BridgeExecute"
ALLOWED = {"RssStockOrder_V": 19, "RssCancelOrder_V": 2,
           "SntExecEqtyOrder": 11, "SntExecCancelOrder": 3}


class BridgeError(ValueError):
    """Workbook protocol, session, command, or COM connection failure."""


class WorkbookPort(Protocol):
    full_name: str
    def read_named(self, name: str) -> Any: ...
    def write_named(self, name: str, value: Any) -> None: ...
    def run_macro(self, name: str) -> Any: ...
    def close(self) -> None: ...


def _fingerprint(command: ExcelCommand) -> str:
    text = json.dumps({"broker": command.broker, "name": command.name,
                       "args": command.args, "request_id": command.request_id,
                       "generation": command.generation}, default=str,
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sta_enter() -> bool:
    if os.name != "nt":
        return False
    result = ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    if result not in (0, 1):
        raise BridgeError(f"STA initialization failed: {result}")
    return True


class ExcelBridge:
    """One request at a time on one STA; ambiguous operations never retry.

    ``reserve_request`` must atomically and durably reserve
    (broker,generation,request_id,fingerprint): return True only for a new ID,
    False for a previously identical ID, and raise on a different payload.
    Replayed IDs return UNKNOWN without invoking VBA, including after restart.
    """

    def __init__(self, workbook_path: str | Path, generation: str,
                 com_factory: Callable[[Path], WorkbookPort],
                 reserve_request: Callable[[str, str, int, str], bool]) -> None:
        path = Path(workbook_path)
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() not in {".xlsm", ".xlsb"}:
            raise BridgeError("explicit existing dedicated .xlsm/.xlsb workbook required")
        if not isinstance(generation, str) or not generation:
            raise BridgeError("nonempty workbook generation required")
        if not callable(com_factory) or not callable(reserve_request):
            raise BridgeError("injected COM factory and durable request guard required")
        self.path, self.generation = path.resolve(), generation
        self._factory, self._reserve = com_factory, reserve_request
        self._in: queue.Queue[Any] = queue.Queue()
        self._ready: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._closed = False
        self._poisoned = False
        self._ledger: dict[tuple[str, str, int], tuple[str, BrokerOutcome]] = {}
        self._worker = threading.Thread(target=self._serve, name="FrameworkV2ExcelSTA", daemon=True)
        self._worker.start()
        try:
            ready = self._ready.get(timeout=5)
        except queue.Empty as exc:
            self._closed = True
            self._in.put(None)  # if factory later returns, worker will exit
            raise BridgeError("dedicated workbook initialization timed out; worker may still be active") from exc
        if isinstance(ready, Exception):
            self._closed = True
            raise BridgeError(f"dedicated workbook unavailable: {type(ready).__name__}: {ready}") from ready

    def _serve(self) -> None:
        initialized = False
        workbook = None
        try:
            initialized = _sta_enter()
            workbook = self._factory(self.path)
            try:
                actual_path = Path(workbook.full_name).resolve()
            except (AttributeError, TypeError, ValueError) as exc:
                raise BridgeError("workbook full_name missing") from exc
            if actual_path != self.path:
                raise BridgeError("COM factory returned a different workbook")
            if str(workbook.read_named("BridgeProtocolVersion")) != PROTOCOL_VERSION:
                raise BridgeError("workbook protocol version mismatch")
            if str(workbook.read_named("BridgeGeneration")) != self.generation:
                raise BridgeError("workbook generation mismatch")
            self._ready.put(True)
            while True:
                job = self._in.get()
                if job is None:
                    break
                command, output = job
                try:
                    workbook.write_named("BridgeRequestID", command.request_id)
                    workbook.write_named("BridgeBroker", command.broker)
                    workbook.write_named("BridgeCommand", command.name)
                    workbook.write_named("BridgeArgCount", len(command.args))
                    workbook.write_named("BridgeArgs", tuple(command.args))
                    workbook.run_macro(MACRO)
                    if str(workbook.read_named("BridgeResponseRequestID")) != str(command.request_id):
                        raise BridgeError("incomplete or mismatched workbook response ID")
                    status = str(workbook.read_named("BridgeResponseStatus"))
                    value = workbook.read_named("BridgeResponseValue")
                    if status not in {"ACCEPTED", "REJECTED", "UNKNOWN"}:
                        raise BridgeError(f"workbook busy/disconnected/invalid status: {status}")
                    # The reviewed VBA module always returns UNKNOWN.  Even a
                    # changed workbook claiming acceptance/rejection cannot
                    # settle the broker state without an independent query.
                    output.put(BrokerOutcome("UNKNOWN", None, command.source_ref,
                                             "VBA response requires broker-query confirmation"))
                except Exception as exc:
                    output.put(exc)
        except Exception as exc:
            self._ready.put(exc)
        finally:
            if workbook is not None:
                try:
                    workbook.close()
                except Exception:
                    pass
            if initialized:
                ctypes.windll.ole32.CoUninitialize()

    def execute(self, command: ExcelCommand, *, timeout: float = 5.0) -> BrokerOutcome:
        if not isinstance(command, ExcelCommand) or command.name not in ALLOWED or len(command.args) != ALLOWED.get(command.name):
            raise BridgeError("unsupported or malformed VBA command")
        if command.generation != self.generation:
            raise BridgeError("Excel session generation mismatch; reconcile IDs")
        if (command.broker == "rakuten") != command.name.startswith("Rss") or command.broker not in {"rakuten", "neotrade"}:
            raise BridgeError("broker/function mismatch")
        if type(command.request_id) is not int or command.request_id <= 0 or command.args[0] != command.request_id:
            raise BridgeError("request ID mismatch")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise BridgeError("positive timeout required")
        key = (command.broker, command.generation, command.request_id)
        fingerprint = _fingerprint(command)
        with self._lock:
            if self._closed:
                raise BridgeError("Excel bridge closed")
            prior = self._ledger.get(key)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise BridgeError("request ID reused with different payload")
                return prior[1]
            if self._poisoned:
                raise BridgeError("Excel bridge uncertain; reconcile before continuing")
            try:
                is_new = self._reserve(*key, fingerprint)
            except Exception as exc:
                self._poisoned = True
                raise BridgeError(f"durable request guard unavailable or conflicted: {type(exc).__name__}: {exc}") from exc
            if type(is_new) is not bool:
                raise BridgeError("request guard must return bool")
            if not is_new:
                outcome = BrokerOutcome("UNKNOWN", None, command.source_ref,
                                        "request ID already reserved; reconcile, never resend")
                self._ledger[key] = (fingerprint, outcome)
                self._poisoned = True
                return outcome
            output: queue.Queue[Any] = queue.Queue(maxsize=1)
            self._in.put((command, output))
            try:
                result = output.get(timeout=timeout)
            except queue.Empty:
                self._poisoned = True
                result = BridgeError("COM timeout; submission outcome UNKNOWN")
            if isinstance(result, Exception):
                self._poisoned = True
                outcome = BrokerOutcome("UNKNOWN", None, command.source_ref,
                                        f"COM/workbook uncertainty: {type(result).__name__}: {result}")
            else:
                outcome = result
            self._ledger[key] = (fingerprint, outcome)
            if outcome.status == "UNKNOWN":
                self._poisoned = True
            return outcome

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._in.put(None)
        self._worker.join(timeout=2)
        if self._worker.is_alive():
            raise BridgeError("STA worker still active; COM call cannot be interrupted safely")

    def __enter__(self) -> "ExcelBridge":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
