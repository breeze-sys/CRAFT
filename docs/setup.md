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

If the default Anaconda repository is blocked, use the China mirror file:

```bash
cd /home/breeze/my-project/CRAFT
conda env create -f environment-cn.yml
conda activate craft
python scripts/check_environment.py
```

Or create the environment in two explicit steps:

```bash
cd /home/breeze/my-project/CRAFT
conda create -n craft \
  -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge \
  --override-channels \
  python=3.10 pip -y
conda activate craft
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
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

To use the China mirror file with the bootstrap script:

```bash
cd /home/breeze/my-project/CRAFT
CRAFT_CONDA_ENV_FILE=environment-cn.yml bash scripts/bootstrap_env.sh
```

If package sources cannot be reached, read `docs/network.md` first. In WSL, package managers often need explicit proxy environment variables even when the Windows browser already works.

## Offline Local Package Fallback

If package sources are temporarily unreachable, you can still create a lightweight local environment and install only the CRAFT package itself:

```bash
cd /home/breeze/my-project/CRAFT
conda run -n mia python -m venv .venv
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/python scripts/check_environment.py
```

This does not install Grid2Op, gmssl or other runtime dependencies. It only makes local scripts and package imports work while waiting for package-source network access to recover.

## Current Host Note

At the time this setup was written:

1. `python3` points to Python 3.13.11 from Miniconda base.
2. `python3.10` exists as Python 3.10.12, but has no `pip` or `ensurepip`.
3. `conda create` could not complete because package-source network access returned `Network is unreachable`.
4. Source-level checks pass without third-party dependencies.

Once package-source network access is restored, use the conda setup path above.

If `conda activate craft` reports `EnvironmentNameNotFound`, it means the create step failed and no environment was created. Re-run the create step first, preferably with `environment-cn.yml` if `repo.anaconda.com` is blocked.

If `python scripts/check_environment.py` reports `ModuleNotFoundError: No module named 'craft'`, either pull the latest repository version or run:

```bash
PYTHONPATH=src python scripts/check_environment.py
```

The latest script already adds `src` to `sys.path` automatically, so this should no longer be necessary after updating.

## Checks

```bash
make check
make check-full
make test
make lint
make format
```

`make check` only verifies the baseline Python/project setup. `make check-full` additionally verifies runtime dependencies such as Grid2Op and gmssl.

Before dependencies are installed, `scripts/check_environment.py --full` will report missing packages. That is expected.
