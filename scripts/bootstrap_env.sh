#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if command -v conda >/dev/null 2>&1; then
  echo "Creating conda environment from environment.yml..."
  conda env create -f environment.yml
  echo
  echo "Activate it with:"
  echo "  conda activate craft"
  echo
  echo "Then run:"
  echo "  python scripts/check_environment.py"
else
  echo "Creating .venv with python3.10..."
  python3.10 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e ".[dev]"
  python scripts/check_environment.py
fi

