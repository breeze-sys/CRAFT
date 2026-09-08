"""Execution-time risk revalidation for CRAFT approvals."""

from __future__ import annotations

from craft.models import (
    ConsequenceMetrics,
    CRAFTModel,
    ExecutionDecision,
    PhysicalConsequenceCertificate,
    RiskLevel,
)
from craft.risk_engine import evaluate_risk

RISK_LEVEL_ORDER: dict[RiskLevel, int] = {
    RiskLevel.L1: 1,
    RiskLevel.L2: 2,
    RiskLevel.L3: 3,
    RiskLevel.REJECT: 4,
}


class RevalidationResult(CRAFTModel):
    decision: ExecutionDecision
    approval_risk_level: RiskLevel
    execution_risk_level: RiskLevel
    reason: str


def risk_level_rank(risk_level: RiskLevel) -> int:
    return RISK_LEVEL_ORDER[risk_level]


def revalidate_execution(
    approval_pcc: PhysicalConsequenceCertificate,
    execution_metrics: ConsequenceMetrics,
) -> RevalidationResult:
    execution_risk_level = evaluate_risk(execution_metrics)
    return decide_revalidation(
        approval_risk_level=approval_pcc.risk_level,
        execution_risk_level=execution_risk_level,
    )


def decide_revalidation(
    approval_risk_level: RiskLevel,
    execution_risk_level: RiskLevel,
) -> RevalidationResult:
    if execution_risk_level == RiskLevel.REJECT:
        return RevalidationResult(
            decision=ExecutionDecision.REJECT,
            approval_risk_level=approval_risk_level,
            execution_risk_level=execution_risk_level,
            reason="Execution-time risk is REJECT; action is not physically acceptable.",
        )

    if risk_level_rank(execution_risk_level) > risk_level_rank(approval_risk_level):
        return RevalidationResult(
            decision=ExecutionDecision.REQUIRE_REAUTHORIZATION,
            approval_risk_level=approval_risk_level,
            execution_risk_level=execution_risk_level,
            reason=(
                f"Execution-time risk {execution_risk_level.value} exceeds "
                f"approval-time risk {approval_risk_level.value}; reauthorization required."
            ),
        )

    return RevalidationResult(
        decision=ExecutionDecision.ALLOW,
        approval_risk_level=approval_risk_level,
        execution_risk_level=execution_risk_level,
        reason=(
            f"Execution-time risk {execution_risk_level.value} does not exceed "
            f"approval-time risk {approval_risk_level.value}; existing approval remains valid."
        ),
    )
