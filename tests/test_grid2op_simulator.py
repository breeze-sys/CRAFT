from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from craft.grid import (
    CRAFT_GRID2OP_METADATA_KEY,
    Grid2OpSimulator,
    Grid2OpSimulatorConfig,
    observation_digest,
)
from craft.models import ActionRequest, ActionType, ActorIdentity, Role


@dataclass(frozen=True)
class FakeObservation:
    rho: Sequence[float]
    line_status: Sequence[bool] = ()
    topo_vect: Sequence[int] = ()
    sub_info: Sequence[int] = ()
    gen_p: Sequence[float] = ()
    load_p: Sequence[float] = ()
    current_step: int = 0


@dataclass(frozen=True)
class FakeGrid2OpAction:
    payload: dict[str, object]


class FakeActionSpace:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def __call__(self, payload: dict[str, object]) -> FakeGrid2OpAction:
        self.payloads.append(payload)
        return FakeGrid2OpAction(payload)


class FakeBackend:
    pass


class FakeEnv:
    def __init__(
        self,
        *,
        obs_before: FakeObservation,
        obs_after: FakeObservation | None = None,
        done: bool = False,
        info: dict[str, object] | None = None,
        reward: float = 1.0,
        step_error: Exception | None = None,
    ) -> None:
        self.name = "fake-grid2op-env"
        self.backend = FakeBackend()
        self.n_sub = 2
        self.n_line = 3
        self.n_gen = 1
        self.n_load = 1
        self.action_space = FakeActionSpace()
        self.obs_before = obs_before
        self.obs_after = obs_after or obs_before
        self.done = done
        self.info = info or {}
        self.reward = reward
        self.step_error = step_error
        self.copies: list[FakeEnv] = []
        self.received_actions: list[FakeGrid2OpAction] = []
        self.reset_calls = 0
        self.get_obs_calls = 0
        self.step_calls = 0
        self.closed = False

    def copy(self) -> "FakeEnv":
        copied = FakeEnv(
            obs_before=self.obs_before,
            obs_after=self.obs_after,
            done=self.done,
            info=self.info,
            reward=self.reward,
            step_error=self.step_error,
        )
        self.copies.append(copied)
        return copied

    def get_obs(self) -> FakeObservation:
        self.get_obs_calls += 1
        return self.obs_before

    def reset(self) -> FakeObservation:
        self.reset_calls += 1
        return self.obs_before

    def step(
        self,
        action: FakeGrid2OpAction,
    ) -> tuple[FakeObservation, float, bool, dict[str, object]]:
        self.step_calls += 1
        self.received_actions.append(action)
        if self.step_error is not None:
            raise self.step_error
        return self.obs_after, self.reward, self.done, dict(self.info)

    def close(self) -> None:
        self.closed = True


def make_action(
    action_type: ActionType = ActionType.NOOP,
    parameters: dict[str, Any] | None = None,
) -> ActionRequest:
    return ActionRequest(
        requested_by=ActorIdentity(subject_id="agent-1", role=Role.AGENT),
        action_type=action_type,
        parameters=parameters or {},
        nonce="grid2op-simulator-test",
    )


def test_simulator_steps_copied_env_without_mutating_live_env() -> None:
    obs_before = FakeObservation(
        rho=(0.40, 0.50, 0.60),
        line_status=(True, True, True),
        topo_vect=(1, 1, 1),
        sub_info=(1, 2),
        gen_p=(10.0,),
        load_p=(9.0,),
        current_step=7,
    )
    obs_after = FakeObservation(
        rho=(0.41, 0.52, 0.63),
        line_status=(True, True, True),
        topo_vect=(1, 1, 1),
        sub_info=(1, 2),
        gen_p=(40.0,),
        load_p=(9.0,),
        current_step=8,
    )
    live_env = FakeEnv(obs_before=obs_before, obs_after=obs_after, reward=2.5)
    simulator = Grid2OpSimulator(
        env=live_env,
        config=Grid2OpSimulatorConfig(env_name="fake-grid2op-env", test=True),
    )
    action = make_action(ActionType.REDISPATCH, {"gen_id": 0, "delta_mw": 30.0})

    result = simulator.simulate(action)

    assert live_env.step_calls == 0
    assert live_env.reset_calls == 0
    assert len(live_env.copies) == 1
    sandbox = live_env.copies[0]
    assert sandbox.get_obs_calls == 1
    assert sandbox.step_calls == 1
    assert sandbox.closed
    assert sandbox.action_space.payloads == [{"redispatch": [(0, 30.0)]}]
    assert result.obs_before == obs_before
    assert result.obs_after == obs_after
    assert result.done is False
    assert result.reward == 2.5
    assert result.simulator is not None
    assert result.simulator.env_name == "fake-grid2op-env"
    assert result.simulator.backend == "FakeBackend"
    assert result.simulator.n_line == 3

    metadata = result.info[CRAFT_GRID2OP_METADATA_KEY]
    assert result.state_digest == observation_digest(obs_before, extra=metadata["state"])
    assert result.predicted_state_digest == observation_digest(
        obs_after,
        extra=metadata["predicted_state"],
    )
    assert metadata["state"]["timestep"] == 7
    assert metadata["predicted_state"]["action_digest"] == action.action_digest


def test_simulator_env_factory_uses_fresh_reset_sandbox() -> None:
    created_envs: list[FakeEnv] = []

    def env_factory() -> FakeEnv:
        env = FakeEnv(
            obs_before=FakeObservation(rho=(0.30,)),
            obs_after=FakeObservation(rho=(0.31,)),
        )
        created_envs.append(env)
        return env

    simulator = Grid2OpSimulator(
        env_factory=env_factory,
        config=Grid2OpSimulatorConfig(env_name="factory-env", scenario_id="factory-scenario"),
    )

    result = simulator.simulate(make_action())

    assert len(created_envs) == 1
    assert created_envs[0].reset_calls == 1
    assert created_envs[0].step_calls == 1
    assert created_envs[0].closed
    assert result.scenario_id == "factory-scenario"
    assert result.simulator is not None
    assert result.simulator.env_name == "factory-env"


def test_simulator_step_exception_returns_failed_step_result() -> None:
    env = FakeEnv(
        obs_before=FakeObservation(rho=(0.80,)),
        step_error=RuntimeError("power flow failed"),
    )
    simulator = Grid2OpSimulator(
        env=env,
        config=Grid2OpSimulatorConfig(env_name="fake-grid2op-env"),
    )

    result = simulator.simulate(make_action())

    assert result.obs_after is None
    assert result.done is True
    assert result.reward is None
    assert result.info["simulation_failed"] is True
    assert result.info["exception"] == ["RuntimeError"]
    assert CRAFT_GRID2OP_METADATA_KEY in result.info
    assert env.copies[0].closed
