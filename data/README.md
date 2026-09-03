# Local Data

This directory is the project-local home for datasets and generated data.

Tracked:

1. Lightweight notes such as this README.
2. Small metadata files that are safe to commit.

Ignored:

1. `data/grid2op/`: local Grid2Op datasets downloaded by CRAFT helpers.
2. Large raw datasets, generated simulation traces, caches and temporary downloads.

Default Grid2Op data path used by CRAFT scripts:

```text
/home/breeze/my-project/CRAFT/data/grid2op
```

Override it with:

```bash
export CRAFT_GRID2OP_DATA_DIR=/path/to/grid2op-data
```
