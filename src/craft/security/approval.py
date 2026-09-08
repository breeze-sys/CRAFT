"""Approval creation and role-policy verification."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from craft.models import (
    ActionRequest,
    Approval,
    ApprovalSet,
    PhysicalConsequenceCertificate,
    utc_now,
)
from craft.security.crypto import (
    PrincipalRegistry,
    RoleCredential,
    TrustedPrincipal,
    is_within_validity_window,
    sign_digest_hex,
    verify_digest_hex,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult
from craft.security.policy import DEFAULT_RISK_POLICY, RiskPolicy, ensure_role_can_approve


def create_approval(
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    approver: RoleCredential,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    expires_minutes: int = 10,
) -> Approval:
    _ensure_approval_context(action=action, pcc=pcc, policy=policy)
    ensure_role_can_approve(approver.role, pcc.risk_level, policy)

    issued_at = utc_now()
    unsigned = Approval(
        pcc_id=pcc.pcc_id,
        action_digest=action.action_digest,
        pcc_digest=pcc.certificate_digest(),
        policy_digest=policy.policy_digest,
        role=approver.role,
        approver_id=approver.subject_id,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=expires_minutes),
    )
    signature = sign_digest_hex(unsigned.signing_digest(), approver.key_pair)
    return unsigned.model_copy(update={"signature": signature})


def build_approval_set(
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    approvals: Iterable[Approval],
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> ApprovalSet:
    _ensure_approval_context(action=action, pcc=pcc, policy=policy)
    return ApprovalSet(
        pcc_id=pcc.pcc_id,
        action_digest=action.action_digest,
        pcc_digest=pcc.certificate_digest(),
        policy_digest=policy.policy_digest,
        required_roles=policy.required_roles_for(pcc.risk_level),
        approvals=tuple(approvals),
    )


def verify_approval(
    approval: Approval,
    approver: TrustedPrincipal,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> bool:
    return explain_approval(
        approval,
        approver,
        action=action,
        pcc=pcc,
        policy=policy,
        at=at,
    ).valid


def explain_approval(
    approval: Approval,
    approver: TrustedPrincipal,
    *,
    action: ActionRequest | None = None,
    pcc: PhysicalConsequenceCertificate | None = None,
    policy: RiskPolicy | None = None,
    at: datetime | None = None,
) -> VerificationResult:
    if approval.signature is None:
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_SIGNATURE,
            "Approval is missing approver signature.",
            details={"approval_id": approval.approval_id},
        )
    if approval.approver_id != approver.identity.subject_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PRINCIPAL_MISMATCH,
            "Approval approver id does not match the provided principal.",
            details={
                "approval_id": approval.approval_id,
                "expected_approver_id": approval.approver_id,
                "provided_subject_id": approver.identity.subject_id,
            },
        )
    if approval.role != approver.identity.role:
        return VerificationResult.fail(
            ProtocolErrorCode.ROLE_MISMATCH,
            "Approval role does not match the provided principal role.",
            details={
                "approval_id": approval.approval_id,
                "approval_role": approval.role.value,
                "provided_role": approver.identity.role.value,
            },
        )
    if not is_within_validity_window(approval.issued_at, approval.expires_at, at=at):
        return VerificationResult.fail(
            ProtocolErrorCode.EXPIRED,
            "Approval is outside its validity window.",
            details={
                "approval_id": approval.approval_id,
                "issued_at": approval.issued_at.isoformat(),
                "expires_at": approval.expires_at.isoformat(),
            },
        )
    if action is not None and approval.action_digest != action.action_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.ACTION_DIGEST_MISMATCH,
            "Approval action digest does not match the ActionRequest.",
            details={
                "approval_id": approval.approval_id,
                "approval_action_digest": approval.action_digest,
                "action_digest": action.action_digest,
            },
        )
    if pcc is not None:
        if approval.pcc_id != pcc.pcc_id:
            return VerificationResult.fail(
                ProtocolErrorCode.PCC_ID_MISMATCH,
                "Approval PCC id does not match the PCC.",
                details={
                    "approval_id": approval.approval_id,
                    "approval_pcc_id": approval.pcc_id,
                    "pcc_id": pcc.pcc_id,
                },
            )
        if approval.pcc_digest != pcc.certificate_digest():
            return VerificationResult.fail(
                ProtocolErrorCode.PCC_DIGEST_MISMATCH,
                "Approval PCC digest does not match the signed PCC.",
                details={
                    "approval_id": approval.approval_id,
                    "approval_pcc_digest": approval.pcc_digest,
                    "pcc_digest": pcc.certificate_digest(),
                },
            )
    if policy is not None:
        if approval.policy_digest != policy.policy_digest:
            return VerificationResult.fail(
                ProtocolErrorCode.POLICY_DIGEST_MISMATCH,
                "Approval policy digest does not match the active policy.",
                details={
                    "approval_id": approval.approval_id,
                    "approval_policy_digest": approval.policy_digest,
                    "active_policy_digest": policy.policy_digest,
                },
            )
        if pcc is not None and not policy.is_authorizable(pcc.risk_level):
            return VerificationResult.fail(
                ProtocolErrorCode.POLICY_REJECTED,
                "PCC risk level has no authorization path under the active policy.",
                details={
                    "approval_id": approval.approval_id,
                    "risk_level": pcc.risk_level.value,
                },
            )
        if pcc is not None and approval.role not in policy.required_roles_for(pcc.risk_level):
            return VerificationResult.fail(
                ProtocolErrorCode.ROLE_MISMATCH,
                "Approval role is not allowed for the PCC risk level.",
                details={
                    "approval_id": approval.approval_id,
                    "approval_role": approval.role.value,
                    "risk_level": pcc.risk_level.value,
                    "required_roles": [
                        role.value for role in policy.required_roles_for(pcc.risk_level)
                    ],
                },
            )
    if not verify_digest_hex(approval.signing_digest(), approval.signature, approver.public_key):
        return VerificationResult.fail(
            ProtocolErrorCode.SIGNATURE_INVALID,
            "Approval signature is invalid.",
            details={"approval_id": approval.approval_id},
        )
    return VerificationResult.pass_("Approval signature and binding are valid.")


def verify_approval_set(
    approval_set: ApprovalSet,
    registry: PrincipalRegistry,
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    at: datetime | None = None,
) -> bool:
    return explain_approval_set(
        approval_set,
        registry,
        action=action,
        pcc=pcc,
        policy=policy,
        at=at,
    ).valid


def explain_approval_set(
    approval_set: ApprovalSet,
    registry: PrincipalRegistry,
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
    at: datetime | None = None,
) -> VerificationResult:
    if approval_set.action_digest != action.action_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.ACTION_DIGEST_MISMATCH,
            "ApprovalSet action digest does not match the ActionRequest.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "approval_set_action_digest": approval_set.action_digest,
                "action_digest": action.action_digest,
            },
        )
    if approval_set.pcc_id != pcc.pcc_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PCC_ID_MISMATCH,
            "ApprovalSet PCC id does not match the PCC.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "approval_set_pcc_id": approval_set.pcc_id,
                "pcc_id": pcc.pcc_id,
            },
        )
    if approval_set.pcc_digest != pcc.certificate_digest():
        return VerificationResult.fail(
            ProtocolErrorCode.PCC_DIGEST_MISMATCH,
            "ApprovalSet PCC digest does not match the signed PCC.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "approval_set_pcc_digest": approval_set.pcc_digest,
                "pcc_digest": pcc.certificate_digest(),
            },
        )
    if approval_set.policy_digest != policy.policy_digest:
        return VerificationResult.fail(
            ProtocolErrorCode.POLICY_DIGEST_MISMATCH,
            "ApprovalSet policy digest does not match the active policy.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "approval_set_policy_digest": approval_set.policy_digest,
                "active_policy_digest": policy.policy_digest,
            },
        )
    if approval_set.required_roles != policy.required_roles_for(pcc.risk_level):
        return VerificationResult.fail(
            ProtocolErrorCode.REQUIRED_ROLES_MISMATCH,
            "ApprovalSet required roles do not match the active policy.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "approval_set_required_roles": [role.value for role in approval_set.required_roles],
                "policy_required_roles": [
                    role.value for role in policy.required_roles_for(pcc.risk_level)
                ],
            },
        )
    if not approval_set.is_satisfied():
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_REQUIRED_ROLES,
            "ApprovalSet is missing required roles.",
            details={
                "approval_set_id": approval_set.approval_set_id,
                "missing_roles": [role.value for role in approval_set.missing_roles],
            },
        )

    for approval in approval_set.approvals:
        try:
            approver = registry.require(approval.approver_id)
        except KeyError:
            return VerificationResult.fail(
                ProtocolErrorCode.UNKNOWN_PRINCIPAL,
                "Approval refers to an unknown principal.",
                details={
                    "approval_set_id": approval_set.approval_set_id,
                    "approval_id": approval.approval_id,
                    "approver_id": approval.approver_id,
                },
            )
        result = explain_approval(
            approval,
            approver,
            action=action,
            pcc=pcc,
            policy=policy,
            at=at,
        )
        if not result.valid:
            details = dict(result.details)
            details["approval_set_id"] = approval_set.approval_set_id
            details["approval_id"] = approval.approval_id
            return VerificationResult.fail(
                result.code,
                f"ApprovalSet contains an invalid approval: {result.message}",
                details=details,
            )
    return VerificationResult.pass_("ApprovalSet satisfies role policy and signatures.")


def _ensure_approval_context(
    *,
    action: ActionRequest,
    pcc: PhysicalConsequenceCertificate,
    policy: RiskPolicy,
) -> None:
    if pcc.evaluator_signature is None:
        raise ValueError("PCC must be signed before approval.")
    if pcc.action_digest != action.action_digest:
        raise ValueError("PCC action digest does not match action.")
    if pcc.policy_digest != policy.policy_digest:
        raise ValueError("PCC policy digest does not match policy.")
    if not policy.is_authorizable(pcc.risk_level):
        raise ValueError(f"Risk level {pcc.risk_level.value} cannot be authorized.")
