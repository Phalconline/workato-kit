PYTHON ?= python3.14
VENV := .venv
SOURCES := scripts tests
TESTS ?= test_*.py
.DEFAULT_GOAL := check
.PHONY: dev check lint format typecheck test sync-harness

# Install the pinned development tools (Ruff, mypy) from pyproject.toml into .venv. The scripts
# themselves need the standard library only.
dev:
	"$(PYTHON)" -m venv $(VENV)
	$(VENV)/bin/python -m pip install --quiet --disable-pip-version-check --group dev

# Everything below is offline: no Workato CLI, no credentials, no network. CI runs `make dev check`.
check:
	"$(PYTHON)" -I -B scripts/check.py

lint:
	$(VENV)/bin/ruff check $(SOURCES)

# Rewrites files: formatting, import order and the lint findings Ruff can fix safely.
format:
	$(VENV)/bin/ruff check --fix $(SOURCES)
	$(VENV)/bin/ruff format $(SOURCES)

typecheck:
	$(VENV)/bin/mypy

# One module: make test TESTS=test_prod_drift.py
test:
	"$(PYTHON)" -I -B -m unittest discover -s tests -t . -p '$(TESTS)'

sync-harness:
	"$(PYTHON)" -I -B scripts/sync_harness.py
