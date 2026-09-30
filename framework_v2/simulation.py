"""Deterministic local matching broker. Never contacts an external service."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from .execution import (AccountState, Position, Quote, OrderIntent, OrderEvent,
                        OrderStatus, Fill, BrokerCapabilities, ExecutionError)
from .local_io import plain

class BrokerAdapter(Protocol):
    capabilities: BrokerCapabilities
    def account(self) -> AccountState: ...
    def submit(self, intent: OrderIntent, *, now: datetime) -> OrderEvent: ...
    def cancel(self, intent_id: str, *, now: datetime) -> OrderEvent: ...
    def reconcile(self, intent_id: str): ...

class FakeBroker:
    """An independent fictional account and order book for fault exercises.

    Broker state is in memory; a new instance cannot reconcile an old instance's
    orders. An unknown lookup is explicit and never authorizes resubmission.
    """
    capabilities=BrokerCapabilities(frozenset({"market","limit"}),frozenset({"DAY"}))

    def __init__(self, account: AccountState):
        self._account=account; self._orders={}; self._keys={}; self._sequence=0

    def account(self): return self._account
    def orders(self): return tuple(self._orders)
    def positions(self): return self._account.positions

    def submit(self,intent,*,now):
        if intent.account_id!=self._account.account_id: raise ExecutionError("foreign simulated account")
        prior=self._keys.get(intent.idempotency_key)
        if prior is not None:
            order=self._orders[prior]
            if order["intent"] != intent: raise ExecutionError("simulated idempotency collision")
            return order["events"][0]
        if intent.intent_id in self._orders: raise ExecutionError("simulated intent ID collision")
        status=OrderStatus.ACCEPTED if intent.created_at<=now<intent.valid_until else OrderStatus.REJECTED
        event=OrderEvent(intent_id=intent.intent_id,status=status,occurred_at=now,
            broker_order_id="fake:"+intent.intent_id,event_id="fake:"+intent.intent_id+":accepted",
            reason=None if status==OrderStatus.ACCEPTED else "outside_validity")
        self._keys[intent.idempotency_key]=intent.intent_id
        self._orders[intent.intent_id]={"intent":intent,"events":[event],"fills":[]}
        return event

    def match(self,intent_id,quote: Quote,*,now,quantity=None,fee=Decimal(0)):
        order=self._orders[intent_id]; intent=order["intent"]
        if order["events"][-1].status in {OrderStatus.CANCELED,OrderStatus.REJECTED,OrderStatus.FILLED}: return None
        if now>=intent.valid_until: return self.cancel(intent_id,now=now),None
        if now<intent.created_at or quote.asof>now or (now-quote.asof).total_seconds()>60:
            raise ExecutionError("invalid simulation quote time")
        if quote.code!=intent.code: raise ExecutionError("wrong simulation quote")
        px=quote.ask if intent.side=="buy" else quote.bid
        if intent.order_type=="limit" and ((intent.side=="buy" and px>intent.limit_price) or (intent.side=="sell" and px<intent.limit_price)):
            return None
        filled=sum(f.quantity for f in order["fills"])
        qty=intent.quantity-filled if quantity is None else quantity
        if type(qty) is not int or not 0<qty<=intent.quantity-filled: raise ExecutionError("invalid partial quantity")
        fill=Fill(intent_id,"fake:"+intent_id+":trade:"+str(len(order["fills"])),intent.code,intent.side,qty,px,fee,now)
        positions={p.code:p for p in self._account.positions}; old=positions.get(intent.code,Position(intent.code,0,Decimal(0)))
        cash=self._account.available_cash
        if intent.side=="buy":
            cash-=px*qty+fill.fee
            if cash<0: raise ExecutionError("simulated broker insufficient cash")
            positions[intent.code]=Position(intent.code,old.quantity+qty,(old.average_cost*old.quantity+px*qty)/(old.quantity+qty))
        else:
            if qty>old.quantity: raise ExecutionError("simulated broker insufficient holdings")
            cash+=px*qty-fill.fee
            if cash<0: raise ExecutionError("simulated broker insufficient cash for fee")
            if qty==old.quantity: positions.pop(intent.code)
            else: positions[intent.code]=replace(old,quantity=old.quantity-qty)
        status=OrderStatus.FILLED if filled+qty==intent.quantity else OrderStatus.PARTIAL
        event=OrderEvent(intent_id,status,now,broker_order_id="fake:"+intent_id,
            event_id=fill.trade_id+":event")
        order["fills"].append(fill); order["events"].append(event); self._sequence+=1
        self._account=AccountState(self._account.account_id,"fake:"+str(self._sequence),self._account.equity,cash,tuple(positions.values()))
        return event,fill

    def cancel(self,intent_id,*,now):
        order=self._orders[intent_id]
        if order["events"][-1].status in {OrderStatus.CANCELED,OrderStatus.REJECTED,OrderStatus.FILLED}:
            return order["events"][-1]
        event=OrderEvent(intent_id,OrderStatus.CANCELED,now,broker_order_id="fake:"+intent_id,
            event_id="fake:"+intent_id+":canceled")
        order["events"].append(event); return event

    def reconcile(self,intent_id):
        if intent_id not in self._orders: raise ExecutionError("simulated order unknown; resubmission is not authorized")
        order=self._orders[intent_id]
        return tuple(order["events"]),tuple(order["fills"])
