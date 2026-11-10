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
	$(PYTHON) scripts/download_data.py

synth:
	$(PYTHON) -m rcwa.cli synth --size $(SIZE) --seed $(SEED) --faults default

run:
	$(PYTHON) -m rcwa.cli run $(if $(TRACE),"$(TRACE)")

calibrate:
	$(PYTHON) -m rcwa.cli calibrate

bench:
	$(PYTHON) -m bench.run --size $(SIZE) --runs $(RUNS) --seed $(SEED)

bench-smoke:
	$(PYTHON) -m bench.run --size 20k --runs 1 --smoke

goldens:
	$(PYTHON) -m rcwa.cli report tests/fixtures/sacct/multiday_cluster.txt --format json --output tests/fixtures/golden/golden_report.json
	$(PYTHON) -m rcwa.cli report tests/fixtures/sacct/multiday_cluster.txt --format markdown --output tests/fixtures/golden/golden_report.md
	$(PYTHON) -m rcwa.cli report tests/fixtures/sacct/multiday_cluster.txt --format csv --output tests/fixtures/golden/golden_report.csv
	$(PYTHON) -m rcwa.cli report tests/fixtures/swf/sample_workload.swf --format json --output tests/fixtures/golden/golden_swf_report.json
	$(PYTHON) -m rcwa.cli report tests/fixtures/swf/sample_workload.swf --format markdown --output tests/fixtures/golden/golden_swf_report.md
	$(PYTHON) -m rcwa.cli report tests/fixtures/swf/sample_workload.swf --format csv --output tests/fixtures/golden/golden_swf_report.csv
	git diff tests/fixtures/golden/

docker:
	docker build -t rcwa:latest .
	docker run --rm rcwa:latest
