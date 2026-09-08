from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from craft.grid2op_evaluator import evaluate_consequence_risk, extract_consequence_metrics
from craft.models import ActionRequest, ActionType, ActorIdentity, RiskLevel, Role


@dataclass(frozen=True)
class FakeObservation:
    rho: Sequence[float]
    line_status: Sequence[bool] = ()
    topo_vect: Sequence[int] = ()
    sub_info: Sequence[int] = ()


def make_action(
    action_type: ActionType = ActionType.NOOP,
    parameters: dict[str, object] | None = None,
) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=action_type,
        parameters=parameters or {},
        nonce="test-nonce",
    )


def test_noop_metrics_extract_line_loading_and_new_overloads() -> None:
    obs_before = FakeObservation(rho=(0.50, 0.99, 1.05))
    obs_after = FakeObservation(rho=(0.70, 1.01, 1.04))

    metrics = extract_consequence_metrics(
        obs_before,
        obs_after,
        done=False,
        info={},
        action_request=make_action(),
    )

    assert metrics.max_line_loading_ratio == pytest.approx(1.04)
    assert metrics.new_overload_count == 1
    assert metrics.min_security_margin == pytest.approx(-0.04)
    assert metrics.converged
    assert not metrics.islanding
    assert metrics.load_shed_mw == 0
    assert metrics.redispatch_mw == 0
    assert metrics.disconnected_line_count == 0
    assert metrics.topology_changed_substations == 0


def test_redispatch_metrics_extract_absolute_mw_and_risk_level() -> None:
    obs_before = FakeObservation(rho=(0.40, 0.50))
    obs_after = FakeObservation(rho=(0.42, 0.51))
    action_request = make_action(
        ActionType.REDISPATCH,
        {"gen_id": 2, "delta_mw": -30.0},
    )

    metrics = extract_consequence_metrics(
        obs_before,
        obs_after,
        done=False,
        info={},
        action_request=action_request,
    )

    assert metrics.redispatch_mw == pytest.approx(30.0)
    assert evaluate_consequence_risk(metrics) == RiskLevel.L2


def test_light_line_overload_is_l3_not_reject() -> None:
    obs_before = FakeObservation(rho=(0.99,))
    obs_after = FakeObservation(rho=(1.0094,))

    metrics = extract_consequence_metrics(
        obs_before,
        obs_after,
        done=False,
        info={},
        action_request=make_action(),
    )

    assert metrics.max_line_loading_ratio == pytest.approx(1.0094)
    assert metrics.new_overload_count == 1
    assert evaluate_consequence_risk(metrics) == RiskLevel.L3


@pytest.mark.parametrize(
    ("done", "info"),
    (
        (True, {}),
        (False, {"exception": ["DivergingPowerFlow"]}),
    ),
)
def test_simulation_failure_marks_metrics_not_converged(
    done: bool,
    info: dict[str, object],
) -> None:
    metrics = extract_consequence_metrics(
        FakeObservation(rho=(0.40,)),
        FakeObservation(rho=(0.41,)),
        done=done,
        info=info,
        action_request=make_action(),
    )

    assert not metrics.converged
    assert evaluate_consequence_risk(metrics) == RiskLevel.REJECT


def test_islanding_and_load_shed_are_extracted_from_info() -> None:
    metrics = extract_consequence_metrics(
        FakeObservation(rho=(0.40,)),
        FakeObservation(rho=(0.41,)),
        done=False,
        info={"islanding": True, "load_shed_mw": 5.5},
        action_request=make_action(),
    )

    assert metrics.islanding
    assert metrics.load_shed_mw == pytest.approx(5.5)
    assert evaluate_consequence_risk(metrics) == RiskLevel.REJECT


def test_line_disconnect_and_topology_changes_are_extracted_from_observations() -> None:
    obs_before = FakeObservation(
        rho=(0.40, 0.50, 0.60),
        line_status=(True, True, False),
        topo_vect=(1, 1, 1, 1, 1),
        sub_info=(2, 2, 1),
    )
    obs_after = FakeObservation(
        rho=(0.42, 0.51, 0.62),
        line_status=(False, True, False),
        topo_vect=(2, 1, 1, 2, 1),
        sub_info=(2, 2, 1),
    )

    metrics = extract_consequence_metrics(
        obs_before,
        obs_after,
        done=False,
        info={},
        action_request=make_action(),
    )

    assert metrics.disconnected_line_count == 1
    assert metrics.topology_changed_substations == 2
    assert evaluate_consequence_risk(metrics) == RiskLevel.L3
