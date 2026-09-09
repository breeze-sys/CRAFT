# ruff: noqa: E402
"""Run Member A security protocol happy-path and attack-scenario demos."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from craft.grid import make_grid2op_consequence_evaluator
from craft.models import (
    ActionRequest,
    ActionType,
    ActorIdentity,
    ApprovalSet,
    ConsequenceMetrics,
    ExecutionReceipt,
    ExecutionTicket,
    PhysicalConsequenceCertificate,
    Role,
    utc_now,
)
from craft.security import (
    DEFAULT_RISK_POLICY,
    PrincipalRegistry,
    ProtocolErrorCode,
    RiskPolicy,
    RoleCredential,
    SecurityProtocol,
    TicketedAction,
    TicketReplayCache,
    VerificationResult,
    build_approval_set,
    consume_execution_ticket,
    create_approval,
    create_demo_security_protocol,
    explain_approval,
    explain_approval_set,
    explain_consume_execution_ticket,
    explain_execution_receipt,
    explain_execution_ticket,
    explain_pcc_for_action,
    issue_execution_receipt,
    sign_digest_hex,
    verify_approval_set,
    verify_execution_receipt,
    verify_execution_ticket,
    verify_pcc_for_action,
)
from craft.serialization import JsonValue, canonical_digest_hex, canonical_json

SCENARIOS = (
    "happy-path",
    "tamper-action",
    "replay-ticket",
    "wrong-role",
    "expired-pcc",
    "policy-mismatch",
    "missing-role",
    "tamper-receipt",
    "revalidation-upgrade",
    "revalidation-reject",
)


@dataclass(frozen=True)
class DemoContext:
    protocol: SecurityProtocol
    credentials: dict[Role, RoleCredential]
    public_registry: PrincipalRegistry
    replay_cache: TicketReplayCache
    action: ActionRequest
    pcc: PhysicalConsequenceCertificate
    approval_set: ApprovalSet
    ticketed: TicketedAction
    ticket: ExecutionTicket
    receipt: ExecutionReceipt


def _short(value: str, width: int = 12) -> str:
    return f"{value[:width]}..."


def _status(name: str, ok: bool) -> str:
    return f"{name:<38} {'PASS' if ok else 'FAIL'}"


def _create_action(delta_mw: float = 20.0) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=ActionType.REDISPATCH,
        parameters={"gen_id": 2, "delta_mw": delta_mw},
        nonce=f"demo-action-nonce-{delta_mw}",
        justification="Reduce overload risk through moderate redispatch.",
    )


def _build_demo_context(evaluator: str = "mock") -> DemoContext:
    protocol = create_demo_security_protocol(
        evaluator=make_grid2op_consequence_evaluator() if evaluator == "grid2op" else None
    )
    credentials = protocol.credentials
    public_registry = protocol.registry
    replay_cache = protocol.replay_cache
    action = _create_action()

    # In the full system, create_demo_security_protocol can receive Member B's
    # real Grid2Op evaluator while preserving the same security protocol calls.
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)
    if authorized.approval_set is None or ticketed.ticket is None:
        raise RuntimeError("Demo context expected a fully authorized L2 action.")

    pcc = certified.pcc
    approval_set = authorized.approval_set
    ticket = ticketed.ticket
    receipt = issue_execution_receipt(
        ticket=ticket,
        executor=credentials[Role.GATEWAY],
        execution_state_digest=canonical_digest_hex({"rho": [0.75, 0.82], "timestep": 43}),
        result_state_digest=canonical_digest_hex({"rho": [0.73, 0.79], "timestep": 44}),
        success=True,
        reward=1.0,
        done=False,
    )

    return DemoContext(
        credentials=credentials,
        protocol=protocol,
        public_registry=public_registry,
        replay_cache=replay_cache,
        action=action,
        pcc=pcc,
        approval_set=approval_set,
        ticketed=ticketed,
        ticket=ticket,
        receipt=receipt,
    )


def _print_context(ctx: DemoContext, scenario: str, evaluator: str) -> None:
    required_roles = DEFAULT_RISK_POLICY.required_roles_for(ctx.pcc.risk_level)
    print("CRAFT Member A Security Protocol Demo")
    print("=" * 44)
    print(f"Scenario:          {scenario}")
    print(f"Evaluator:         {evaluator}")
    print(f"Action type:       {ctx.action.action_type.value}")
    print(f"Action digest:     {_short(ctx.action.action_digest)}")
    print(f"Risk level:        {ctx.pcc.risk_level.value}")
    print(f"Required roles:    {', '.join(role.value for role in required_roles)}")
    print(f"PCC digest:        {_short(ctx.pcc.certificate_digest())}")
    print(f"ApprovalSet:       {_short(ctx.approval_set.digest())}")
    print(f"Ticket id:         {ctx.ticket.ticket_id}")
    print(f"Receipt id:        {ctx.receipt.receipt_id}")
    print()


def _render_detail(value: JsonValue) -> str:
    if isinstance(value, str) and len(value) >= 48:
        return _short(value, 18)
    if isinstance(value, dict | list):
        return canonical_json(value)
    return str(value)


def _print_verification_result(result: VerificationResult) -> None:
    print("VerificationResult")
    print(f"  valid:   {str(result.valid).lower()}")
    print(f"  code:    {result.code.value}")
    print(f"  message: {result.message}")
    if result.details:
        print("  details:")
        for key, value in result.details.items():
            print(f"    {key}: {_render_detail(value)}")
    print()


def _run_happy_path(evaluator: str) -> int:
    ctx = _build_demo_context(evaluator=evaluator)
    _print_context(ctx, "happy-path", evaluator)

    pcc_result = explain_pcc_for_action(
        ctx.pcc,
        ctx.action,
        ctx.credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
    )
    approval_result = explain_approval_set(
        ctx.approval_set,
        ctx.public_registry,
        action=ctx.action,
        pcc=ctx.pcc,
        policy=DEFAULT_RISK_POLICY,
    )
    ticket_result = explain_execution_ticket(
        ctx.ticket,
        ctx.credentials[Role.GATEWAY].public_principal,
        action=ctx.action,
        pcc=ctx.pcc,
        approval_set=ctx.approval_set,
        policy=DEFAULT_RISK_POLICY,
        replay_cache=ctx.replay_cache,
    )
    first_use_ok = consume_execution_ticket(
        ctx.ticket,
        ctx.credentials[Role.GATEWAY].public_principal,
        ctx.replay_cache,
        action=ctx.action,
        pcc=ctx.pcc,
        approval_set=ctx.approval_set,
        policy=DEFAULT_RISK_POLICY,
    )
    replay_result = explain_consume_execution_ticket(
        ctx.ticket,
        ctx.credentials[Role.GATEWAY].public_principal,
        ctx.replay_cache,
        action=ctx.action,
        pcc=ctx.pcc,
        approval_set=ctx.approval_set,
        policy=DEFAULT_RISK_POLICY,
    )
    receipt_result = explain_execution_receipt(
        ctx.receipt,
        ctx.credentials[Role.GATEWAY].public_principal,
        ticket=ctx.ticket,
    )

    checks = (
        ("PCC signature and action binding", pcc_result.valid),
        ("Approval signatures and roles", approval_result.valid),
        ("Execution ticket signature", ticket_result.valid),
        ("First ticket consumption", first_use_ok),
        ("Replay rejected", replay_result.code == ProtocolErrorCode.TICKET_REPLAY),
        ("Receipt signature and ticket binding", receipt_result.valid),
    )
    for name, ok in checks:
        print(_status(name, ok))

    print()
    print("Replay rejection reason for Dashboard:")
    _print_verification_result(replay_result)

    bool_apis_ok = all(
        (
            verify_pcc_for_action(
                ctx.pcc,
                ctx.action,
                ctx.credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
                policy=DEFAULT_RISK_POLICY,
            ),
            verify_approval_set(
                ctx.approval_set,
                ctx.public_registry,
                action=ctx.action,
                pcc=ctx.pcc,
                policy=DEFAULT_RISK_POLICY,
            ),
            verify_execution_ticket(
                ctx.ticket,
                ctx.credentials[Role.GATEWAY].public_principal,
                action=ctx.action,
                pcc=ctx.pcc,
                approval_set=ctx.approval_set,
                policy=DEFAULT_RISK_POLICY,
                replay_cache=TicketReplayCache(),
            ),
            verify_execution_receipt(
                ctx.receipt,
                ctx.credentials[Role.GATEWAY].public_principal,
                ticket=ctx.ticket,
            ),
        )
    )
    return 0 if all(ok for _, ok in checks) and bool_apis_ok else 1


def _scenario_tamper_action(ctx: DemoContext) -> VerificationResult:
    tampered_action = _create_action(delta_mw=80.0)
    return explain_pcc_for_action(
        ctx.pcc,
        tampered_action,
        ctx.credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
    )


def _scenario_replay_ticket(ctx: DemoContext) -> VerificationResult:
    first_use = explain_consume_execution_ticket(
        ctx.ticket,
        ctx.credentials[Role.GATEWAY].public_principal,
        ctx.replay_cache,
        action=ctx.action,
        pcc=ctx.pcc,
        approval_set=ctx.approval_set,
        policy=DEFAULT_RISK_POLICY,
    )
    if not first_use.valid:
        return first_use
    return explain_consume_execution_ticket(
        ctx.ticket,
        ctx.credentials[Role.GATEWAY].public_principal,
        ctx.replay_cache,
        action=ctx.action,
        pcc=ctx.pcc,
        approval_set=ctx.approval_set,
        policy=DEFAULT_RISK_POLICY,
    )


def _scenario_wrong_role(ctx: DemoContext) -> VerificationResult:
    forged = create_approval(
        action=ctx.action,
        pcc=ctx.pcc,
        approver=ctx.credentials[Role.DISPATCHER],
    )
    forged_operator_approval = forged.model_copy(update={"role": Role.OPERATOR, "signature": None})
    forged_operator_approval = forged_operator_approval.model_copy(
        update={
            "signature": sign_digest_hex(
                forged_operator_approval.signing_digest(),
                ctx.credentials[Role.DISPATCHER].key_pair,
            )
        }
    )
    return explain_approval(
        forged_operator_approval,
        ctx.credentials[Role.DISPATCHER].public_principal,
        action=ctx.action,
        pcc=ctx.pcc,
        policy=DEFAULT_RISK_POLICY,
    )


def _scenario_expired_pcc(ctx: DemoContext) -> VerificationResult:
    now = utc_now()
    expired_pcc = ctx.pcc.model_copy(
        update={
            "issued_at": now - timedelta(minutes=10),
            "expires_at": now - timedelta(minutes=5),
        }
    )
    return explain_pcc_for_action(
        expired_pcc,
        ctx.action,
        ctx.credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=DEFAULT_RISK_POLICY,
        at=now,
    )


def _scenario_policy_mismatch(ctx: DemoContext) -> VerificationResult:
    changed_policy = RiskPolicy(version="0.2.0")
    return explain_pcc_for_action(
        ctx.pcc,
        ctx.action,
        ctx.credentials[Role.CONSEQUENCE_EVALUATOR].public_principal,
        policy=changed_policy,
    )


def _scenario_missing_role(ctx: DemoContext) -> VerificationResult:
    operator_approval = create_approval(
        action=ctx.action,
        pcc=ctx.pcc,
        approver=ctx.credentials[Role.OPERATOR],
    )
    incomplete_approval_set = build_approval_set(
        action=ctx.action,
        pcc=ctx.pcc,
        approvals=(operator_approval,),
    )
    return explain_approval_set(
        incomplete_approval_set,
        ctx.public_registry,
        action=ctx.action,
        pcc=ctx.pcc,
        policy=DEFAULT_RISK_POLICY,
    )


def _scenario_tamper_receipt(ctx: DemoContext) -> VerificationResult:
    tampered_receipt = ctx.receipt.model_copy(update={"success": not ctx.receipt.success})
    return explain_execution_receipt(
        tampered_receipt,
        ctx.credentials[Role.GATEWAY].public_principal,
        ticket=ctx.ticket,
    )


def _scenario_revalidation_upgrade(ctx: DemoContext) -> VerificationResult:
    executed = ctx.protocol.consume_ticket_and_issue_receipt(
        ctx.ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [0.97, 1.01], "timestep": 43}),
        execution_metrics=ConsequenceMetrics(
            max_line_loading_ratio=0.97,
            new_overload_count=0,
            min_security_margin=0.03,
            converged=True,
        ),
        success=True,
    )
    return executed.ticket_consumption


def _scenario_revalidation_reject(ctx: DemoContext) -> VerificationResult:
    executed = ctx.protocol.consume_ticket_and_issue_receipt(
        ctx.ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [1.21, 1.02], "timestep": 43}),
        execution_metrics=ConsequenceMetrics(
            max_line_loading_ratio=1.21,
            new_overload_count=3,
            min_security_margin=-0.21,
            converged=True,
        ),
        success=True,
    )
    return executed.ticket_consumption


SCENARIO_RUNNERS: dict[str, Callable[[DemoContext], VerificationResult]] = {
    "tamper-action": _scenario_tamper_action,
    "replay-ticket": _scenario_replay_ticket,
    "wrong-role": _scenario_wrong_role,
    "expired-pcc": _scenario_expired_pcc,
    "policy-mismatch": _scenario_policy_mismatch,
    "missing-role": _scenario_missing_role,
    "tamper-receipt": _scenario_tamper_receipt,
    "revalidation-upgrade": _scenario_revalidation_upgrade,
    "revalidation-reject": _scenario_revalidation_reject,
}

EXPECTED_ERROR_CODES = {
    "tamper-action": ProtocolErrorCode.ACTION_DIGEST_MISMATCH,
    "replay-ticket": ProtocolErrorCode.TICKET_REPLAY,
    "wrong-role": ProtocolErrorCode.ROLE_MISMATCH,
    "expired-pcc": ProtocolErrorCode.EXPIRED,
    "policy-mismatch": ProtocolErrorCode.POLICY_DIGEST_MISMATCH,
    "missing-role": ProtocolErrorCode.MISSING_REQUIRED_ROLES,
    "tamper-receipt": ProtocolErrorCode.SIGNATURE_INVALID,
    "revalidation-upgrade": ProtocolErrorCode.REVALIDATION_REQUIRED,
    "revalidation-reject": ProtocolErrorCode.REVALIDATION_REJECTED,
}


def _run_attack_scenario(scenario: str, evaluator: str) -> int:
    ctx = _build_demo_context(evaluator=evaluator)
    _print_context(ctx, scenario, evaluator)
    result = SCENARIO_RUNNERS[scenario](ctx)
    expected_code = EXPECTED_ERROR_CODES[scenario]
    _print_verification_result(result)

    expected_rejection_observed = not result.valid and result.code == expected_code
    print(_status(f"Expected rejection: {expected_code.value}", expected_rejection_observed))
    return 0 if expected_rejection_observed else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CRAFT Member A security protocol demos.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="happy-path",
        help="Demo scenario to run. Attack scenarios exit 0 when expected rejection is observed.",
    )
    parser.add_argument(
        "--evaluator",
        choices=("mock", "grid2op"),
        default="mock",
        help="Consequence evaluator backend. grid2op requires the local l2rpn_2019 dataset.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.scenario == "happy-path":
        return _run_happy_path(args.evaluator)
    return _run_attack_scenario(args.scenario, args.evaluator)


if __name__ == "__main__":
    raise SystemExit(main())
