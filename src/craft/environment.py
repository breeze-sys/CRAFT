"""Environment health checks for local development."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

RECOMMENDED_PYTHON = ">=3.10,<3.13"
RUNTIME_IMPORTS = (
    "fastapi",
    "gmssl",
    "grid2op",
    "numpy",
    "pandas",
    "pydantic",
    "scipy",
    "typer",
    "uvicorn",
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    installed: bool


def check_dependency(name: str) -> DependencyStatus:
    return DependencyStatus(name=name, installed=importlib.util.find_spec(name) is not None)


def collect_dependency_status() -> list[DependencyStatus]:
    return [check_dependency(name) for name in RUNTIME_IMPORTS]


def python_version_supported() -> bool:
    return (3, 10) <= sys.version_info < (3, 13)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Check the local CRAFT development environment.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="also require runtime dependencies such as Grid2Op and gmssl",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_local_env()
    args = build_parser().parse_args(argv)

    print("Project: CRAFT")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Recommended Python: {RECOMMENDED_PYTHON}")
    supported = python_version_supported()
    print(f"Python supported: {'yes' if supported else 'no'}")
    print(f"CRAFT_GRID2OP_ENV: {os.getenv('CRAFT_GRID2OP_ENV', 'not set')}")

    if not supported:
        print()
        print("Base environment check failed: use Python >=3.10,<3.13.")
        return 1

    if not args.full:
        print()
        print("Base environment check passed.")
        print("Run with `--full` after installing runtime dependencies.")
        return 0

    print()
    print("Runtime dependency status:")

    missing: list[str] = []
    for dep in collect_dependency_status():
        marker = "ok" if dep.installed else "missing"
        print(f"  {marker:7} {dep.name}")
        if not dep.installed:
            missing.append(dep.name)

    if missing:
        print()
        print("Missing dependencies are expected before running `make setup` or conda/pip install.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
