# Architectural and Implementation Decisions

This document records permanent technical and architectural decisions governing how `research-cluster-waste-attributor` (`rcwa`) preserves Guarantees G1–G4 across ingestion, attribution, rightsizing, simulation, and reporting.

---

### DEC-001: Python Version Compatibility Matrix
- **Decision**: Declare `requires-python = ">=3.11"` in [`pyproject.toml`](../pyproject.toml) while targeting Python `3.12` syntax rules in Ruff and Pyright.
- **Rationale**: Allows execution on standard Linux Python 3.11 runtimes while matching Python 3.12 container builds ([`Dockerfile`](../Dockerfile)) and CI workflows ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
- **Guarantee Maintained**: Reproducible execution across Python 3.11 and 3.12 environments.

---

### DEC-002: Dynamic Python Interpreter Resolution in Build Harness
- **Decision**: Resolve the Python executable in [`Makefile`](../Makefile) using `PYTHON ?= $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)`.
- **Rationale**: Allows developers working inside `.venv` and container/CI environments using system interpreters to invoke identical Make targets without manual environment variables.
- **Guarantee Maintained**: Portable verification across local workstations and CI runners.

---

### DEC-003: Continuous Integration Bench-Smoke Verification Gate
- **Decision**: Expose `make bench-smoke` (`python -m bench.run --size 20k --runs 1 --smoke`) as a mandatory gate invoked in `make all` and [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
- **Rationale**: Exercises end-to-end synthetic generation, Slurm/SWF parsing, waste attribution, guarded recommendations, EASY-backfill simulation, and calibration on 20,000 jobs while asserting exact G1 conservation (`g1_exact`) and zero G2 guardrail violations (`guardrail_violations == 0`).
- **Guarantee Maintained**: Guarantee G1 (Conservation) and Guarantee G2 (Safety Guardrails) at scale in CI.

---

### DEC-004: Strict Offline Determinism and Trace Isolation
- **Decision**: Isolate large downloaded public traces to gitignored paths (`data/raw/`, `data/out/`, `data/results/`) while committing small deterministic fixtures to [`tests/fixtures/`](../tests/fixtures/).
- **Rationale**: Automated test suites must execute completely offline without network dependencies. Network downloads occur strictly upon explicit invocation of `make data`.
- **Guarantee Maintained**: Guarantee G3 (Determinism) and zero-network test execution.

---

### DEC-005: Click 8.2+ Compatibility Bridges
- **Decision**: Apply targeted compatibility shims in [`rcwa/__init__.py`](../rcwa/__init__.py) for Click `make_metavar` optional context handling and `value_is_missing` handling of `None`.
- **Rationale**: Recent Click releases introduced an internal `UNSET` sentinel for omitted options and required explicit `ctx` arguments in `Parameter.make_metavar`. Because Typer `0.15.1` defaults unset required options to `None`, the bridges ensure required CLI parameters raise `MissingParameter` and help metavars render consistently across Click 8.2+ / 8.5.1 builds.
- **Guarantee Maintained**: CLI interface correctness across unit and E2E subprocess invocations.

---

### DEC-006: Lazy Schema and Model Initialization for Sub-Second CLI Startup
- **Decision**: Lazily construct `CANONICAL_ARROW_SCHEMA` and `CanonicalJobRecord` in [`rcwa/model.py`](../rcwa/model.py) via module-level `__getattr__` (guarded by `TYPE_CHECKING`), while keeping `POLARS_CANONICAL_SCHEMA` eager.
- **Rationale**: Eager top-level imports of `pyarrow` and `pydantic` add ~240ms startup latency to every subprocess invocation. Deferring their initialization sustains high single-process CLI ingestion responsiveness while retaining full static type checking in Pyright.
- **Guarantee Maintained**: High CLI throughput without sacrificing type safety.

---

### DEC-007: Conservation Precedence Hierarchy
- **Decision**: Partition every evaluated job's `reserved_core_s` and `reserved_mem_mb_s` strictly in single-pass precedence order: Class 3 (failed/retried work) $\to$ Class 4 (redundant recomputation) $\to$ Class 2 (idle reserved CPU) and Class 1 (memory over-request) $\to$ Utilized / Unattributed.
- **Rationale**: Real batch jobs frequently exhibit multiple concurrent inefficiencies (for instance, a failed job with unused cores, or a duplicate execution with over-requested memory). Evaluating one strict hierarchy prevents double counting and guarantees mutually exclusive, sum-preserving columns.
- **Guarantee Maintained**: Guarantee G1 (Conservation) per job and across cluster totals.

---

### DEC-008: Non-Null Memory Reservation Normalization
- **Decision**: Normalize null `reserved_mem_mb_s` values to `0` at the entry of `attribute_trace` prior to partitioning and conservation validation.
- **Rationale**: Scheduler logs with missing memory requests (`ReqMem=?`) yield `null` in the raw canonical model (`CanonicalJobRecord`). Normalizing null reservations to `0` ensures every memory partition column stores non-null integers obeying `0 == 0 + 0 + 0 + 0 + 0`.
- **Guarantee Maintained**: Guarantee G1 integer arithmetic invariants without null propagation errors.

---

### DEC-009: 1-to-1 Earliest Candidate Claiming for Retry Chains
- **Decision**: Link each failed job deterministically to the earliest unlinked eligible candidate resubmission matching `(user, task_signature)` submitted within `retry_window_s` after effective job end, then resolve multi-hop sequences to a shared `retry_chain_id` and root `retry_of`.
- **Rationale**: Prevents ambiguous many-to-one or cyclic linkage when concurrent jobs from the same user run close in time, establishing deterministic causal cost aggregation.
- **Guarantee Maintained**: Guarantee G3 (Determinism) and unambiguous retry chain accounting.

---

### DEC-010: Guarantee G2 Guardrail Priority Order and OOM Escalation
- **Decision**: Enforce Guarantee G2 in strict priority order:
  1. Any group exhibiting an `OUT_OF_MEMORY` termination (or `class3_sub_label == "oom"`) overrides `min_samples`, receives `recommended_req_mem_mb = max(ceil(oom_base * oom_multiplier), observed_max_rss)` with `recommendation_direction = "increase"`, and zeros `reclaimable_gb_hours`.
  2. Non-OOM groups with fewer than `min_samples` (default `5`) receive `None` for all resource recommendations and `recommendation_action = "below_sample_floor"`.
  3. Recommended memory is strictly floored at `observed_max_rss` computed across all states in the cohort, regardless of job outcome.
- **Rationale**: Out-of-memory failures prove current allocations are unsafe even on a single observation; excluding OOM cohorts from memory reclamation while immediately escalating capacity eliminates dangerous downsizing recommendations.
- **Guarantee Maintained**: Guarantee G2 (Safety Guardrails).

---

### DEC-011: Command-Only Duplicate Classification and Class 4 Exclusion
- **Decision**: Classify `COMPLETED` runs sharing a `command_hash` within `recompute_window_s` without a matching `input_hash` as `possible_recompute = True` (`recompute_confidence = "command_only"`), while assigning `class4_core_s = 0` and `class4_mem_mb_s = 0`.
- **Rationale**: Batch researchers routinely invoke identical analysis scripts against distinct external datasets that were not hashed with `rcwa-wrap`. Requiring matching `(command_hash, input_hash)` before classifying resources into Class 4 eliminates false-positive waste attribution while surfacing candidate workflows for input wrapping.
- **Guarantee Maintained**: Guarantee G1 precision and conservative attribution.

---

### DEC-012: Deterministic 6-Decimal Quantization for G3 Serialization
- **Decision**: Round all floating-point output metrics to `6` decimal places (`_round_floats`) and sort dictionary keys in `rcwa/report.py` prior to Markdown, JSON, and CSV emission.
- **Rationale**: Parallel vector reductions inside Polars can differ in low-order floating-point bits across thread schedules. Quantizing output floats to 6 decimal places guarantees byte-identical report artifacts across identical runs.
- **Guarantee Maintained**: Guarantee G3 (Determinism).

---

### DEC-013: Integer Epoch Timestamps and Automatic Cluster Inference in Simulation
- **Decision**: Emit `submit_time`, `sim_start`, `sim_end`, `sim_wait_s`, and `run_s` as integer seconds (`Int64`) in simulator output tables, and infer a `ClusterConfig` (`min 16 nodes, 32 cores/node, 131072 MB/node`) from trace maximum allocations when no cluster YAML file is provided.
- **Rationale**: Integer second timestamps avoid timezone serialization drift during G4 interval and wait-time checks. Automatic peak-bounded inference lets `rcwa simulate` and `rcwa run` evaluate any `sacct` or SWF trace immediately without requiring manual cluster definitions.
- **Guarantee Maintained**: Guarantee G4 (Simulation Validity).

---

### DEC-014: Automated Six-Scenario Simulation and SWF Recomputation Status
- **Decision**: Execute all six counterfactual simulation scenarios (`baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, `all`) automatically when building reports (`include_simulation=True`) unless precomputed scenarios are supplied; mark Class 4 recomputation as `"not available"` for SWF traces; hide the Markdown Result Cache Recommendations section when no cohort qualifies.
- **Rationale**: Ensures single-command reports (`rcwa run`, `rcwa report`) contain full scenario deltas and SWF audit clarity without speculative heuristics or cluttering Markdown reports with empty tables.
- **Guarantee Maintained**: Guarantee G1 accuracy and Guarantee G3 report determinism.

---

### DEC-015: Monotonic Submit Offsets and Bounded Lookahead Backfill
- **Decision**: Distribute synthetic trace submission timestamps monotonically (`35`-second cadence incremented per profile) rather than wrapping modulo fixed days; bound EASY-backfill candidate testing in `rcwa/simulate.py` to the first `50` waiting jobs (`max_test = 50`); clamp job requests exceeding single-node hardware envelopes to the node limit.
- **Rationale**: Modulo wrapping concentrates unrelated jobs at identical timestamps, inducing artificial queue starvation. Bounded 50-job backfill lookahead mirrors Slurm `bf_max_job_test` behavior, eliminating quadratic scheduling overhead, while node-envelope clamping prevents unfulfillable recommendations from deadlocking simulation queues.
- **Guarantee Maintained**: Guarantee G4 (Simulation Validity) and high simulation throughput.

---

### DEC-016: Exact Pinned Dependencies and Zero External Telemetry
- **Decision**: Pin exact versions for all runtime (`polars==1.14.0`, `pyarrow==18.1.0`, `numpy==2.1.3`, `pydantic==2.10.3`, `typer==0.15.1`, `pyyaml==6.0.2`) and development dependencies in [`pyproject.toml`](../pyproject.toml), with zero external HTTP calls, analytics SDKs, or telemetry hooks in `rcwa/`.
- **Rationale**: Prevents silent behavior drift from floating transitive dependencies and guarantees safe offline operation inside restricted institutional clusters.
- **Guarantee Maintained**: Guarantee G3 (Determinism) and offline hermetic operation.

---

### DEC-017: Active Job Exclusion and Zero-Runtime Early Failure Retention
- **Decision**: Filter `RUNNING` and `PENDING` jobs prior to waste attribution (recording excluded counts under report Data Quality metrics), while retaining completed/terminated jobs with `run_s == 0` under Class 3 (`early_failure`).
- **Rationale**: Active and queued jobs lack terminal accounting counters and must not pollute historical utilization metrics, whereas zero-runtime failures represent real scheduler allocation churn that contributes to early-failure triage.
- **Guarantee Maintained**: Guarantee G1 (Conservation) over terminal accounting records.

---

### DEC-018: `.extern*` Step Exclusion in Slurm Step Rollups
- **Decision**: Aggregate Slurm step rows by taking the maximum `MaxRSS` across child steps while summing `TotalCPU` strictly across non-`.extern*` steps (`not step_id.startswith("extern")`), falling back to parent row counters only when child step metrics are absent.
- **Rationale**: Slurm `.extern` steps record PAM and cgroup lifecycle overhead outside user computation; excluding `.extern*` `TotalCPU` prevents spurious CPU inflation while retaining full peak memory measurements.
- **Guarantee Maintained**: Accurate CPU utilization and Class 2 attribution.

---

### DEC-019: Explicit Scope Boundaries and Canonical GPU Preservation
- **Decision**: Ingest and preserve `req_gpus` and `alloc_gpus` from `ReqTRES`/`AllocTRES` (`gres/gpu`, typed GPUs, `gpu`) in the 27-field canonical table, while excluding GPU waste attribution, network fabric topology, job preemption, fair-share priority decay, and live Slurm hooks from attribution and simulation.
- **Rationale**: Captures GPU reservation fields for downstream schema stability while keeping core CPU/memory conservation and calibrated FCFS EASY-backfill simulation self-contained and verifiable.
- **Guarantee Maintained**: Scope clarity, Guarantee G1 exactness, and Guarantee G4 simulator calibration.
