"""Real Grid2Op simulation callback for the CRAFT consequence evaluator."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from typing import Any, cast

from craft.grid.evaluator import (
    Grid2OpConsequenceEvaluator,
    Grid2OpStepResult,
    observation_digest,
)
from craft.grid.grid2op_actions import action_request_to_grid2op_action
from craft.grid2op_datasets import (
    DEFAULT_NON_TEST_DATASET,
    apply_dataset_compatibility_patches,
    configure_grid2op_data_dir,
)
from craft.models import ActionRequest, SimulatorInfo
from craft.serialization import JsonValue

CRAFT_GRID2OP_METADATA_KEY = "craft_grid2op_metadata"


class Grid2OpSimulationError(RuntimeError):
    """Raised when the Grid2Op sandbox cannot be prepared."""


@dataclass(frozen=True)
class Grid2OpSimulatorConfig:
    env_name: str = DEFAULT_NON_TEST_DATASET
    test: bool = False
    scenario_id: str | None = None


class Grid2OpSimulator:
    """Callable one-step simulator suitable for Grid2OpConsequenceEvaluator."""

    def __init__(
        self,
        *,
        env: Any | None = None,
        env_factory: Callable[[], Any] | None = None,
        config: Grid2OpSimulatorConfig | None = None,
    ) -> None:
        if env is not None and env_factory is not None:
            raise ValueError("Provide either env or env_factory, not both.")
        self.env = env
        self.env_factory = env_factory
        self.config = config or Grid2OpSimulatorConfig()

    def __call__(self, action: ActionRequest) -> Grid2OpStepResult:
        return self.simulate(action)

    def simulate(self, action: ActionRequest) -> Grid2OpStepResult:
        sandbox, reset_before_step = self._make_sandbox_env()
        try:
            obs_before = _initial_observation(sandbox, reset_before_step=reset_before_step)
            grid2op_action = action_request_to_grid2op_action(sandbox.action_space, action)
            simulator = simulator_info_from_env(
                sandbox,
                requested_env_name=self.config.env_name,
                test_mode=self.config.test,
            )
            scenario_id = _scenario_id(sandbox, obs_before, self.config.scenario_id)
            state_metadata = state_digest_metadata(
                sandbox,
                obs_before,
                simulator=simulator,
                scenario_id=scenario_id,
                phase="before",
            )
            state_digest = observation_digest(obs_before, extra=state_metadata)

            try:
                obs_after, reward, done, raw_info = sandbox.step(grid2op_action)
            except Exception as exc:
                info = _info_mapping(
                    {
                        "exception": [type(exc).__name__],
                        "error": str(exc),
                        "simulation_failed": True,
                    }
                )
                predicted_metadata = state_digest_metadata(
                    sandbox,
                    None,
                    simulator=simulator,
                    scenario_id=scenario_id,
                    phase="after",
                    action_digest=action.action_digest,
                    done=True,
                    reward=None,
                )
                _attach_metadata(info, state_metadata, predicted_metadata, simulator)
                return Grid2OpStepResult(
                    obs_before=obs_before,
                    obs_after=None,
                    done=True,
                    info=info,
                    reward=None,
                    state_digest=state_digest,
                    predicted_state_digest=observation_digest(None, extra=predicted_metadata),
                    simulator=simulator,
                    scenario_id=scenario_id,
                )

            info = _info_mapping(raw_info)
            reward_value = _float_or_none(reward)
            done_value = bool(done)
            predicted_metadata = state_digest_metadata(
                sandbox,
                obs_after,
                simulator=simulator,
                scenario_id=scenario_id,
                phase="after",
                action_digest=action.action_digest,
                done=done_value,
                reward=reward_value,
            )
            _attach_metadata(info, state_metadata, predicted_metadata, simulator)
            return Grid2OpStepResult(
                obs_before=obs_before,
                obs_after=obs_after,
                done=done_value,
                info=info,
                reward=reward_value,
                state_digest=state_digest,
                predicted_state_digest=observation_digest(obs_after, extra=predicted_metadata),
                simulator=simulator,
                scenario_id=scenario_id,
            )
        finally:
            _close_env(sandbox)

    def _make_sandbox_env(self) -> tuple[Any, bool]:
        if self.env_factory is not None:
            return self.env_factory(), True
        if self.env is not None:
            return _copy_env(self.env), False
        return make_grid2op_env(self.config.env_name, test=self.config.test), True


def make_grid2op_env(env_name: str = DEFAULT_NON_TEST_DATASET, *, test: bool = False) -> Any:
    """Create a project-local Grid2Op env with broad action support."""
    try:
        configure_grid2op_data_dir()
        if not test:
            apply_dataset_compatibility_patches(env_name)
        import grid2op  # type: ignore[import-untyped]
        from grid2op.Action import CompleteAction  # type: ignore[import-untyped]

        return grid2op.make(env_name, test=test, action_class=CompleteAction)
    except Exception as exc:
        raise Grid2OpSimulationError(f"Unable to create Grid2Op env '{env_name}': {exc}") from exc


def make_grid2op_consequence_evaluator(
    *,
    env: Any | None = None,
    env_factory: Callable[[], Any] | None = None,
    config: Grid2OpSimulatorConfig | None = None,
) -> Grid2OpConsequenceEvaluator:
    simulator = Grid2OpSimulator(env=env, env_factory=env_factory, config=config)
    simulator_info = SimulatorInfo(
        env_name=simulator.config.env_name,
        version=_grid2op_version(),
        test_mode=simulator.config.test,
    )
    return Grid2OpConsequenceEvaluator(
        simulate=simulator,
        simulator=simulator_info,
        scenario_id=simulator.config.scenario_id,
    )


def simulator_info_from_env(
    env: Any,
    *,
    requested_env_name: str,
    test_mode: bool,
) -> SimulatorInfo:
    return SimulatorInfo(
        env_name=requested_env_name,
        version=_grid2op_version(),
        backend=type(getattr(env, "backend", None)).__name__,
        test_mode=test_mode,
        n_sub=_optional_int_attr(env, "n_sub"),
        n_line=_optional_int_attr(env, "n_line"),
        n_gen=_optional_int_attr(env, "n_gen"),
        n_load=_optional_int_attr(env, "n_load"),
    )


def state_digest_metadata(
    env: Any,
    observation: Any | None,
    *,
    simulator: SimulatorInfo,
    scenario_id: str | None,
    phase: str,
    action_digest: str | None = None,
    done: bool | None = None,
    reward: float | None = None,
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "action_digest": action_digest,
        "actual_env_name": _optional_str_attr(env, "name"),
        "backend": simulator.backend,
        "done": done,
        "env_name": simulator.env_name,
        "phase": phase,
        "reward": reward,
        "scenario_id": scenario_id,
        "test_mode": simulator.test_mode,
        "timestep": _timestep(observation),
    }
    return payload


def _copy_env(env: Any) -> Any:
    copy_method = getattr(env, "copy", None)
    if callable(copy_method):
        return copy_method()
    return copy.deepcopy(env)


def _initial_observation(env: Any, *, reset_before_step: bool) -> Any:
    if reset_before_step:
        return env.reset()
    get_obs = getattr(env, "get_obs", None)
    if callable(get_obs):
        return get_obs()
    current_obs = getattr(env, "current_obs", None)
    if current_obs is not None:
        return current_obs
    return env.reset()


def _close_env(env: Any) -> None:
    close = getattr(env, "close", None)
    if callable(close):
        close()


def _info_mapping(info: object) -> dict[str, Any]:
    if info is None:
        return {}
    if isinstance(info, Mapping):
        return dict(info)
    return {"raw_info": repr(info)}


def _attach_metadata(
    info: dict[str, Any],
    state_metadata: Mapping[str, JsonValue],
    predicted_metadata: Mapping[str, JsonValue],
    simulator: SimulatorInfo,
) -> None:
    info[CRAFT_GRID2OP_METADATA_KEY] = {
        "state": dict(state_metadata),
        "predicted_state": dict(predicted_metadata),
        "simulator": simulator.model_dump(mode="json"),
    }


def _scenario_id(env: Any, observation: Any | None, configured: str | None) -> str | None:
    if configured:
        return configured
    obs_id = _first_attr(observation, ("scenario_id", "episode_id", "chronics_id"))
    if obs_id is not None:
        return str(obs_id)
    chronics_handler = getattr(env, "chronics_handler", None)
    for method_name in ("get_name", "get_id"):
        method = getattr(chronics_handler, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                continue
            if value is not None:
                return str(value)
    return None


def _timestep(observation: Any | None) -> int | None:
    value = _first_attr(
        observation,
        ("current_step", "timestep", "time_step", "_current_step"),
    )
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _first_attr(obj: Any | None, names: tuple[str, ...]) -> object | None:
    if obj is None:
        return None
    for name in names:
        value = cast(object | None, getattr(obj, name, None))
        if value is not None:
            return value
    return None


def _optional_int_attr(obj: Any, name: str) -> int | None:
    value = getattr(obj, name, None)
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _optional_str_attr(obj: Any, name: str) -> str | None:
    value = getattr(obj, name, None)
    return None if value is None else str(value)


def _float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _grid2op_version() -> str:
    try:
        return metadata.version("grid2op")
    except metadata.PackageNotFoundError:
        return "unknown"
