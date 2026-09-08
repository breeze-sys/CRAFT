"""Structured verification results for security protocol failures."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, JsonValue, model_validator
from typing_extensions import Self

from craft.models import CRAFTModel


class ProtocolErrorCode(str, Enum):
    OK = "ok"
    MISSING_SIGNATURE = "missing_signature"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    ROLE_MISMATCH = "role_mismatch"
    EXPIRED = "expired"
    ACTION_DIGEST_MISMATCH = "action_digest_mismatch"
    PCC_ID_MISMATCH = "pcc_id_mismatch"
    PCC_DIGEST_MISMATCH = "pcc_digest_mismatch"
    POLICY_DIGEST_MISMATCH = "policy_digest_mismatch"
    POLICY_REJECTED = "policy_rejected"
    REQUIRED_ROLES_MISMATCH = "required_roles_mismatch"
    MISSING_REQUIRED_ROLES = "missing_required_roles"
    UNKNOWN_PRINCIPAL = "unknown_principal"
    APPROVAL_SET_DIGEST_MISMATCH = "approval_set_digest_mismatch"
    RISK_LEVEL_MISMATCH = "risk_level_mismatch"
    REVALIDATION_REQUIRED = "revalidation_required"
    REVALIDATION_REJECTED = "revalidation_rejected"
    TICKET_REPLAY = "ticket_replay"
    RECEIPT_TICKET_MISMATCH = "receipt_ticket_mismatch"
    RECEIPT_ACTION_MISMATCH = "receipt_action_mismatch"
    AUDIT_CHAIN_MISMATCH = "audit_chain_mismatch"
    SIGNATURE_INVALID = "signature_invalid"


class VerificationResult(CRAFTModel):
    """Machine-readable result that can be shown directly by a dashboard."""

    valid: bool
    code: ProtocolErrorCode
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_code_consistency(self) -> Self:
        if self.valid and self.code != ProtocolErrorCode.OK:
            raise ValueError("A valid verification result must use code=ok.")
        if not self.valid and self.code == ProtocolErrorCode.OK:
            raise ValueError("An invalid verification result must include an error code.")
        return self

    def __bool__(self) -> bool:
        return self.valid

    @classmethod
    def pass_(cls, message: str = "verification passed") -> VerificationResult:
        return cls(valid=True, code=ProtocolErrorCode.OK, message=message)

    @classmethod
    def fail(
        cls,
        code: ProtocolErrorCode,
        message: str,
        *,
        details: dict[str, JsonValue] | None = None,
    ) -> VerificationResult:
        return cls(valid=False, code=code, message=message, details=details or {})
