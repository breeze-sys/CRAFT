"""Physical Consequence Certificate issuing and verification."""

from __future__ import annotations

from datetime import datetime, timedelta

from craft.models import (
    ActionRequest,
    ConsequenceMetrics,
    PhysicalConsequenceCertificate,
    RiskLevel,
    Role,
    SimulatorInfo,
    utc_now,
)
from craft.security.crypto import (
    RoleCredential,
    TrustedPrincipal,
    is_within_validity_window,
    sign_digest_hex,
    verify_digest_hex,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult
from craft.security.policy import DEFAULT_RISK_POLICY, RiskPolicy


def issue_pcc(
    *,
    action: ActionRequest,
    state_digest: str,
    predicted_state_digest: str,
    metrics: ConsequenceMetrics,
    risk_level: RiskLevel,
    simulator: SimulatorInfo,
    evaluator: RoleCredential,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    expires_minutes: int = 5,
) -> PhysicalConsequenceCertificate:
    if evaluator.role != Role.CONSEQUENCE_EVALUATOR:
        raise ValueError("Only a consequence evaluator can sign a PCC.")

    issued_at = utc_now()
    unsigned = PhysicalConsequenceCertificate(
        state_digest=state_digest,
        action_digest=action.action_digest,
        predicted_state_digest=predicted_state_digest,
        metrics=metrics,
        risk_level=risk_level,
        policy_digest=policy.policy_digest,
        simulator=simulator,
        evaluator_id=evaluator.subject_id,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=expires_minutes),
    )
    signature = sign_digest_hex(unsigned.signing_digest(), evaluator.key_pair)
    return unsigned.model_copy(update={"evaluator_signature": signature})


def verify_pcc(
    pcc: PhysicalConsequenceCertificate,
    evaluator: TrustedPrincipal,
    *,
    at: datetime | None = None,
) -> bool:
    return explain_pcc(pcc, evaluator, at=at).valid


def explain_pcc(
    pcc: PhysicalConsequenceCertificate,
    evaluator: TrustedPrincipal,
    *,
    at: datetime | None = None,
) -> VerificationResult:
    if pcc.evaluator_signature is None:
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_SIGNATURE,
            "PCC is missing evaluator signature.",
            details={"pcc_id": pcc.pcc_id},
        )
    if pcc.evaluator_id != evaluator.identity.subject_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PRINCIPAL_MISMATCH,
            "PCC evaluator id does not match the provided evaluator principal.",
            details={
                "pcc_id": pcc.pcc_id,
                "expected_evaluator_id": pcc.evaluator_id,
                "provided_subject_id": evaluator.identity.subject_id,
            },
        )
    if evaluator.identity.role != Role.CONSEQUENCE_EVALUATOR:
        return VerificationResult.fail(
            ProtocolErrorCode.ROLE_MISMATCH,
            "PCC must be verified with a consequence evaluator principal.",
            details={
                "pcc_id": pcc.pcc_id,
                "provided_role": evaluator.identity.role.value,
            },
        )
    if not is_within_validity_window(pcc.issued_at, pcc.expires_at, at=at):
        return VerificationResult.fail(
            ProtocolErrorCode.EXPIRED,
            "PCC is outside its validity window.",
            details={
                "pcc_id": pcc.pcc_id,
                "issued_at": pcc.issued_at.isoformat(),
                "expires_at": pcc.expires_at.isoformat(),
            },
        )
    if not verify_digest_hex(pcc.signing_digest(), pcc.evaluator_signature, evaluator.public_key):
        return VerificationResult.fail(
            ProtocolErrorCode.SIGNATURE_INVALID,
            "PCC evaluator signature is invalid.",
            details={"pcc_id": pcc.pcc_id},
        )
    return VerificationResult.pass_("PCC signature and validity window are valid.")


def verify_pcc_for_action(
    pcc: PhysicalConsequenceCertificate,
    action: ActionRequest,
    evaluator: TrustedPrincipal,
    *,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> bool:
    return explain_pcc_for_action(pcc, action, evaluator, policy=policy, at=at).valid


def explain_pcc_for_action(
    pcc: PhysicalConsequenceCertificate,
    action: ActionRequest,
    evaluator: TrustedPrincipal,
    *,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> VerificationResult:
    if pcc.action_digest != action.action_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.ACTION_DIGEST_MISMATCH,
            "PCC action digest does not match the ActionRequest.",
            details={
                "pcc_id": pcc.pcc_id,
                "pcc_action_digest": pcc.action_digest,
                "action_digest": action.action_digest,
            },
        )
    if policy is not None and pcc.policy_digest != policy.policy_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.POLICY_DIGEST_MISMATCH,
            "PCC policy digest does not match the active policy.",
            details={
                "pcc_id": pcc.pcc_id,
                "pcc_policy_digest": pcc.policy_digest,
                "active_policy_digest": policy.policy_digest,
            },
        )
    return explain_pcc(pcc, evaluator, at=at)
