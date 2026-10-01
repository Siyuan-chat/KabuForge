"""Reserved R3 extension contract; never connects to or calls a real broker.

Reference surface: https://github.com/alpacahq/alpaca-mcp-server
Approval authority must be injected by a trusted human-facing host in a future
release. Agent tools cannot mint an approval or turn on this extension.
"""
from dataclasses import dataclass
from typing import Protocol
from .core import STRING, schema, AgentError


EXTERNAL_TOOLS = {
    'request_order_approval': schema({'run_id':STRING,'plan_hash':STRING,'account_id':STRING},['run_id','plan_hash','account_id']),
    'submit_order': schema({'run_id':STRING,'intent_id':STRING,'plan_hash':STRING,'account_id':STRING,'approval_ref':STRING,'idempotency_key':STRING},['run_id','intent_id','plan_hash','account_id','approval_ref','idempotency_key']),
    'cancel_order': schema({'run_id':STRING,'broker_order_id':STRING,'account_id':STRING,'approval_ref':STRING,'idempotency_key':STRING},['run_id','broker_order_id','account_id','approval_ref','idempotency_key']),
}


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    action: str
    account_id: str
    plan_hash: str
    order_identity: str
    expires_at: str


class ApprovalAuthority(Protocol):
    def verify_and_consume(self, *, approval_ref: str, request: ApprovalRequest) -> bool:
        """Trusted host checks action/account/hash/order/expiry and consumes once."""
        ...


class ExternalActionService(Protocol):
    def submit_order(self, *, intent_id: str, approval_ref: str, idempotency_key: str): ...
    def cancel_order(self, *, broker_order_id: str, approval_ref: str, idempotency_key: str): ...


class ReservedExternalActions:
    """Discoverable disabled hooks, for future trusted broker/approval integration."""
    def catalog(self):
        return [{'name':name,'risk_class':'R3','enabled':False,'inputSchema':spec,
                 'requires':['trusted_broker_transport','human_approval_authority','single_use_action_bound_approval','durable_submission_journal']}
                for name,spec in EXTERNAL_TOOLS.items()]

    def execute(self, name, arguments):
        raise AgentError('KF_AGENT_DISABLED')
