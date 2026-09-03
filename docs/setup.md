# Development Setup

CRAFT is expected to run on Python `>=3.10,<3.13`.

Use Python 3.10 for the first competition MVP. The host default Python may be newer, but Grid2Op and related scientific-computing packages are usually less risky on Python 3.10 or 3.11.

## Option A: Conda

```bash
cd /home/breeze/my-project/CRAFT
conda env create -f environment.yml
conda activate craft
python scripts/check_environment.py
```

If the `craft` environment already exists:

```bash
conda activate craft
python -m pip install -e ".[dev]"
python scripts/check_environment.py
```

## Option B: venv

```bash
cd /home/breeze/my-project/CRAFT
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/check_environment.py
```

On some Ubuntu installations, `python3.10 -m venv` fails because `ensurepip` is not installed. In that case install the system package `python3.10-venv`, or use conda.

## Quick Bootstrap

```bash
cd /home/breeze/my-project/CRAFT
bash scripts/bootstrap_env.sh
```

The script prefers conda when available and falls back to `python3.10 -m venv`.

## Current Host Note

At the time this setup was written:

1. `python3` points to Python 3.13.11 from Miniconda base.
2. `python3.10` exists as Python 3.10.12, but has no `pip` or `ensurepip`.
3. `conda create` could not complete because package-source network access returned `Network is unreachable`.
4. Source-level checks pass without third-party dependencies.

Once package-source network access is restored, use the conda setup path above.

## Checks

```bash
make check
make test
make lint
make format
```

Before dependencies are installed, `scripts/check_environment.py` will report missing packages. That is expected.

