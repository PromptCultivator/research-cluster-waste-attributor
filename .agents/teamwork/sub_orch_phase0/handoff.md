# Milestone M0 (Phase 0 — Scaffold) Handoff Report

## Executive Summary
Milestone M0: Phase 0 (Scaffold) of `research-cluster-waste-attributor` is complete. The repository infrastructure, package configuration, dependency locking, build harness, CI workflow, container specification, complete documentation catalog, baseline configurations, CLI entry points, and verification test suites have been implemented and verified through the full iteration loop.

## Deliverables Inventory

### 1. Build and Packaging
- `pyproject.toml`:
  - Runtime dependencies pinned: `polars==1.14.0`, `pyarrow==18.1.0`, `numpy==2.1.3`, `pydantic==2.10.3`, `typer==0.15.1`, `pyyaml==6.0.2`.
  - Development dependencies pinned: `pytest==8.3.3`, `pytest-cov==6.0.0`, `hypothesis==6.120.0`, `ruff==0.8.2`, `pyright==1.1.390`.
  - Console scripts: `rcwa = "rcwa.cli:app"`, `rcwa-wrap = "rcwa.wrap:main"`.
  - License: Apache-2.0, Author: PromptCultivator.
  - Tool configurations: Ruff (Python 3.12, line length 100), Pyright (standard mode, Python 3.12), Pytest, and Coverage (`fail_under = 85`, `branch = true`).
- `LICENSE`: Apache-2.0 full text with year 2026 and copyright owner PromptCultivator.
- `Makefile`: All 13 targets implemented and verified (`all`, `setup`, `lint`, `typecheck`, `test`, `data`, `synth`, `run`, `calibrate`, `bench`, `bench-smoke`, `goldens`, `docker`).
- `Dockerfile`: Based on `python:3.12-slim`, copies package, documentation, and tests, installs dependencies, default `CMD ["make", "test"]`.
- `.dockerignore`: Excludes virtual environments, VCS metadata, and caches.
- `.github/workflows/ci.yml`: GitHub Actions workflow running on push and pull request, executing `make lint`, `make typecheck`, `make test`, and `make bench-smoke`.

### 2. Documentation and Architectural Decision Records
- `README.md`: Contains all 14 numbered sections conforming to SPEC §13 in short plain sentences, with `TBD` placeholders for unmeasured benchmark results and hardware specs.
- `docs/DECISIONS.md`: Structured decision log recording DEC-001 (Python version matrix), DEC-002 (Dynamic Python resolution), DEC-003 (Phase 0 bench-smoke execution), and DEC-004 (Strict offline determinism and trace isolation).
- `docs/AI-ASSISTANCE.md`: Complete code provenance tracking ledger recording every file and module created, with human reviewer verification columns.
- `docs/DATA.md`: Detailed public trace specifications for CEA-Curie and SDSC-SP2 with archive URLs, header pragma documentation, and usage terms.
- `docs/adr/`: Five architectural decision records with Title, Status (Accepted), Context, Options, Decision, and Measured/Expected Cost:
  - `001-conservation-partition.md`
  - `002-declared-inputs-for-recomputation.md`
  - `003-percentile-rightsizing-with-guardrails.md`
  - `004-easy-backfill-simulator.md`
  - `005-single-process-polars.md`

### 3. Policy and Cluster Configurations
- `policies/default.yaml`: Configured with primary grouping keys (`user`, `command_hash_or_job_name`), secondary rollups (`account`, `partition`, `user`), minimum sample floor (5), attribution parameters, rightsizing guardrails (p99 * 1.2, OOM increase to 1.5, timeout multiplier 1.5), and wrapper path stripping patterns.
- `clusters/example.yaml`: Configured with 64 nodes, 32 cores per node, 131,072 MB memory per node, and core-to-memory ratio 0.25.

### 4. Package Code and Verification Tests
- `rcwa/__init__.py`: Package version `0.1.0` and Click/Typer parameter metavar compatibility bridge.
- `rcwa/cli.py`: Typer CLI application supporting `version`, `synth`, `ingest`, `attribute`, `recommend`, `simulate`, `calibrate`, `report`, and `run` commands with path existence validation.
- `rcwa/wrap.py`: CLI wrapper for `rcwa-wrap` with declared input hashing, flag normalization, Comment and sidecar recording, and process error handling (status 127 and 126).
- `tests/unit/test_scaffold.py`: 25 unit tests exercising package version, CLI subcommands, flag parsing, help rendering, argument validation, process error handling, YAML configuration validation, and Git exclusion rules.
- `tests/unit/test_forbidden_words.py`: Automated scanner verifying zero occurrences of the 9 prohibited vocabulary words across all repository files.
- `data/.gitignore`: Excludes raw traces, uncompressed sacct exports, and intermediate outputs.

## Quality Gate Summary
- **Explorers (3)**: Build/CI Explorer, Documentation/ADR Explorer, and Package/Test Scaffold Explorer formulated comprehensive plans.
- **Worker (1)**: Implemented all assets and applied Challenger remediations.
- **Reviewers (2)**:
  - Reviewer 1 (Packaging & Build): APPROVE
  - Reviewer 2 (Documentation & Contract): APPROVE
- **Challengers (2)**:
  - Challenger 1 (CLI & Interfaces): APPROVE (after verifying Typer argument compatibility, path validation, wrap error handling, and .gitignore patterns).
  - Challenger 2 (Build Harness): APPROVE (after verifying Makefile TRACE expansion and RUNS parameter propagation).
- **Forensic Auditor (1)**: CLEAN (binary veto cleared; verified genuine implementations, Apache-2.0 licensing, exact pinned dependencies, zero prohibited words).
- **Test Metrics**:
  - Test Count: 26 passed, 0 failed.
  - Code Coverage: 95.24% statement coverage across `rcwa/` (exceeds >=85% gate).
  - Linting: `ruff check` and `ruff format --check` passed with 0 errors.
  - Type Checking: `pyright` passed with 0 errors, 0 warnings.
  - Prohibited Words Scan: 0 occurrences found.

## Next Steps: Phase 1 (Adapters and Canonical Record)
1. Implement canonical job record Arrow schema and Pydantic model in `rcwa/model.py` per SPEC §5.3.
2. Implement duration parsing, state normalization, and unit conversion in `rcwa/normalize.py` per SPEC §5.1, §5.2.
3. Implement Slurm `sacct` parser in `rcwa/adapters/sacct.py` with step rollup and array decomposing per SPEC §5.1.
