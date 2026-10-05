"""Cash-equity broker protocol mappings.  No default transport or credentials.

``KabuCashBroker.map_order`` is a local mapping operation only. The separate
research preview workflow uses an injected no-call transport and does not
resolve credentials or invoke submission, cancellation, or query methods.

Official references:
Kabu https://raw.githubusercontent.com/kabucom/kabusapi/master/reference/kabu_STATION_API.yaml
Rakuten https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_06.html
NeoTrade https://www.sbineotrade.jp/manual/pdf/manual_api_VBA_function.pdf
Mapping tests do not establish terminal, COM, or live-account compatibility.
"""

from __future__ import annotations

import copy
import math
import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from .execution import OrderIntent, aware

KABU_REF = "https://raw.githubusercontent.com/kabucom/kabusapi/master/reference/kabu_STATION_API.yaml"
RAKUTEN_REF = "https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_06.html"
NEO_REF = "https://www.sbineotrade.jp/manual/pdf/manual_api_VBA_function.pdf"


class BrokerContractError(ValueError):
    """Unsafe, unsupported, or incomplete broker mapping/result."""


@dataclass(frozen=True)
class BrokerOutcome:
    status: str  # ACCEPTED, REJECTED, or UNKNOWN; never asserts a fill
    broker_order_id: str | None
    source_ref: str
    reason: str = ""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: Any


class HttpTransport(Protocol):
    def request(self, method: str, path: str, *, json_body: Mapping[str, Any] | None = None,
                params: Mapping[str, str] | None = None) -> HttpResponse: ...


def _day(intent: OrderIntent, now: datetime) -> int:
    if not isinstance(intent, OrderIntent):
        raise BrokerContractError("OrderIntent required")
    aware(now, "broker now")
    zone = ZoneInfo("Asia/Tokyo")
    local = now.astimezone(zone)
    expiry = intent.valid_until.astimezone(zone)
    if (now < intent.created_at or now >= intent.valid_until or
            expiry.date() != local.date() + timedelta(days=1) or
            any((expiry.hour, expiry.minute, expiry.second, expiry.microsecond))):
        raise BrokerContractError("DAY intent is expired or not today's Tokyo session")
    if intent.time_in_force != "DAY":
        raise BrokerContractError("only DAY is mapped")
    return int(local.strftime("%Y%m%d"))


def _intent_digest(intent: OrderIntent) -> str:
    payload = json.dumps(asdict(intent), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KabuCashBroker:
    """Injected HTTP transport only; no token acquisition or automatic retry.

    Account type and exchange must be explicitly selected.  Exchange 9 (SOR)
    and 27 (Tokyo+) have different terminal availability; live capability
    probing is outside this mapping.  Exchange 1 is deliberately unavailable
    for normal new orders under the current official description.  Its local
    duplicate guard is process-scoped; a durable Store/coordinator gate is
    required across restarts before any transport call.
    """

    def __init__(self, transport: HttpTransport, *, exchange: int,
                 account_type: int, fund_type: str = "02") -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise BrokerContractError("injected HTTP transport required")
        if type(exchange) is not int or exchange not in {9, 27}:
            raise BrokerContractError("Kabu new cash orders require explicit SOR(9) or Tokyo+(27) capability")
        if type(account_type) is not int or account_type not in {2, 4}:
            raise BrokerContractError("Kabu account type must be general(2) or specified(4)")
        if fund_type != "02":
            raise BrokerContractError("only protected cash-buy fund type 02 is mapped")
        self.transport = transport
        self.exchange = exchange
        self.account_type = account_type
        self.fund_type = fund_type
        self._submitted: dict[str, tuple[str, BrokerOutcome]] = {}
        self._keys: dict[str, tuple[str, str]] = {}
        self._canceled: dict[str, BrokerOutcome] = {}
        # Hold through the transport call: a concurrent duplicate must see the
        # first outcome (including UNKNOWN), never send a second request.
        self._request_lock = threading.Lock()

    def map_order(self, intent: OrderIntent, *, now: datetime) -> dict[str, Any]:
        day = _day(intent, now)
        if not intent.code.isalnum() or len(intent.code) not in {4, 5}:
            raise BrokerContractError("Kabu cash code must be a 4- or 5-character symbol")
        if intent.order_type not in {"market", "limit"}:
            raise BrokerContractError("unsupported order type")
        if intent.order_type == "market":
            price = 0
        else:
            try:
                price = float(intent.limit_price)
            except (OverflowError, TypeError, ValueError) as exc:
                raise BrokerContractError("limit price cannot be represented by Kabu JSON number") from exc
            if not math.isfinite(price) or Decimal(str(price)) != intent.limit_price:
                raise BrokerContractError("limit price loses precision in Kabu JSON number")
        return {
            "Symbol": intent.code, "Exchange": self.exchange, "SecurityType": 1,
            "Side": "1" if intent.side == "sell" else "2", "CashMargin": 1,
            "DelivType": 0 if intent.side == "sell" else 2,
            "FundType": "  " if intent.side == "sell" else self.fund_type,
            "AccountType": self.account_type, "Qty": intent.quantity,
            "Price": price,
            "ExpireDay": day, "FrontOrderType": 10 if intent.order_type == "market" else 20,
        }

    def submit(self, intent: OrderIntent, *, now: datetime) -> BrokerOutcome:
        if not isinstance(intent, OrderIntent):
            raise BrokerContractError("OrderIntent required")
        with self._request_lock:
            return self._submit_locked(intent, now=now)

    def _submit_locked(self, intent: OrderIntent, *, now: datetime) -> BrokerOutcome:
        digest = _intent_digest(intent)
        prior = self._submitted.get(intent.intent_id)
        if prior is not None:
            if prior[0] != digest:
                raise BrokerContractError("intent ID reused with different payload")
            return prior[1]
        key_prior = self._keys.get(intent.idempotency_key)
        if key_prior is not None:
            raise BrokerContractError("idempotency key already bound to a different intent")
        body = self.map_order(intent, now=now)
        try:
            response = self.transport.request("POST", "/sendorder", json_body=body)
        except Exception as exc:
            outcome = BrokerOutcome("UNKNOWN", None, KABU_REF, f"transport uncertainty: {type(exc).__name__}")
            self._submitted[intent.intent_id] = (digest, outcome)
            self._keys[intent.idempotency_key] = (intent.intent_id, digest)
            return outcome
        outcome = self._submission_response(response)
        self._submitted[intent.intent_id] = (digest, outcome)
        self._keys[intent.idempotency_key] = (intent.intent_id, digest)
        return outcome

    @staticmethod
    def _submission_response(response: HttpResponse) -> BrokerOutcome:
        if not isinstance(response, HttpResponse) or type(response.status_code) is not int:
            return BrokerOutcome("UNKNOWN", None, KABU_REF, "incomplete HTTP response")
        data = response.body
        if response.status_code == 200 and isinstance(data, Mapping):
            if type(data.get("Result")) is int and data["Result"] == 0 and isinstance(data.get("OrderId"), str) and data["OrderId"]:
                return BrokerOutcome("ACCEPTED", data["OrderId"], KABU_REF)
            if type(data.get("Result")) is int and data["Result"] != 0:
                return BrokerOutcome("REJECTED", None, KABU_REF, f"Result={data['Result']}")
        return BrokerOutcome("UNKNOWN", None, KABU_REF, f"HTTP {response.status_code} or incomplete result")

    def cancel(self, broker_order_id: str) -> BrokerOutcome:
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise BrokerContractError("Kabu cancellation requires broker OrderId")
        with self._request_lock:
            return self._cancel_locked(broker_order_id)

    def _cancel_locked(self, broker_order_id: str) -> BrokerOutcome:
        if broker_order_id in self._canceled:
            return self._canceled[broker_order_id]
        try:
            response = self.transport.request("PUT", "/cancelorder", json_body={"OrderId": broker_order_id})
        except Exception as exc:
            outcome = BrokerOutcome("UNKNOWN", broker_order_id, KABU_REF, f"cancel transport uncertainty: {type(exc).__name__}")
            self._canceled[broker_order_id] = outcome
            return outcome
        outcome = self._submission_response(response)
        result = BrokerOutcome(outcome.status, broker_order_id, KABU_REF, outcome.reason)
        self._canceled[broker_order_id] = result
        return result

    def account(self) -> dict[str, Any]:
        return {"wallet": self._read("/wallet/cash"),
                "positions": self._read("/positions", {"product": "1"})}

    def orders(self, broker_order_id: str | None = None) -> Any:
        params = {"product": "1"}
        if broker_order_id is not None:
            if not isinstance(broker_order_id, str) or not broker_order_id:
                raise BrokerContractError("broker_order_id must be nonempty")
            params["id"] = broker_order_id
        return self._read("/orders", params)

    def fills(self, broker_order_id: str) -> Any:
        """Return raw order Details; normalization requires real response validation."""
        return self.orders(broker_order_id)

    def reconcile(self, broker_order_id: str) -> BrokerOutcome:
        rows = self.orders(broker_order_id)
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping) or rows[0].get("ID") != broker_order_id:
            return BrokerOutcome("UNKNOWN", broker_order_id, KABU_REF, "order lookup absent or incomplete")
        return BrokerOutcome("UNKNOWN", broker_order_id, KABU_REF,
                             "order visible; state/fills require explicit raw-record review")

    def _read(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        try:
            response = self.transport.request("GET", path, params=params)
        except Exception as exc:
            raise BrokerContractError(f"query transport unavailable: {type(exc).__name__}") from exc
        if not isinstance(response, HttpResponse) or response.status_code != 200 or response.body is None:
            raise BrokerContractError("incomplete broker query")
        return copy.deepcopy(response.body)


@dataclass(frozen=True)
class ExcelCommand:
    broker: str
    name: str
    args: tuple[Any, ...]
    request_id: int
    generation: str
    source_ref: str


def _request_id(value: Any, upper: int) -> int:
    if type(value) is not int or not 1 <= value <= upper:
        raise BrokerContractError(f"request ID must be integer 1..{upper}")
    return value


def _excel_day(intent: OrderIntent, now: datetime) -> None:
    _day(intent, now)


class RakutenMapper:
    """Official 19-position normal cash-stock VBA mapping, no worksheet trigger."""

    def __init__(self, generation: str, *, account_type: str = "0") -> None:
        if not isinstance(generation, str) or not generation or account_type not in {"0", "1"}:
            raise BrokerContractError("generation and general/specified account type required")
        self.generation, self.account_type = generation, account_type

    def submit(self, intent: OrderIntent, request_id: int, *, now: datetime) -> ExcelCommand:
        _excel_day(intent, now)
        _request_id(request_id, 2147483647)
        if not intent.code.isalnum():
            raise BrokerContractError("invalid symbol")
        args = (request_id, f"{intent.code}.T", "1" if intent.side == "sell" else "3",
                "0", "0", intent.quantity, "0" if intent.order_type == "market" else "1",
                "" if intent.order_type == "market" else float(intent.limit_price),
                "1", "", self.account_type, "", "", "", "", "0", "", "", "")
        return ExcelCommand("rakuten", "RssStockOrder_V", args, request_id, self.generation, RAKUTEN_REF)

    def cancel(self, request_id: int, broker_order_number: str) -> ExcelCommand:
        _request_id(request_id, 2147483647)
        if not isinstance(broker_order_number, str) or not broker_order_number:
            raise BrokerContractError("Rakuten cancel needs broker order number, not request ID")
        return ExcelCommand("rakuten", "RssCancelOrder_V", (request_id, broker_order_number),
                            request_id, self.generation, RAKUTEN_REF)


class NeoTradeMapper:
    """Official V01/V05 cash-equity positional VBA mapping (PDF v2.0.1)."""

    def __init__(self, generation: str, *, account_type: str = "1") -> None:
        if not isinstance(generation, str) or not generation or account_type not in {"0", "1"}:
            raise BrokerContractError("generation and general/specified account type required")
        self.generation, self.account_type = generation, account_type

    def submit(self, intent: OrderIntent, request_id: int, *, now: datetime) -> ExcelCommand:
        _excel_day(intent, now)
        _request_id(request_id, 100_000_000_000_000)
        if not intent.code.isalnum():
            raise BrokerContractError("invalid symbol")
        args = (request_id, f"{intent.code}.T", "1" if intent.side == "sell" else "3",
                "0", str(intent.quantity), "0" if intent.order_type == "market" else "1",
                "" if intent.order_type == "market" else str(intent.limit_price),
                "1", "1", "", self.account_type)
        return ExcelCommand("neotrade", "SntExecEqtyOrder", args, request_id,
                            self.generation, NEO_REF)

    def cancel(self, request_id: int, broker_order_id: str) -> ExcelCommand:
        _request_id(request_id, 100_000_000_000_000)
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise BrokerContractError("NeoTrade cancel needs broker order ID")
        return ExcelCommand("neotrade", "SntExecCancelOrder", (request_id, "2", broker_order_id),
                            request_id, self.generation, NEO_REF)


EXCEL_QUERY_CONTRACTS = {
    "rakuten": ("RssOrderList", "RssExecutionList", "RssPositionList",
                "RssBuyingPower", "RssOrderIDList", "RssOrderStatus"),
    "neotrade": ("SntGetEqtyOrderList", "SntGetEqtyEnableOrderList",
                 "SntGetEqtyPositionList", "SntGetTradingPower", "SntGetOrderIdList"),
}
