# Project Architecture and Interface Reference

## System Overview

`research-cluster-waste-attributor` (`rcwa`) is an offline Python package and CLI toolkit for batch compute cluster accounting analysis. It ingests Slurm `sacct` pipe-delimited exports and Standard Workload Format (`SWF`) logs into a unified 27-field Apache Arrow and Polars canonical schema, partitions reserved core-seconds and memory megabyte-seconds across four mutually exclusive waste classes and utilized consumption under exact conservation guarantees, generates safety-guarded resource rightsizing recommendations, replays workloads through a deterministic EASY-backfill discrete-event simulator, calibrates baseline wait predictions against historical trace waits, and exports deterministic Markdown, JSON, and CSV reports.

---

## Data Flow Architecture

```text
[ sacct export / SWF trace ]
            │
            ▼
[ Adapters: sacct.py / swf.py ] ──► [ normalize.py ]
                                            │
                                            ▼
                               [ Canonical Job Table (Arrow / Polars) ]
                                            │
               ┌────────────────────────────┼───────────────────────────┐
               ▼                            ▼                           ▼
      [ retries.py / recompute.py ]   [ groups.py ]               [ rcwa-wrap ]
               │                            │                           │
               ▼                            ▼                           │
      [ attribute.py ]             [ recommend.py ]                     │
   (Conservation G1)               (Guardrails G2)                      │
               │                            │                           │
               └────────────────────────────┼───────────────────────────┘
                                            │
                                            ▼
                                  [ simulate.py ]
                                (EASY-backfill G4)
                                            │
                                            ▼
                                  [ calibrate.py ]
                                            │
                                            ▼
                                   [ report.py ]
                         (Reclaim list, G3 Determinism)
```

---

## Capability Inventory

| # | Capability | Implementation | Summary |
|---|---|---|---|
| 1 | Package & Build Harness | [`pyproject.toml`](pyproject.toml), [`Makefile`](Makefile), [`Dockerfile`](Dockerfile) | Pinned runtime/dev dependencies, Apache-2.0 license, CI workflow, 13 Make targets |
| 2 | Slurm `sacct` Ingestion | [`rcwa/adapters/sacct.py`](rcwa/adapters/sacct.py) | Pipe-delimited parser over 26 Slurm fields; warns on extra columns; rolls up step `MaxRSS` max and `TotalCPU` sum excluding `.extern*`; decomposes arrays/pack jobs |
| 3 | SWF Format Ingestion | [`rcwa/adapters/swf.py`](rcwa/adapters/swf.py) | 18-field parser with gzip support and `;` header pragma extraction (`UnixStartTime`, `MaxProcs`, `MaxNodes`, `Note`); maps `-1` sentinels to `null` |
| 4 | Normalization Engine | [`rcwa/normalize.py`](rcwa/normalize.py) | Parses `D-HH:MM:SS` / `MM:SS.mmm` durations, `K/M/G/T/P` + `c/n` memory suffixes, state qualifiers, `ReqTRES`/`AllocTRES`, job IDs, and `Comment` hashes |
| 5 | Canonical Job Model | [`rcwa/model.py`](rcwa/model.py) | Lazy PyArrow schema (`CANONICAL_ARROW_SCHEMA`), Polars schema (`POLARS_CANONICAL_SCHEMA`), and Pydantic v2 `CanonicalJobRecord` across 27 fields |
| 6 | Active Job Filtering & Zero-Run Retention | [`rcwa/attribute.py`](rcwa/attribute.py) | Excludes `RUNNING`/`PENDING` into data-quality counts; retains `run_s == 0` as Class 3 `early_failure` |
| 7 | Conservation Waste Partitioning (G1) | [`rcwa/attribute.py`](rcwa/attribute.py) | Single-pass precedence: Class 3 -> Class 4 -> Class 2 (`class2_idle_core_s`) & Class 1 (`class1_over_mem_mb_s`) -> Used / Unattributed |
| 8 | Retry Chain Linkage | [`rcwa/retries.py`](rcwa/retries.py) | Deterministic 1-to-1 earliest candidate matching by `(user, command_hash or job_name)` within `retry_window_s` (24h), resolving multi-hop roots and chain costs |
| 9 | Declared Input Wrapper (`rcwa-wrap`) | [`rcwa/wrap.py`](rcwa/wrap.py) | Computes SHA-256 or `size_mtime` hashes over comma-separated `--inputs`, normalizes commands, updates Slurm `Comment`, writes `$RCWA_DIR/<job_id>.json` sidecars |
| 10 | Recomputation & Result Cache Analysis | [`rcwa/recompute.py`](rcwa/recompute.py) | Classifies `declared_inputs` Class 4 within `recompute_window_s` (30d); flags `command_only` as `possible_recompute`; simulates cache hits; SWF returns `"not_available"` |
| 11 | Job Grouping & Reclaim Scoring | [`rcwa/groups.py`](rcwa/groups.py) | Groups by `(user, job_name or command_hash)` plus `account`, `partition`, `user` rollups; scores by weighted core + GB hours with top-5 evidence IDs |
| 12 | Safety-Guarded Rightsizing (G2) | [`rcwa/recommend.py`](rcwa/recommend.py) | P99 * 1.2 memory floored at all-state max RSS; OOM escalation overrides `min_samples` and zeros `reclaimable_gb_hours`; short-job CPU suppression; timeout P99 * 1.5 |
| 13 | EASY-Backfill Cluster Simulator (G4) | [`rcwa/simulate.py`](rcwa/simulate.py) | Heap-driven FCFS + 50-candidate non-delaying EASY backfill on homogeneous/partitioned YAML configs or inferred clusters across 6 scenarios |
| 14 | Historical Trace Calibration | [`rcwa/calibrate.py`](rcwa/calibrate.py) | Evaluates baseline simulation waits against recorded `wait_s` using Median Absolute Error, Mean AE, P95 AE, and Spearman rank correlation |
| 15 | Deterministic Multi-Format Reporting (G3) | [`rcwa/report.py`](rcwa/report.py) | Renders sorted, 6-decimal rounded Markdown, JSON, and CSV reports with reclaim lists, early failures, result caches, scenarios, calibration, and data quality |
| 16 | Synthetic Trace Generator & Benchmarks | [`rcwa/synth.py`](rcwa/synth.py), [`bench/run.py`](bench/run.py), [`bench/hardware.py`](bench/hardware.py) | Generates `sacct` workloads with `.truth.parquet` planted waste labels and evaluates throughput, peak RSS, G1/G2 invariants, and per-class accuracy |

---

## Interface Contracts

### 1. Canonical Model (`rcwa.model`)

27 canonical columns in [`POLARS_CANONICAL_SCHEMA`](rcwa/model.py) and `CANONICAL_ARROW_SCHEMA`:
- **Identifiers & Provenance**: `job_id: String`, `parent_job_id: String?`, `source: String` (`"sacct"` or `"swf"`), `user: String`, `account: String?`, `partition: String?`, `job_name: String?`, `command_hash: String?`, `input_hash: String?`
- **Timestamps & Durations**: `submit_time: Datetime("ms", "UTC")`, `start_time: Datetime("ms", "UTC")?`, `end_time: Datetime("ms", "UTC")?`, `wait_s: Int64`, `run_s: Int64` (stored as `timestamp("s", tz="UTC")` in PyArrow)
- **Status**: `state: String` (`JobState` 10-value enum: `COMPLETED`, `FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `CANCELLED`, `PREEMPTED`, `RUNNING`, `PENDING`, `OTHER`), `exit_code: Int32?`
- **Resources & Derived Reservations**: `req_cpus: Int32`, `alloc_cpus: Int32`, `cpu_time_used_s: Float64?`, `req_mem_mb: Int64?`, `max_rss_mb: Int64?`, `req_gpus: Int32`, `alloc_gpus: Int32`, `nodes: Int32`, `node_list: String?`, `reserved_core_s: Int64`, `reserved_mem_mb_s: Int64?`

### 2. Adapters (`rcwa.adapters.sacct`, `rcwa.adapters.swf`) & Normalization (`rcwa.normalize`)

```python
def parse_sacct(source: Path | IO[str] | str) -> pl.DataFrame: ...
def parse_swf(source: Path | IO[str] | str, return_pragmas: bool = False) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]: ...
def parse_swf_with_pragmas(source: Path | IO[str] | str) -> tuple[pl.DataFrame, dict[str, Any]]: ...
def normalize_to_canonical(df: pl.DataFrame, source_type: str = "sacct") -> pl.DataFrame: ...
```

### 3. Attribution, Retries, Recomputation & Grouping

```python
def detect_retry_chains(df: pl.DataFrame, retry_window_s: int = 86400) -> pl.DataFrame: ...
def merge_sidecars(df: pl.DataFrame, sidecar_dir: Path | str | None = None) -> pl.DataFrame: ...
def detect_recomputations(df: pl.DataFrame, recompute_window_s: int = 2592000) -> pl.DataFrame: ...
def attribute_trace(canonical_df: pl.DataFrame, policy: Any = None) -> pl.DataFrame: ...
def group_jobs(attributed_df: pl.DataFrame, policy: Any = None, group_keys: list[str] | None = None) -> pl.DataFrame: ...
def generate_secondary_rollups(attributed_df: pl.DataFrame, policy: Any = None) -> dict[str, pl.DataFrame]: ...
```

### 4. Recommendations (`rcwa.recommend`)

```python
def recommend_jobs(
    attributed_df: pl.DataFrame,
    policy: Any = None,
    grouped_df: pl.DataFrame | None = None,
    trace_path: str | Path | None = None,
) -> pl.DataFrame: ...
```

### 5. Simulation & Calibration (`rcwa.simulate`, `rcwa.calibrate`)

```python
def load_cluster_config(cluster_path: Path | str | ClusterConfig | None) -> ClusterConfig: ...
def infer_cluster_from_trace(df: pl.DataFrame) -> ClusterConfig: ...
def simulate_trace(
    df: pl.DataFrame,
    cluster: ClusterConfig | None = None,
    scenario: str = "baseline",
    policy: Any = None,
) -> tuple[pl.DataFrame, dict[str, Any]]: ...
def compute_calibration_metrics(sim_df: pl.DataFrame, historical_df: pl.DataFrame) -> dict[str, Any]: ...
def calibrate_trace(trace_path: Path | str, cluster_path: Path | str | None = None) -> dict[str, Any]: ...
```

### 6. Reporting (`rcwa.report`)

```python
def build_report_data(
    canonical_df: pl.DataFrame,
    attributed_df: pl.DataFrame,
    policy: Any = None,
    cluster: Any = None,
    simulation_scenarios: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    include_simulation: bool = True,
) -> dict[str, Any]: ...
def render_markdown_report(report_data: dict[str, Any]) -> str: ...
def render_csv_report(report_data: dict[str, Any]) -> str: ...
```

---

## Repository Layout

```text
research-cluster-waste-attributor/
├── README.md                    # System overview, quickstart, guarantees, ADRs, benchmark results
├── PROJECT.md                   # System architecture and Python interface reference
├── TEST_READY.md                # Test suite readiness and collection verification summary
├── LICENSE                      # Apache-2.0 License
├── pyproject.toml               # Pinned dependencies, Ruff/Pyright/pytest config, scripts rcwa / rcwa-wrap
├── Makefile                     # 13 task targets
├── Dockerfile                   # Python 3.12-slim image executing `make test`
├── .github/workflows/ci.yml     # CI pipeline (lint, typecheck, test, bench-smoke)
├── rcwa/
│   ├── __init__.py              # Package version and Click compatibility bridges
│   ├── cli.py                   # Typer CLI entrypoint (`rcwa`)
│   ├── model.py                 # Canonical Arrow/Polars/Pydantic job model
│   ├── adapters/
│   │   ├── sacct.py             # Slurm sacct parser
│   │   └── swf.py               # Standard Workload Format parser
│   ├── normalize.py             # Durations, memory units, states, TRES, job ID decomposition
│   ├── attribute.py             # Single-pass 4-class attribution engine (G1)
│   ├── retries.py               # Causal failure retry chain detector
│   ├── groups.py                # Grouping, scoring, secondary rollups, evidence selection
│   ├── recompute.py             # Declared input recomputation and result cache simulation
│   ├── recommend.py             # Guarded percentile rightsizing engine (G2)
│   ├── simulate.py              # Event-driven EASY-backfill scheduler simulator (G4)
│   ├── calibrate.py             # Historical trace wait-time calibration
│   ├── report.py                # Deterministic Markdown, JSON, CSV report generators (G3)
│   ├── wrap.py                  # Declared input hashing wrapper CLI (`rcwa-wrap`)
│   └── synth.py                 # Synthetic trace and truth generator
├── policies/default.yaml        # Default policy weights, windows, and safety guardrails
├── clusters/example.yaml        # Example cluster topology definition
├── scripts/download_data.py     # Public SWF trace downloader
├── bench/
│   ├── run.py                   # Benchmark harness
│   ├── hardware.py              # Host hardware telemetry formatter
│   └── results/                 # Recorded benchmark reports (bench.md, bench.csv)
├── tests/
│   ├── unit/                    # 21 unit test modules (including vocabulary and conservation checks)
│   ├── property/                # Hypothesis G2 safety property tests
│   ├── golden/                  # G3 determinism and golden output regression checks
│   ├── e2e/                     # 28 opaque-box CLI E2E test modules across Tiers 1-4
│   └── fixtures/                # 40 deterministic test fixtures across 10 categories
└── docs/                        # Specification, design, decisions, ADRs, component & testing docs
```

---

## Guarantees Verification Matrix

| Guarantee | Description | Verification Suite |
|---|---|---|
| **G1: Conservation** | For every job and cluster sum, `reserved = used + waste + unattributed` in exact integer `core_s` and `mb_s` | [`tests/unit/test_conservation.py`](tests/unit/test_conservation.py), [`tests/e2e/tier4_real_world/test_guarantee_g1_conservation_suite.py`](tests/e2e/tier4_real_world/test_guarantee_g1_conservation_suite.py) |
| **G2: Safety Guardrails** | Recommended memory never below cohort peak RSS; OOM cohorts escalate (`ceil(max * 1.5)`) and zero `reclaimable_gb_hours`; non-OOM cohorts below `min_samples` emit `None` | [`tests/property/test_safety_guardrails.py`](tests/property/test_safety_guardrails.py) (10,000 groups), [`tests/e2e/tier4_real_world/test_guarantee_g2_safety_suite.py`](tests/e2e/tier4_real_world/test_guarantee_g2_safety_suite.py) |
| **G3: Determinism** | Identical trace inputs and YAML configs yield byte-identical Markdown, JSON, CSV, and Parquet outputs | [`tests/golden/test_determinism.py`](tests/golden/test_determinism.py), [`tests/e2e/tier4_real_world/test_guarantee_g3_determinism_suite.py`](tests/e2e/tier4_real_world/test_guarantee_g3_determinism_suite.py) |
| **G4: Simulator Validity** | Every job schedules once per scenario, `sim_start >= submit_time`, and cluster/node core and memory limits hold at all event steps | [`tests/unit/test_simulate.py`](tests/unit/test_simulate.py), [`tests/e2e/tier4_real_world/test_guarantee_g4_simulation_validity_suite.py`](tests/e2e/tier4_real_world/test_guarantee_g4_simulation_validity_suite.py) |

---

## Prohibited Vocabulary Policy

All repository source code, test suites, configuration files, and documentation enforce zero occurrences of the nine excluded promotional/vague terms audited continuously by [`tests/unit/test_forbidden_words.py`](tests/unit/test_forbidden_words.py).
