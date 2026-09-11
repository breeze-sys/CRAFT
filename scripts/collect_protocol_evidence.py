# ruff: noqa: E402
"""Collect report-ready CRAFT protocol evidence as JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from demo_security_protocol import (  # noqa: E402
    EXPECTED_ERROR_CODES,
    SCENARIO_RUNNERS,
    SCENARIOS,
    DemoContext,
    _build_demo_context,
)

from craft.models import ConsequenceMetrics, Role
from craft.security import ProtocolErrorCode, VerificationResult, explain_audit_chain
from craft.serialization import canonical_digest_hex

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "protocol" / "security_protocol_evidence.json"


def _json_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _result_json(result: VerificationResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def _scenario_expected_result(scenario: str) -> ProtocolErrorCode:
    return ProtocolErrorCode.OK if scenario == "happy-path" else EXPECTED_ERROR_CODES[scenario]


def _happy_path_execution_metrics() -> ConsequenceMetrics:
    return ConsequenceMetrics(
        max_line_loading_ratio=0.80,
        new_overload_count=0,
        min_security_margin=0.20,
        converged=True,
        redispatch_mw=20.0,
    )


def _collect_happy_path(ctx: DemoContext) -> dict[str, Any]:
    execution_metrics = _happy_path_execution_metrics()
    executed = ctx.protocol.consume_ticket_and_issue_receipt(
        ctx.ticketed,
        execution_state_digest=canonical_digest_hex({"rho": [0.75, 0.82], "timestep": 43}),
        execution_metrics=execution_metrics,
        result_state_digest=canonical_digest_hex({"rho": [0.73, 0.79], "timestep": 44}),
        success=True,
        reward=1.0,
        done=False,
    )
    audit_chain = ctx.protocol.build_audit_chain(
        certified=ctx.ticketed.authorized.certified,
        authorized=ctx.ticketed.authorized,
        ticketed=ctx.ticketed,
        executed=executed,
    )
    audit_result = explain_audit_chain(audit_chain, ctx.protocol.registry)
    transcript = ctx.protocol.build_transcript(
        certified=ctx.ticketed.authorized.certified,
        authorized=ctx.ticketed.authorized,
        ticketed=ctx.ticketed,
        executed=executed,
        audit_chain=audit_chain,
    )
    results = {
        "pcc": ctx.ticketed.authorized.certified.verification,
        "approval_set": ctx.ticketed.authorized.verification,
        "ticket": ctx.ticketed.verification,
        "ticket_consumption": executed.ticket_consumption,
        "receipt": executed.receipt_verification,
        "audit_chain": audit_result,
    }
    passed = all(result is not None and result.valid for result in results.values())

    return {
        "scenario": "happy-path",
        "claim": "Valid PCC, role approvals, one-time Ticket and Receipt are accepted.",
        "expected_code": ProtocolErrorCode.OK.value,
        "scenario_result": _result_json(executed.ticket_consumption),
        "passed": passed,
        "verification_results": {
            name: _result_json(result) if result is not None else None
            for name, result in results.items()
        },
        "execution_metrics": execution_metrics.model_dump(mode="json"),
        "receipt": _json_dump(executed.receipt),
        "audit_chain": _json_dump(audit_chain),
        "transcript": transcript.model_dump(mode="json"),
    }


def _collect_attack_or_revalidation_scenario(
    scenario: str,
    ctx: DemoContext,
) -> dict[str, Any]:
    result = SCENARIO_RUNNERS[scenario](ctx)
    expected_code = _scenario_expected_result(scenario)
    audit_chain = ctx.protocol.build_audit_chain(
        certified=ctx.ticketed.authorized.certified,
        authorized=ctx.ticketed.authorized,
        ticketed=ctx.ticketed,
    )
    audit_result = explain_audit_chain(audit_chain, ctx.protocol.registry)
    transcript = ctx.protocol.build_transcript(
        certified=ctx.ticketed.authorized.certified,
        authorized=ctx.ticketed.authorized,
        ticketed=ctx.ticketed,
        audit_chain=audit_chain,
    )

    return {
        "scenario": scenario,
        "claim": _scenario_claim(scenario),
        "expected_code": expected_code.value,
        "scenario_result": _result_json(result),
        "passed": (not result.valid and result.code == expected_code),
        "verification_results": {
            "scenario_result": _result_json(result),
            "audit_chain": _result_json(audit_result),
        },
        "audit_chain": _json_dump(audit_chain),
        "transcript": transcript.model_dump(mode="json"),
    }


def collect_scenario(scenario: str, evaluator: str) -> dict[str, Any]:
    started = time.perf_counter()
    ctx = _build_demo_context(evaluator=evaluator)
    required_roles = ctx.protocol.policy.required_roles_for(ctx.pcc.risk_level)
    base = {
        "evaluator": evaluator,
        "action": ctx.action.model_dump(mode="json"),
        "pcc": ctx.pcc.model_dump(mode="json"),
        "approval_set": ctx.approval_set.model_dump(mode="json"),
        "ticket": ctx.ticket.model_dump(mode="json"),
        "risk_level": ctx.pcc.risk_level.value,
        "required_roles": [role.value for role in required_roles],
        "approved_roles": [role.value for role in ctx.approval_set.approved_roles],
        "digests": {
            "action": ctx.action.action_digest,
            "pcc": ctx.pcc.certificate_digest(),
            "approval_set": ctx.approval_set.digest(),
            "ticket": ctx.ticket.digest(),
            "state": ctx.pcc.state_digest,
            "predicted_state": ctx.pcc.predicted_state_digest,
            "policy": ctx.pcc.policy_digest,
        },
        "simulator": ctx.pcc.simulator.model_dump(mode="json"),
        "metrics": ctx.pcc.metrics.model_dump(mode="json"),
    }

    evidence = (
        _collect_happy_path(ctx)
        if scenario == "happy-path"
        else _collect_attack_or_revalidation_scenario(scenario, ctx)
    )
    evidence.update(base)
    evidence["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return evidence


def _scenario_claim(scenario: str) -> str:
    claims = {
        "tamper-action": (
            "Changing action parameters after certification breaks action digest binding."
        ),
        "replay-ticket": "A consumed ExecutionTicket cannot be used a second time.",
        "wrong-role": (
            "A valid signature from the wrong role cannot satisfy another role's approval."
        ),
        "expired-pcc": "Expired PCC objects cannot authorize execution.",
        "policy-mismatch": "A PCC signed under another policy digest is rejected.",
        "missing-role": "ApprovalSet verification fails when a required role is missing.",
        "tamper-receipt": "Changing a signed Receipt invalidates the Gateway signature.",
        "revalidation-upgrade": "Execution-time risk above approval risk requires reauthorization.",
        "revalidation-reject": "Physically unacceptable execution-time risk is rejected.",
    }
    return claims[scenario]


def collect_evidence(scenarios: list[str], evaluator: str) -> dict[str, Any]:
    cases = [collect_scenario(scenario, evaluator) for scenario in scenarios]
    return {
        "project": "CRAFT",
        "title": (
            "Consequence-aware Risk-Adaptive Framework for Trusted Execution "
            "of AI-Driven Power Grid Agents"
        ),
        "artifact_type": "security_protocol_evidence",
        "generated_at_unix": int(time.time()),
        "evaluator": evaluator,
        "scenarios": cases,
        "summary": {
            "scenario_count": len(cases),
            "passed_count": sum(1 for case in cases if case["passed"]),
            "failed_count": sum(1 for case in cases if not case["passed"]),
            "roles": [role.value for role in Role],
        },
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect CRAFT protocol scenario evidence for reports and Dashboard handoff.",
    )
    parser.add_argument(
        "--evaluator",
        choices=("mock", "grid2op"),
        default="mock",
        help="Consequence evaluator backend. grid2op requires local data/grid2op/l2rpn_2019.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=SCENARIOS,
        default=list(SCENARIOS),
        help="Scenarios to collect. Defaults to all security protocol scenarios.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "JSON evidence output path. Defaults to "
            "artifacts/protocol/security_protocol_evidence.json."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    output = args.output
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    bundle = collect_evidence(args.scenarios, args.evaluator)
    output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    passed_count = bundle["summary"]["passed_count"]
    scenario_count = bundle["summary"]["scenario_count"]
    print(f"Wrote {scenario_count} protocol evidence scenarios to {output}")
    print(f"Passed: {passed_count}/{scenario_count}")
    return 0 if passed_count == scenario_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
