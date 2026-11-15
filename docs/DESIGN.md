# High-Level System Design

## 1. Overview and Problem Statement

Batch schedulers on high-performance computing and research clusters allocate compute cores and memory from user-submitted requests rather than physical runtime consumption. Across quantitative modeling, simulation, and data-intensive workloads, reserved capacity diverges from utilized capacity through four distinct causes:

1. **Memory Over-Request (Class 1)**: Requested memory far above observed peak resident set size (`MaxRSS`).
2. **Idle Reserved CPU (Class 2)**: Multi-core reservations running under-threaded or I/O-stalled execution.
3. **Failed and Retried Work (Class 3)**: Capacity consumed by jobs terminating with failure, out-of-memory kills, wallclock timeouts, node faults, post-start cancellations, or zero-duration starts, plus linked resubmissions.
4. **Redundant Recomputation (Class 4)**: Completed executions running identical normalized commands against identical declared input hashes within a configured horizon.

Lowering submission limits blindly introduces production disruption and cascading out-of-memory failures. `research-cluster-waste-attributor` (`rcwa`) ingests accounting traces, partitions every reserved core-second and megabyte-second into non-overlapping categories under exact conservation, recommends guarded limits, and evaluates queue wait-time deltas through a calibrated EASY-backfill scheduler simulator before limits are adjusted.

---

## 2. Core Architectural Principles and Guarantees

The architecture enforces four verifiable guarantees:

```text
+------------------------------------------------------------------------------------+
|                                SYSTEM GUARANTEES                                   |
+------------------------------------------------------------------------------------+
|  [G1] Conservation:                                                                |
|       For every evaluated job and dimension:                                       |
|       Reserved = Utilized + Attributed Waste + Unattributed                        |
|       Holds strictly in integer core-seconds and megabyte-seconds.                 |
+------------------------------------------------------------------------------------+
|  [G2] Safety Guardrails:                                                           |
|       Recommended memory is never below observed peak RSS across all states.       |
|       Groups with OOM kills escalate memory and contribute zero reclaimable mem.   |
|       Non-OOM groups below min_samples receive no resource recommendations.          |
+------------------------------------------------------------------------------------+
|  [G3] Determinism:                                                                 |
|       Identical input accounting traces and YAML configurations yield              |
|       byte-identical Parquet, CSV, JSON, and Markdown outputs.                     |
+------------------------------------------------------------------------------------+
|  [G4] Simulator Validity:                                                          |
|       Every eligible job schedules once per scenario.                              |
|       Simulated start time is never earlier than submit time.                      |
|       Allocated cores and memory never exceed cluster node capacities.             |
+------------------------------------------------------------------------------------+
```

---

## 3. End-to-End System Pipeline

Traces traverse eight sequential processing stages in a single OS process:

```text
[ Raw Accounting Traces ]
  - Slurm sacct export (`sacct -a -P --units=M`)
  - Standard Workload Format (`SWF` / `.swf.gz`)
            │
            ▼
┌─────────────────────────┐
│     Ingest Adapters     │ ◄─── Decomposes array/pack jobs, rolls up steps
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Normalization Engine   │ ◄─── Unifies durations (s), memory (MB), states, TRES
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Canonical Job Record   │ ◄─── 27-field Apache Arrow & Polars tabular model
└───────────┬─────────────┘
            │
            ├────────────────────────────────────────┬────────────────────────┐
            ▼                                        ▼                        ▼
┌─────────────────────────┐              ┌──────────────────────┐  ┌──────────────────┐
│  Waste Attribution      │              │ Failure & Retry      │  │ Recomputation    │
│  (Precedence Cascade)   │              │ Chain Tracker        │  │ Detector         │
└───────────┬─────────────┘              └──────────┬───────────┘  └────────┬─────────┘
            │                                        │                       │
            └────────────────────────────────────────┴───────────────────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Group Aggregation &  │ ◄─── Computes weighted reclaim scores
                         │  Reclaim Ranking      │      and top-5 evidence job IDs
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Recommendation       │ ◄─── P99 rightsizing, OOM escalation,
                         │  Engine & Guardrails  │      short-job CPU & timeout guards
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  EASY-Backfill        │ ◄─── Replays six counterfactual
                         │  Scheduler Simulator  │      cluster scenarios
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Calibration Engine   │ ◄─── Evaluates baseline replay vs
                         └───────────┬───────────┘      historical queue waits (MAE/rho)
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Reporting & Export   │ ◄─── Deterministic MD, JSON, CSV
                         └───────────────────────┘
```

---

## 4. Architectural Components

The codebase separates concerns into focused package modules, CLI wrappers, and verification harnesses:

| Component | Implementation | Documentation | Description |
|---|---|---|---|
| **CLI & Wrapper** | [`rcwa/cli.py`](../rcwa/cli.py), [`rcwa/wrap.py`](../rcwa/wrap.py) | [`docs/INPUTS.md`](INPUTS.md) | Typer CLI (`rcwa`) and declared input checksum wrapper (`rcwa-wrap`). |
| **Canonical Model** | [`rcwa/model.py`](../rcwa/model.py) | [`docs/components/model.md`](components/model.md) | 27-field PyArrow schema, Polars schema, and Pydantic `CanonicalJobRecord`. |
| **Ingest Adapters** | [`rcwa/adapters/`](../rcwa/adapters/) | [`docs/components/adapters.md`](components/adapters.md) | Slurm `sacct` pipe-delimited parser and SWF / gzip parser with pragmas. |
| **Normalization** | [`rcwa/normalize.py`](../rcwa/normalize.py) | [`docs/components/normalize.md`](components/normalize.md) | Unit conversions (KB/MB/GB/TB/PB + `c`/`n`), durations, TRES strings, state mappings. |
| **Attribution** | [`rcwa/attribute.py`](../rcwa/attribute.py) | [`docs/components/attribute.md`](components/attribute.md) | Single-pass non-overlapping precedence cascade enforcing Guarantee G1. |
| **Retry Tracker** | [`rcwa/retries.py`](../rcwa/retries.py) | [`docs/components/retries.md`](components/retries.md) | 1-to-1 earliest candidate linking of failed jobs to resubmission chains. |
| **Job Grouping** | [`rcwa/groups.py`](../rcwa/groups.py) | [`docs/components/groups.md`](components/groups.md) | Cohort aggregation, secondary rollups, weighted scoring, top-5 evidence extraction. |
| **Recomputation** | [`rcwa/recompute.py`](../rcwa/recompute.py), [`rcwa/wrap.py`](../rcwa/wrap.py) | [`docs/components/recompute.md`](components/recompute.md) | Sidecar merging, Class 4 detection, `command_only` flagging, result cache estimation. |
| **Recommendations** | [`rcwa/recommend.py`](../rcwa/recommend.py) | [`docs/components/recommend.md`](components/recommend.md) | P99 rightsizing formulas and Guarantee G2 safety guardrails. |
| **Simulator** | [`rcwa/simulate.py`](../rcwa/simulate.py) | [`docs/components/simulate.md`](components/simulate.md) | Discrete-event EASY-backfill scheduler supporting homogeneous and partitioned nodes. |
| **Calibration** | [`rcwa/calibrate.py`](../rcwa/calibrate.py) | [`docs/components/calibrate.md`](components/calibrate.md) | Statistical error and Spearman rank validation against recorded queue waits. |
| **Reporting** | [`rcwa/report.py`](../rcwa/report.py) | [`docs/components/report.md`](components/report.md) | Deterministic 6-decimal quantized Markdown, JSON, and CSV output generators. |
| **Synthetic Generator** | [`rcwa/synth.py`](../rcwa/synth.py) | [`docs/components/synth.md`](components/synth.md) | Seeded synthetic `sacct` trace generator paired with `.truth.parquet` labels. |

---

## 5. Data Flow and Lifecycle

1. **Ingestion & Normalization**:
   - Raw records stream through Python text/gzip readers into vectorized Polars and PyArrow columns (`source` is `"sacct"` or `"swf"`).
   - Durations formatted as `D-HH:MM:SS`, `HH:MM:SS`, or `MM:SS.mmm` convert to integer `run_s` and floating `cpu_time_used_s`.
   - Memory strings (`4000Mc`, `16G`, `500000K`) resolve to cluster-total integer megabytes (`req_mem_mb`); SWF per-processor fields multiply by `alloc_cpus` and divide by `1024`.
   - Child step records (`.batch`, `.0`, `.extern`) roll up into parent job rows: `max_rss_mb` takes the step maximum, while `cpu_time_used_s` sums `TotalCPU` excluding `.extern` and `.extern*` overhead steps.
   - Array tasks (`10001_0`) and heterogeneous pack components (`10002+0`) emit distinct canonical rows referencing `parent_job_id`.

2. **Attribution & Partitioning**:
   - Jobs in active states (`RUNNING`, `PENDING`) are removed prior to attribution and summarized in Data Quality exclusion counts.
   - Zero-duration terminated jobs (`run_s == 0`) remain and are assigned to Class 3 (`early_failure`).
   - Null `reserved_mem_mb_s` values normalize to `0`, and `reserved_core_s` (`alloc_cpus * run_s`) and `reserved_mem_mb_s` (`req_mem_mb * run_s`) partition via the precedence cascade:
     $$\text{Class 3 (Failed)} \to \text{Class 4 (Recompute)} \to \text{Class 2 (Idle CPU)} \mathbin{/} \text{Class 1 (Over-Requested Memory)} \to \text{Utilized}$$
   - Missing `cpu_time_used_s` or `max_rss_mb` on otherwise successful jobs assigns reservations directly to `unattributed_core_s` or `unattributed_mem_mb_s`.
   - Guarantee G1 asserts exact integer equality:
     $$\text{Reserved} \equiv \text{Utilized} + \text{Waste} + \text{Unattributed}$$

3. **Aggregation & Guarded Recommendations**:
   - Attributed rows group by `(user, job_name or command_hash)` alongside secondary rollups (`account`, `partition`, `user`).
   - Any cohort containing `OUT_OF_MEMORY` terminations bypasses `min_samples`, receives an upward memory escalation (`ceil(max_base * 1.5)` floored at `observed_max_rss`), and contributes `0.0` to `reclaimable_gb_hours`.
   - Non-OOM cohorts meeting `min_samples` receive `P99 * 1.2` memory limits floored at the all-state historical peak RSS, clamped P99 CPU targets (unless median or all job durations fall below `min_run_s`), and `P99 * 1.5` wallclock recommendations when timeouts occur. Non-OOM cohorts below `min_samples` receive `None` across recommendations.

4. **Counterfactual Simulation & Calibration**:
   - Nodes initialize from explicit homogeneous/partitioned YAML topology definitions or infer capacity from peak trace allocations (`min 16 nodes, 32 cores/node, 131072 MB/node`).
   - The discrete-event heap processes completions before arrivals at each second, scheduling the head of FCFS queue `wait_queue` or reserving future capacity for the head and scanning up to 50 queued candidates for non-delaying backfill.
   - Replay covers `baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, and `all`. Calibration measures baseline simulated wait against historical `wait_s`.

---

## 6. Execution Environment and Scope Boundaries

- **Technology Stack**: Python `3.11+` (`>=3.11` runtime, Python `3.12` static analysis target), Polars `1.14.0`, PyArrow `18.1.0`, NumPy `2.1.3`, Pydantic `2.10.3`, Typer `0.15.1`, PyYAML `6.0.2`.
- **Automation Harness (`Makefile`)**: 13 standard targets (`all`, `setup`, `lint`, `typecheck`, `test`, `data`, `synth`, `run`, `calibrate`, `bench`, `bench-smoke`, `goldens`, `docker`).
- **Process & Storage Model**: Single-process execution with zero external worker daemons, relational servers, or telemetry clients. Downloaded public traces remain isolated in gitignored `data/raw/`.
- **Explicit Scope Limits**:
  - Offline analysis only (no live Slurm plugins or SPANK hooks).
  - Canonical schema tracks `req_gpus` and `alloc_gpus` from TRES fields without GPU utilization attribution.
  - Discrete-event simulator omits network/switch topology, job preemption, fair-share decay, and dependency DAG constraints.
- **Measured Single-Process Throughput**: `34,610.4` jobs/s Slurm `sacct` ingestion, `90,618.1` jobs/s SWF fixture ingestion, and `90,486.8` jobs/s baseline simulation at `310.77 MB` peak RSS on `20k` synthetic records ([`bench/results/bench.md`](../bench/results/bench.md)).
