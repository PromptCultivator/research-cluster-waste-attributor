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

---

### DEC-005: Click 8.5.1 Compatibility Bridges
- **Date**: 2026-11-09
- **Decision**: Implement compatibility bridges in `rcwa/__init__.py` for Click 8.5.1 parameter validation and metavar rendering.
- **Rationale**: Click 8.5.1 changed parameter missing validation to use an internal `UNSET` sentinel rather than `None`, causing Typer arguments defaulting to `None` to bypass missing-value errors. In addition, Click 8.5.1 requires `ctx` in `Parameter.make_metavar`. The compatibility shims ensure required Typer arguments raise `MissingParameter` when omitted and metavars render even when no active Click context exists.
- **Guarantee Maintained**: CLI interface correctness and automated test validation.

---

### DEC-006: Lazy Schema and Model Initialization for Sub-Second CLI Ingestion
- **Date**: 2026-11-09
- **Decision**: Lazily evaluate PyArrow schema generation and Pydantic record models in `rcwa/model.py` via module-level `__getattr__` while retaining Polars canonical schema eagerly.
- **Rationale**: Immediate import of `pyarrow` and `pydantic` introduces ~240ms of interpreter startup overhead per CLI invocation. Deferring Arrow schema construction and Pydantic model compilation enables CLI ingestion commands to execute at over 700 jobs/s even on small 100-job batches while maintaining full type safety in static analysis via `TYPE_CHECKING` guards.
- **Guarantee Maintained**: Ingestion throughput targets and reproducible sub-second CLI invocations.

---

### DEC-007: Conservation Precedence Hierarchy Implementation
- **Date**: 2026-11-09
- **Decision**: Enforce single-pass precedence ordering: Class 3 (failed work) -> Class 4 (recomputation) -> Class 2 (idle CPU) and Class 1 (memory over-request) -> Utilized.
- **Rationale**: When multiple conditions coincide (such as a job that failed after recomputing prior inputs), allocating resources to multiple categories would violate conservation or double-count losses. Attributing failed jobs entirely to Class 3 ensures auditable, non-overlapping partitions.
- **Guarantee Maintained**: Guarantee G1 (Conservation) across individual jobs and cluster-wide aggregations.

---

### DEC-008: Non-Null Memory Reservation Normalization for Conservation Arithmetic
- **Date**: 2026-11-09
- **Decision**: Normalize null memory reservations to 0 in `attribute_trace` prior to conservation checks.
- **Rationale**: Unspecified job memory requests (`ReqMem=?`) yield null reservation values in raw canonical records. Evaluating arithmetic on null values in conservation checkers leads to TypeErrors. Replacing null with 0 ensures every memory component evaluates to valid integer megabyte-seconds where `0 == 0 + 0 + 0 + 0 + 0`.
- **Guarantee Maintained**: Guarantee G1 arithmetic validation without TypeErrors.

---

### DEC-009: 1-to-1 Temporal Earliest Candidate Claiming for Retry Chains
- **Date**: 2026-11-09
- **Decision**: Assign failure retry links such that the earliest candidate resubmission (ordered by submit time ascending) claims the failure.
- **Rationale**: Provides deterministic, causal matching when multiple matching jobs are submitted following a failure, preventing duplicate linkage and resolving multi-hop chains to their original root failure.
- **Guarantee Maintained**: Guarantee G3 (Determinism) and causality in retry chain identification.

---

### DEC-010: Guarantee G2 Safety Guardrail Priority Order and OOM Escalation Invariants
- **Date**: 2026-11-09
- **Decision**: Prioritize OUT_OF_MEMORY failure escalation over sample floor exclusions such that any group exhibiting an out-of-memory termination receives an immediate memory increase recommendation (`ceil(max_observed * 1.5)`) and has `reclaimable_gb_hours` zeroed, even if its sample count is below `min_samples`. Non-OOM groups with sample counts below `min_samples` receive `None` across all recommendations and action `below_sample_floor`. Memory recommendations are strictly floored at the maximum observed RSS across all jobs in the cohort regardless of terminal state.
- **Rationale**: An out-of-memory termination represents a fatal workload disruption requiring memory allocation escalation rather than statistical reduction. Zeroing reclaimable memory prevents hazardous capacity reclamation while ensuring that groups with insufficient sample counts are protected from uncalibrated reductions.
- **Guarantee Maintained**: Guarantee G2 (Safety Guardrails).

---

### DEC-011: Command-Only Duplicate Classification and Recomputation Exclusion
- **Date**: 2026-11-09
- **Decision**: Command-only matches (where `command_hash` matches but `input_hash` is absent) are assigned `recompute_confidence="command_only"` and `possible_recompute=True`, but are strictly excluded from Class 4 waste totals (`class4_core_s = 0`, `class4_mem_mb_s = 0`).
- **Rationale**: In batch clusters, users frequently execute identical scripts with differing runtime flags or external unmetered inputs. Attributing waste without verified input checksum matches risks false positives. Restricting Class 4 resource attribution exclusively to verified input hash matches preserves precision while surfacing potential duplicates for inspection.
- **Guarantee Maintained**: Guarantee G1 (Conservation) and precision in redundant recomputation attribution.

---

### DEC-012: Deterministic Floating-Point Metric Quantization for Guarantee G3 Serialization
- **Date**: 2026-11-09
- **Decision**: Round floating-point metrics to 6 decimal places during report serialization across JSON, Markdown, and CSV outputs.
- **Rationale**: Multi-threaded reductions across Polars execution partitions can cause floating-point variations in least significant bits due to non-associative summation order. Quantizing floating-point numbers to 6 decimal places ensures reproducible, byte-identical serializations across runs on identical data.
- **Guarantee Maintained**: Guarantee G3 (Determinism).
