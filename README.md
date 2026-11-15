# Research Cluster Waste Attributor (`rcwa`)

[![CI](https://github.com/PromptCultivator/research-cluster-waste-attributor/actions/workflows/ci.yml/badge.svg)](https://github.com/PromptCultivator/research-cluster-waste-attributor/actions)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](pyproject.toml)

![Research Cluster Waste Attributor](.github/social-preview.png)

`research-cluster-waste-attributor` (`rcwa`) ingests batch-scheduler accounting traces, partitions reserved CPU core-seconds and memory megabyte-seconds across four non-overlapping waste classes and used consumption under exact conservation guarantees, recommends guarded resource limits, and simulates queue wait-time impact with a calibrated EASY-backfill scheduler before limits change in production.

**Status**: Verified and benchmarked on `Intel(R) Xeon(R) Platinum 8481C` (`20k` planted-waste benchmark in [`bench/results/bench.md`](bench/results/bench.md)).

---

## Problem Statement

Batch schedulers reserve cores and memory from what users request rather than what workloads consume. Researchers routinely over-request memory and CPU cores to avoid out-of-memory kills and timeouts, causing actual utilization to diverge sharply from cluster reservations. Reducing submission limits blindly risks interrupting production runs and creating cascading retries. `rcwa` closes this gap by attributing every second of reserved capacity to a concrete cause, applying statistical rightsizing bounded by safety guardrails, and replaying historical arrivals under proposed limits through an EASY-backfill simulator calibrated against observed queue wait times.

---

## Quick Start

### Prerequisites and Installation

Requires Python `3.11+`, POSIX `make`, and `git`:

```bash
git clone https://github.com/PromptCultivator/research-cluster-waste-attributor.git
cd research-cluster-waste-attributor

# Create .venv and install pinned runtime + development dependencies
make setup
source .venv/bin/activate
```

### Exporting Scheduler Traces

Export completed Slurm accounting records (`sacct`) using pipe-delimited output (`-P`) and megabyte memory units (`--units=M`):

```bash
sacct -a -P --units=M -S 2026-01-01 -E 2026-02-01 \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine > trace.sacct
```

For public supercomputer evaluation workloads from the Parallel Workloads Archive:

```bash
make data
```

### Running the Pipeline

Run the full ingestion, attribution, recommendation, simulation, calibration, and reporting pipeline via CLI or Makefile:

```bash
# End-to-end run on a Slurm or SWF trace
rcwa run tests/fixtures/sacct/multiday_cluster.txt --output-dir data/out

# Makefile shortcut
make run TRACE=tests/fixtures/sacct/multiday_cluster.txt
```

Artifacts written to `data/out/`:
- `canonical.parquet`: 27-field normalized job table.
- `attributed.parquet`: Per-job waste partition satisfying Guarantee G1.
- `recommendations.parquet` and `recommendations.csv`: Cohort rightsizing recommendations satisfying Guarantee G2.
- `simulated_baseline.parquet`: Baseline EASY-backfill schedule replay.
- `report.md`, `report.json`, and `report.csv`: Deterministic summary reports satisfying Guarantee G3.

---

## Usage Examples

### Individual CLI Stages

```bash
# 1. Ingest raw Slurm sacct or SWF trace to canonical Parquet
rcwa ingest trace.sacct --output data/out/canonical.parquet

# 2. Attribute waste across Classes 1-4
rcwa attribute data/out/canonical.parquet --policy policies/default.yaml --output data/out/attributed.parquet

# 3. Compute safety-guarded recommendations
rcwa recommend data/out/attributed.parquet --policy policies/default.yaml --output data/out/recommendations.csv

# 4. Replay cluster schedule under counterfactual scenarios
rcwa simulate data/out/canonical.parquet --cluster clusters/example.yaml --scenario all --output data/out/sim_metrics.json

# 5. Calibrate simulator baseline against recorded queue waits
rcwa calibrate data/out/canonical.parquet --cluster clusters/example.yaml

# 6. Render Markdown, JSON, or CSV report
rcwa report data/out/canonical.parquet --format markdown --output data/out/report.md
```

### Declared Input Tracking (`rcwa-wrap`)

Wrap batch job commands to record deterministic SHA-256 (or `size_mtime`) input checksums in Slurm `Comment` metadata and optional `$RCWA_DIR/<job_id>.json` sidecars:

```bash
rcwa-wrap \
  --inputs data/train.csv,data/params.json \
  --big-file-mode size_mtime \
  -- python train.py --epochs 20
```

### Python API

```python
import polars as pl
from rcwa.attribute import attribute_trace
from rcwa.recommend import recommend_jobs

canonical_df = pl.read_parquet("data/out/canonical.parquet")
attributed_df = attribute_trace(canonical_df)
recommendations_df = recommend_jobs(attributed_df)

print(
    recommendations_df.select(
        ["group", "recommended_req_mem_mb", "recommended_cpus", "recommendation_direction"]
    ).head(5)
)
```

---

## How It Works

### Pipeline Architecture

```text
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
                         (baseline, mem_rightsized, cpu_rightsized_*,
                                        cache_dedup, all)
                                                │
                                                ▼
                              [ Calibration & Deterministic Reports ]
                                                (G3)
```

- **Canonical Job Record (`rcwa/model.py`)**: 27-field Apache Arrow and Polars schema unifying Slurm `sacct` step rollups (`MaxRSS` peak over steps, `TotalCPU` sum excluding `.extern*`), array/heterogeneous jobs, TRES GPU counts, and SWF workloads. Active jobs (`RUNNING`, `PENDING`) are excluded from attribution and audited in the report's Data Quality section; zero-runtime jobs (`run_s == 0`) are retained as Class 3 `early_failure`.
- **Single-Pass Conservation Precedence (`rcwa/attribute.py`)**: Each job's integer `reserved_core_s` and `reserved_mem_mb_s` pass through a mutually exclusive cascade:
  1. **Class 3 (Failed & Retried Work)**: Abnormal terminations (`FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `PREEMPTED`, `CANCELLED` after start, or `run_s == 0`) allocate 100% of both dimensions to Class 3, tagged with one of six sub-labels (`early_failure`, `oom`, `timeout`, `node_fail`, `cancelled_after_start`, `other_failure`). Causal 1-to-1 retry chains are linked across `(user, task_id)` within `retry_window_s` (default 24h).
  2. **Class 4 (Redundant Recomputation)**: Completed executions matching an earlier completed run on both `command_hash` and `input_hash` within `recompute_window_s` (default 30 days) allocate 100% of both dimensions to Class 4 (`declared_inputs`). Command-only matches without `input_hash` are surfaced as `possible_recompute` (`command_only`) and excluded from Class 4 resource totals. SWF workloads report Class 4 as `"not available"`.
  3. **Class 2 (Idle Reserved CPU)** & **Class 1 (Memory Over-Request)**: Remaining completed runs partition cores into `used_core_s` and `class2_idle_core_s`, and memory into `used_mem_mb_s` and `class1_over_mem_mb_s`. Missing `cpu_time_used_s` or `max_rss_mb` map explicitly to `unattributed_core_s` or `unattributed_mem_mb_s`.
- **Grouping & Ranking (`rcwa/groups.py`)**: Groups by `(user, job_name or command_hash)` (with `account`, `partition`, and `user` secondary rollups), scored by `reclaimable_core_hours + mem_weight * reclaimable_gb_hours` (`mem_weight = 0.25` default), extracting the top five waste-contributing evidence job IDs per group.
- **Safety-Guarded Rightsizing (`rcwa/recommend.py`)**: Memory limits target `ceil(P99(max_rss_mb | COMPLETED) * 1.2)` floored at the all-state cohort peak RSS; any group containing `OUT_OF_MEMORY` skips the sample floor and escalates to `ceil(max_observed * 1.5)` while zeroing `reclaimable_gb_hours`; non-OOM cohorts below `min_samples` (default 5) receive no recommendation (`below_sample_floor`); short cohorts (`median_run_s < 120` or all `< 120`) omit CPU recommendations.
- **EASY-Backfill Simulator & Calibration (`rcwa/simulate.py`, `rcwa/calibrate.py`)**: Deterministic FCFS scheduler with shadow reservation for the queue head and bounded 50-job non-delaying backfill (`all_nodes_disjoint_from_head` or `finishes_by_head_reservation`). Replays `baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, and `all`, comparing `baseline` waits against historical `wait_s` using Median Absolute Error and Spearman rank correlation.

---

## System Guarantees

| Guarantee | Property Enforced | Verification Suite |
|---|---|---|
| **G1: Conservation** | `reserved = used + waste + unattributed` in exact integer `core_s` and `mb_s` per job and across cluster totals | [`tests/unit/test_conservation.py`](tests/unit/test_conservation.py) |
| **G2: Safety Guardrails** | Memory recommendation never drops below cohort peak RSS; OOM cohorts escalate and report zero reclaimable GB-hours; non-OOM cohorts under `min_samples` receive `None` | [`tests/property/test_safety_guardrails.py`](tests/property/test_safety_guardrails.py) (10,000 generated groups) |
| **G3: Determinism** | Identical inputs and configs produce byte-identical Markdown, JSON, CSV, and Parquet outputs | [`tests/golden/test_determinism.py`](tests/golden/test_determinism.py) |
| **G4: Simulator Validity** | Every job schedules once per scenario, `sim_start >= submit_time`, and concurrent allocations never exceed node capacities | [`tests/unit/test_simulate.py`](tests/unit/test_simulate.py) |

End-to-end CLI verification for G1–G4 is implemented in [`tests/e2e/tier4_real_world/`](tests/e2e/tier4_real_world/).

---

## Benchmark Results and Method

### Benchmark Method

`bench/run.py` measures throughput, conservation exactness, guardrail compliance, ground-truth recall/precision, scenario queue wait shifts, SWF calibration error, and peak RSS (`ru_maxrss`):

```bash
# Quick CI invariant gate (20k planted-waste trace, 1 run)
make bench-smoke

# Multi-run scale benchmark (e.g. 1M jobs, 5 iterations, reporting median and min-max)
make bench SIZE=1M RUNS=5 SEED=1
```

### Measured Benchmark Hardware and Environment

Verbatim hardware profile recorded in [`bench/results/bench.md`](bench/results/bench.md):

```text
CPU Model: Intel(R) Xeon(R) Platinum 8481C
Physical Cores: 2
RAM: 7.76 GB
Operating System: Linux 6.12.105+
Python Version: 3.11.2 (polars=1.14.0, pyarrow=18.1.0, numpy=2.1.3, pydantic=2.10.3)
Commit Hash: 7b4c0d8cbccd1bc46f4889fc081793442a21fb6f
```

### Measured Benchmark Metrics (`size=20k`, `n_jobs=20000`, `seed=1`, `runs=1`)

Figures sourced from [`bench/results/bench.md`](bench/results/bench.md) and [`bench/results/bench.csv`](bench/results/bench.csv):

| Metric | Measured Result | Source Detail |
|---|---|---|
| Guarantee G1 Conservation | **EXACT** | Per-job integer check on 20,000-job synthetic trace |
| Guarantee G2 Guardrail Violations | **0** | Property checks across all recommended groups |
| Attribution Coverage | **96.23%** | Share of reserved core-s and memory-s attributed vs unattributed |
| Reclaimable Core-Hours Share | **72.95%** | Sum of wasted core-hours over total reserved core-hours |
| Reclaimable GB-Hours Share | **76.12%** | Sum of wasted GB-hours over total reserved GB-hours |
| Class 1 (Memory Over-Request) Recall / Precision | **1.0000 / 0.4829** | `0.4800` precision in rounded summary table |
| Class 2 (Idle Reserved CPU) Recall / Precision | **1.0000 / 0.3970** | `0.4000` precision in rounded summary table |
| Class 3 (Failed & Retried Work) Recall / Precision | **1.0000 / 1.0000** | Exact recall and precision against planted failures |
| Class 4 (Redundant Recomputation) Recall / Precision | **0.8039 / 0.2273** | `0.8000 / 0.2300` in rounded summary table |
| `sacct` Ingestion Throughput | **34,610.4 jobs/s** | Single-process text parsing |
| `swf` Ingestion Throughput | **90,618.1 jobs/s** | Single-process SWF fixture replay |
| Simulation Baseline Throughput | **90,486.8 jobs/s** | Discrete-event EASY-backfill heap loop |
| Peak Resident Memory | **310.77 MB** | `ru_maxrss` of Python process |
| Simulated Median Wait Change (`all` vs `baseline`) | **+61,851.0 s** | Combined counterfactual replay over `20k` synthetic trace |
| Simulated P95 Wait Change (`all` vs `baseline`) | **+103,929.4 s** | 95th-percentile wait shift on `20k` synthetic trace |
| Historical Trace Calibration Error (MAE) | **12.0 s** | `baseline` vs recorded `wait_s` on SWF fixture (`n=10`) |
| Historical Trace Rank Correlation (Spearman $\rho$) | **0.0** | Zero simulated variance on `sample_workload.swf` |

Note: Lower precision on Classes 1, 2, and 4 reflects secondary inefficiencies inside nominally normal synthetic jobs (for example, `normal` jobs generated with 75%–95% RSS still trigger measurable `req_mem_mb - max_rss_mb` over-request deltas). Calibration figures in the recorded run reflect the 10-job committed SWF fixture (`sample_workload.swf`).

---

## Design Decisions

Formal architectural trade-offs are documented in [`docs/adr/`](docs/adr/) and [`docs/DECISIONS.md`](docs/DECISIONS.md):

| ADR | Title | Optimizes | Costs |
|---|---|---|---|
| [ADR 001](docs/adr/001-conservation-partition.md) | Conservation Partitioning | Exact, auditable accounting with zero double counting | Subordinates idle CPU inside failed jobs to Class 3 sub-labels |
| [ADR 002](docs/adr/002-declared-inputs-for-recomputation.md) | Declared Input Hashing | Zero runtime tracing overhead and scheduler portability | Unwrapped jobs without `input_hash` remain excluded from Class 4 totals |
| [ADR 003](docs/adr/003-percentile-rightsizing-with-guardrails.md) | Percentile Rightsizing with Guardrails | Workflow stability and OOM protection | Leaves conservative P99-vs-P50 capacity buffer unharvested |
| [ADR 004](docs/adr/004-easy-backfill-simulator.md) | EASY-Backfill Simulator | Deterministic replay calibrated against historical waits | Omits network fabric topology, preemption, fair-share decay, and GPUs |
| [ADR 005](docs/adr/005-single-process-polars.md) | Single-Process Polars | One-command workstation execution without external daemons | Trace size bounded by physical RAM (`310.77 MB` peak RSS at 20k scale) |

---

## Scope Limits and Known Omissions

- **Offline Analytics Only**: No live Slurm scheduler plugin, SPANK integration, or automated job mutation.
- **No GPU Utilization Attribution**: `req_gpus` and `alloc_gpus` are parsed from `ReqTRES`/`AllocTRES` and reported in canonical tables without GPU SM/memory waste classification.
- **Simplified Cluster Mechanics**: The simulator models identical nodes per partition without rack/network topology, preemption, fair-share priority decay, or external dependency DAG holds.
- **No Web UI, External ML Models, or Telemetry**: CLI and file exports only; pure deterministic logic with pinned dependencies.

---

## Related Work

- **Slurm `sreport` and `sacct`**: Native Slurm tools export raw allocation and usage totals without decomposing root waste causes, tracking input duplicates, or replaying limits in a simulator.
- **Open XDMoD**: Provides institutional warehouse dashboards for retrospective HPC utilization metrics without counterfactual backfill simulation or declared-input deduplication.
- **Kubecost**: Focuses on live Kubernetes container cost allocation without batch-scheduler queue simulation.

`rcwa` combines four-class conservation accounting, cryptographic declared-input recomputation detection, guarded rightsizing, and calibrated EASY-backfill queue simulation in a single offline toolkit.

---

## Public Traces and Committed Fixtures

Trace ingestion evaluation uses public workload logs from the Parallel Workloads Archive:
- **CEA-Curie** (`CEA-Curie-2011-2.swf.gz`): 5,544 nodes / 93,312 cores ([source index](https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/index.html)).
- **SDSC-SP2** (`SDSC-SP2-1998-4.2-cln.swf.gz`): 128 nodes ([source index](https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/index.html)).

Source metadata, header pragmas, and usage terms appear in [`docs/DATA.md`](docs/DATA.md). Only miniature synthetic fixtures (`40` files in [`tests/fixtures/`](tests/fixtures/)) are committed to git; downloaded raw traces live under gitignored `data/raw/`.

---

## Project Layout

```text
research-cluster-waste-attributor/
├── .github/workflows/   # CI validation (lint, typecheck, test, bench-smoke)
├── bench/               # Benchmark harness (run.py, hardware.py) and results/
├── clusters/            # Cluster topology YAML definitions (example.yaml)
├── data/                # Gitignored workspace for downloaded raw traces and outputs
├── docs/                # System specs, architecture, decisions, ADRs, component & test guides
├── policies/            # Default attribution, grouping, and guardrail YAML configuration
├── rcwa/                # Core Python package (CLI, wrap, model, adapters, attribution, simulator)
├── scripts/             # Public Parallel Workloads Archive downloader (download_data.py)
├── tests/               # Unit (21), property (1), golden (2), E2E (28) suites and 40 fixtures
├── Dockerfile           # Python 3.12 container running `make test`
├── LICENSE              # Apache-2.0 License
├── Makefile             # Standard build, test, data, synth, run, calibrate, bench targets
├── PROJECT.md           # System architecture and interface contract index
├── TEST_READY.md        # Test suite readiness summary and verification counts
└── pyproject.toml       # Package metadata, exact pinned dependencies, ruff/pyright/pytest config
```

---

## Development and Verification

```bash
make lint        # ruff check . and ruff format --check .
make typecheck   # pyright static type validation
make test        # unit, property, and golden suites (389 tests, >= 85% coverage)
pytest tests/e2e/ -o addopts=""   # opaque-box CLI E2E suite (610 tests)
```

For full documentation of test tiers, fixtures, and CLI harnesses, see [`docs/TESTING.md`](docs/TESTING.md) and [`TEST_READY.md`](TEST_READY.md). For input preparation and `rcwa-wrap`, see [`docs/INPUTS.md`](docs/INPUTS.md).

---

## License

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
