"""Signed audit chain and protocol transcript export helpers."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from craft.models import (
    ActionRequest,
    ApprovalSet,
    AuditEvent,
    CRAFTModel,
    ExecutionReceipt,
    ExecutionTicket,
    HexDigest,
    PhysicalConsequenceCertificate,
    RiskLevel,
    Role,
    new_uuid,
    utc_now,
)
from craft.security.crypto import (
    PrincipalRegistry,
    RoleCredential,
    TrustedPrincipal,
    sign_digest_hex,
    verify_digest_hex,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult
from craft.serialization import JsonValue, canonical_digest_hex, canonical_json


class AuditChain(CRAFTModel):
    """Immutable signed hash chain of protocol events."""

    chain_id: str = Field(default_factory=new_uuid)
    events: tuple[AuditEvent, ...] = ()

    @property
    def latest_event_digest(self) -> HexDigest | None:
        if not self.events:
            return None
        return self.events[-1].digest()

    @property
    def event_digests(self) -> tuple[HexDigest, ...]:
        return tuple(event.digest() for event in self.events)

    @property
    def chain_digest(self) -> HexDigest:
        return canonical_digest_hex(
            {
                "chain_id": self.chain_id,
                "event_digests": self.event_digests,
            }
        )

    def append_signed(
        self,
        *,
        event_type: str,
        actor: RoleCredential,
        object_digests: Mapping[str, str],
        details: Mapping[str, JsonValue] | None = None,
    ) -> AuditChain:
        event = issue_audit_event(
            event_type=event_type,
            actor=actor,
            object_digests=dict(object_digests),
            details=dict(details or {}),
            previous_event_digest=self.latest_event_digest,
        )
        return self.model_copy(update={"events": (*self.events, event)})


class ProtocolTranscript(CRAFTModel):
    """Portable summary of a CRAFT protocol run for Dashboard/report export."""

    transcript_id: str = Field(default_factory=new_uuid)
    action_digest: HexDigest
    pcc_digest: HexDigest | None = None
    approval_set_digest: HexDigest | None = None
    ticket_digest: HexDigest | None = None
    receipt_digest: HexDigest | None = None
    risk_level: RiskLevel | None = None
    required_roles: tuple[Role, ...] = ()
    approved_roles: tuple[Role, ...] = ()
    verification_results: dict[str, VerificationResult] = Field(default_factory=dict)
    audit_chain_digest: HexDigest | None = None
    audit_event_digests: tuple[HexDigest, ...] = ()
    audit_event_types: tuple[str, ...] = ()

    def export_json(self) -> str:
        return canonical_json(self)


def issue_audit_event(
    *,
    event_type: str,
    actor: RoleCredential,
    object_digests: dict[str, str],
    details: dict[str, JsonValue] | None = None,
    previous_event_digest: str | None = None,
) -> AuditEvent:
    unsigned = AuditEvent(
        event_type=event_type,
        actor_id=actor.subject_id,
        object_digests=object_digests,
        details=details or {},
        previous_event_digest=previous_event_digest,
        occurred_at=utc_now(),
    )
    signature = sign_digest_hex(unsigned.signing_digest(), actor.key_pair)
    return unsigned.model_copy(update={"event_signature": signature})


def explain_audit_event(
    event: AuditEvent,
    actor: TrustedPrincipal,
    *,
    expected_previous_event_digest: str | None = None,
    check_previous: bool = False,
) -> VerificationResult:
    if event.event_signature is None:
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_SIGNATURE,
            "AuditEvent is missing actor signature.",
            details={"event_id": event.event_id, "event_type": event.event_type},
        )
    if event.actor_id != actor.identity.subject_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PRINCIPAL_MISMATCH,
            "AuditEvent actor id does not match the provided principal.",
            details={
                "event_id": event.event_id,
                "event_actor_id": event.actor_id,
                "provided_subject_id": actor.identity.subject_id,
            },
        )
    if check_previous and event.previous_event_digest != expected_previous_event_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.AUDIT_CHAIN_MISMATCH,
            "AuditEvent previous digest does not match the prior event.",
            details={
                "event_id": event.event_id,
                "event_type": event.event_type,
                "expected_previous_event_digest": expected_previous_event_digest,
                "actual_previous_event_digest": event.previous_event_digest,
            },
        )
    if not verify_digest_hex(event.signing_digest(), event.event_signature, actor.public_key):
        return VerificationResult.fail(
            ProtocolErrorCode.SIGNATURE_INVALID,
            "AuditEvent actor signature is invalid.",
            details={"event_id": event.event_id, "event_type": event.event_type},
        )
    return VerificationResult.pass_("AuditEvent signature and chain link are valid.")


def explain_audit_chain(chain: AuditChain, registry: PrincipalRegistry) -> VerificationResult:
    expected_previous_event_digest: str | None = None
    for index, event in enumerate(chain.events):
        try:
            actor = registry.require(event.actor_id)
        except KeyError:
            return VerificationResult.fail(
                ProtocolErrorCode.UNKNOWN_PRINCIPAL,
                "AuditEvent refers to an unknown actor.",
                details={
                    "chain_id": chain.chain_id,
                    "event_index": index,
                    "event_id": event.event_id,
                    "actor_id": event.actor_id,
                },
            )
        result = explain_audit_event(
            event,
            actor,
            expected_previous_event_digest=expected_previous_event_digest,
            check_previous=True,
        )
        if not result.valid:
            details = dict(result.details)
            details["chain_id"] = chain.chain_id
            details["event_index"] = index
            return VerificationResult.fail(
                result.code,
                f"Audit chain verification failed: {result.message}",
                details=details,
            )
        expected_previous_event_digest = event.digest()

    return VerificationResult.pass_("Audit chain signatures and hash links are valid.")


def build_protocol_transcript(
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate | None = None,
    approval_set: ApprovalSet | None = None,
    ticket: ExecutionTicket | None = None,
    receipt: ExecutionReceipt | None = None,
    verification_results: Mapping[str, VerificationResult] | None = None,
    audit_chain: AuditChain | None = None,
) -> ProtocolTranscript:
    return ProtocolTranscript(
        action_digest=action.action_digest,
        pcc_digest=pcc.certificate_digest() if pcc is not None else None,
        approval_set_digest=approval_set.digest() if approval_set is not None else None,
        ticket_digest=ticket.digest() if ticket is not None else None,
        receipt_digest=receipt.digest() if receipt is not None else None,
        risk_level=pcc.risk_level if pcc is not None else None,
        required_roles=approval_set.required_roles if approval_set is not None else (),
        approved_roles=approval_set.approved_roles if approval_set is not None else (),
        verification_results=dict(verification_results or {}),
        audit_chain_digest=audit_chain.chain_digest if audit_chain is not None else None,
        audit_event_digests=audit_chain.event_digests if audit_chain is not None else (),
        audit_event_types=tuple(event.event_type for event in audit_chain.events)
        if audit_chain is not None
        else (),
    )


def export_protocol_transcript_json(transcript: ProtocolTranscript) -> str:
    return transcript.export_json()
