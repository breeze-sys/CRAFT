import warnings
from dataclasses import dataclass
from typing import Any

import pytest

from craft.grid import (
    Grid2OpActionError,
    action_request_to_grid2op_action,
    action_request_to_grid2op_payload,
)
from craft.models import ActionRequest, ActionType, ActorIdentity, Role


@dataclass(frozen=True)
class FakeGrid2OpAction:
    payload: dict[str, object]


class FakeActionSpace:
    def __init__(self, *, warn_ignored: bool = False) -> None:
        self.warn_ignored = warn_ignored
        self.payloads: list[dict[str, object]] = []
        self.gen_redispatchable = (True, True, True)
        self.n_line = 8
        self.n_sub = 5

    def __call__(self, payload: dict[str, object]) -> FakeGrid2OpAction:
        self.payloads.append(payload)
        if self.warn_ignored:
            warnings.warn(
                'The key "redispatch" used to update an action will be ignored.',
                stacklevel=2,
            )
        return FakeGrid2OpAction(payload)


def make_action(action_type: ActionType, parameters: dict[str, Any]) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=action_type,
        parameters=parameters,
        nonce="grid2op-action-test",
    )


def test_redispatch_maps_strict_parameter_contract_to_grid2op_payload() -> None:
    action = make_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": -30.0})

    assert action_request_to_grid2op_payload(action) == {"redispatch": [(2, -30.0)]}


def test_line_status_actions_map_to_set_line_status() -> None:
    disconnect = make_action(ActionType.DISCONNECT_LINE, {"line_id": 3})
    reconnect = make_action(ActionType.RECONNECT_LINE, {"line_ids": [3, 7]})

    assert action_request_to_grid2op_payload(disconnect) == {"set_line_status": [(3, -1)]}
    assert action_request_to_grid2op_payload(reconnect) == {
        "set_line_status": [(3, 1), (7, 1)]
    }


def test_change_topology_maps_topology_vector_to_set_bus() -> None:
    action = make_action(
        ActionType.CHANGE_TOPOLOGY,
        {"substation_id": 4, "topology_vector": [1, 2, 1]},
    )

    assert action_request_to_grid2op_payload(action) == {
        "set_bus": {"substations_id": [(4, [1, 2, 1])]}
    }


@pytest.mark.parametrize(
    ("action_type", "parameters", "message"),
    (
        (ActionType.REDISPATCH, {"gen_id": 2}, "gen_id, delta_mw"),
        (ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": -30.0, "x": 1}, "Unsupported"),
        (ActionType.DISCONNECT_LINE, {"line_id": 1, "line_ids": [1, 2]}, "Ambiguous"),
        (ActionType.RECONNECT_LINE, {"line_ids": []}, "must not be empty"),
        (ActionType.CHANGE_TOPOLOGY, {"substation_id": 4}, "requires one of"),
        (
            ActionType.CHANGE_TOPOLOGY,
            {"substation_id": 4, "bus": 1, "set_bus": {"load_1": 2}},
            "ambiguous",
        ),
        (ActionType.SHED_LOAD, {"load_shed_mw": 5.0}, "Unsupported Grid2Op action type"),
    ),
)
def test_unsupported_or_ambiguous_parameters_raise_clear_errors(
    action_type: ActionType,
    parameters: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(Grid2OpActionError, match=message):
        action_request_to_grid2op_payload(make_action(action_type, parameters))


def test_grid2op_ignored_payload_warning_is_not_treated_as_noop() -> None:
    action_space = FakeActionSpace(warn_ignored=True)
    action = make_action(ActionType.REDISPATCH, {"gen_id": 2, "delta_mw": -30.0})

    with pytest.raises(Grid2OpActionError, match="ignored"):
        action_request_to_grid2op_action(action_space, action)

    assert action_space.payloads == [{"redispatch": [(2, -30.0)]}]


def test_non_redispatchable_generator_is_rejected_before_action_space_call() -> None:
    action_space = FakeActionSpace()
    action_space.gen_redispatchable = (False, True)
    action = make_action(ActionType.REDISPATCH, {"gen_id": 0, "delta_mw": 1.0})

    with pytest.raises(Grid2OpActionError, match="not redispatchable"):
        action_request_to_grid2op_action(action_space, action)

    assert action_space.payloads == []


def test_action_space_exception_is_wrapped_with_action_context() -> None:
    action = make_action(ActionType.DISCONNECT_LINE, {"line_id": 3})

    def failing_action_space(_payload: dict[str, object]) -> object:
        raise RuntimeError("backend refused payload")

    with pytest.raises(Grid2OpActionError, match="disconnect_line"):
        action_request_to_grid2op_action(failing_action_space, action)
