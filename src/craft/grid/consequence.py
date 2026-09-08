"""Consequence evaluation contract shared by grid and security modules."""

from __future__ import annotations

from typing import Protocol

from craft.models import (
    ActionRequest,
    ActionType,
    ConsequenceMetrics,
    CRAFTModel,
    HexDigest,
    RiskLevel,
    SimulatorInfo,
)
from craft.serialization import JsonValue, canonical_digest_hex


class ConsequenceEvaluationResult(CRAFTModel):
    """Member B output consumed by Member A when issuing a PCC."""

    action_digest: HexDigest
    state_digest: HexDigest
    predicted_state_digest: HexDigest
    metrics: ConsequenceMetrics
    risk_level: RiskLevel
    simulator: SimulatorInfo
    scenario_id: str | None = None
    notes: tuple[str, ...] = ()

    def ensure_matches_action(self, action: ActionRequest) -> None:
        if self.action_digest != action.action_digest:
            raise ValueError("Consequence result action digest does not match ActionRequest.")

    def pcc_fields(self) -> dict[str, JsonValue]:
        return {
            "state_digest": self.state_digest,
            "predicted_state_digest": self.predicted_state_digest,
            "metrics": self.metrics.model_dump(mode="json"),
            "risk_level": self.risk_level.value,
            "simulator": self.simulator.model_dump(mode="json"),
        }


class ConsequenceEvaluator(Protocol):
    """Protocol implemented by mock and real Grid2Op evaluators."""

    def evaluate(self, action: ActionRequest) -> ConsequenceEvaluationResult:
        """Return consequence metrics and risk for an already-normalized action."""


class MockConsequenceEvaluator:
    """Deterministic evaluator used before the real Grid2Op implementation lands."""

    def __init__(
        self,
        *,
        simulator: SimulatorInfo | None = None,
        scenario_id: str = "mock-grid-l2",
        forced_risk_level: RiskLevel | None = None,
    ) -> None:
        self.simulator = simulator or SimulatorInfo(
            env_name="l2rpn_2019",
            version="mock",
            backend="mock",
            test_mode=False,
            n_sub=14,
            n_line=20,
            n_gen=5,
            n_load=11,
        )
        self.scenario_id = scenario_id
        self.forced_risk_level = forced_risk_level

    def evaluate(self, action: ActionRequest) -> ConsequenceEvaluationResult:
        risk_level = self.forced_risk_level or _risk_level_for_action(action)
        metrics = _metrics_for_action(action, risk_level)
        state_digest = canonical_digest_hex(
            {
                "kind": "mock-grid-state",
                "scenario_id": self.scenario_id,
                "env_name": self.simulator.env_name,
            }
        )
        predicted_state_digest = canonical_digest_hex(
            {
                "kind": "mock-predicted-grid-state",
                "scenario_id": self.scenario_id,
                "action_digest": action.action_digest,
                "metrics_digest": metrics.digest(),
                "risk_level": risk_level.value,
            }
        )
        return ConsequenceEvaluationResult(
            action_digest=action.action_digest,
            state_digest=state_digest,
            predicted_state_digest=predicted_state_digest,
            metrics=metrics,
            risk_level=risk_level,
            simulator=self.simulator,
            scenario_id=self.scenario_id,
            notes=("mock consequence evaluator; replace with Grid2Op evaluator",),
        )


def _risk_level_for_action(action: ActionRequest) -> RiskLevel:
    if action.action_type == ActionType.NOOP:
        return RiskLevel.L1
    if action.action_type == ActionType.REDISPATCH:
        delta_mw = _non_negative_float(action.parameters.get("delta_mw", 0.0))
        if delta_mw <= 10.0:
            return RiskLevel.L1
        if delta_mw <= 30.0:
            return RiskLevel.L2
        if delta_mw <= 60.0:
            return RiskLevel.L3
        return RiskLevel.REJECT
    if action.action_type == ActionType.RECONNECT_LINE:
        return RiskLevel.L2
    if action.action_type in (ActionType.DISCONNECT_LINE, ActionType.CHANGE_TOPOLOGY):
        return RiskLevel.L3
    if action.action_type == ActionType.SHED_LOAD:
        return RiskLevel.REJECT
    return RiskLevel.REJECT


def _metrics_for_action(action: ActionRequest, risk_level: RiskLevel) -> ConsequenceMetrics:
    redispatch_mw = _non_negative_float(action.parameters.get("delta_mw", 0.0))
    load_shed_mw = _non_negative_float(action.parameters.get("load_shed_mw", 0.0))
    disconnected_line_count = 1 if action.action_type == ActionType.DISCONNECT_LINE else 0
    topology_changed_substations = 1 if action.action_type == ActionType.CHANGE_TOPOLOGY else 0

    risk_shape = {
        RiskLevel.L1: {"max_rho": 0.78, "margin": 0.22, "new_overloads": 0, "converged": True},
        RiskLevel.L2: {"max_rho": 0.92, "margin": 0.08, "new_overloads": 0, "converged": True},
        RiskLevel.L3: {"max_rho": 0.99, "margin": 0.01, "new_overloads": 0, "converged": True},
        RiskLevel.REJECT: {
            "max_rho": 1.18,
            "margin": -0.18,
            "new_overloads": 1,
            "converged": True,
        },
    }[risk_level]

    return ConsequenceMetrics(
        max_line_loading_ratio=float(risk_shape["max_rho"]),
        new_overload_count=int(risk_shape["new_overloads"]),
        min_security_margin=float(risk_shape["margin"]),
        converged=bool(risk_shape["converged"]),
        islanding=False,
        load_shed_mw=load_shed_mw if action.action_type == ActionType.SHED_LOAD else 0.0,
        redispatch_mw=redispatch_mw if action.action_type == ActionType.REDISPATCH else 0.0,
        disconnected_line_count=disconnected_line_count,
        topology_changed_substations=topology_changed_substations,
    )


def _non_negative_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        return max(abs(float(value)), 0.0)
    except (TypeError, ValueError):
        return 0.0
