import pytest

from craft.grid import MockConsequenceEvaluator
from craft.models import ActionRequest, ActionType, ActorIdentity, RiskLevel, Role
from craft.security import (
    DEFAULT_RISK_POLICY,
    create_demo_credentials,
    issue_pcc,
    verify_pcc_for_action,
)


def _agent_action(action_type: ActionType, parameters: dict[str, object]) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=action_type,
        parameters=parameters,
        nonce="contract-test-nonce",
    )


@pytest.mark.parametrize(
    ("delta_mw", "expected_risk"),
    (
        (5.0, RiskLevel.L1),
        (20.0, RiskLevel.L2),
        (45.0, RiskLevel.L3),
        (80.0, RiskLevel.REJECT),
    ),
)
def test_mock_consequence_evaluator_maps_redispatch_to_risk(
    delta_mw: float,
    expected_risk: RiskLevel,
) -> None:
    action = _agent_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": delta_mw})

    evaluation = MockConsequenceEvaluator().evaluate(action)

    assert evaluation.action_digest == action.action_digest
    assert evaluation.risk_level == expected_risk


def test_consequence_result_rejects_action_digest_mismatch() -> None:
    original = _agent_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": 20.0})
    tampered = _agent_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": 80.0})
    evaluation = MockConsequenceEvaluator().evaluate(original)

    with pytest.raises(ValueError, match="action digest"):
        evaluation.ensure_matches_action(tampered)


def test_consequence_contract_output_can_issue_member_a_pcc() -> None:
    action = _agent_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": 20.0})
    evaluation = MockConsequenceEvaluator().evaluate(action)
    evaluation.ensure_matches_action(action)
    credentials = create_demo_credentials()

    pcc = issue_pcc(
        action=action,
        state_digest=evaluation.state_digest,
        predicted_state_digest=evaluation.predicted_state_digest,
        metrics=evaluation.metrics,
        risk_level=evaluation.risk_level,
        simulator=evaluation.simulator,
        evaluator=credentials[Role.CONSEQUENCE_EVALUATOR],
        policy=DEFAULT_RISK_POLICY,
    )

    assert verify_pcc_for_action(
        pcc,
        action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
    )
