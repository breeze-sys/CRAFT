"""Execution Ticket issuing, verification and one-time replay protection."""

from __future__ import annotations

from datetime import datetime, timedelta

from craft.models import (
    ActionRequest,
    ApprovalSet,
    ExecutionDecision,
    ExecutionTicket,
    PhysicalConsequenceCertificate,
    Role,
    utc_now,
)
from craft.security.approval import explain_approval_set
from craft.security.crypto import (
    PrincipalRegistry,
    RoleCredential,
    TrustedPrincipal,
    is_within_validity_window,
    sign_digest_hex,
    verify_digest_hex,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult
from craft.security.policy import DEFAULT_RISK_POLICY, RiskPolicy


class TicketReplayCache:
    """Small in-memory replay cache for MVP tests and demos."""

    def __init__(self) -> None:
        self._used_ticket_ids: set[str] = set()

    def is_used(self, ticket_id: str) -> bool:
        return ticket_id in self._used_ticket_ids

    def mark_used(self, ticket_id: str) -> bool:
        if self.is_used(ticket_id):
            return False
        self._used_ticket_ids.add(ticket_id)
        return True

    @property
    def used_ticket_ids(self) -> set[str]:
        return set(self._used_ticket_ids)


def issue_execution_ticket(
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    approval_set: ApprovalSet,
    approval_registry: PrincipalRegistry,
    gateway: RoleCredential,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    expires_minutes: int = 2,
    decision: ExecutionDecision = ExecutionDecision.ALLOW,
    at: datetime | None = None,
) -> ExecutionTicket:
    if gateway.role != Role.GATEWAY:
        raise ValueError("Only the gateway can sign an execution ticket.")
    approval_result = explain_approval_set(
        approval_set,
        approval_registry,
        action=action,
        pcc=pcc,
        policy=policy,
        at=at,
    )
    if not approval_result.valid:
        raise ValueError(f"Cannot issue ticket: {approval_result.message}")

    issued_at = utc_now()
    required_roles = policy.required_roles_for(pcc.risk_level)
    unsigned = ExecutionTicket(
        action_digest=action.action_digest,
        pcc_digest=pcc.certificate_digest(),
        approval_set_digest=approval_set.digest(),
        risk_level=pcc.risk_level,
        authorized_roles=required_roles,
        decision=decision,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=expires_minutes),
        gateway_id=gateway.subject_id,
    )
    signature = sign_digest_hex(unsigned.signing_digest(), gateway.key_pair)
    return unsigned.model_copy(update={"gateway_signature": signature})


def verify_execution_ticket(
    ticket: ExecutionTicket,
    gateway: TrustedPrincipal,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    approval_set: ApprovalSet | None = None,
    policy: RiskPolicy | None = None,
    replay_cache: TicketReplayCache | None = None,
    require_unused: bool = True,
    at: datetime | None = None,
) -> bool:
    return explain_execution_ticket(
        ticket,
        gateway,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=policy,
        replay_cache=replay_cache,
        require_unused=require_unused,
        at=at,
    ).valid


def explain_execution_ticket(
    ticket: ExecutionTicket,
    gateway: TrustedPrincipal,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    approval_set: ApprovalSet | None = None,
    policy: RiskPolicy | None = None,
    replay_cache: TicketReplayCache | None = None,
    require_unused: bool = True,
    at: datetime | None = None,
) -> VerificationResult:
    if ticket.gateway_signature is None:
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_SIGNATURE,
            "ExecutionTicket is missing gateway signature.",
            details={"ticket_id": ticket.ticket_id},
        )
    if ticket.gateway_id != gateway.identity.subject_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PRINCIPAL_MISMATCH,
            "ExecutionTicket gateway id does not match the provided principal.",
            details={
                "ticket_id": ticket.ticket_id,
                "expected_gateway_id": ticket.gateway_id,
                "provided_subject_id": gateway.identity.subject_id,
            },
        )
    if gateway.identity.role != Role.GATEWAY:
        return VerificationResult.fail(
            ProtocolErrorCode.ROLE_MISMATCH,
            "ExecutionTicket must be verified with a gateway principal.",
            details={
                "ticket_id": ticket.ticket_id,
                "provided_role": gateway.identity.role.value,
            },
        )
    if not is_within_validity_window(ticket.issued_at, ticket.expires_at, at=at):
        return VerificationResult.fail(
            ProtocolErrorCode.EXPIRED,
            "ExecutionTicket is outside its validity window.",
            details={
                "ticket_id": ticket.ticket_id,
                "issued_at": ticket.issued_at.isoformat(),
                "expires_at": ticket.expires_at.isoformat(),
            },
        )
    if require_unused and replay_cache is not None and replay_cache.is_used(ticket.ticket_id):
        return VerificationResult.fail(
            ProtocolErrorCode.TICKET_REPLAY,
            "ExecutionTicket has already been consumed.",
            details={"ticket_id": ticket.ticket_id},
        )
    if action is not None and ticket.action_digest != action.action_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.ACTION_DIGEST_MISMATCH,
            "ExecutionTicket action digest does not match the ActionRequest.",
            details={
                "ticket_id": ticket.ticket_id,
                "ticket_action_digest": ticket.action_digest,
                "action_digest": action.action_digest,
            },
        )
    if pcc is not None:
        if ticket.pcc_digest != pcc.certificate_digest():
            return VerificationResult.fail(
                ProtocolErrorCode.PCC_DIGEST_MISMATCH,
                "ExecutionTicket PCC digest does not match the signed PCC.",
                details={
                    "ticket_id": ticket.ticket_id,
                    "ticket_pcc_digest": ticket.pcc_digest,
                    "pcc_digest": pcc.certificate_digest(),
                },
            )
        if ticket.risk_level != pcc.risk_level:
            return VerificationResult.fail(
                ProtocolErrorCode.RISK_LEVEL_MISMATCH,
                "ExecutionTicket risk level does not match the PCC risk level.",
                details={
                    "ticket_id": ticket.ticket_id,
                    "ticket_risk_level": ticket.risk_level.value,
                    "pcc_risk_level": pcc.risk_level.value,
                },
            )
    if approval_set is not None and ticket.approval_set_digest != approval_set.digest():
        return VerificationResult.fail(
            ProtocolErrorCode.APPROVAL_SET_DIGEST_MISMATCH,
            "ExecutionTicket approval-set digest does not match the ApprovalSet.",
            details={
                "ticket_id": ticket.ticket_id,
                "ticket_approval_set_digest": ticket.approval_set_digest,
                "approval_set_digest": approval_set.digest(),
            },
        )
    if policy is not None:
        if not policy.is_authorizable(ticket.risk_level):
            return VerificationResult.fail(
                ProtocolErrorCode.POLICY_REJECTED,
                "ExecutionTicket risk level has no authorization path under the active policy.",
                details={
                    "ticket_id": ticket.ticket_id,
                    "risk_level": ticket.risk_level.value,
                },
            )
        if ticket.authorized_roles != policy.required_roles_for(ticket.risk_level):
            return VerificationResult.fail(
                ProtocolErrorCode.REQUIRED_ROLES_MISMATCH,
                "ExecutionTicket authorized roles do not match the active policy.",
                details={
                    "ticket_id": ticket.ticket_id,
                    "ticket_authorized_roles": [role.value for role in ticket.authorized_roles],
                    "policy_required_roles": [
                        role.value for role in policy.required_roles_for(ticket.risk_level)
                    ],
                },
            )
    if not verify_digest_hex(ticket.signing_digest(), ticket.gateway_signature, gateway.public_key):
        return VerificationResult.fail(
            ProtocolErrorCode.SIGNATURE_INVALID,
            "ExecutionTicket gateway signature is invalid.",
            details={"ticket_id": ticket.ticket_id},
        )
    return VerificationResult.pass_("ExecutionTicket signature and binding are valid.")


def consume_execution_ticket(
    ticket: ExecutionTicket,
    gateway: TrustedPrincipal,
    replay_cache: TicketReplayCache,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    approval_set: ApprovalSet | None = None,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> bool:
    return explain_consume_execution_ticket(
        ticket,
        gateway,
        replay_cache,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=policy,
        at=at,
    ).valid


def explain_consume_execution_ticket(
    ticket: ExecutionTicket,
    gateway: TrustedPrincipal,
    replay_cache: TicketReplayCache,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    approval_set: ApprovalSet | None = None,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> VerificationResult:
    result = explain_execution_ticket(
        ticket,
        gateway,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=policy,
        replay_cache=replay_cache,
        at=at,
    )
    if not result.valid:
        return result
    if not replay_cache.mark_used(ticket.ticket_id):
        return VerificationResult.fail(
            ProtocolErrorCode.TICKET_REPLAY,
            "ExecutionTicket has already been consumed.",
            details={"ticket_id": ticket.ticket_id},
        )
    return VerificationResult.pass_("ExecutionTicket was consumed successfully.")
