# ruff: noqa: E402
"""Run Member 2 real Grid2Op report experiments.

The script is intentionally explicit and opt-in: it uses the local l2rpn_2019
dataset, scans real Grid2Op states, and feeds the existing CRAFT grid/security
pipeline without adding a real-data dependency to pytest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from craft.grid import (
    CRAFT_GRID2OP_METADATA_KEY,
    ConsequenceEvaluationResult,
    Grid2OpConsequenceEvaluator,
    Grid2OpSimulationError,
    Grid2OpSimulator,
    Grid2OpSimulatorConfig,
    Grid2OpStepResult,
    make_grid2op_env,
    simulator_info_from_env,
)
from craft.grid2op_datasets import DEFAULT_NON_TEST_DATASET, get_grid2op_data_dir
from craft.models import (
    ActionRequest,
    ActionType,
    ActorIdentity,
    RiskLevel,
    Role,
    SimulatorInfo,
)
from craft.security import (
    DEFAULT_RISK_POLICY,
    CertifiedAction,
    ExecutedAction,
    SecurityProtocol,
    TicketedAction,
    create_demo_security_protocol,
)

DEFAULT_EXP1_DELTA_MW = 1.0
DEFAULT_EXP2_DELTA_MW = 20.0
DEFAULT_SCAN_STEPS = 260
REPORT_CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class CapturingSimulation:
    simulator: Grid2OpSimulator
    last_step: Grid2OpStepResult | None = None

    def __call__(self, action: ActionRequest) -> Grid2OpStepResult:
        step = self.simulator.simulate(action)
        self.last_step = step
        return step


@dataclass(frozen=True)
class StaticConsequenceEvaluator:
    evaluation: ConsequenceEvaluationResult

    def evaluate(self, action: ActionRequest) -> ConsequenceEvaluationResult:
        self.evaluation.ensure_matches_action(action)
        return self.evaluation


@dataclass(frozen=True)
class ReportEvaluation:
    evaluation: ConsequenceEvaluationResult
    step: Grid2OpStepResult
    timestep: int | None
    predicted_timestep: int | None
    episode: str | None

    @property
    def risk_level(self) -> RiskLevel:
        return self.evaluation.risk_level

    @property
    def simulator(self) -> SimulatorInfo:
        return self.evaluation.simulator


@dataclass(frozen=True)
class AuthorizationBundle:
    protocol: SecurityProtocol
    certified: CertifiedAction
    ticketed: TicketedAction


def _create_redispatch_action(
    *,
    gen_id: int,
    delta_mw: float,
    nonce_suffix: str,
) -> ActionRequest:
    return ActionRequest(
        action_id=f"member2-grid2op-{nonce_suffix}-redispatch",
        requested_by=ActorIdentity(
            subject_id="member2-report-agent",
            role=Role.AGENT,
            display_name="Member 2 report experiment",
        ),
        action_type=ActionType.REDISPATCH,
        parameters={"gen_id": gen_id, "delta_mw": delta_mw},
        nonce=f"member2-grid2op-{nonce_suffix}-gen{gen_id}-delta{delta_mw:g}",
        created_at=REPORT_CREATED_AT,
        justification="Member 2 report experiment using real Grid2Op simulation.",
    )


def _first_redispatchable_generator(env: Any) -> int:
    flags = getattr(getattr(env, "action_space", None), "gen_redispatchable", None)
    if flags is None:
        flags = getattr(env, "gen_redispatchable", None)
    if flags is None:
        raise RuntimeError("Grid2Op env does not expose redispatchable generator metadata.")

    for gen_id, can_redispatch in enumerate(flags):
        if bool(can_redispatch):
            return gen_id
    raise RuntimeError("Grid2Op env has no redispatchable generator for redispatch experiments.")


def _evaluate_current_state(
    env: Any,
    *,
    env_name: str,
    action: ActionRequest,
) -> ReportEvaluation:
    simulator = Grid2OpSimulator(
        env=env,
        config=Grid2OpSimulatorConfig(env_name=env_name, test=False),
    )
    capture = CapturingSimulation(simulator)
    evaluator = Grid2OpConsequenceEvaluator(
        simulate=capture,
        simulator=simulator_info_from_env(env, requested_env_name=env_name, test_mode=False),
    )
    evaluation = evaluator.evaluate(action)
    if capture.last_step is None:
        raise RuntimeError("Grid2Op evaluator did not return a captured simulation step.")

    state_metadata, predicted_metadata = _metadata_from_step(capture.last_step)
    return ReportEvaluation(
        evaluation=evaluation,
        step=capture.last_step,
        timestep=_int_or_none(state_metadata.get("timestep")),
        predicted_timestep=_int_or_none(predicted_metadata.get("timestep")),
        episode=_episode_from_step(capture.last_step),
    )


def _scan_for_risks(
    *,
    env_name: str,
    action: ActionRequest,
    target_risks: Sequence[RiskLevel],
    max_steps: int,
) -> dict[RiskLevel, ReportEvaluation]:
    wanted = tuple(target_risks)
    found: dict[RiskLevel, ReportEvaluation] = {}
    env = make_grid2op_env(env_name, test=False)
    try:
        env.reset()
        for _step_index in range(max_steps + 1):
            record = _evaluate_current_state(env, env_name=env_name, action=action)
            if record.risk_level in wanted and record.risk_level not in found:
                found[record.risk_level] = record
                if all(risk in found for risk in wanted):
                    return found

            obs_after, _reward, done, _info = env.step(env.action_space({}))
            if bool(done):
                break
            if obs_after is None:
                break
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()

    missing = ", ".join(risk.value for risk in wanted if risk not in found)
    seen = ", ".join(risk.value for risk in found) or "none"
    raise RuntimeError(
        f"Unable to find required Grid2Op risk states within {max_steps} noop steps. "
        f"Missing: {missing}. Seen: {seen}."
    )


def _certify_evaluation(action: ActionRequest, record: ReportEvaluation) -> AuthorizationBundle:
    protocol = create_demo_security_protocol(
        evaluator=StaticConsequenceEvaluator(record.evaluation),
    )
    certified = protocol.certify_action(action)
    authorized = protocol.approve_action(certified)
    ticketed = protocol.issue_ticket(authorized)
    return AuthorizationBundle(protocol=protocol, certified=certified, ticketed=ticketed)


def _consume_with_execution_metrics(
    *,
    approval: AuthorizationBundle,
    execution_record: ReportEvaluation,
) -> ExecutedAction:
    return approval.protocol.consume_ticket_and_issue_receipt(
        approval.ticketed,
        execution_state_digest=execution_record.evaluation.state_digest,
        execution_metrics=execution_record.evaluation.metrics,
        result_state_digest=execution_record.evaluation.predicted_state_digest,
        success=not execution_record.step.done,
        reward=execution_record.step.reward,
        done=execution_record.step.done,
    )


def _print_header(
    *,
    run_command: str,
    env_name: str,
    dataset_path: Path,
    gen_id: int,
    max_scan_steps: int,
) -> None:
    print("CRAFT Member 2 Real Grid2Op Report Experiments")
    print("=" * 52)
    print(f"Run command: {run_command}")
    print(f"Dataset/env: {env_name} ({dataset_path})")
    print(f"Redispatch generator: gen_id={gen_id}")
    print(f"State selection: scan reset episode with noop for up to {max_scan_steps} steps")
    print()


def _print_experiment_context(
    *,
    title: str,
    run_command: str,
    env_name: str,
    dataset_path: Path,
    sample: ReportEvaluation,
) -> None:
    print(title)
    print("-" * len(title))
    print(f"Run command: {run_command}")
    print(f"Dataset/env: {env_name} ({dataset_path})")
    print(f"Grid2Op version: {sample.simulator.version}")
    print(f"Backend: {sample.simulator.backend or 'unknown'}")


def _print_evaluation_block(
    label: str,
    *,
    action: ActionRequest,
    record: ReportEvaluation,
    certified: CertifiedAction,
    revalidation: ExecutedAction | None = None,
) -> None:
    metrics = record.evaluation.metrics
    required_roles = DEFAULT_RISK_POLICY.required_roles_for(record.risk_level)
    revalidation_text = "not_applicable"
    if revalidation is not None:
        decision = (
            revalidation.revalidation.decision.value
            if revalidation.revalidation is not None
            else "not_run"
        )
        revalidation_text = (
            f"{revalidation.ticket_consumption.code.value} / decision={decision} / "
            f"valid={str(revalidation.ticket_consumption.valid).lower()}"
        )

    print(f"\n{label}")
    print(f"  episode/timestep: {_display(record.episode)} / {record.timestep}")
    print(f"  predicted timestep: {record.predicted_timestep}")
    print(f"  action type: {action.action_type.value}")
    print(f"  action parameters: {_json(action.parameters)}")
    print(f"  max rho: {metrics.max_line_loading_ratio:.4f}")
    print(f"  new overload count: {metrics.new_overload_count}")
    print(f"  security margin: {metrics.min_security_margin:.4f}")
    print(f"  converged: {str(metrics.converged).lower()}")
    print(
        "  islanding/load_shed: "
        f"{str(metrics.islanding).lower()} / {metrics.load_shed_mw:.4f} MW"
    )
    print(
        "  redispatch/topology changes: "
        f"{metrics.redispatch_mw:.4f} MW / {metrics.topology_changed_substations} substations"
    )
    print(f"  disconnected lines: {metrics.disconnected_line_count}")
    print(f"  RiskLevel: {record.risk_level.value}")
    print(f"  required roles: {_roles(required_roles)}")
    print(f"  action digest: {action.action_digest}")
    print(f"  PCC digest: {certified.pcc.certificate_digest()}")
    print(f"  policy digest: {certified.pcc.policy_digest}")
    print(f"  state digest: {record.evaluation.state_digest}")
    print(f"  predicted state digest: {record.evaluation.predicted_state_digest}")
    print(f"  revalidation code/decision: {revalidation_text}")


def _run_experiments(args: argparse.Namespace, *, run_command: str) -> int:
    dataset_path = get_grid2op_data_dir() / args.env_name
    probe_env = make_grid2op_env(args.env_name, test=False)
    try:
        gen_id = args.gen_id if args.gen_id is not None else _first_redispatchable_generator(
            probe_env
        )
    finally:
        close = getattr(probe_env, "close", None)
        if callable(close):
            close()

    _print_header(
        run_command=run_command,
        env_name=args.env_name,
        dataset_path=dataset_path,
        gen_id=gen_id,
        max_scan_steps=args.max_scan_steps,
    )

    exp1_action = _create_redispatch_action(
        gen_id=gen_id,
        delta_mw=args.exp1_delta_mw,
        nonce_suffix="experiment1",
    )
    exp1_records = _scan_for_risks(
        env_name=args.env_name,
        action=exp1_action,
        target_risks=(RiskLevel.L1, RiskLevel.L2),
        max_steps=args.max_scan_steps,
    )
    exp1_l1 = exp1_records[RiskLevel.L1]
    exp1_l2 = exp1_records[RiskLevel.L2]
    exp1_l1_auth = _certify_evaluation(exp1_action, exp1_l1)
    exp1_l2_auth = _certify_evaluation(exp1_action, exp1_l2)

    _print_experiment_context(
        title="Experiment 1: same ActionRequest, different Grid2Op states",
        run_command=run_command,
        env_name=args.env_name,
        dataset_path=dataset_path,
        sample=exp1_l1,
    )
    _print_evaluation_block(
        "State A",
        action=exp1_action,
        record=exp1_l1,
        certified=exp1_l1_auth.certified,
    )
    _print_evaluation_block(
        "State B",
        action=exp1_action,
        record=exp1_l2,
        certified=exp1_l2_auth.certified,
    )

    exp2_action = _create_redispatch_action(
        gen_id=gen_id,
        delta_mw=args.exp2_delta_mw,
        nonce_suffix="experiment2",
    )
    exp2_records = _scan_for_risks(
        env_name=args.env_name,
        action=exp2_action,
        target_risks=(RiskLevel.L2, RiskLevel.L3, RiskLevel.REJECT),
        max_steps=args.max_scan_steps,
    )
    approval_l2 = exp2_records[RiskLevel.L2]
    execution_l3 = exp2_records[RiskLevel.L3]
    execution_reject = exp2_records[RiskLevel.REJECT]
    approval_auth = _certify_evaluation(exp2_action, approval_l2)
    revalidation_required = _consume_with_execution_metrics(
        approval=approval_auth,
        execution_record=execution_l3,
    )
    revalidation_rejected = _consume_with_execution_metrics(
        approval=approval_auth,
        execution_record=execution_reject,
    )

    _print_experiment_context(
        title="Experiment 2: L2 approval, execution-time revalidation blocks",
        run_command=run_command,
        env_name=args.env_name,
        dataset_path=dataset_path,
        sample=approval_l2,
    )
    _print_evaluation_block(
        "Approval-time PCC",
        action=exp2_action,
        record=approval_l2,
        certified=approval_auth.certified,
    )
    _print_evaluation_block(
        "Execution-time L3 -> revalidation_required",
        action=exp2_action,
        record=execution_l3,
        certified=approval_auth.certified,
        revalidation=revalidation_required,
    )
    _print_evaluation_block(
        "Execution-time REJECT -> revalidation_rejected",
        action=exp2_action,
        record=execution_reject,
        certified=approval_auth.certified,
        revalidation=revalidation_rejected,
    )

    required_ok = (
        revalidation_required.ticket_consumption.code.value == "revalidation_required"
        and revalidation_rejected.ticket_consumption.code.value == "revalidation_rejected"
    )
    print()
    print(f"Expected revalidation codes observed: {str(required_ok).lower()}")
    return 0 if required_ok else 1


def _metadata_from_step(
    step: Grid2OpStepResult,
) -> tuple[dict[str, Any], dict[str, Any]]:
    info = step.info or {}
    metadata = info.get(CRAFT_GRID2OP_METADATA_KEY)
    if not isinstance(metadata, dict):
        return {}, {}
    state = metadata.get("state")
    predicted_state = metadata.get("predicted_state")
    return (
        dict(state) if isinstance(state, dict) else {},
        dict(predicted_state) if isinstance(predicted_state, dict) else {},
    )


def _episode_from_step(step: Grid2OpStepResult) -> str | None:
    info = step.info or {}
    time_series_id = info.get("time_series_id")
    if time_series_id is not None:
        return Path(str(time_series_id)).name
    if step.scenario_id is not None:
        return Path(str(step.scenario_id)).name
    return None


def _roles(roles: Sequence[Role]) -> str:
    if not roles:
        return "none"
    return ", ".join(role.value for role in roles)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _display(value: object | None) -> str:
    return "unknown" if value is None else str(value)


def _int_or_none(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Grid2Op report experiments for Member 2.",
    )
    parser.add_argument(
        "--env-name",
        default=DEFAULT_NON_TEST_DATASET,
        help="Grid2Op dataset/env name. Defaults to l2rpn_2019.",
    )
    parser.add_argument(
        "--gen-id",
        type=int,
        default=None,
        help="Redispatchable generator id. Defaults to the first redispatchable generator.",
    )
    parser.add_argument(
        "--exp1-delta-mw",
        type=float,
        default=DEFAULT_EXP1_DELTA_MW,
        help="Redispatch delta for experiment 1.",
    )
    parser.add_argument(
        "--exp2-delta-mw",
        type=float,
        default=DEFAULT_EXP2_DELTA_MW,
        help="Redispatch delta for experiment 2.",
    )
    parser.add_argument(
        "--max-scan-steps",
        type=int,
        default=DEFAULT_SCAN_STEPS,
        help="Maximum noop-advanced timesteps to scan for report states.",
    )
    return parser.parse_args(list(argv))


def _run_command(argv: Sequence[str]) -> str:
    script = Path(__file__).relative_to(REPO_ROOT)
    args = " ".join(argv)
    return f"python {script}{(' ' + args) if args else ''}"


def main(argv: Sequence[str] | None = None) -> int:
    parsed_argv = tuple(sys.argv[1:] if argv is None else argv)
    args = _parse_args(parsed_argv)
    try:
        return _run_experiments(args, run_command=_run_command(parsed_argv))
    except Grid2OpSimulationError as exc:
        print(f"Grid2Op simulation setup failed: {exc}", file=sys.stderr)
        print(
            "Run `make download-grid-data` before this explicit real-data report script.",
            file=sys.stderr,
        )
        return 2
    except RuntimeError as exc:
        print(f"Member 2 Grid2Op report experiment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
