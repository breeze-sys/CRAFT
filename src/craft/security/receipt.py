"""Execution Receipt issuing and verification."""

from __future__ import annotations

from craft.models import ExecutionReceipt, ExecutionTicket, Role, utc_now
from craft.security.crypto import (
    RoleCredential,
    TrustedPrincipal,
    sign_digest_hex,
    verify_digest_hex,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult


def issue_execution_receipt(
    *,
    ticket: ExecutionTicket,
    executor: RoleCredential,
    execution_state_digest: str,
    result_state_digest: str | None = None,
    success: bool,
    reward: float | None = None,
    done: bool | None = None,
    error: str | None = None,
) -> ExecutionReceipt:
    if executor.role != Role.GATEWAY:
        raise ValueError("Only the gateway executor can sign an execution receipt.")

    unsigned = ExecutionReceipt(
        ticket_id=ticket.ticket_id,
        action_digest=ticket.action_digest,
        execution_state_digest=execution_state_digest,
        result_state_digest=result_state_digest,
        executed_at=utc_now(),
        success=success,
        reward=reward,
        done=done,
        error=error,
        executor_id=executor.subject_id,
    )
    signature = sign_digest_hex(unsigned.signing_digest(), executor.key_pair)
    return unsigned.model_copy(update={"receipt_signature": signature})


def verify_execution_receipt(
    receipt: ExecutionReceipt,
    executor: TrustedPrincipal,
    *,
    ticket: ExecutionTicket | None = None,
) -> bool:
    return explain_execution_receipt(receipt, executor, ticket=ticket).valid


def explain_execution_receipt(
    receipt: ExecutionReceipt,
    executor: TrustedPrincipal,
    *,
    ticket: ExecutionTicket | None = None,
) -> VerificationResult:
    if receipt.receipt_signature is None:
        return VerificationResult.fail(
            ProtocolErrorCode.MISSING_SIGNATURE,
            "ExecutionReceipt is missing executor signature.",
            details={"receipt_id": receipt.receipt_id},
        )
    if receipt.executor_id != executor.identity.subject_id:
        return VerificationResult.fail(
            ProtocolErrorCode.PRINCIPAL_MISMATCH,
            "ExecutionReceipt executor id does not match the provided principal.",
            details={
                "receipt_id": receipt.receipt_id,
                "expected_executor_id": receipt.executor_id,
                "provided_subject_id": executor.identity.subject_id,
            },
        )
    if executor.identity.role != Role.GATEWAY:
        return VerificationResult.fail(
            ProtocolErrorCode.ROLE_MISMATCH,
            "ExecutionReceipt must be verified with a gateway principal.",
            details={
                "receipt_id": receipt.receipt_id,
                "provided_role": executor.identity.role.value,
            },
        )
    if ticket is not None:
        if receipt.ticket_id != ticket.ticket_id:
            return VerificationResult.fail(
                ProtocolErrorCode.RECEIPT_TICKET_MISMATCH,
                "ExecutionReceipt ticket id does not match the ExecutionTicket.",
                details={
                    "receipt_id": receipt.receipt_id,
                    "receipt_ticket_id": receipt.ticket_id,
                    "ticket_id": ticket.ticket_id,
                },
            )
        if receipt.action_digest != ticket.action_digest:
            return VerificationResult.fail(
                ProtocolErrorCode.RECEIPT_ACTION_MISMATCH,
                "ExecutionReceipt action digest does not match the ExecutionTicket.",
                details={
                    "receipt_id": receipt.receipt_id,
                    "receipt_action_digest": receipt.action_digest,
                    "ticket_action_digest": ticket.action_digest,
                },
            )
    if not verify_digest_hex(
        receipt.signing_digest(),
        receipt.receipt_signature,
        executor.public_key,
    ):
        return VerificationResult.fail(
            ProtocolErrorCode.SIGNATURE_INVALID,
            "ExecutionReceipt executor signature is invalid.",
            details={"receipt_id": receipt.receipt_id},
        )
    return VerificationResult.pass_("ExecutionReceipt signature and binding are valid.")
