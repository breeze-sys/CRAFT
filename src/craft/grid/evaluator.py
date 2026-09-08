"""Grid2Op consequence metric extraction and evaluator adapters."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any

from craft.grid.consequence import ConsequenceEvaluationResult
from craft.grid.risk import evaluate_risk
from craft.models import ActionRequest, ActionType, ConsequenceMetrics, RiskLevel, SimulatorInfo
from craft.serialization import JsonValue, canonical_digest_hex

OVERLOAD_RATIO = 1.0

_FAILURE_INFO_KEYS = (
    "exception",
    "exceptions",
    "error",
    "errors",
    "diverging_powerflow",
    "is_illegal",
    "is_ambiguous",
    "simulation_failed",
)
_ISLANDING_INFO_KEYS = (
    "islanding",
    "is_islanding",
    "is_islanded",
    "has_islanding",
)
_LOAD_SHED_INFO_KEYS = (
    "load_shed_mw",
    "loadshed_mw",
    "load_shed",
    "load_cut_mw",
    "load_curtailment_mw",
)


@dataclass(frozen=True)
class Grid2OpStepResult:
    """Normalized output from a one-step Grid2Op simulation callback."""

    obs_before: Any
    obs_after: Any | None
    done: bool
    info: Mapping[str, Any] | None = None
    reward: float | None = None
    state_digest: str | None = None
    predicted_state_digest: str | None = None
    simulator: SimulatorInfo | None = None
    scenario_id: str | None = None


Grid2OpStepSimulator = Callable[[ActionRequest], Grid2OpStepResult]


class Grid2OpConsequenceEvaluator:
    """Adapter from a Grid2Op step simulator callback to CRAFT PCC input."""

    def __init__(
        self,
        *,
        simulate: Grid2OpStepSimulator,
        simulator: SimulatorInfo,
        scenario_id: str | None = None,
    ) -> None:
        self.simulate = simulate
        self.simulator = simulator
        self.scenario_id = scenario_id

    def evaluate(self, action: ActionRequest) -> ConsequenceEvaluationResult:
        step = self.simulate(action)
        metrics = extract_consequence_metrics(
            step.obs_before,
            step.obs_after,
            done=step.done,
            info=step.info,
            action_request=action,
        )
        risk_level = evaluate_consequence_risk(metrics)
        simulator = step.simulator or self.simulator
        scenario_id = step.scenario_id or self.scenario_id

        return ConsequenceEvaluationResult(
            action_digest=action.action_digest,
            state_digest=step.state_digest
            or observation_digest(
                step.obs_before,
                extra={
                    "kind": "grid2op-state-before",
                    "env_name": simulator.env_name,
                    "scenario_id": scenario_id,
                },
            ),
            predicted_state_digest=step.predicted_state_digest
            or observation_digest(
                step.obs_after,
                extra={
                    "kind": "grid2op-state-after",
                    "done": step.done,
                    "env_name": simulator.env_name,
                    "scenario_id": scenario_id,
                    "metrics_digest": metrics.digest(),
                    "risk_level": risk_level.value,
                },
            ),
            metrics=metrics,
            risk_level=risk_level,
            simulator=simulator,
            scenario_id=scenario_id,
            notes=("grid2op consequence evaluator adapter",),
        )


def extract_consequence_metrics(
    obs_before: Any,
    obs_after: Any | None,
    done: bool,
    info: Mapping[str, Any] | None,
    action_request: ActionRequest,
) -> ConsequenceMetrics:
    """Build CRAFT consequence metrics from a Grid2Op step result."""
    info_map = info or {}
    rho_before = _float_tuple(_get_attr(obs_before, "rho"))
    rho_after = _float_tuple(_get_attr(obs_after, "rho"))
    has_invalid_rho = _has_non_finite(rho_after)
    max_rho = _max_finite_or_zero(rho_after)

    converged = (
        obs_after is not None
        and not done
        and not has_invalid_rho
        and not _info_has_truthy_value(info_map, _FAILURE_INFO_KEYS)
    )

    return ConsequenceMetrics(
        max_line_loading_ratio=max_rho,
        new_overload_count=_new_overload_count(rho_before, rho_after),
        min_security_margin=1.0 - max_rho,
        converged=converged,
        islanding=_info_has_truthy_value(info_map, _ISLANDING_INFO_KEYS),
        load_shed_mw=_load_shed_mw(info_map, action_request),
        redispatch_mw=_redispatch_mw(action_request),
        disconnected_line_count=_disconnected_line_count(obs_before, obs_after, action_request),
        topology_changed_substations=_topology_changed_substations(
            obs_before,
            obs_after,
            action_request,
        ),
    )


def evaluate_consequence_risk(metrics: ConsequenceMetrics) -> RiskLevel:
    """Classify extracted consequence metrics with the default risk engine."""
    return evaluate_risk(metrics)


def observation_digest(
    observation: Any | None,
    *,
    extra: Mapping[str, JsonValue] | None = None,
) -> str:
    """Return a portable digest for the Grid2Op observation fields CRAFT uses."""
    payload = {
        "rho": _float_tuple(_get_attr(observation, "rho")),
        "line_status": _bool_tuple(_get_attr(observation, "line_status")),
        "topo_vect": _int_tuple(_get_attr(observation, "topo_vect")),
        "sub_info": _int_tuple(_get_attr(observation, "sub_info")),
        "gen_p": _float_tuple(_get_attr(observation, "gen_p")),
        "load_p": _float_tuple(_get_attr(observation, "load_p")),
        "extra": dict(extra or {}),
    }
    return canonical_digest_hex(payload)


def _get_attr(obj: Any | None, name: str) -> Any | None:
    if obj is None:
        return None
    return getattr(obj, name, None)


def _float_tuple(value: Any | None) -> tuple[float, ...]:
    if value is None:
        return ()
    try:
        return tuple(float(item) for item in value)
    except TypeError:
        return (float(value),)


def _int_tuple(value: Any | None) -> tuple[int, ...]:
    if value is None:
        return ()
    try:
        return tuple(int(item) for item in value)
    except TypeError:
        return (int(value),)


def _bool_tuple(value: Any | None) -> tuple[bool, ...]:
    if value is None:
        return ()
    try:
        return tuple(bool(item) for item in value)
    except TypeError:
        return (bool(value),)


def _has_non_finite(values: tuple[float, ...]) -> bool:
    return any(not math.isfinite(value) for value in values)


def _max_finite_or_zero(values: tuple[float, ...]) -> float:
    finite_values = tuple(value for value in values if math.isfinite(value))
    if not finite_values:
        return 0.0
    return max(0.0, max(finite_values))


def _new_overload_count(rho_before: tuple[float, ...], rho_after: tuple[float, ...]) -> int:
    return sum(
        1
        for before, after in zip_longest(rho_before, rho_after, fillvalue=0.0)
        if math.isfinite(after) and after > OVERLOAD_RATIO and before <= OVERLOAD_RATIO
    )


def _info_has_truthy_value(info: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        if key in info and _truthy_info_value(info[key]):
            return True
    return False


def _truthy_info_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, Mapping):
        return any(_truthy_info_value(item) for item in value.values())
    try:
        return any(_truthy_info_value(item) for item in value)
    except TypeError:
        return bool(value)


def _load_shed_mw(info: Mapping[str, Any], action_request: ActionRequest) -> float:
    for key in _LOAD_SHED_INFO_KEYS:
        if key in info:
            return max(0.0, _numeric_magnitude(info[key]))
    if action_request.action_type == ActionType.SHED_LOAD:
        return _first_parameter_magnitude(
            action_request,
            ("load_shed_mw", "amount_mw", "delta_mw", "mw"),
        )
    return 0.0


def _redispatch_mw(action_request: ActionRequest) -> float:
    if action_request.action_type != ActionType.REDISPATCH:
        return 0.0
    explicit_value = _first_parameter_magnitude(
        action_request,
        ("redispatch_mw", "delta_mw", "amount_mw", "mw", "delta"),
    )
    if explicit_value > 0:
        return explicit_value
    return _numeric_magnitude(action_request.parameters.get("redispatch"))


def _first_parameter_magnitude(action_request: ActionRequest, keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in action_request.parameters:
            return _numeric_magnitude(action_request.parameters[key])
    return 0.0


def _numeric_magnitude(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return abs(float(value)) if math.isfinite(float(value)) else float("inf")
    if isinstance(value, Mapping):
        return sum(_numeric_magnitude(item) for item in value.values())
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return 0.0
        return abs(parsed) if math.isfinite(parsed) else float("inf")
    try:
        return sum(_numeric_magnitude(item) for item in value)
    except TypeError:
        return 0.0


def _disconnected_line_count(
    obs_before: Any,
    obs_after: Any | None,
    action_request: ActionRequest,
) -> int:
    status_before = _bool_tuple(_get_attr(obs_before, "line_status"))
    status_after = _bool_tuple(_get_attr(obs_after, "line_status"))
    if status_before and status_after:
        return sum(
            1
            for before, after in zip_longest(status_before, status_after, fillvalue=True)
            if before and not after
        )
    if action_request.action_type == ActionType.DISCONNECT_LINE:
        return _target_count(action_request, singular_key="line_id", plural_key="line_ids")
    return 0


def _topology_changed_substations(
    obs_before: Any,
    obs_after: Any | None,
    action_request: ActionRequest,
) -> int:
    topo_before = _int_tuple(_get_attr(obs_before, "topo_vect"))
    topo_after = _int_tuple(_get_attr(obs_after, "topo_vect"))
    if topo_before and topo_after:
        sub_info = _int_tuple(_get_attr(obs_after, "sub_info")) or _int_tuple(
            _get_attr(obs_before, "sub_info")
        )
        if sub_info and sum(sub_info) == min(len(topo_before), len(topo_after)):
            return _changed_substation_count(topo_before, topo_after, sub_info)
        if topo_before != topo_after:
            return 1
    if action_request.action_type == ActionType.CHANGE_TOPOLOGY:
        return _target_count(
            action_request,
            singular_key="substation_id",
            plural_key="substation_ids",
        )
    return 0


def _changed_substation_count(
    topo_before: tuple[int, ...],
    topo_after: tuple[int, ...],
    sub_info: tuple[int, ...],
) -> int:
    start = 0
    changed = 0
    for width in sub_info:
        stop = start + width
        if topo_before[start:stop] != topo_after[start:stop]:
            changed += 1
        start = stop
    return changed


def _target_count(action_request: ActionRequest, *, singular_key: str, plural_key: str) -> int:
    parameters = action_request.parameters
    if plural_key in parameters:
        return int(_sequence_length(parameters[plural_key]))
    if singular_key in parameters:
        return 1
    return 0


def _sequence_length(value: Any) -> int:
    if value is None or isinstance(value, str | bytes):
        return 0
    try:
        return len(value)
    except TypeError:
        return 1
