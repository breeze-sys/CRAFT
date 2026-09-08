import pytest

from craft.grid import revalidate_execution
from craft.models import (
    ConsequenceMetrics,
    ExecutionDecision,
    PhysicalConsequenceCertificate,
    RiskLevel,
    SimulatorInfo,
)
from craft.serialization import canonical_digest_hex


def make_metrics(**overrides: object) -> ConsequenceMetrics:
    values = {
        "max_line_loading_ratio": 0.50,
        "new_overload_count": 0,
        "min_security_margin": 0.50,
        "converged": True,
    }
    values.update(overrides)
    return ConsequenceMetrics(**values)


def metrics_for_risk(risk_level: RiskLevel) -> ConsequenceMetrics:
    if risk_level == RiskLevel.L1:
        return make_metrics(max_line_loading_ratio=0.50, min_security_margin=0.50)
    if risk_level == RiskLevel.L2:
        return make_metrics(max_line_loading_ratio=0.85, min_security_margin=0.15)
    if risk_level == RiskLevel.L3:
        return make_metrics(max_line_loading_ratio=0.95, min_security_margin=0.05)
    return make_metrics(
        max_line_loading_ratio=1.20,
        min_security_margin=-0.20,
        converged=True,
    )


def make_pcc(risk_level: RiskLevel) -> PhysicalConsequenceCertificate:
    return PhysicalConsequenceCertificate(
        state_digest=canonical_digest_hex({"state": "approval"}),
        action_digest=canonical_digest_hex({"action": "redispatch"}),
        predicted_state_digest=canonical_digest_hex({"state": "predicted"}),
        metrics=metrics_for_risk(risk_level),
        risk_level=risk_level,
        policy_digest=canonical_digest_hex({"policy": "test"}),
        simulator=SimulatorInfo(env_name="fake-grid2op-env", version="test"),
        evaluator_id="evaluator-1",
    )


@pytest.mark.parametrize(
    (
        "approval_risk_level",
        "execution_risk_level",
        "expected_decision",
        "reason_fragment",
    ),
    (
        (RiskLevel.L1, RiskLevel.L1, ExecutionDecision.ALLOW, "does not exceed"),
        (RiskLevel.L2, RiskLevel.L1, ExecutionDecision.ALLOW, "does not exceed"),
        (
            RiskLevel.L1,
            RiskLevel.L2,
            ExecutionDecision.REQUIRE_REAUTHORIZATION,
            "reauthorization required",
        ),
        (
            RiskLevel.L2,
            RiskLevel.L3,
            ExecutionDecision.REQUIRE_REAUTHORIZATION,
            "reauthorization required",
        ),
        (RiskLevel.L3, RiskLevel.REJECT, ExecutionDecision.REJECT, "not physically acceptable"),
        (
            RiskLevel.REJECT,
            RiskLevel.REJECT,
            ExecutionDecision.REJECT,
            "not physically acceptable",
        ),
    ),
)
def test_revalidation_decisions(
    approval_risk_level: RiskLevel,
    execution_risk_level: RiskLevel,
    expected_decision: ExecutionDecision,
    reason_fragment: str,
) -> None:
    result = revalidate_execution(
        make_pcc(approval_risk_level),
        metrics_for_risk(execution_risk_level),
        execution_state_digest=canonical_digest_hex({"state": "execution"}),
    )

    assert result.decision == expected_decision
    assert result.approval_risk_level == approval_risk_level
    assert result.execution_risk_level == execution_risk_level
    assert result.execution_metrics_digest == metrics_for_risk(execution_risk_level).digest()
    assert result.execution_state_digest == canonical_digest_hex({"state": "execution"})
    assert reason_fragment in result.reason
