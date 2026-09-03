PYTHON ?= python
CRAFT_GRID2OP_REAL_ENV ?= l2rpn_neurips_2020_track1_small

.PHONY: setup setup-local check check-full check-grid check-grid-real download-grid-data test lint format

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

setup-local:
	$(PYTHON) -m pip install -e . --no-deps --no-build-isolation

check:
	PYTHONPATH=src $(PYTHON) scripts/check_environment.py

check-full:
	PYTHONPATH=src $(PYTHON) scripts/check_environment.py --full

check-grid:
	PYTHONPATH=src $(PYTHON) scripts/check_grid2op.py --all-defaults

check-grid-real:
	PYTHONPATH=src $(PYTHON) scripts/check_grid2op.py --real-default

download-grid-data:
	PYTHONPATH=src $(PYTHON) scripts/download_grid2op_dataset.py download $(CRAFT_GRID2OP_REAL_ENV)

test:
	PYTHONPATH=src $(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .
