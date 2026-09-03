PYTHON ?= python

.PHONY: setup setup-local check test lint format

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

setup-local:
	$(PYTHON) -m pip install -e . --no-deps --no-build-isolation

check:
	PYTHONPATH=src $(PYTHON) scripts/check_environment.py

test:
	PYTHONPATH=src $(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .
