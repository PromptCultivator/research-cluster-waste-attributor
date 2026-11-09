# Architectural and Implementation Decisions

This document records technical decisions made during implementation where choices between valid alternatives preserve testable guarantees.

---

### DEC-001: Python Version Compatibility Matrix
- **Date**: 2026-11-09
- **Decision**: Specify `requires-python = ">=3.11"` in package configuration while enforcing Python 3.12 syntax and rules in static analysis (Ruff) and type validation (Pyright).
- **Rationale**: Enables development execution across Linux distributions running Python 3.11 while matching Python 3.12 specifications for production container builds and continuous integration environments.
- **Guarantee Maintained**: Deterministic reproducibility across standard Python 3.11 and 3.12 environments.

---

### DEC-002: Dynamic Python Interpreter Resolution in Build Harness
- **Date**: 2026-11-09
- **Decision**: Configure `PYTHON ?= $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)` in the Makefile.
- **Rationale**: Allows developers using virtual environments and automation executing in bare containers to run make targets without manual interpreter flag configuration.
- **Guarantee Maintained**: Portability of verification commands across host operating systems and continuous integration runners.

---

### DEC-003: Operational Phase 0 Bench-Smoke Execution
- **Date**: 2026-11-09
- **Decision**: Implement `make bench-smoke` in Phase 0 as a validation pass executing the Typer CLI commands (`rcwa version`, `rcwa synth --size $(SIZE) --seed $(SEED)`).
- **Rationale**: Guarantees that continuous integration pipelines exercise the package entry points without waiting for Phase 7 synthetic generator completion.
- **Guarantee Maintained**: Continuous integration verification of build artifacts at every project phase.

---

### DEC-004: Strict Offline Determinism and Trace Isolation
- **Date**: 2026-11-09
- **Decision**: Isolate large downloaded workloads to gitignored directories (`data/raw/`, `data/out/`, `data/results/`) while committing small synthetic fixtures to `tests/fixtures/`.
- **Rationale**: Tests must execute without internet access (SPEC §1 rule 5). Raw trace downloads are confined strictly to explicit execution of `make data`.
- **Guarantee Maintained**: Guarantee G3 (Determinism) and zero-network test suite execution.
