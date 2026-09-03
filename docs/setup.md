# Development Setup

CRAFT is expected to run on Python `>=3.10,<3.13`.

Use Python 3.10 for the first competition MVP. The host default Python may be newer, but Grid2Op and related scientific-computing packages are usually less risky on Python 3.10 or 3.11.

## Option A: Conda

```bash
cd CRAFT
conda env create -f environment.yml
conda activate craft
python scripts/check_environment.py
```

If the default Anaconda repository is blocked, use the China mirror file:

```bash
cd CRAFT
conda env create -f environment-cn.yml
conda activate craft
python scripts/check_environment.py
```

Or create the environment in two explicit steps:

```bash
cd CRAFT
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
cd CRAFT
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/check_environment.py
```

On some Ubuntu installations, `python3.10 -m venv` fails because `ensurepip` is not installed. In that case install the system package `python3.10-venv`, or use conda.

## Quick Bootstrap

```bash
cd CRAFT
bash scripts/bootstrap_env.sh
```

The script prefers conda when available and falls back to `python3.10 -m venv`.

To use the China mirror file with the bootstrap script:

```bash
cd CRAFT
CRAFT_CONDA_ENV_FILE=environment-cn.yml bash scripts/bootstrap_env.sh
```

If package sources cannot be reached, read `docs/network.md` first. In WSL, package managers often need explicit proxy environment variables even when the Windows browser already works.

## Offline Local Package Fallback

If package sources are temporarily unreachable, you can still create a lightweight local environment and install only the CRAFT package itself:

```bash
cd CRAFT
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
make check-grid
make download-grid-data
make check-grid-real
make test
make lint
make format
```

`make check` only verifies the baseline Python/project setup. `make check-full` additionally verifies runtime dependencies such as Grid2Op and gmssl.
`make check-grid` creates the default Grid2Op case14 smoke-test environments and runs one no-op step in each.
`make download-grid-data` downloads the default compact non-test Grid2Op dataset. `make check-grid-real` loads that dataset and runs one no-op step.

Before dependencies are installed, `scripts/check_environment.py --full` will report missing packages. That is expected.

Optional Grid2Op acceleration:

```bash
python -m pip install -e ".[grid-accelerated]"
```

Keep this optional for the first MVP; the default PandaPower backend is enough for functional demos.

## Non-Test Grid2Op Dataset

Default dataset:

```bash
l2rpn_2019
```

Why this one:

1. It is a non-test L2RPN competition dataset.
2. It is already verified locally and uses about 231.6 MiB.
3. It is enough for developing the first Consequence Evaluator, Risk Engine, PCC and reauthorization path.
4. CRAFT stores downloaded datasets under the project-local ignored directory `data/grid2op`.

Useful commands:

```bash
cd CRAFT
conda run -n craft python scripts/download_grid2op_dataset.py list
conda run -n craft python scripts/download_grid2op_dataset.py download
conda run -n craft python scripts/download_grid2op_dataset.py inspect
conda run -n craft make check-grid-real PYTHON=python
```

The downloader uses curated direct dataset URLs and checks the remote archive size before download when `Content-Length` is available.
If the remote size probe times out, the downloader prints a warning and continues; the local 5G budget is still enforced through the curated dataset metadata and extraction-size check.
When `curl` is available, the downloader uses resumable mode (`curl -C -`) with retries. If the large file transfer is slow or interrupted, run the same download command again and it will continue from the partial archive in `data/grid2op/.downloads`.
If `curl` returns HTTP range error `33`, the script will automatically discard the incompatible partial archive and retry from scratch without resumable mode.

CRAFT scripts point Grid2Op to the project-local directory by default:

```bash
data/grid2op
```

Relative paths in `CRAFT_GRID2OP_DATA_DIR` are resolved from the repository root, not the caller's current working directory.

Override it only when you intentionally want datasets on another disk:

```bash
export CRAFT_GRID2OP_DATA_DIR=/path/to/grid2op-data
```

The 900 MB `l2rpn_neurips_2020_track1_small` dataset is optional. It is useful later for more convincing report experiments and screenshots, but it is not required for the current MVP implementation:

```bash
conda run --no-capture-output -n craft python scripts/download_grid2op_dataset.py download l2rpn_neurips_2020_track1_small
```

`l2rpn_2019` ships with an old `ReadPypowNetData` import in its dataset `config.py`. The CRAFT dataset helper patches this import automatically for Grid2Op `>=1.12` during download, inspect and smoke checks.
