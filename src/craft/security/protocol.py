"""High-level protocol orchestration for CRAFT security artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from craft.grid import (
    ConsequenceEvaluator,
    MockConsequenceEvaluator,
    RevalidationResult,
    revalidate_execution,
)
from craft.models import (
    ActionRequest,
    ApprovalSet,
    ConsequenceMetrics,
    CRAFTModel,
    ExecutionDecision,
    ExecutionReceipt,
    ExecutionTicket,
    HexDigest,
    PhysicalConsequenceCertificate,
    RiskLevel,
    Role,
)
from craft.security.approval import build_approval_set, create_approval, explain_approval_set
from craft.security.audit import AuditChain, ProtocolTranscript, build_protocol_transcript
from craft.security.crypto import (
    PrincipalRegistry,
    RoleCredential,
    create_demo_credentials,
)
from craft.security.errors import ProtocolErrorCode, VerificationResult
from craft.security.pcc import explain_pcc_for_action, issue_pcc
from craft.security.policy import DEFAULT_RISK_POLICY, RiskPolicy
from craft.security.receipt import explain_execution_receipt, issue_execution_receipt
from craft.security.ticket import (
    TicketReplayCache,
    explain_consume_execution_ticket,
    explain_execution_ticket,
    issue_execution_ticket,
)
from craft.serialization import JsonValue


class CertifiedAction(CRAFTModel):
    """Action plus consequence evaluation and signed PCC."""

    action: ActionRequest
    evaluation_digest: HexDigest
    pcc: PhysicalConsequenceCertificate
    required_roles: tuple[Role, ...]
    verification: VerificationResult


class AuthorizedAction(CRAFTModel):
    """Certified action plus collected approvals."""

    certified: CertifiedAction
    approval_set: ApprovalSet | None = None
    verification: VerificationResult


class TicketedAction(CRAFTModel):
    """Authorized action plus issued execution ticket."""

    authorized: AuthorizedAction
    ticket: ExecutionTicket | None = None
    verification: VerificationResult


class ExecutedAction(CRAFTModel):
    """Ticket consumption result and optional signed execution receipt."""

    ticketed: TicketedAction
    revalidation: RevalidationResult | None = None
    ticket_consumption: VerificationResult
    receipt: ExecutionReceipt | None = None
    receipt_verification: VerificationResult | None = None


class SecurityProtocol:
    """Composable protocol facade used by Gateway demos and future API handlers."""

    def __init__(
        self,
        *,
        evaluator: ConsequenceEvaluator,
        credentials: Mapping[Role, RoleCredential],
        policy: RiskPolicy = DEFAULT_RISK_POLICY,
        replay_cache: TicketReplayCache | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.credentials = dict(credentials)
        self.policy = policy
        self.replay_cache = replay_cache or TicketReplayCache()
        self.registry = PrincipalRegistry.from_credentials(self.credentials.values())
        self._require_role(Role.CONSEQUENCE_EVALUATOR)
        self._require_role(Role.GATEWAY)

    def certify_action(self, action: ActionRequest) -> CertifiedAction:
        evaluation = self.evaluator.evaluate(action)
        evaluation.ensure_matches_action(action)
        evaluator = self._require_role(Role.CONSEQUENCE_EVALUATOR)
        pcc = issue_pcc(
            action=action,
            state_digest=evaluation.state_digest,
            predicted_state_digest=evaluation.predicted_state_digest,
            metrics=evaluation.metrics,
            risk_level=evaluation.risk_level,
            simulator=evaluation.simulator,
            evaluator=evaluator,
            policy=self.policy,
        )
        verification = explain_pcc_for_action(
            pcc,
            action,
            evaluator.public_principal,
            policy=self.policy,
        )
        return CertifiedAction(
            action=action,
            evaluation_digest=evaluation.digest(),
            pcc=pcc,
            required_roles=self.policy.required_roles_for(pcc.risk_level),
            verification=verification,
        )

    def approve_action(
        self,
        certified: CertifiedAction,
        *,
        roles: Sequence[Role] | None = None,
    ) -> AuthorizedAction:
        if not self.policy.is_authorizable(certified.pcc.risk_level):
            return AuthorizedAction(
                certified=certified,
                approval_set=None,
                verification=_policy_rejected_result(certified.pcc.risk_level),
            )

        requested_roles = tuple(roles) if roles is not None else certified.required_roles
        approvals = tuple(
            create_approval(
                action=certified.action,
                pcc=certified.pcc,
                approver=self._require_role(role),
                policy=self.policy,
            )
            for role in requested_roles
        )
        approval_set = build_approval_set(
            action=certified.action,
            pcc=certified.pcc,
            approvals=approvals,
            policy=self.policy,
        )
        verification = explain_approval_set(
            approval_set,
            self.registry,
            action=certified.action,
            pcc=certified.pcc,
            policy=self.policy,
        )
        return AuthorizedAction(
            certified=certified,
            approval_set=approval_set,
            verification=verification,
        )

    def issue_ticket(self, authorized: AuthorizedAction) -> TicketedAction:
        if authorized.approval_set is None or not authorized.verification.valid:
            return TicketedAction(
                authorized=authorized,
                ticket=None,
                verification=authorized.verification,
            )

        gateway = self._require_role(Role.GATEWAY)
        ticket = issue_execution_ticket(
            action=authorized.certified.action,
            pcc=authorized.certified.pcc,
            approval_set=authorized.approval_set,
            approval_registry=self.registry,
            gateway=gateway,
            policy=self.policy,
        )
        verification = explain_execution_ticket(
            ticket,
            gateway.public_principal,
            action=authorized.certified.action,
            pcc=authorized.certified.pcc,
            approval_set=authorized.approval_set,
            policy=self.policy,
            replay_cache=self.replay_cache,
        )
        return TicketedAction(authorized=authorized, ticket=ticket, verification=verification)

    def consume_ticket_and_issue_receipt(
        self,
        ticketed: TicketedAction,
        *,
        execution_state_digest: str,
        execution_metrics: ConsequenceMetrics | None = None,
        result_state_digest: str | None = None,
        success: bool,
        reward: float | None = None,
        done: bool | None = None,
        error: str | None = None,
    ) -> ExecutedAction:
        if ticketed.ticket is None or ticketed.authorized.approval_set is None:
            return ExecutedAction(
                ticketed=ticketed,
                ticket_consumption=ticketed.verification,
                receipt=None,
                receipt_verification=None,
            )

        gateway = self._require_role(Role.GATEWAY)
        revalidation: RevalidationResult | None = None
        if execution_metrics is not None:
            revalidation = revalidate_execution(
                ticketed.authorized.certified.pcc,
                execution_metrics,
                execution_state_digest=execution_state_digest,
            )
            if revalidation.decision != ExecutionDecision.ALLOW:
                return ExecutedAction(
                    ticketed=ticketed,
                    revalidation=revalidation,
                    ticket_consumption=_verification_result_from_revalidation(revalidation),
                    receipt=None,
                    receipt_verification=None,
                )

        consumption = explain_consume_execution_ticket(
            ticketed.ticket,
            gateway.public_principal,
            self.replay_cache,
            action=ticketed.authorized.certified.action,
            pcc=ticketed.authorized.certified.pcc,
            approval_set=ticketed.authorized.approval_set,
            policy=self.policy,
        )
        if not consumption.valid:
            return ExecutedAction(
                ticketed=ticketed,
                ticket_consumption=consumption,
                receipt=None,
                receipt_verification=None,
            )

        receipt = issue_execution_receipt(
            ticket=ticketed.ticket,
            executor=gateway,
            execution_state_digest=execution_state_digest,
            result_state_digest=result_state_digest,
            success=success,
            reward=reward,
            done=done,
            error=error,
        )
        receipt_verification = explain_execution_receipt(
            receipt,
            gateway.public_principal,
            ticket=ticketed.ticket,
        )
        return ExecutedAction(
            ticketed=ticketed,
            revalidation=revalidation,
            ticket_consumption=consumption,
            receipt=receipt,
            receipt_verification=receipt_verification,
        )

    def authorize_action(
        self,
        action: ActionRequest,
        *,
        roles: Sequence[Role] | None = None,
    ) -> TicketedAction:
        certified = self.certify_action(action)
        authorized = self.approve_action(certified, roles=roles)
        return self.issue_ticket(authorized)

    def build_audit_chain(
        self,
        *,
        certified: CertifiedAction,
        authorized: AuthorizedAction | None = None,
        ticketed: TicketedAction | None = None,
        executed: ExecutedAction | None = None,
        chain: AuditChain | None = None,
    ) -> AuditChain:
        audit_chain = chain or AuditChain()
        gateway = self._require_role(Role.GATEWAY)
        audit_chain = audit_chain.append_signed(
            event_type="pcc_issued",
            actor=self._require_role(Role.CONSEQUENCE_EVALUATOR),
            object_digests={
                "action": certified.action.action_digest,
                "evaluation": certified.evaluation_digest,
                "pcc": certified.pcc.certificate_digest(),
                "policy": certified.pcc.policy_digest,
            },
            details={
                "risk_level": certified.pcc.risk_level.value,
                "required_roles": [role.value for role in certified.required_roles],
                "verification": certified.verification.model_dump(mode="json"),
            },
        )

        if authorized is not None:
            if authorized.approval_set is not None:
                for approval in authorized.approval_set.approvals:
                    audit_chain = audit_chain.append_signed(
                        event_type="approval_signed",
                        actor=self._require_subject(approval.approver_id),
                        object_digests={
                            "action": certified.action.action_digest,
                            "approval": approval.approval_digest(),
                            "pcc": certified.pcc.certificate_digest(),
                            "policy": approval.policy_digest,
                        },
                        details={
                            "approver_id": approval.approver_id,
                            "role": approval.role.value,
                        },
                    )
                audit_chain = audit_chain.append_signed(
                    event_type="approval_set_verified",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "approval_set": authorized.approval_set.digest(),
                        "pcc": certified.pcc.certificate_digest(),
                        "policy": authorized.approval_set.policy_digest,
                    },
                    details={"verification": authorized.verification.model_dump(mode="json")},
                )
            else:
                audit_chain = audit_chain.append_signed(
                    event_type="approval_rejected",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "pcc": certified.pcc.certificate_digest(),
                        "policy": certified.pcc.policy_digest,
                    },
                    details={"verification": authorized.verification.model_dump(mode="json")},
                )

        if ticketed is not None:
            if ticketed.ticket is not None:
                audit_chain = audit_chain.append_signed(
                    event_type="ticket_issued",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "approval_set": ticketed.authorized.approval_set.digest()
                        if ticketed.authorized.approval_set is not None
                        else certified.pcc.certificate_digest(),
                        "pcc": certified.pcc.certificate_digest(),
                        "ticket": ticketed.ticket.digest(),
                    },
                    details={"verification": ticketed.verification.model_dump(mode="json")},
                )
            else:
                audit_chain = audit_chain.append_signed(
                    event_type="ticket_not_issued",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "pcc": certified.pcc.certificate_digest(),
                    },
                    details={"verification": ticketed.verification.model_dump(mode="json")},
                )

        if executed is not None:
            if executed.revalidation is not None:
                object_digests = {
                    "action": certified.action.action_digest,
                    "pcc": certified.pcc.certificate_digest(),
                }
                if executed.ticketed.ticket is not None:
                    object_digests["ticket"] = executed.ticketed.ticket.digest()
                if executed.revalidation.execution_metrics_digest is not None:
                    object_digests["execution_metrics"] = (
                        executed.revalidation.execution_metrics_digest
                    )
                if executed.revalidation.execution_state_digest is not None:
                    object_digests["execution_state"] = executed.revalidation.execution_state_digest
                audit_chain = audit_chain.append_signed(
                    event_type="execution_revalidated",
                    actor=gateway,
                    object_digests=object_digests,
                    details={
                        "revalidation": executed.revalidation.model_dump(mode="json"),
                        "verification": _verification_result_from_revalidation(
                            executed.revalidation
                        ).model_dump(mode="json"),
                    },
                )
            if executed.ticketed.ticket is not None:
                audit_chain = audit_chain.append_signed(
                    event_type="ticket_consumed"
                    if executed.ticket_consumption.valid
                    else "ticket_not_consumed",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "ticket": executed.ticketed.ticket.digest(),
                    },
                    details={"verification": executed.ticket_consumption.model_dump(mode="json")},
                )
            if executed.receipt is not None and executed.ticketed.ticket is not None:
                audit_chain = audit_chain.append_signed(
                    event_type="receipt_issued",
                    actor=gateway,
                    object_digests={
                        "action": certified.action.action_digest,
                        "receipt": executed.receipt.digest(),
                        "ticket": executed.ticketed.ticket.digest(),
                    },
                    details={
                        "verification": executed.receipt_verification.model_dump(mode="json")
                        if executed.receipt_verification is not None
                        else None,
                    },
                )

        return audit_chain

    def build_transcript(
        self,
        *,
        certified: CertifiedAction,
        authorized: AuthorizedAction | None = None,
        ticketed: TicketedAction | None = None,
        executed: ExecutedAction | None = None,
        audit_chain: AuditChain | None = None,
    ) -> ProtocolTranscript:
        effective_ticketed = ticketed or (executed.ticketed if executed is not None else None)
        effective_authorized = authorized or (
            effective_ticketed.authorized if effective_ticketed is not None else None
        )
        verification_results = {"pcc": certified.verification}
        if effective_authorized is not None:
            verification_results["approval_set"] = effective_authorized.verification
        if effective_ticketed is not None:
            verification_results["ticket"] = effective_ticketed.verification
        if executed is not None:
            if executed.revalidation is not None:
                verification_results["revalidation"] = _verification_result_from_revalidation(
                    executed.revalidation
                )
            verification_results["ticket_consumption"] = executed.ticket_consumption
            if executed.receipt_verification is not None:
                verification_results["receipt"] = executed.receipt_verification

        return build_protocol_transcript(
            action=certified.action,
            pcc=certified.pcc,
            approval_set=effective_authorized.approval_set
            if effective_authorized is not None
            else None,
            ticket=effective_ticketed.ticket if effective_ticketed is not None else None,
            receipt=executed.receipt if executed is not None else None,
            verification_results=verification_results,
            audit_chain=audit_chain,
        )

    def _require_role(self, role: Role) -> RoleCredential:
        credential = self.credentials.get(role)
        if credential is None:
            raise KeyError(f"Missing credential for role: {role.value}")
        if credential.role != role:
            raise ValueError(
                f"Credential role mismatch for {role.value}: got {credential.role.value}"
            )
        return credential

    def _require_subject(self, subject_id: str) -> RoleCredential:
        for credential in self.credentials.values():
            if credential.subject_id == subject_id:
                return credential
        raise KeyError(f"Missing credential for subject: {subject_id}")


def create_demo_security_protocol(
    *,
    evaluator: ConsequenceEvaluator | None = None,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> SecurityProtocol:
    return SecurityProtocol(
        evaluator=evaluator or MockConsequenceEvaluator(),
        credentials=create_demo_credentials(),
        policy=policy,
    )


def _policy_rejected_result(risk_level: RiskLevel) -> VerificationResult:
    return VerificationResult.fail(
        ProtocolErrorCode.POLICY_REJECTED,
        "Risk level has no authorization path under the active policy.",
        details={"risk_level": risk_level.value},
    )


def _verification_result_from_revalidation(
    revalidation: RevalidationResult,
) -> VerificationResult:
    details: dict[str, JsonValue] = {
        "decision": revalidation.decision.value,
        "approval_risk_level": revalidation.approval_risk_level.value,
        "execution_risk_level": revalidation.execution_risk_level.value,
    }
    if revalidation.execution_metrics_digest is not None:
        details["execution_metrics_digest"] = revalidation.execution_metrics_digest
    if revalidation.execution_state_digest is not None:
        details["execution_state_digest"] = revalidation.execution_state_digest

    if revalidation.decision == ExecutionDecision.ALLOW:
        return VerificationResult.pass_("Execution-time risk does not exceed approved risk.")
    if revalidation.decision == ExecutionDecision.REQUIRE_REAUTHORIZATION:
        return VerificationResult.fail(
            ProtocolErrorCode.REVALIDATION_REQUIRED,
            revalidation.reason,
            details=details,
        )
    return VerificationResult.fail(
        ProtocolErrorCode.REVALIDATION_REJECTED,
        revalidation.reason,
        details=details,
    )
