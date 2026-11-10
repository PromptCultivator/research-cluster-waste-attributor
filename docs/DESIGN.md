# High-Level System Design

## 1. Overview and Problem Statement

Batch schedulers on high-performance computing and research clusters allocate compute cores and system memory based on limits requested by users rather than physical consumption during execution. Across quantitative trading, scientific computing, and financial modeling workloads, reserved capacity deviates significantly from utilized capacity due to four systematic causes:

1. **Memory Over-Request (Class 1)**: Memory requested far above the job's peak resident set size (MaxRSS).
2. **Idle Reserved CPU (Class 2)**: Multi-core allocations where code executes largely single-threaded, leaving cores unused.
3. **Failed and Retried Work (Class 3)**: Compute consumed by jobs that crash, exceed memory limits (OOM), hit wallclock time limits, or fail on host nodes, followed by resubmissions.
4. **Redundant Recomputation (Class 4)**: Successful executions that compute outputs identical to earlier runs given identical input data and commands.

Arbitrarily reducing limits across cluster users introduces risks of production job failure, out-of-memory terminations, and delayed pipelines. The Research Cluster Waste Attributor (`rcwa`) provides an end-to-end framework that ingests scheduler accounting data, partitions every reserved core-second and megabyte-second into non-overlapping waste classes, computes right-sized allocations protected by safety guardrails, and simulates the schedule replay through a discrete-event scheduler simulator before limits are altered in production.

---

## 2. Core Architectural Principles and Guarantees

The design enforces four verifiable guarantees:

```
+------------------------------------------------------------------------------------+
|                                SYSTEM GUARANTEES                                   |
+------------------------------------------------------------------------------------+
|  [G1] Conservation:                                                                |
|       For every job and dimension:                                                 |
|       Reserved = Utilized + Attributed Waste + Unattributed                        |
|       Holds exactly in integer core-seconds and megabyte-seconds.                  |
+------------------------------------------------------------------------------------+
|  [G2] Safety Guardrails:                                                           |
|       Recommended memory is never below observed peak RSS * safety factor.         |
|       Groups with OOM kills receive allocation increases, never reductions.        |
|       Groups below sample floor receive no recommendation.                         |
+------------------------------------------------------------------------------------+
|  [G3] Determinism:                                                                 |
|       Identical input accounting records and policy configurations generate        |
|       byte-identical reports, tables, and scenario projections.                    |
+------------------------------------------------------------------------------------+
|  [G4] Simulator Validity:                                                          |
|       Every job schedules exactly once per scenario.                               |
|       Scheduled start time is never earlier than submit time.                     |
|       Allocations never exceed cluster node core and memory capacities.            |
+------------------------------------------------------------------------------------+
```

---

## 3. End-to-End System Pipeline

The system processes accounting traces through eight sequential stages:

```
[ Raw Accounting Traces ]
  - Slurm sacct export
  - Standard Workload Format (SWF)
            │
            ▼
┌─────────────────────────┐
│     Ingest Adapters     │ ◄─── Decomposes array/pack jobs, parses steps
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Normalization Engine   │ ◄─── Unifies units (MB, seconds), state mappings, TRES
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  Canonical Job Record   │ ◄─── PyArrow / Polars tabular storage (32-byte layout)
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
                         │  Group Aggregation &  │ ◄─── Evaluates sample floors,
                         │  Reclaim Ranking      │      scores reclaimable capacity
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Recommendation       │ ◄─── P99 rightsizing, OOM escalation,
                         │  Engine & Guardrails  │      timeout safety multipliers
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  EASY-Backfill        │ ◄─── Simulates replay across
                         │  Scheduler Simulator  │      multiple policy scenarios
                         └───────────┬───────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Calibration Engine   │ ◄─── Compares baseline replay vs
                         └───────────┬───────────┘      historical wait times (MAE/Spearman)
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │  Reporting & Export   │ ◄─── Markdown, JSON, CSV summaries
                         └───────────────────────┘
```

---

## 4. Architectural Components

The repository is modularized into dedicated components:

| Component | Implementation | Documentation | Description |
|---|---|---|---|
| **Canonical Model** | `rcwa/model.py` | [docs/components/model.md](components/model.md) | Standard Arrow schema, Polars lazy expressions, and Pydantic record models. |
| **Ingest Adapters** | `rcwa/adapters/` | [docs/components/adapters.md](components/adapters.md) | Slurm `sacct` pipe-delimited parser and Standard Workload Format (SWF) parser. |
| **Normalization** | `rcwa/normalize.py` | [docs/components/normalize.md](components/normalize.md) | Unit conversions (KB/MB/GB/TB), durations, TRES strings, and state categorizations. |
| **Attribution** | `rcwa/attribute.py` | [docs/components/attribute.md](components/attribute.md) | Single-pass non-overlapping precedence cascade enforcing Guarantee G1. |
| **Retry Tracker** | `rcwa/retries.py` | [docs/components/retries.md](components/retries.md) | Temporal linking of failed jobs to resubmission sequences within configurable windows. |
| **Job Grouping** | `rcwa/groups.py` | [docs/components/groups.md](components/groups.md) | Workload categorization by user/command, secondary rollups, and evidence extraction. |
| **Recomputation** | `rcwa/recompute.py`, `rcwa/wrap.py` | [docs/components/recompute.md](components/recompute.md) | Input hashing CLI wrapper, Slurm comment/sidecar readers, and duplicate detection. |
| **Recommendations** | `rcwa/recommend.py` | [docs/components/recommend.md](components/recommend.md) | P99 rightsizing formulas and Guarantee G2 safety constraints. |
| **Simulator** | `rcwa/simulate.py` | [docs/components/simulate.md](components/simulate.md) | Discrete-event EASY-backfill scheduler supporting multiple counterfactual scenarios. |
| **Calibration** | `rcwa/calibrate.py` | [docs/components/calibrate.md](components/calibrate.md) | Statistical validation of simulator baseline against observed trace wait times. |
| **Reporting** | `rcwa/report.py` | [docs/components/report.md](components/report.md) | Output generation in Markdown, JSON, and CSV with data quality auditing. |
| **Synthetic Generator** | `rcwa/synth.py` | [docs/components/synth.md](components/synth.md) | Workload generator with planted waste categories and known ground-truth outputs. |

---

## 5. Data Flow and In-Memory Lifecycle

1. **Ingestion & Normalization**:
   - Raw records are read from text files into columnar chunks.
   - Durations formatted as `D-HH:MM:SS` or `MM:SS.mmm` convert to integer seconds.
   - Memory specifications (`4000Mc`, `16G`, `500000K`) resolve to integer megabytes.
   - Job step records (`.batch`, `.0`) roll up into parent job rows: peak RSS is the maximum over steps; CPU time is the sum of step `TotalCPU` excluding `.extern`.
   - Heterogeneous job steps (`+0`, `+1`) and array tasks (`_0`, `_1`) evaluate as distinct jobs with `parent_job_id` references.

2. **Attribution & Partitioning**:
   - Jobs in active states (`RUNNING`, `PENDING`) are excluded from attribution and tracked in data quality audit counts.
   - For completed and terminated jobs, `reserved_core_s` (`alloc_cpus * run_s`) and `reserved_mem_mb_s` (`req_mem_mb * run_s`) are partitioned strictly via the precedence cascade:
     $$\text{Class 3 (Failed)} \to \text{Class 4 (Recompute)} \to \text{Class 2 (Idle CPU) / Class 1 (Over-Requested Memory)} \to \text{Utilized}$$
   - Any record lacking hardware consumption measurements is marked as `unattributed_missing_cpu_time` or `unattributed_missing_rss`.
   - Guarantee G1 asserts exact equality without approximation:
     $$\text{Reserved} \equiv \text{Utilized} + \text{Waste} + \text{Unattributed}$$

3. **Aggregation & Policy Application**:
   - Attributed records group by `(user, command_hash_or_job_name)` alongside secondary aggregates (`account`, `partition`).
   - Groups meeting `min_samples` generate rightsizing recommendations. Groups with fewer samples receive explicit indicators withholding limit changes.
   - Groups displaying `OUT_OF_MEMORY` events trigger safety escalations (`req_mem_mb = ceil(max_rss * 1.5)`), excluding reclaimable memory from savings sums.

4. **Counterfactual Simulation**:
   - The cluster topology is instantiated as $N$ identical compute nodes with fixed core and memory limits.
   - Jobs are scheduled using an event heap. When queued, the head job reserves a future execution window; subsequent jobs backfill if they do not delay the reservation.
   - Replay runs across multiple scenarios: `baseline`, `mem_rightsized`, `cpu_rightsized` (fixed and proportional runtimes), `cache_dedup`, and `all`.
   - Metrics recorded per scenario include queue wait percentiles (p50, p95), makespan, node utilization, and daily completed throughput.

---

## 6. Execution Constraints and Performance Targets

- **Technology Stack**: Python 3.11+, Polars, PyArrow, NumPy, Pydantic v2, Typer, PyYAML.
- **Process Model**: Single-process tabular execution with vectorized operations in Polars and PyArrow.
- **Offline Hermetic Operation**: Unit and property test suites execute completely without external network dependencies. Trace downloads occur only via explicit invocation of `make data`.
- **Target Performance**: 1,000,000 canonical jobs pass through `baseline` simulation in under 15 minutes on a workstation. Ingestion throughput exceeds 30,000 jobs/second for Slurm `sacct` text parsing.
