# 1. research-cluster-waste-attributor

Research cluster waste attributor partitions batch-scheduler resource reservations into four non-overlapping waste classes and used consumption under exact conservation guarantees, recommends right-sized requests with safety guardrails, and simulates queue wait impact before limits change.

## 2. Status

Status: design complete

## 3. Results

The table below summarizes measured benchmark metrics across evaluation workloads. Values remain `TBD` pending formal benchmark runs on designated reference hardware.

| Metric | How Measured | Curie Trace | SP2 Trace | Synthetic (1M) |
|---|---|---|---|---|
| Reclaimable core-hours (% of trace) | Per-job attribution table | TBD | TBD | TBD |
| Reclaimable GB-hours (% of trace) | Per-job attribution table | TBD | TBD | TBD |
| Class 1 recall / precision | Planted ground truth | TBD | TBD | TBD |
| Class 2 recall / precision | Planted ground truth | TBD | TBD | TBD |
| Class 3 recall / precision | Planted ground truth | TBD | TBD | TBD |
| Class 4 recall / precision | Planted ground truth | TBD | TBD | TBD |
| Conservation check (G1) | Exact integer balance | TBD | TBD | TBD |
| Guardrail violations (G2) | Safety constraint assertions | TBD | TBD | TBD |
| Median wait change (all scenario) | Simulation replay | TBD | TBD | TBD |
| p95 wait change (all scenario) | Simulation replay | TBD | TBD | TBD |
| Calibration error (MAE wait) | Historical wait comparison | TBD | TBD | TBD |
| Calibration error (Spearman r) | Rank correlation | TBD | TBD | TBD |
| Ingest throughput (jobs/s) | Parser throughput | TBD | TBD | TBD |
| Simulation throughput (jobs/s) | EASY backfill loop | TBD | TBD | TBD |
| Peak resident memory (MB) | Max process RSS | TBD | TBD | TBD |
| Attribution coverage (%) | Attributed share of reservation | TBD | TBD | TBD |

### Benchmark Hardware Environment

```
CPU Model: TBD
Physical Cores: TBD
RAM: TBD
Operating System: Linux
Python Version: 3.12
Commit Hash: TBD
```

## 4. Quick Start

Export scheduler accounting records using Slurm `sacct`:

```bash
sacct -a -P --units=M -S 2026-01-01 -E 2026-02-01 \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine > trace.sacct
```

Acquire public evaluation traces:

```bash
make data
```

Execute the full analysis pipeline:

```bash
make run TRACE=trace.sacct
```

## 5. Problem

Research computing clusters allocate cores and memory by reservation rather than actual usage. Users request generous margins to prevent job timeouts and out-of-memory terminations. As a consequence, reserved resources diverge substantially from real consumption. Arbitrarily tightening submission limits without empirical modeling risks terminating critical jobs and disrupting research workflows.

## 6. How It Works

The attribution and simulation pipeline proceeds through sequential stages:

```
[ sacct export / SWF trace ]
             │
             ▼
[ Ingestion & Normalization ] ──► [ Canonical Job Records (Parquet) ]
                                                │
       ┌────────────────────────────────────────┼───────────────────────────────────┐
       ▼                                        ▼                                   ▼
[ Retry Chains ]                       [ Recomputation Detection ]          [ Utilization Analysis ]
       │                                        │                                   │
       └────────────────────────────────────────┼───────────────────────────────────┘
                                                │
                                                ▼
                                [ Conservation Partitioning (G1) ]
                                (Class 3 -> Class 4 -> Class 2/1)
                                                │
                                                ▼
                                  [ Grouping & Aggregation ]
                                                │
                                                ▼
                             [ Rightsizing with Guardrails (G2) ]
                                                │
                                                ▼
                               [ EASY-Backfill Simulator (G4) ]
                               (Baseline, Rightsized, Replay)
                                                │
                                                ▼
                               [ Calibration & Ranked Reporting ]
```

### Canonical Record
Every job maps to an Arrow record capturing identifiers, timestamps, elapsed times, resource allocations, measured peak memory, total CPU time, exit codes, and hashes.

### The Four Waste Classes and Precedence Rule
Reserved core-seconds and megabyte-seconds partition across four mutually exclusive classes:
1. **Class 3 (Failed / Retried Work)**: Work executed by jobs that failed, timed out, ran out of memory, or were cancelled after launch.
2. **Class 4 (Redundant Recomputation)**: Completed jobs matching an earlier completed job with identical command and declared input hashes.
3. **Class 2 (Idle Reserved CPU)**: Unused allocated core capacity on completed jobs (`reserved_core_s - cpu_time_used_s`).
4. **Class 1 (Memory Over-Request)**: Memory allocated above observed peak resident size (`(req_mem_mb - max_rss_mb) * run_s`).

Precedence resolves each second once: Class 3 takes priority, followed by Class 4, followed by Class 2 and Class 1, with the remainder marked used.

### Grouping and Reclaim Ranking
Jobs group by user and command hash or job name, with secondary rollups across accounts and partitions. Groups rank by recoverable core-hours weighted by cluster memory value.

### Recommendations and Guardrails
Memory recommendations target the 99th percentile of observed peak RSS plus a 20 percent buffer, floored at the historical peak. Groups with out-of-memory terminations only receive upward adjustments. Groups with fewer than 5 samples receive no reductions.

### Declared Input Tracking (`rcwa-wrap`)
The `rcwa-wrap` wrapper computes sha256 checksums on declared input files, normalizes execution flags, writes hashes to job comments or sidecar metadata, and launches the command.

### Scheduler Simulator and Scenarios
An event-driven FCFS scheduler with EASY backfill replays jobs across five scenarios: baseline, memory rightsized, CPU rightsized (none and proportional), recomputation deduplication, and all recommendations combined.

### Calibration
Simulated wait times under baseline configuration compare directly against historical trace wait times, publishing median absolute error and Spearman rank correlation.

## 7. Guarantees

The codebase enforces four formal operational guarantees verified by dedicated test suites:

- **G1: Conservation Invariant**: For every job and both resource dimensions, reserved units equal used plus attributed waste plus unattributed amounts. Verified by `tests/unit/test_conservation.py`.
- **G2: Safety Guardrails**: Recommendations never recommend memory below observed group peak times safety factor, never lower limits for groups with OOM errors, and never alter groups below sample size floors. Verified by `tests/property/test_safety_guardrails.py`.
- **G3: Determinism**: Identical trace inputs generate byte-identical output reports and Parquet tables. Verified by `tests/golden/test_determinism.py`.
- **G4: Simulator Validity**: Every job schedules exactly once per scenario, start times never precede submit times, and node capacity limits hold across all time intervals. Verified by `tests/unit/test_simulator_validity.py`.

## 8. Benchmark Method

The benchmark evaluates performance and accuracy targets:
- `make bench SIZE=1M RUNS=5 SEED=1` executes 5 iterations over a 1,000,000 job workload with planted waste.
- `make bench-smoke SIZE=20k RUNS=1` provides fast continuous integration validation on smaller fixtures.
- Results record median, minimum, and maximum across iterations for all ten primary metrics.
- Machine hardware configuration and library versions append automatically via `bench/hardware.py`.

## 9. Design Decisions

Architectural decisions follow formal records in `docs/adr/`:

| ADR | Title | Optimizes | Costs |
|---|---|---|---|
| ADR 001 | Conservation Partitioning | Exact auditable balance across four classes | Subordinates idle CPU visibility in failed jobs to sub-labels |
| ADR 002 | Declared Input Hashing | Scheduler portability and low execution overhead | Unwrapped jobs without input declarations cannot attribute Class 4 |
| ADR 003 | Percentile Rightsizing | Workflow safety and prevention of OOM failures | Leaves safety margin unharvested relative to median usage |
| ADR 004 | EASY-Backfill Simulator | Deterministic baseline calibrated to real waits | Omits topology, preemption, and multi-factor fair-share decay |
| ADR 005 | Single-Process Polars | Reproducible execution without daemon services | Constrains maximum workload scale by available physical RAM |

## 10. Limits and Follow-ups

Scope boundaries and intentional omissions:
- Live scheduler plugins and dynamic rescheduling remain non-goals.
- GPU waste attribution is not provided; GPU counts are parsed and reported without waste classification.
- Cluster network topology, fair-share decay mechanics, and preemption policies are excluded from the simulator.
- User interfaces and web dashboards are excluded.
- Machine learning models and cloud telemetry are excluded.

## 11. Related Work

Existing tooling addresses isolated facets of cluster accounting:
- **Slurm sreport and sacct**: Native accounting tools report raw utilization summaries and allocations without attributing root causes or simulating policy changes.
- **XDMoD**: Provides comprehensive retrospective cluster analytics across institutional environments without simulation replay capabilities.
- **Kubecost**: Focuses on real-time Kubernetes expenditure allocation without batch-queue backfill modeling.

This repository provides conservation-checked attribution across four discrete causes, recomputation detection from declared inputs, and calibrated simulation of recommendations in a unified tool.

## 12. Data

The evaluation harness uses public traces from the Parallel Workloads Archive:
- **CEA-Curie**: Bullx cluster log with 93,312 cores (`https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/index.html`).
- **SDSC-SP2**: IBM SP2 cluster log with 128 nodes (`https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/index.html`).

Details, header pragmas, and academic usage terms appear in `docs/DATA.md`. Repository commits contain only small synthetic fixtures in `tests/fixtures/`.

## 13. AI Assistance

Repository files, initial templates, and test harnesses were generated with AI assistance. Detailed file provenance and human verification records appear in [docs/AI-ASSISTANCE.md](docs/AI-ASSISTANCE.md).

## 14. License

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
