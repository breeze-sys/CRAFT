import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from craft.grid import MockConsequenceEvaluator
from craft.models import (
    ActionRequest,
    ActionType,
    ActorIdentity,
    ConsequenceMetrics,
    RiskLevel,
    Role,
    SimulatorInfo,
    utc_now,
)
from craft.security import (
    DEFAULT_RISK_POLICY,
    PrincipalRegistry,
    ProtocolErrorCode,
    RiskPolicy,
    SM2KeyPair,
    TicketReplayCache,
    build_approval_set,
    consume_execution_ticket,
    create_approval,
    create_demo_credentials,
    create_demo_security_protocol,
    explain_approval,
    explain_approval_set,
    explain_audit_chain,
    explain_execution_receipt,
    explain_execution_ticket,
    explain_pcc_for_action,
    issue_execution_receipt,
    issue_execution_ticket,
    issue_pcc,
    sign_digest_hex,
    verify_approval,
    verify_approval_set,
    verify_digest_hex,
    verify_execution_receipt,
    verify_execution_ticket,
    verify_pcc_for_action,
)
from craft.serialization import canonical_digest_hex, canonical_json

REPO_ROOT = Path(__file__).resolve().parents[1]


def _action(delta_mw: float = 20.0) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=ActionType.REDISPATCH,
        parameters={"gen_id": 2, "delta_mw": delta_mw},
        nonce="action-nonce",
    )


def _metrics() -> ConsequenceMetrics:
    return ConsequenceMetrics(
        max_line_loading_ratio=0.76,
        new_overload_count=0,
        min_security_margin=0.24,
        converged=True,
        redispatch_mw=20.0,
    )


def _simulator() -> SimulatorInfo:
    return SimulatorInfo(env_name="l2rpn_2019", version="1.12.5", n_sub=14, n_line=20)


def _issue_l2_pcc(action: ActionRequest):
    credentials = create_demo_credentials()
    pcc = issue_pcc(
        action=action,
        state_digest=canonical_digest_hex({"rho": [0.70, 0.80]}),
        predicted_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        metrics=_metrics(),
        risk_level=RiskLevel.L2,
        simulator=_simulator(),
        evaluator=credentials[Role.CONSEQUENCE_EVALUATOR],
    )
    return credentials, pcc


def _issue_l2_ticket(action: ActionRequest):
    credentials, pcc = _issue_l2_pcc(action)
    approvals = (
        create_approval(action=action, pcc=pcc, approver=credentials[Role.OPERATOR]),
        create_approval(action=action, pcc=pcc, approver=credentials[Role.DISPATCHER]),
    )
    approval_set = build_approval_set(action=action, pcc=pcc, approvals=approvals)
    registry = PrincipalRegistry.from_credentials(credentials.values())
    ticket = issue_execution_ticket(
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        approval_registry=registry,
        gateway=credentials[Role.GATEWAY],
    )
    return credentials, pcc, approval_set, registry, ticket


def test_pcc_can_be_signed_and_verified_for_action() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)

    assert pcc.evaluator_signature is not None
    assert verify_pcc_for_action(
        pcc,
        action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
    )


def test_sm2_verification_accepts_public_key_with_04_x_coordinate_prefix() -> None:
    key_pair = SM2KeyPair(
        private_key="8eb3f0f632d432d0205993e2cc324d8fb6270dd6ba8b358fbf78b0aaa3a1f349",
        public_key=(
            "04a8f91df1dd6e62cff2c798480e2a029ac8898c617a63e9929305fc2dc0a6501"
            "ccb8c36e448e6adc4df854f06e3fc8a27ae5829c5c3a4c196cb834efb631da9"
        ),
    )
    digest = canonical_digest_hex({"edge_case": "public_key_starts_with_04"})

    signature = sign_digest_hex(digest, key_pair)

    assert key_pair.public_key.startswith("04")
    assert verify_digest_hex(digest, signature, key_pair.public_key)


def test_l2_approval_set_requires_operator_and_dispatcher_before_ticket() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    operator_approval = create_approval(
        action=action,
        pcc=pcc,
        approver=credentials[Role.OPERATOR],
    )
    dispatcher_approval = create_approval(
        action=action,
        pcc=pcc,
        approver=credentials[Role.DISPATCHER],
    )
    approval_set = build_approval_set(
        action=action,
        pcc=pcc,
        approvals=(operator_approval, dispatcher_approval),
    )
    registry = PrincipalRegistry.from_credentials(
        (credentials[Role.OPERATOR], credentials[Role.DISPATCHER])
    )

    assert approval_set.is_satisfied()
    assert verify_approval_set(approval_set, registry, action=action, pcc=pcc)

    ticket = issue_execution_ticket(
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        approval_registry=registry,
        gateway=credentials[Role.GATEWAY],
    )

    assert ticket.gateway_signature is not None
    assert verify_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=DEFAULT_RISK_POLICY,
    )


def test_action_parameter_tampering_breaks_pcc_approval_and_ticket_binding() -> None:
    action = _action(delta_mw=20.0)
    tampered_action = _action(delta_mw=80.0)
    credentials, pcc = _issue_l2_pcc(action)
    operator_approval = create_approval(
        action=action,
        pcc=pcc,
        approver=credentials[Role.OPERATOR],
    )
    dispatcher_approval = create_approval(
        action=action,
        pcc=pcc,
        approver=credentials[Role.DISPATCHER],
    )
    approval_set = build_approval_set(
        action=action,
        pcc=pcc,
        approvals=(operator_approval, dispatcher_approval),
    )
    registry = PrincipalRegistry.from_credentials(
        (credentials[Role.OPERATOR], credentials[Role.DISPATCHER])
    )
    ticket = issue_execution_ticket(
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        approval_registry=registry,
        gateway=credentials[Role.GATEWAY],
    )

    assert not verify_pcc_for_action(
        pcc,
        tampered_action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
    )
    assert not verify_approval(
        operator_approval,
        credentials[Role.OPERATOR].public_principal,
        action=tampered_action,
        pcc=pcc,
    )
    assert not verify_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        action=tampered_action,
        pcc=pcc,
        approval_set=approval_set,
    )


def test_old_ticket_replay_is_rejected_after_first_consumption() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    approvals = (
        create_approval(action=action, pcc=pcc, approver=credentials[Role.OPERATOR]),
        create_approval(action=action, pcc=pcc, approver=credentials[Role.DISPATCHER]),
    )
    approval_set = build_approval_set(action=action, pcc=pcc, approvals=approvals)
    registry = PrincipalRegistry.from_credentials(
        (credentials[Role.OPERATOR], credentials[Role.DISPATCHER])
    )
    ticket = issue_execution_ticket(
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        approval_registry=registry,
        gateway=credentials[Role.GATEWAY],
    )
    replay_cache = TicketReplayCache()

    assert consume_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        replay_cache,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=DEFAULT_RISK_POLICY,
    )
    assert not consume_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        replay_cache,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=DEFAULT_RISK_POLICY,
    )


def test_wrong_role_impersonation_is_rejected_even_with_valid_signature() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    forged = create_approval(action=action, pcc=pcc, approver=credentials[Role.DISPATCHER])
    forged_operator_approval = forged.model_copy(
        update={
            "role": Role.OPERATOR,
            "signature": None,
        }
    )
    forged_operator_approval = forged_operator_approval.model_copy(
        update={
            "signature": sign_digest_hex(
                forged_operator_approval.signing_digest(),
                credentials[Role.DISPATCHER].key_pair,
            )
        }
    )

    result = explain_approval(
        forged_operator_approval,
        credentials[Role.DISPATCHER].public_principal,
        action=action,
        pcc=pcc,
        policy=DEFAULT_RISK_POLICY,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.ROLE_MISMATCH
    assert not verify_approval(
        forged_operator_approval,
        credentials[Role.DISPATCHER].public_principal,
        action=action,
        pcc=pcc,
        policy=DEFAULT_RISK_POLICY,
    )


def test_execution_receipt_is_signed_and_verifiable() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    approvals = (
        create_approval(action=action, pcc=pcc, approver=credentials[Role.OPERATOR]),
        create_approval(action=action, pcc=pcc, approver=credentials[Role.DISPATCHER]),
    )
    approval_set = build_approval_set(action=action, pcc=pcc, approvals=approvals)
    registry = PrincipalRegistry.from_credentials(
        (credentials[Role.OPERATOR], credentials[Role.DISPATCHER])
    )
    ticket = issue_execution_ticket(
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        approval_registry=registry,
        gateway=credentials[Role.GATEWAY],
    )
    receipt = issue_execution_receipt(
        ticket=ticket,
        executor=credentials[Role.GATEWAY],
        execution_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        result_state_digest=canonical_digest_hex({"rho": [0.74, 0.79]}),
        success=True,
        reward=1.0,
        done=False,
    )

    assert receipt.receipt_signature is not None
    assert verify_execution_receipt(
        receipt,
        credentials[Role.GATEWAY].public_principal,
        ticket=ticket,
    )

    tampered_receipt = receipt.model_copy(update={"success": False})
    assert not verify_execution_receipt(
        tampered_receipt,
        credentials[Role.GATEWAY].public_principal,
        ticket=ticket,
    )


def test_reject_risk_cannot_be_approved() -> None:
    action = _action()
    credentials = create_demo_credentials()
    pcc = issue_pcc(
        action=action,
        state_digest=canonical_digest_hex({"rho": [1.30]}),
        predicted_state_digest=canonical_digest_hex({"rho": [1.45]}),
        metrics=ConsequenceMetrics(
            max_line_loading_ratio=1.45,
            new_overload_count=1,
            min_security_margin=-0.45,
            converged=True,
        ),
        risk_level=RiskLevel.REJECT,
        simulator=_simulator(),
        evaluator=credentials[Role.CONSEQUENCE_EVALUATOR],
    )

    with pytest.raises(ValueError, match="cannot be authorized"):
        create_approval(action=action, pcc=pcc, approver=credentials[Role.OPERATOR])


def test_verification_result_reports_action_digest_mismatch() -> None:
    action = _action(delta_mw=20.0)
    tampered_action = _action(delta_mw=80.0)
    credentials, pcc = _issue_l2_pcc(action)

    result = explain_pcc_for_action(
        pcc,
        tampered_action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
    )

    assert not result
    assert result.code == ProtocolErrorCode.ACTION_DIGEST_MISMATCH
    assert result.model_dump(mode="json")["code"] == "action_digest_mismatch"


def test_verification_result_reports_policy_digest_mismatch() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    different_policy = RiskPolicy(version="0.2.0")

    result = explain_pcc_for_action(
        pcc,
        action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=different_policy,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.POLICY_DIGEST_MISMATCH


def test_verification_result_reports_expired_pcc() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    now = utc_now()
    expired_pcc = pcc.model_copy(
        update={
            "issued_at": now - timedelta(minutes=10),
            "expires_at": now - timedelta(minutes=5),
        }
    )

    result = explain_pcc_for_action(
        expired_pcc,
        action,
        credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
        at=now,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.EXPIRED


def test_verification_result_reports_missing_required_roles() -> None:
    action = _action()
    credentials, pcc = _issue_l2_pcc(action)
    operator_approval = create_approval(
        action=action,
        pcc=pcc,
        approver=credentials[Role.OPERATOR],
    )
    approval_set = build_approval_set(
        action=action,
        pcc=pcc,
        approvals=(operator_approval,),
    )
    registry = PrincipalRegistry.from_credentials(credentials.values())

    result = explain_approval_set(
        approval_set,
        registry,
        action=action,
        pcc=pcc,
        policy=DEFAULT_RISK_POLICY,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.MISSING_REQUIRED_ROLES
    assert result.details["missing_roles"] == ["dispatcher"]


def test_verification_result_reports_ticket_replay() -> None:
    action = _action()
    credentials, pcc, approval_set, _registry, ticket = _issue_l2_ticket(action)
    replay_cache = TicketReplayCache()

    assert consume_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        replay_cache,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=DEFAULT_RISK_POLICY,
    )
    result = explain_execution_ticket(
        ticket,
        credentials[Role.GATEWAY].public_principal,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        policy=DEFAULT_RISK_POLICY,
        replay_cache=replay_cache,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.TICKET_REPLAY


def test_verification_result_reports_receipt_signature_invalid_after_tamper() -> None:
    action = _action()
    credentials, _pcc, _approval_set, _registry, ticket = _issue_l2_ticket(action)
    receipt = issue_execution_receipt(
        ticket=ticket,
        executor=credentials[Role.GATEWAY],
        execution_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        result_state_digest=canonical_digest_hex({"rho": [0.74, 0.79]}),
        success=True,
    )
    tampered_receipt = receipt.model_copy(update={"success": False})

    result = explain_execution_receipt(
        tampered_receipt,
        credentials[Role.GATEWAY].public_principal,
        ticket=ticket,
    )

    assert not result.valid
    assert result.code == ProtocolErrorCode.SIGNATURE_INVALID


def test_security_protocol_facade_runs_full_authorization_and_receipt_flow() -> None:
    protocol = create_demo_security_protocol()
    action = _action()

    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)
    executed = protocol.consume_ticket_and_issue_receipt(
        ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        result_state_digest=canonical_digest_hex({"rho": [0.74, 0.79]}),
        success=True,
        reward=1.0,
        done=False,
    )
    replayed = protocol.consume_ticket_and_issue_receipt(
        ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        success=True,
    )

    assert certified.verification.valid
    assert certified.required_roles == (Role.DISPATCHER, Role.OPERATOR)
    assert authorized.verification.valid
    assert ticketed.ticket is not None
    assert ticketed.verification.valid
    assert executed.ticket_consumption.valid
    assert executed.receipt is not None
    assert executed.receipt_verification is not None
    assert executed.receipt_verification.valid
    assert not replayed.ticket_consumption.valid
    assert replayed.ticket_consumption.code == ProtocolErrorCode.TICKET_REPLAY


def test_security_protocol_revalidation_blocks_risk_escalation_before_ticket_consumption() -> None:
    protocol = create_demo_security_protocol()
    action = _action()
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)
    execution_state_digest = canonical_digest_hex({"rho": [0.97, 1.01]})

    executed = protocol.consume_ticket_and_issue_receipt(
        ticketed,
        execution_state_digest=execution_state_digest,
        execution_metrics=ConsequenceMetrics(
            max_line_loading_ratio=0.97,
            new_overload_count=0,
            min_security_margin=0.03,
            converged=True,
        ),
        success=True,
    )

    assert certified.pcc.risk_level == RiskLevel.L2
    assert executed.revalidation is not None
    assert executed.revalidation.execution_risk_level == RiskLevel.L3
    assert not executed.ticket_consumption.valid
    assert executed.ticket_consumption.code == ProtocolErrorCode.REVALIDATION_REQUIRED
    assert executed.ticket_consumption.details["execution_state_digest"] == execution_state_digest
    assert executed.receipt is None
    assert ticketed.ticket is not None
    assert ticketed.ticket.ticket_id not in protocol.replay_cache.used_ticket_ids
    audit_chain = protocol.build_audit_chain(
        certified=certified,
        authorized=authorized,
        ticketed=ticketed,
        executed=executed,
    )
    assert explain_audit_chain(audit_chain, protocol.registry).valid
    assert "execution_revalidated" in tuple(event.event_type for event in audit_chain.events)
    assert "ticket_not_consumed" in tuple(event.event_type for event in audit_chain.events)


def test_security_protocol_facade_reports_missing_roles_without_ticket() -> None:
    protocol = create_demo_security_protocol()
    certified = protocol.certify_action(_action())

    authorized = protocol.approve_action(certified, roles=(Role.OPERATOR,))
    ticketed = protocol.issue_ticket(authorized)

    assert not authorized.verification.valid
    assert authorized.verification.code == ProtocolErrorCode.MISSING_REQUIRED_ROLES
    assert ticketed.ticket is None
    assert ticketed.verification.code == ProtocolErrorCode.MISSING_REQUIRED_ROLES


def test_security_protocol_facade_reports_reject_risk_without_approval_path() -> None:
    protocol = create_demo_security_protocol(
        evaluator=MockConsequenceEvaluator(forced_risk_level=RiskLevel.REJECT)
    )
    certified = protocol.certify_action(_action(delta_mw=80.0))

    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)

    assert certified.pcc.risk_level == RiskLevel.REJECT
    assert authorized.approval_set is None
    assert authorized.verification.code == ProtocolErrorCode.POLICY_REJECTED
    assert ticketed.ticket is None
    assert ticketed.verification.code == ProtocolErrorCode.POLICY_REJECTED


def test_security_protocol_builds_verifiable_audit_chain_and_transcript() -> None:
    protocol = create_demo_security_protocol()
    action = _action()
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)
    executed = protocol.consume_ticket_and_issue_receipt(
        ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [0.78, 0.82]}),
        result_state_digest=canonical_digest_hex({"rho": [0.74, 0.79]}),
        success=True,
    )

    audit_chain = protocol.build_audit_chain(
        certified=certified,
        authorized=authorized,
        ticketed=ticketed,
        executed=executed,
    )
    transcript = protocol.build_transcript(
        certified=certified,
        authorized=authorized,
        ticketed=ticketed,
        executed=executed,
        audit_chain=audit_chain,
    )

    assert explain_audit_chain(audit_chain, protocol.registry).valid
    assert audit_chain.events[0].previous_event_digest is None
    assert audit_chain.events[-1].event_type == "receipt_issued"
    assert "approval_signed" in transcript.audit_event_types
    assert transcript.audit_chain_digest == audit_chain.chain_digest
    assert transcript.receipt_digest == executed.receipt.digest()
    assert transcript.verification_results["ticket_consumption"].valid
    assert "receipt_issued" in canonical_json(transcript)


def test_audit_chain_detects_event_tampering() -> None:
    protocol = create_demo_security_protocol()
    action = _action()
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    audit_chain = protocol.build_audit_chain(certified=certified, authorized=authorized)
    first_event = audit_chain.events[0]
    tampered_first_event = first_event.model_copy(update={"event_type": "pcc_modified"})
    tampered_chain = audit_chain.model_copy(
        update={"events": (tampered_first_event, *audit_chain.events[1:])}
    )

    result = explain_audit_chain(tampered_chain, protocol.registry)

    assert not result.valid
    assert result.code == ProtocolErrorCode.SIGNATURE_INVALID


def test_audit_chain_detects_broken_previous_digest_link() -> None:
    protocol = create_demo_security_protocol()
    action = _action()
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    audit_chain = protocol.build_audit_chain(certified=certified, authorized=authorized)
    broken_second_event = audit_chain.events[1].model_copy(
        update={"previous_event_digest": canonical_digest_hex({"broken": True})}
    )
    broken_chain = audit_chain.model_copy(
        update={"events": (audit_chain.events[0], broken_second_event, *audit_chain.events[2:])}
    )

    result = explain_audit_chain(broken_chain, protocol.registry)

    assert not result.valid
    assert result.code == ProtocolErrorCode.AUDIT_CHAIN_MISMATCH


def test_demo_security_protocol_cli_happy_path_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/demo_security_protocol.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Scenario:          happy-path" in result.stdout
    assert "Replay rejected" in result.stdout
    assert "code:    ticket_replay" in result.stdout


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    (
        ("tamper-action", "action_digest_mismatch"),
        ("replay-ticket", "ticket_replay"),
        ("wrong-role", "role_mismatch"),
        ("expired-pcc", "expired"),
        ("policy-mismatch", "policy_digest_mismatch"),
        ("missing-role", "missing_required_roles"),
        ("tamper-receipt", "signature_invalid"),
        ("revalidation-upgrade", "revalidation_required"),
        ("revalidation-reject", "revalidation_rejected"),
    ),
)
def test_demo_security_protocol_cli_attack_scenarios_report_expected_codes(
    scenario: str,
    expected_code: str,
) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/demo_security_protocol.py", "--scenario", scenario],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Scenario:          {scenario}" in result.stdout
    assert f"code:    {expected_code}" in result.stdout
    assert f"Expected rejection: {expected_code}" in result.stdout
