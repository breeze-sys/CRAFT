from datetime import timedelta

import pytest

from craft.models import (
    ActionRequest,
    ActionType,
    ActorIdentity,
    Approval,
    ApprovalSet,
    ConsequenceMetrics,
    PhysicalConsequenceCertificate,
    RiskLevel,
    Role,
    SimulatorInfo,
    expires_in,
    utc_now,
)
from craft.policy import DEFAULT_RISK_POLICY, RiskPolicy
from craft.serialization import canonical_digest_hex, canonical_json, sm3_digest_hex


def test_canonical_digest_is_stable_across_dict_order() -> None:
    left = {"b": [2, 1], "a": {"x": True}}
    right = {"a": {"x": True}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_digest_hex(left) == canonical_digest_hex(right)
    assert (
        sm3_digest_hex("abc")
        == "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"
    )


def test_action_digest_changes_when_parameters_are_tampered() -> None:
    agent = ActorIdentity(subject_id="agent-1", role=Role.AGENT)
    action = ActionRequest(
        requested_by=agent,
        action_type=ActionType.REDISPATCH,
        parameters={"gen_id": 2, "delta_mw": 20.0},
        nonce="demo-nonce",
    )
    tampered = action.model_copy(update={"parameters": {"gen_id": 2, "delta_mw": 80.0}})

    assert action.action_digest != tampered.action_digest


def test_pcc_signing_digest_excludes_signature_but_certificate_digest_binds_it() -> None:
    policy = RiskPolicy()
    pcc = PhysicalConsequenceCertificate(
        state_digest=canonical_digest_hex({"rho": [0.7, 0.8]}),
        action_digest=canonical_digest_hex({"type": "redispatch", "delta_mw": 20}),
        predicted_state_digest=canonical_digest_hex({"rho": [0.72, 0.76]}),
        metrics=ConsequenceMetrics(
            max_line_loading_ratio=0.76,
            new_overload_count=0,
            min_security_margin=0.24,
            converged=True,
        ),
        risk_level=RiskLevel.L1,
        policy_digest=policy.policy_digest,
        simulator=SimulatorInfo(
            env_name="l2rpn_neurips_2020_track1_small",
            version="1.12.5",
            n_sub=36,
            n_line=59,
        ),
        evaluator_id="evaluator-1",
    )
    signed = pcc.model_copy(update={"evaluator_signature": "fake-sm2-signature"})

    assert pcc.signing_digest() == signed.signing_digest()
    assert pcc.certificate_digest() != signed.certificate_digest()


def test_default_policy_maps_risk_to_required_roles() -> None:
    assert DEFAULT_RISK_POLICY.required_roles_for(RiskLevel.L1) == (Role.OPERATOR,)
    assert DEFAULT_RISK_POLICY.required_roles_for(RiskLevel.L2) == (
        Role.DISPATCHER,
        Role.OPERATOR,
    )
    assert DEFAULT_RISK_POLICY.required_roles_for(RiskLevel.L3) == (
        Role.DISPATCHER,
        Role.OPERATOR,
        Role.SAFETY_OFFICER,
    )
    assert not DEFAULT_RISK_POLICY.is_authorizable(RiskLevel.REJECT)


def test_approval_set_requires_matching_digests_and_roles() -> None:
    action_digest = canonical_digest_hex({"action": "redispatch"})
    pcc_digest = canonical_digest_hex({"pcc": "signed"})
    policy_digest = DEFAULT_RISK_POLICY.policy_digest
    approval = Approval(
        pcc_id="pcc-1",
        action_digest=action_digest,
        pcc_digest=pcc_digest,
        policy_digest=policy_digest,
        role=Role.OPERATOR,
        approver_id="operator-1",
        signature="fake-signature",
    )
    approval_set = ApprovalSet(
        pcc_id="pcc-1",
        action_digest=action_digest,
        pcc_digest=pcc_digest,
        policy_digest=policy_digest,
        required_roles=(Role.OPERATOR,),
        approvals=(approval,),
    )

    assert approval_set.is_satisfied()
    assert approval_set.missing_roles == ()


def test_approval_set_rejects_role_mismatch() -> None:
    action_digest = canonical_digest_hex({"action": "redispatch"})
    pcc_digest = canonical_digest_hex({"pcc": "signed"})
    policy_digest = DEFAULT_RISK_POLICY.policy_digest
    approval = Approval(
        pcc_id="pcc-1",
        action_digest=action_digest,
        pcc_digest=pcc_digest,
        policy_digest=policy_digest,
        role=Role.SAFETY_OFFICER,
        approver_id="safety-1",
    )

    with pytest.raises(ValueError, match="Unexpected approval role"):
        ApprovalSet(
            pcc_id="pcc-1",
            action_digest=action_digest,
            pcc_digest=pcc_digest,
            policy_digest=policy_digest,
            required_roles=(Role.OPERATOR,),
            approvals=(approval,),
        )


def test_validity_windows_must_move_forward() -> None:
    now = utc_now()

    with pytest.raises(ValueError, match="PCC expiry"):
        PhysicalConsequenceCertificate(
            state_digest=canonical_digest_hex({"state": 1}),
            action_digest=canonical_digest_hex({"action": 1}),
            predicted_state_digest=canonical_digest_hex({"state": 2}),
            metrics=ConsequenceMetrics(
                max_line_loading_ratio=0.9,
                new_overload_count=0,
                min_security_margin=0.1,
                converged=True,
            ),
            risk_level=RiskLevel.L1,
            policy_digest=DEFAULT_RISK_POLICY.policy_digest,
            simulator=SimulatorInfo(env_name="l2rpn_neurips_2020_track1_small", version="1.12.5"),
            evaluator_id="evaluator-1",
            issued_at=now,
            expires_at=now - timedelta(seconds=1),
        )

    assert expires_in(1) > now
