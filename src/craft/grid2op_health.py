"""Grid2Op health checks used by CRAFT development setup."""

from __future__ import annotations

import os
import warnings
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_GRID2OP_ENV = "l2rpn_case14_sandbox"
DEFAULT_GRID2OP_REAL_ENV = "l2rpn_2019"
SMOKE_TEST_ENVS = ("l2rpn_case14_sandbox", "educ_case14_redisp")


@dataclass(frozen=True)
class Grid2OpHealthResult:
    requested_env: str
    actual_env: str
    backend: str
    n_line: int
    n_gen: int
    n_load: int
    redispatchable_generators: int
    rho_max: float
    reward_type: str
    done_after_noop: bool


def _sum_bool_array(value: Any) -> int:
    if value is None:
        return 0
    return int(value.sum())


def run_grid2op_smoke(env_name: str, *, test: bool = True) -> Grid2OpHealthResult:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Numba cannot be loaded.*")
        warnings.filterwarnings("ignore", message="You are using a development environment.*")
        import grid2op

        if not test:
            from craft.grid2op_datasets import (
                apply_dataset_compatibility_patches,
                configure_grid2op_data_dir,
            )

            configure_grid2op_data_dir()
            for patch_message in apply_dataset_compatibility_patches(env_name):
                print(f"Compatibility patch: {patch_message}")
        env = grid2op.make(env_name, test=test)

    try:
        obs = env.reset()
        noop = env.action_space({})
        next_obs, reward, done, _info = env.step(noop)
        rho_max = float(max(float(obs.rho.max()), float(next_obs.rho.max())))
        backend = type(env.backend).__name__
        return Grid2OpHealthResult(
            requested_env=env_name,
            actual_env=env.name,
            backend=backend,
            n_line=int(env.n_line),
            n_gen=int(env.n_gen),
            n_load=int(env.n_load),
            redispatchable_generators=_sum_bool_array(getattr(env, "gen_redispatchable", None)),
            rho_max=rho_max,
            reward_type=type(reward).__name__,
            done_after_noop=bool(done),
        )
    finally:
        env.close()


def format_result(result: Grid2OpHealthResult) -> str:
    lines = [
        f"Grid2Op env: {result.requested_env}",
        f"  actual env: {result.actual_env}",
        f"  backend: {result.backend}",
        f"  lines: {result.n_line}",
        f"  generators: {result.n_gen}",
        f"  loads: {result.n_load}",
        f"  redispatchable generators: {result.redispatchable_generators}",
        f"  max rho during smoke test: {result.rho_max:.4f}",
        f"  reward type: {result.reward_type}",
        f"  done after noop: {result.done_after_noop}",
    ]
    return "\n".join(lines)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run a Grid2Op smoke test for CRAFT.")
    parser.add_argument(
        "env",
        nargs="?",
        default=os.getenv("CRAFT_GRID2OP_ENV", DEFAULT_GRID2OP_ENV),
        help="Grid2Op environment name",
    )
    parser.add_argument(
        "--no-test",
        action="store_true",
        help="create a normal Grid2Op environment instead of test=True",
    )
    parser.add_argument(
        "--all-defaults",
        action="store_true",
        help="check the default CRAFT smoke-test environments",
    )
    parser.add_argument(
        "--real-default",
        action="store_true",
        help=f"check the compact non-test dataset ({DEFAULT_GRID2OP_REAL_ENV})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.real_default:
        env_names = (DEFAULT_GRID2OP_REAL_ENV,)
        test = False
    else:
        env_names = SMOKE_TEST_ENVS if args.all_defaults else (args.env,)
        test = not args.no_test

    for index, env_name in enumerate(env_names):
        if index:
            print()
        result = run_grid2op_smoke(env_name, test=test)
        print(format_result(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
