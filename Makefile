.PHONY: all setup lint typecheck test data synth run calibrate bench bench-smoke goldens docker

VENV ?= .venv
PYTHON ?= $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)

SIZE ?= 20k
RUNS ?= 1
SEED ?= 1
TRACE ?=

all: lint typecheck test bench-smoke

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m pyright

test:
	$(PYTHON) -m pytest

data:
	@echo "Data download target for public traces (Phase 7)"

synth:
	$(PYTHON) -m rcwa.cli synth --size $(SIZE) --seed $(SEED) --faults default

run:
	$(PYTHON) -m rcwa.cli run $(if $(TRACE),"$(TRACE)")

calibrate:
	$(PYTHON) -m rcwa.cli calibrate

bench:
	$(PYTHON) -m rcwa.cli synth --size $(SIZE) --seed $(SEED) --runs $(RUNS)

bench-smoke:
	$(PYTHON) -m rcwa.cli version
	$(PYTHON) -m rcwa.wrap --version
	$(PYTHON) -m rcwa.cli synth --size $(SIZE) --seed $(SEED) --runs $(RUNS)

goldens:
	@echo "Golden diff verification target (Phase 6)"

docker:
	docker build -t rcwa:latest .
	docker run --rm rcwa:latest
