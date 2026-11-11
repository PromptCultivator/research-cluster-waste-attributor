# Project: research-cluster-waste-attributor

## Architecture
`research-cluster-waste-attributor` (`rcwa`) is a Python package and CLI suite for research compute cluster accounting analysis. It ingests batch-scheduler accounting records (Slurm `sacct` exports and Standard Workload Format traces), partitions reserved resources into four non-overlapping waste classes and used consumption under exact conservation guarantees, recommends right-sized resource requests with safety guardrails, replays workloads through a deterministic EASY-backfill scheduler simulator, and produces comprehensive reports.

### Data Flow
```
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

## Feature Inventory
Every feature extracted from `docs/SPEC.md` and `ORIGINAL_REQUEST.md` is inventoried and mapped to an assigned milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Repository Scaffold | Directory structure, pyproject.toml with pinned deps, LICENSE (Apache-2.0), Makefile, Dockerfile, CI workflow | M0 | SPEC §4, §10, §11, §14 |
| 2 | Documentation Stubs | README skeleton, docs/DECISIONS.md, docs/DATA.md template, 5 ADR stubs | M0 | SPEC §4, §12, §14 |
| 3 | Default Configurations | policies/default.yaml (grouping, sample floors, thresholds), clusters/example.yaml (node specs) | M0 | SPEC §4, §5.4, §8 |
| 4 | sacct Column Parsing | Ingest pipe-delimited sacct export with 26 mandatory columns, handle empty fields, warn on extra columns | M1 | SPEC §5.1 |
| 5 | sacct Step Hierarchy Rollup | MaxRSS max over steps, TotalCPU sum over steps excluding .extern; parent carries allocations | M1 | SPEC §5.1 |
| 6 | Array & Heterogeneous Jobs | Array jobs (12345_7) and pack components (12345+0) decomposed into discrete jobs with parent_job_id | M1 | SPEC §5.1 |
| 7 | Time & Duration Parsing | Parse Elapsed and TotalCPU formats (D-HH:MM:SS, HH:MM:SS, MM:SS.mmm) to seconds; compute wait_s | M1 | SPEC §5.1, §5.3 |
| 8 | Slurm Memory Suffix Parsing | Parse ReqMem with M, Mc (per-CPU), Mn (per-node), G, Gc, Gn, K, Kc, Kn suffixes, and ?/Unknown | M1 | SPEC §5.1 |
| 9 | Slurm State & TRES Parsing | Strip state qualifiers, map to canonical enum with OUT_OF_MEMORY; parse ReqTRES/AllocTRES for GPUs and nodes | M1 | SPEC §5.1 |
| 10 | SWF Format Parser | Parse 18 whitespace-separated fields, header pragmas (UnixStartTime, MaxProcs, MaxNodes, Note) | M1 | SPEC §5.2 |
| 11 | SWF Metric Conversions | Convert KB/proc memory to job total MB; proc CPU time to job total seconds; map missing (-1) to null | M1 | SPEC §5.2 |
| 12 | Canonical Job Record Model | Arrow schema and Pydantic v2 model with 22 fields, calculated reserved_core_s and reserved_mem_mb_s | M1 | SPEC §5.3 |
| 13 | Exclusion & Zero-Run Handling | Exclude RUNNING/PENDING to data quality; retain run_s=0 as early failures with 0 consumption | M1 | SPEC §5.3 |
| 14 | Ingest Throughput Verification | Verify 100k-row sacct export parse throughput measured in jobs/s | M1 | SPEC §14 |
| 15 | Conservation Precedence Order | One-pass precedence: Class 3 -> Class 4 -> Class 2 (cores) / Class 1 (memory) -> Used / Unattributed | M2 | SPEC §6.1 |
| 16 | Class 3 Failed & Retried Work | Attributes entire core & memory reservation of failed/cancelled jobs; assigns 6 sub-labels | M2 | SPEC §6.1 |
| 17 | Retry Chain Detection | Chains subsequent matching job by same user submitted within retry_window (default 24h) with retry_of | M2 | SPEC §6.1 |
| 18 | Class 2 Idle Reserved CPU | idle_core_s = max(0, reserved_core_s - cpu_time_used_s); used_core_s = reserved - idle | M2 | SPEC §6.1 |
| 19 | Class 1 Memory Over-Request | over_mem_mb_s = max(0, req_mem_mb - max_rss_mb) * run_s; used_mem_mb_s = reserved - over | M2 | SPEC §6.1 |
| 20 | Unattributed Metric Labeling | Labels unattributed_missing_cpu_time and unattributed_missing_rss; counted in coverage | M2 | SPEC §6.1 |
| 21 | Guarantee G1 Conservation Invariant | reserved = used + class1_or_2 + class3 + class4 + unattributed in exact integer seconds and MB-seconds | M2 | SPEC §6.1, §3 |
| 22 | Job Grouping & Aggregations | Group by (user, command_hash or job_name); secondary rollups by account, partition, user | M2 | SPEC §5.4, §6.2 |
| 23 | Ranked Reclaim Scoring | Score = reclaimable_core_hours + mem_weight * reclaimable_gb_hours; top 5 evidence job IDs | M2 | SPEC §6.2 |
| 24 | Memory Rightsizing with Guardrails | req_mem_mb = ceil(p99(max_rss) * 1.2), floor at observed max RSS across all states | M3 | SPEC §7 |
| 25 | OOM Escalation Guardrail | Any OOM job in group forces direction=increase to ceil(max * 1.5); excluded from reclaimable memory | M3 | SPEC §7 |
| 26 | CPU Rightsizing with Guardrails | cpus = clamp(ceil(p99(cpu_rate) * 1.2), 1, alloc_cpus); short jobs (run_s < 120s) get no recommendation | M3 | SPEC §7 |
| 27 | Timeout & Early Failure Actions | time_limit = ceil(p99(run_s) * 1.5) for timeouts; early failures report exit codes & failure share | M3 | SPEC §7 |
| 28 | Guarantee G2 Safety Property Tests | Hypothesis tests over 10,000 generated groups verifying floor, OOM, and min_samples guardrails | M3 | SPEC §7, §3, §14 |
| 29 | rcwa-wrap CLI & Hash Pipeline | Wrapper CLI computing sha256 or size_mtime hashes of declared inputs, normalized command lines | M4 | SPEC §5.5 |
| 30 | Dual Hash Recording & Tolerances | Records hash in scontrol Comment and sidecar json; missing inputs recorded without blocking job | M4 | SPEC §5.5 |
| 31 | Class 4 Recomputation Attribution | Identical (command_hash, input_hash) completed within recompute_window attributed to Class 4 | M4 | SPEC §6.1 |
| 32 | Command-Only Duplicate Listing | Missing input_hash with matching command_hash listed as possible_recompute; excluded from Class 4 totals | M4 | SPEC §6.1 |
| 33 | Result Cache Recommendation | Recommends cache keyed by (command_hash, input_hash) with simulated hit rate | M4 | SPEC §7 |
| 34 | SWF Recomputation Disable | SWF traces report recomputation as "not available", never estimated | M4 | SPEC §5.2 |
| 35 | Cluster Topology Inference | Load cluster spec from YAML or infer nodes, cores_per_node, mem_mb_per_node from trace peak | M5 | SPEC §8 |
| 36 | EASY-Backfill Simulator Engine | FCFS scheduler with shadow reservation for queue head and non-delaying backfill; deterministic | M5 | SPEC §8 |
| 37 | Five Simulation Scenarios | Full replays: baseline, mem_rightsized, cpu_rightsized (none & proportional), cache_dedup, all | M5 | SPEC §8 |
| 38 | Simulator Calibration | Calibrate baseline against real trace waits: report median absolute error and Spearman correlation | M5 | SPEC §8 |
| 39 | Guarantee G4 Validity Invariants | Every job scheduled once, sim_start >= submit_time, node capacity respected at every timestep | M5 | SPEC §8, §3 |
| 40 | 1M Job Simulation Performance Target | Baseline scenario runs 1,000,000 jobs in < 15 min using heap event queue and indexed node capacity | M5 | SPEC §8 |
| 41 | Multi-Format Report Generator | Generate Markdown, JSON, and CSV reports containing ranked reclaim lists and scenario summaries | M6 | SPEC §4, §6.2, §8 |
| 42 | Data Quality Accounting Section | Report counts of excluded RUNNING/PENDING, unattributed shares, and missing input coverage | M6 | SPEC §5.3, §6.1, §9 |
| 43 | Golden Reference Diff Tests | Golden test suite comparing output reports against stored reference fixtures | M6 | SPEC §10, §14 |
| 44 | Guarantee G3 Determinism Test | Verify identical inputs produce byte-identical report outputs across independent runs | M6 | SPEC §3, §14 |
| 45 | Synthetic Trace Generator (synth.py) | Generate synthetic traces with planted ground-truth waste for all 4 classes | M7 | SPEC §4, §9, §14 |
| 46 | Public SWF Trace Ingest (make data) | Download two public SWF traces from Parallel Workloads Archive; populate docs/DATA.md | M7 | SPEC §10, §14 |
| 47 | Full Benchmark Suite (bench/) | bench/run.py and bench/hardware.py collecting all 10 metrics across 5 runs (median and min-max) | M7 | SPEC §9, §10 |
| 48 | Five Architectural Decision Records | Complete docs/adr/001 through 005 with context, options, decision, and measured/stated costs | M7 | SPEC §12 |
| 49 | README Completion & Verification | Complete 14-section README with hardware block and results; zero prohibited words audit | M7 | SPEC §13, §16 |
| 50 | E2E Requirement-Driven Test Suite | Opaque-box test suite across Tiers 1-4 (>=11*N tests) covering all features from CLI | M_E2E | Project Pattern |
| 51 | Final E2E Pass & Tier 5 Hardening | 100% pass of E2E tests + adversarial coverage hardening with challenger loop | M_FINAL | Project Pattern |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Phase 0 — Scaffold | Repository layout, pyproject.toml (pinned deps), Makefile (13 targets), Dockerfile, CI workflow, initial docs (DECISIONS.md, DATA.md, 5 ADR stubs), README skeleton, default policies, example cluster | none | DONE (26 tests, 95.24% cov, ruff/pyright pass, 0 prohibited words, auditor verified) |
| M1 | Phase 1 — Adapters & Canonical Record | model.py, normalize.py, adapters/sacct.py, adapters/swf.py, fixtures, 100k-row throughput benchmark | M0 | DONE (261 tests, 92.13% cov, 31,017 jobs/s, ruff/pyright pass, auditor clean) |
| M2 | Phase 2 — Attribution | attribute.py, groups.py, retries.py, G1 conservation test on fixtures and 20k trace, Parquet/CSV output | M1 | DONE (310 tests, 90.89% cov, G1 exact on 20k trace, ruff/pyright pass, auditor clean) |
| M3 | Phase 3 — Recommendations | recommend.py with guardrails (floor, OOM, min_samples), G2 Hypothesis property tests (10k groups) | M2 | PLANNED |
| M4 | Phase 4 — Recomputation | wrap.py (rcwa-wrap), recompute.py, sidecar and Comment readers, recall/precision verification | M2 | PLANNED |
| M5 | Phase 5 — Simulator & Calibration | simulate.py (FCFS + EASY backfill), calibrate.py, G4 validity tests, 1M job target benchmark | M3, M4 | PLANNED |
| M6 | Phase 6 — Report | report.py (MD, JSON, CSV), ranked reclaim list, data quality section, golden tests, G3 determinism test | M5 | PLANNED |
| M7 | Phase 7 — Synthetic Generator & Benchmarks | synth.py with planted waste, make data public traces, bench/run.py, bench/hardware.py, 5 ADRs, README | M6 | PLANNED |
| M_E2E | E2E Testing Suite (Tiers 1-4) | Opaque-box requirement-driven test suite derived from SPEC.md, publishing TEST_READY.md | M0 | DONE (608 tests across 28 modules, 38 fixtures, TEST_READY.md published, auditor clean) |
| M_FINAL | Final Milestone | Pass 100% E2E tests (Tiers 1-4) + Phase 2 adversarial coverage hardening (Tier 5) | M7, M_E2E | PLANNED |

---

## Interface Contracts

### 1. `rcwa.model` (Canonical Record)
```python
# Arrow schema fields:
# job_id (str), parent_job_id (str|None), source (str: sacct|swf|k8s|ray)
# user (str), account (str|None), partition (str|None), job_name (str|None)
# command_hash (str|None), input_hash (str|None)
# submit_time (timestamp[s, UTC]), start_time (timestamp[s, UTC]|None), end_time (timestamp[s, UTC]|None)
# wait_s (int64), run_s (int64)
# state (str enum: COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER)
# exit_code (int32|None)
# req_cpus (int32), alloc_cpus (int32), cpu_time_used_s (float64|None)
# req_mem_mb (int64|None), max_rss_mb (int64|None)
# req_gpus (int32), alloc_gpus (int32)
# nodes (int32), node_list (str|None)
# reserved_core_s (int64 = alloc_cpus * run_s)
# reserved_mem_mb_s (int64 = req_mem_mb * run_s)
```

### 2. Adapters (`rcwa.adapters.sacct`, `rcwa.adapters.swf`) -> `rcwa.normalize`
```python
def parse_sacct(source: Path | IO[str]) -> polars.DataFrame: ...
def parse_swf(source: Path | IO[str], header_pragmas: dict[str, str] | None = None) -> polars.DataFrame: ...
def normalize_to_canonical(df: polars.DataFrame, source_type: str) -> polars.DataFrame: ...
```

### 3. Attribution & Grouping (`rcwa.attribute`, `rcwa.groups`, `rcwa.retries`)
```python
def attribute_trace(canonical_df: polars.DataFrame, policy: PolicyConfig) -> polars.DataFrame:
    """Returns per-job attribution table satisfying G1."""
    ...

def group_jobs(attributed_df: polars.DataFrame, policy: PolicyConfig) -> polars.DataFrame:
    """Returns grouped table with waste totals, reclaimable metrics, and top 5 evidence job IDs."""
    ...
```

### 4. Recommendations (`rcwa.recommend`)
```python
def generate_recommendations(groups_df: polars.DataFrame, policy: PolicyConfig) -> polars.DataFrame:
    """Applies p99 rightsizing with G2 guardrails (observed max floor, OOM increase, min_samples)."""
    ...
```

### 5. Simulator & Calibration (`rcwa.simulate`, `rcwa.calibrate`)
```python
def run_simulation(
    canonical_df: polars.DataFrame,
    cluster: ClusterConfig,
    recommendations: polars.DataFrame | None,
    scenario: Literal["baseline", "mem_rightsized", "cpu_rightsized_none", "cpu_rightsized_proportional", "cache_dedup", "all"]
) -> SimulationResult: ...

def calibrate_trace(canonical_df: polars.DataFrame, cluster: ClusterConfig) -> CalibrationResult:
    """Returns median absolute error and Spearman correlation of baseline wait vs trace wait."""
    ...
```

### 6. Reporting (`rcwa.report`)
```python
def generate_report(
    attributed_df: polars.DataFrame,
    groups_df: polars.DataFrame,
    simulation_results: dict[str, SimulationResult],
    calibration: CalibrationResult | None,
    format: Literal["markdown", "json", "csv"]
) -> str: ...
```

---

## Code Layout
```
research-cluster-waste-attributor/
  README.md                    14 required sections, TBD placeholders until bench
  LICENSE                      Apache-2.0
  pyproject.toml               license = "Apache-2.0"; pinned dependencies; scripts rcwa, rcwa-wrap
  Makefile                     13 targets (all, setup, lint, typecheck, test, data, synth, run, calibrate, bench, bench-smoke, goldens, docker)
  Dockerfile                   python:3.12-slim; runs make test by default
  .github/workflows/ci.yml     lint, typecheck, tests with 85% coverage gate, bench-smoke
  rcwa/
    __init__.py
    cli.py                     typer entry point
    config.py                  Pydantic models for PolicyConfig, ClusterConfig, SimSettings
    model.py                   Canonical Arrow schema and Pydantic models
    adapters/
      sacct.py                 Slurm sacct parser
      swf.py                   SWF parser
      k8s.py                   Phase 8 (optional)
      ray.py                   Phase 8 (optional)
    normalize.py               Unit conversions, timestamp parsing, step/array roll-up
    attribute.py               Precedence-based 4-class attribution engine
    groups.py                  Grouping logic, secondary rollups, evidence selection
    recommend.py               Percentile rightsizing with safety guardrails
    recompute.py               Input/command hash duplicate detection
    retries.py                 Retry chain detector
    simulate.py                FCFS + EASY backfill simulator
    calibrate.py               Simulator calibration against historical wait times
    report.py                  Markdown, JSON, and CSV report emitters
    wrap.py                    rcwa-wrap CLI tool
    synth.py                   Synthetic trace generator with planted waste
  policies/default.yaml        Default policy configuration
  clusters/example.yaml        Example cluster configuration
  data/                        gitignored (raw, out, results)
  tests/
    unit/
    property/
    golden/
    fixtures/
  bench/
    run.py
    hardware.py
    results/
  docs/
    SPEC.md
    DECISIONS.md
    DATA.md
    adr/
      001-conservation-partition.md
      002-declared-inputs-for-recomputation.md
      003-percentile-rightsizing-with-guardrails.md
      004-easy-backfill-simulator.md
      005-single-process-polars.md
```

---

## Four Guarantees Verification Matrix

| Guarantee | Description | Verification Test | Phase Gate |
|-----------|-------------|-------------------|------------|
| **G1: Conservation** | For every job, `reserved = used + class1_or_2 + class3 + class4 + unattributed` in integer seconds and MB-seconds | `tests/unit/test_conservation.py` asserting G1 on fixtures and 20k synthetic trace | Phase 2, Phase 7, Bench |
| **G2: Safety** | No memory recommendation below observed maximum * 1.2; no decrease for groups with OOM; no recommendation for `< min_samples` | `tests/property/test_safety_guardrails.py` running Hypothesis across 10,000 groups | Phase 3, Bench |
| **G3: Determinism** | Identical inputs produce byte-identical report outputs across independent executions | `tests/golden/test_determinism.py` comparing output byte diff of two runs | Phase 6 |
| **G4: Simulator Validity** | Every job scheduled once, `sim_start >= submit_time`, node capacity never exceeded at any sampled timestamp | `tests/unit/test_simulator_validity.py` + brute-force small trace checker | Phase 5 |

---

## Prohibited Vocabulary Compliance
The following 9 words are strictly prohibited anywhere in code, comments, docstrings, commits, or documentation:
`"simply"`, `"robust"`, `"seamless"`, `"best"`, `"optimal"`, `"clean"`, `"minimal"`, `"powerful"`, `"cutting-edge"`.
An automated check (`grep -rn -i -E '\b(simply|robust|seamless|best|optimal|clean|minimal|powerful|cutting-edge)\b'`) will be enforced during review and CI.
