# Local Data

This directory is the project-local home for datasets and generated data.

## Git Policy

Tracked:

1. Lightweight notes such as this README.
2. Small metadata files that are safe to commit.

Ignored:

1. `data/grid2op/`: local Grid2Op datasets downloaded by CRAFT helpers.
2. Large raw datasets, generated simulation traces, caches and temporary downloads.

The actual Grid2Op datasets are intentionally not uploaded to GitHub. Each teammate
should keep their own local copy under the same relative project path.

## Expected Layout

Use this project-relative path by default:

```text
data/grid2op
```

For the current lightweight non-test setup, the expected dataset layout is:

```text
data/grid2op/l2rpn_2019
```

CRAFT resolves the relative path from the repository root, not from the shell's
current working directory. This keeps the setup portable when another teammate
clones the repository to a different absolute path.

## Team Setup Notes

Recommended command from the repository root:

```bash
conda run --no-capture-output -n craft python scripts/download_grid2op_dataset.py download
```

Check the local dataset after download:

```bash
conda run --no-capture-output -n craft python scripts/download_grid2op_dataset.py inspect
conda run --no-capture-output -n craft make check-grid-real PYTHON=python
```

If a teammate already has Grid2Op data elsewhere, prefer moving or copying it into:

```text
data/grid2op
```

Only override the path when local disk layout requires it:

```bash
export CRAFT_GRID2OP_DATA_DIR=/path/to/grid2op-data
```

If `CRAFT_GRID2OP_DATA_DIR` is relative, CRAFT treats it as relative to the
repository root.
