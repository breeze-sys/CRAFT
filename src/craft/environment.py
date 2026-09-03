"""Environment health checks for local development."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from dataclasses import dataclass


RECOMMENDED_PYTHON = ">=3.10,<3.13"
OPTIONAL_IMPORTS = (
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


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    installed: bool


def check_dependency(name: str) -> DependencyStatus:
    return DependencyStatus(name=name, installed=importlib.util.find_spec(name) is not None)


def collect_dependency_status() -> list[DependencyStatus]:
    return [check_dependency(name) for name in OPTIONAL_IMPORTS]


def python_version_supported() -> bool:
    return (3, 10) <= sys.version_info < (3, 13)


def main() -> int:
    print("Project: CRAFT")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Recommended Python: {RECOMMENDED_PYTHON}")
    print(f"Python supported: {'yes' if python_version_supported() else 'no'}")
    print(f"CRAFT_GRID2OP_ENV: {os.getenv('CRAFT_GRID2OP_ENV', 'not set')}")
    print()
    print("Dependency status:")

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
