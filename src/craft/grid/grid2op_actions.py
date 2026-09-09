"""Translate CRAFT action requests into Grid2Op actions."""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from craft.models import ActionRequest, ActionType

Grid2OpActionPayload = dict[str, object]
Grid2OpActionSpace = Callable[[Grid2OpActionPayload], Any]


class Grid2OpActionError(ValueError):
    """Raised when a CRAFT action cannot be safely translated for Grid2Op."""


def action_request_to_grid2op_payload(action_request: ActionRequest) -> Grid2OpActionPayload:
    """Return the Grid2Op action-space payload for a normalized CRAFT action."""
    if action_request.action_type == ActionType.NOOP:
        _reject_unknown_parameters(action_request, allowed=())
        return {}
    if action_request.action_type == ActionType.REDISPATCH:
        return _redispatch_payload(action_request)
    if action_request.action_type == ActionType.DISCONNECT_LINE:
        return _line_status_payload(action_request, connected=False)
    if action_request.action_type == ActionType.RECONNECT_LINE:
        return _line_status_payload(action_request, connected=True)
    if action_request.action_type == ActionType.CHANGE_TOPOLOGY:
        return _change_topology_payload(action_request)
    raise Grid2OpActionError(
        f"Unsupported Grid2Op action type: {action_request.action_type.value}."
    )


def action_request_to_grid2op_action(
    action_space: Grid2OpActionSpace,
    action_request: ActionRequest,
) -> Any:
    """Build a Grid2Op action and fail if Grid2Op reports ignored payload keys."""
    payload = action_request_to_grid2op_payload(action_request)
    _validate_against_action_space(action_space, action_request)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            grid2op_action = action_space(payload)
        except Exception as exc:
            raise Grid2OpActionError(
                f"Grid2Op rejected {action_request.action_type.value} payload {payload!r}: {exc}"
            ) from exc

    ignored_warnings = tuple(
        str(warning.message)
        for warning in caught
        if "ignored" in str(warning.message).lower()
    )
    if ignored_warnings:
        raise Grid2OpActionError(
            "Grid2Op ignored part of the requested action payload; refusing to "
            f"treat it as noop. Warnings: {'; '.join(ignored_warnings)}"
        )
    return grid2op_action


def _validate_against_action_space(
    action_space: Grid2OpActionSpace,
    action_request: ActionRequest,
) -> None:
    if action_request.action_type == ActionType.REDISPATCH:
        gen_id = _parse_non_negative_int(action_request.parameters["gen_id"], "gen_id")
        _validate_redispatchable_generator(action_space, gen_id)
    elif action_request.action_type in (ActionType.DISCONNECT_LINE, ActionType.RECONNECT_LINE):
        line_ids = _parse_exclusive_ids(
            action_request,
            singular_key="line_id",
            plural_key="line_ids",
        )
        _validate_id_upper_bound(action_space, line_ids, attr_name="n_line", field_name="line_id")
    elif action_request.action_type == ActionType.CHANGE_TOPOLOGY:
        substation_ids = _parse_exclusive_ids(
            action_request,
            singular_key="substation_id",
            plural_key="substation_ids",
        )
        _validate_id_upper_bound(
            action_space,
            substation_ids,
            attr_name="n_sub",
            field_name="substation_id",
        )


def _validate_redispatchable_generator(action_space: Grid2OpActionSpace, gen_id: int) -> None:
    gen_redispatchable = getattr(action_space, "gen_redispatchable", None)
    if gen_redispatchable is not None:
        flags = _bool_tuple(gen_redispatchable)
        if gen_id >= len(flags):
            raise Grid2OpActionError(f"gen_id {gen_id} is outside action_space generator range.")
        if not flags[gen_id]:
            raise Grid2OpActionError(f"gen_id {gen_id} is not redispatchable in this Grid2Op env.")
        return

    n_gen = _optional_non_negative_int_attr(action_space, "n_gen")
    if n_gen is not None and gen_id >= n_gen:
        raise Grid2OpActionError(f"gen_id {gen_id} is outside action_space generator range.")


def _validate_id_upper_bound(
    action_space: Grid2OpActionSpace,
    ids: tuple[int, ...],
    *,
    attr_name: str,
    field_name: str,
) -> None:
    upper_bound = _optional_non_negative_int_attr(action_space, attr_name)
    if upper_bound is None:
        return
    for item_id in ids:
        if item_id >= upper_bound:
            raise Grid2OpActionError(
                f"{field_name} {item_id} is outside action_space range 0..{upper_bound - 1}."
            )


def _redispatch_payload(action_request: ActionRequest) -> Grid2OpActionPayload:
    _reject_unknown_parameters(action_request, allowed=("gen_id", "delta_mw"))
    parameters = action_request.parameters
    if "gen_id" not in parameters or "delta_mw" not in parameters:
        raise Grid2OpActionError("redispatch requires parameters: gen_id, delta_mw.")

    gen_id = _parse_non_negative_int(parameters["gen_id"], "gen_id")
    delta_mw = _parse_finite_float(parameters["delta_mw"], "delta_mw")
    return {"redispatch": [(gen_id, delta_mw)]}


def _line_status_payload(
    action_request: ActionRequest,
    *,
    connected: bool,
) -> Grid2OpActionPayload:
    _reject_unknown_parameters(action_request, allowed=("line_id", "line_ids"))
    line_ids = _parse_exclusive_ids(
        action_request,
        singular_key="line_id",
        plural_key="line_ids",
    )
    status = 1 if connected else -1
    return {"set_line_status": [(line_id, status) for line_id in line_ids]}


def _change_topology_payload(action_request: ActionRequest) -> Grid2OpActionPayload:
    _reject_unknown_parameters(
        action_request,
        allowed=("substation_id", "substation_ids", "topology_vector", "bus", "set_bus"),
    )
    substation_ids = _parse_exclusive_ids(
        action_request,
        singular_key="substation_id",
        plural_key="substation_ids",
    )
    topology_keys = tuple(
        key
        for key in ("topology_vector", "bus", "set_bus")
        if key in action_request.parameters
    )
    if not topology_keys:
        raise Grid2OpActionError(
            "change_topology requires one of: topology_vector, bus, set_bus."
        )
    if len(topology_keys) > 1:
        raise Grid2OpActionError(
            "change_topology parameters are ambiguous; provide only one of "
            "topology_vector, bus, set_bus."
        )

    topology_key = topology_keys[0]
    topology_value = action_request.parameters[topology_key]
    substations_id: list[tuple[int, object]]
    if topology_key == "topology_vector":
        substations_id = _topology_vector_entries(substation_ids, topology_value)
    elif topology_key == "bus":
        if len(substation_ids) != 1:
            raise Grid2OpActionError("change_topology bus requires a single substation_id.")
        substations_id = [(substation_ids[0], _parse_non_negative_int(topology_value, "bus"))]
    else:
        substations_id = _set_bus_entries(substation_ids, topology_value)

    return {"set_bus": {"substations_id": substations_id}}


def _topology_vector_entries(
    substation_ids: tuple[int, ...],
    value: object,
) -> list[tuple[int, object]]:
    if len(substation_ids) == 1:
        return [(substation_ids[0], _parse_int_vector(value, "topology_vector"))]
    if not isinstance(value, Mapping):
        raise Grid2OpActionError(
            "change_topology with multiple substation_ids requires topology_vector "
            "to map each substation id to a vector."
        )
    return [
        (
            substation_id,
            _parse_int_vector(_mapping_lookup(value, substation_id), "topology_vector"),
        )
        for substation_id in substation_ids
    ]


def _set_bus_entries(
    substation_ids: tuple[int, ...],
    value: object,
) -> list[tuple[int, object]]:
    if len(substation_ids) == 1:
        return [(substation_ids[0], value)]
    if not isinstance(value, Mapping):
        raise Grid2OpActionError(
            "change_topology with multiple substation_ids requires set_bus to map "
            "each substation id to its bus assignment."
        )
    return [
        (substation_id, _mapping_lookup(value, substation_id))
        for substation_id in substation_ids
    ]


def _mapping_lookup(mapping: Mapping[object, object], key: int) -> object:
    if key in mapping:
        return mapping[key]
    text_key = str(key)
    if text_key in mapping:
        return mapping[text_key]
    raise Grid2OpActionError(f"Missing topology assignment for substation id {key}.")


def _parse_exclusive_ids(
    action_request: ActionRequest,
    *,
    singular_key: str,
    plural_key: str,
) -> tuple[int, ...]:
    parameters = action_request.parameters
    has_singular = singular_key in parameters
    has_plural = plural_key in parameters
    if has_singular and has_plural:
        raise Grid2OpActionError(
            f"Ambiguous parameters: provide either {singular_key} or {plural_key}, not both."
        )
    if has_singular:
        return (_parse_non_negative_int(parameters[singular_key], singular_key),)
    if has_plural:
        return _parse_id_sequence(parameters[plural_key], plural_key)
    raise Grid2OpActionError(f"Missing required parameter: {singular_key} or {plural_key}.")


def _parse_id_sequence(value: object, field_name: str) -> tuple[int, ...]:
    if isinstance(value, bool | int | str | bytes) or value is None:
        raise Grid2OpActionError(f"{field_name} must be a non-empty list of integer ids.")
    if not isinstance(value, Sequence):
        raise Grid2OpActionError(f"{field_name} must be a non-empty list of integer ids.")
    parsed = tuple(_parse_non_negative_int(item, field_name) for item in value)
    if not parsed:
        raise Grid2OpActionError(f"{field_name} must not be empty.")
    if len(parsed) != len(set(parsed)):
        raise Grid2OpActionError(f"{field_name} must not contain duplicate ids.")
    return parsed


def _parse_int_vector(value: object, field_name: str) -> list[int]:
    if isinstance(value, bool | int | str | bytes) or value is None:
        raise Grid2OpActionError(f"{field_name} must be a non-empty list of integers.")
    if not isinstance(value, Sequence):
        raise Grid2OpActionError(f"{field_name} must be a non-empty list of integers.")
    parsed = [_parse_int(item, field_name) for item in value]
    if not parsed:
        raise Grid2OpActionError(f"{field_name} must not be empty.")
    return parsed


def _parse_non_negative_int(value: object, field_name: str) -> int:
    parsed = _parse_int(value, field_name)
    if parsed < 0:
        raise Grid2OpActionError(f"{field_name} must be non-negative.")
    return parsed


def _parse_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Grid2OpActionError(f"{field_name} must be an integer.")
    return value


def _parse_finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise Grid2OpActionError(f"{field_name} must be a finite number.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise Grid2OpActionError(f"{field_name} must be finite.")
    return parsed


def _bool_tuple(value: object) -> tuple[bool, ...]:
    try:
        return tuple(bool(item) for item in cast(Any, value))
    except TypeError:
        return (bool(value),)


def _optional_non_negative_int_attr(obj: object, attr_name: str) -> int | None:
    value = getattr(obj, attr_name, None)
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _reject_unknown_parameters(action_request: ActionRequest, *, allowed: tuple[str, ...]) -> None:
    allowed_set = set(allowed)
    unknown = sorted(key for key in action_request.parameters if key not in allowed_set)
    if unknown:
        raise Grid2OpActionError(
            f"Unsupported parameters for {action_request.action_type.value}: {', '.join(unknown)}."
        )
