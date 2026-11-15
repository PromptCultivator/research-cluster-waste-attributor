# System Specification: `research-cluster-waste-attributor`

## 1. Purpose and Scope

`research-cluster-waste-attributor` (`rcwa`) reads batch-scheduler accounting traces from compute clusters, partitions every reserved CPU core-second and memory megabyte-second into four mutually exclusive waste classes or utilized consumption under exact integer conservation, generates safety-guarded resource limit recommendations, replays traces through an EASY-backfill scheduler simulator across counterfactual scenarios calibrated against real queue wait times, and writes reproducible reports.

### 1.1 System Goals

- Turn an accounting trace export into a ranked reclaim report and counterfactual queue simulation via a single CLI command (`rcwa run`).
- Enforce four formal system guarantees, each verified by dedicated automated test suites:
  - **Guarantee G1 (Conservation)**: For every evaluated job and across trace totals, `reserved = used + waste + unattributed` holds without double counting or floating-point rounding drift in integer core-seconds and megabyte-seconds.
  - **Guarantee G2 (Safety)**: Recommended memory never falls below observed peak RSS; cohorts exhibiting `OUT_OF_MEMORY` terminations strictly escalate memory and contribute zero reclaimable GB-hours; non-OOM cohorts below `min_samples` receive no reductions or resource changes.
  - **Guarantee G3 (Determinism)**: Identical input traces, cluster definitions, and policy configurations yield byte-identical Markdown, JSON, CSV, and Parquet outputs.
  - **Guarantee G4 (Simulator Validity)**: Every eligible job schedules once per scenario, never before its submission timestamp, and node CPU/memory limits are never exceeded at any simulated timestamp.
- Measure and report: reclaimable core-hours and GB-hours as shares of the trace, per-class recall and precision against planted synthetic ground truth, simulated median and P95 wait-time shifts per scenario, historical baseline calibration error, attribution coverage, single-process ingest and simulation throughput, and peak resident memory.

### 1.2 Explicit Non-Goals

The following are outside system scope:
- Live scheduler plugins, SPANK hooks, or dynamic in-flight rescheduling.
- GPU utilization waste attribution (`req_gpus` and `alloc_gpus` are ingested from TRES fields and preserved in the canonical table, not classified as GPU waste).
- Switch/rack network topology, job preemption, multi-factor fair-share decay, and dependency DAG modeling inside the discrete-event simulator.
- Graphical or web user interfaces.
- External neural or ML prediction models and outbound telemetry.

### 1.3 Engineering Constraints

- **Pinned Dependencies**: Exact runtime versions pinned in [`pyproject.toml`](../pyproject.toml) (`polars==1.14.0`, `pyarrow==18.1.0`, `numpy==2.1.3`, `pydantic==2.10.3`, `typer==0.15.1`, `pyyaml==6.0.2`). Development dependencies pinned to `pytest==8.3.3`, `pytest-cov==6.0.0`, `hypothesis==6.120.0`, `ruff==0.8.2`, `pyright==1.1.390`. No external telemetry or network clients.
- **Offline Hermetic Testing**: Tests never require internet connectivity; trace downloads are isolated to `make data` storing gitignored workloads under `data/raw/`.
- **Single-Process Execution**: Tabular processing executes in-process using Polars and PyArrow without external worker daemons or relational server processes.
- **Prohibited Vocabulary**: The nine excluded promotional/vague terms checked by [`tests/unit/test_forbidden_words.py`](../tests/unit/test_forbidden_words.py) are barred from source code, comments, tests, configuration files, and documentation.

---

## 2. Inputs and Canonical Job Record

### 2.1 Slurm `sacct` Export

Accepted via pipe-delimited (`-P`) `sacct` exports with megabyte memory units (`--units=M`):

```bash
sacct -a -P --units=M -S <start> -E <end> \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine
```

Parser specifications:
- Pipe-delimited with a header row; optional empty fields resolve to `null`. Unknown extra columns emit a `UserWarning` and are ignored without failing ingestion.
- Step rows (`12345.batch`, `12345.0`, `12345.extern`) roll up to the parent row (`12345`): `max_rss_mb` takes the maximum across steps; `cpu_time_used_s` sums `TotalCPU` across steps while excluding `.extern*` system overhead steps.
- Array jobs (`12345_7`) and heterogeneous pack components (`12345+0`) ingest as independent records with `parent_job_id` populated.
- Duration parsing accepts `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`, `SS.mmm`, and raw seconds.
- `ReqMem` parsing converts `K`/`M`/`G`/`T`/`P` suffixes and scope flags (`c` per CPU multiplied by `alloc_cpus`; `n` per node multiplied by `nodes`), mapping `?`/`Unknown` to `null`.
- State normalization strips suffixes (`CANCELLED by <uid>`, trailing `+`) and maps to the 10-state canonical enum.
- `ReqTRES` and `AllocTRES` extract CPU, node, memory, and GPU (`gres/gpu`, typed GPU, or `gpu`) counts.
- `Comment` (`RCWA_INPUT_HASH=<hex>`) and `$RCWA_DIR/<job_id>.json` sidecars provide declared input and command hashes.

### 2.2 Standard Workload Format (SWF)

Parses 18 whitespace-separated columns (plus `.swf.gz` gzip compression) and semicolon header pragmas (`UnixStartTime`, `MaxProcs`, `MaxNodes`, `Note`):
- Missing `-1` sentinels in runtime, wait, memory, CPU, group, executable, queue, or partition fields map to `null` or zeroed duration bounds without corrupting statistical percentiles.
- Status codes map deterministically: `1 -> COMPLETED`, `0 -> FAILED`, `5 -> CANCELLED`, others -> `OTHER`.
- Per-processor memory (`used_mem`, `req_mem` in KB/proc) multiplies by `alloc_cpus` and divides by `1024` (rounded integer MB) for cluster-total MB; `avg_cpu` multiplies by `alloc_cpus` for total CPU seconds.
- `executable number` populates `command_hash`. Because SWF lacks input file tracking, Class 4 recomputation is explicitly marked `"not available"` and never inferred heuristically.

### 2.3 Canonical Schema (27 Fields)

Defined in [`rcwa/model.py`](../rcwa/model.py) across Polars (`POLARS_CANONICAL_SCHEMA`), PyArrow (`CANONICAL_ARROW_SCHEMA`), and Pydantic (`CanonicalJobRecord`):

```text
job_id: string                  parent_job_id: string | null     source: string ("sacct" | "swf")
user: string                    account: string | null           partition: string | null
job_name: string | null         command_hash: string | null      input_hash: string | null
submit_time: timestamp[UTC]     start_time: timestamp[UTC]|null  end_time: timestamp[UTC]|null
wait_s: int64                   run_s: int64
state: enum {COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER}
exit_code: int32 | null
req_cpus: int32                 alloc_cpus: int32                cpu_time_used_s: float64 | null
req_mem_mb: int64 | null        max_rss_mb: int64 | null
req_gpus: int32                 alloc_gpus: int32
nodes: int32                    node_list: string | null
reserved_core_s: int64          reserved_mem_mb_s: int64 | null
```

Exclusion and retention rules:
- Rows with `state` in `{"RUNNING", "PENDING"}` are excluded prior to waste attribution and reported under Data Quality exclusions.
- Terminated rows with `run_s == 0` are retained and classified under Class 3 (`early_failure`) with zero reservation and zero consumption.

### 2.4 Declared Inputs Wrapper (`rcwa-wrap`)

```bash
rcwa-wrap --inputs data/a.parquet,config.yaml --big-file-mode size_mtime -- python train.py --lr 0.01
```

- Computes SHA-256 content hashes over declared paths (or `hash("<basename>:<bytes>:<int_mtime>")` when `big_file_mode == "size_mtime"` and file size exceeds `--big-file-threshold`, default `104857600` bytes).
- Normalizes the wrapped command line by stripping matching regex path prefixes (`--regex-strip`), keeping executable first, sorting `-` / `--` flags lexicographically, and preserving positional arguments in order.
- Missing declared files record `"missing"` in the sidecar and hash without blocking command execution.
- Persists checksums via `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>` when `SLURM_JOB_ID` is present and writes `$RCWA_DIR/<job_id>.json` when `RCWA_DIR` is set.
- Executes the command directly and propagates its exact exit code (`127` on `FileNotFoundError`, `126` on `PermissionError`).

---

## 3. Waste Attribution and Grouping Specification

### 3.1 Single-Pass Four-Class Precedence Cascade

For each non-active job, `reserved_core_s` and non-null-filled `reserved_mem_mb_s` are partitioned in strict precedence order:

1. **Class 3 (Failed & Retried Work)**: Jobs with `state` in `{"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}`, `state == "CANCELLED"` with `run_s > 0`, or `run_s == 0` assign 100% of core and memory reservations to Class 3 and receive one sub-label (`early_failure` checked first when `run_s <= 60`, then `oom`, `timeout`, `node_fail`, `cancelled_after_start`, `other_failure`). Causal resubmissions by the same `user` and task signature submitted within `retry_window_s` (default `86400`) after failure completion link 1-to-1 to the earliest eligible resubmission via `retry_of`, resolving `retry_chain_id`, `retry_count`, and cumulative chain cost.
2. **Class 4 (Redundant Recomputation)**: Remaining `COMPLETED` jobs (from non-SWF sources) matching an earlier `COMPLETED` job on both `(command_hash, input_hash)` within `recompute_window_s` (default `2592000` seconds = 30 days) assign 100% of core and memory reservations to Class 4 (`recompute_confidence = "declared_inputs"`). Matches lacking `input_hash` receive `possible_recompute = True` (`recompute_confidence = "command_only"`) and assign `0` to Class 4 totals.
3. **Class 2 (Idle Reserved CPU)** & **Class 1 (Memory Over-Request)**: Remaining runs partition each resource dimension independently:
   - Core: If `cpu_time_used_s` is `null`, assign `reserved_core_s` to `unattributed_core_s`. Otherwise, `class2_idle_core_s = max(0, reserved_core_s - max(0, int(round(cpu_time_used_s))))` and `used_core_s = reserved_core_s - class2_idle_core_s`.
   - Memory: If `req_mem_mb` is `null` or `reserved_mem_mb_s == 0`, all memory columns equal `0`. If `max_rss_mb` is `null`, assign `reserved_mem_mb_s` to `unattributed_mem_mb_s`. Otherwise, `class1_over_mem_mb_s = min(reserved_mem_mb_s, max(0, req_mem_mb - max_rss_mb) * run_s)` and `used_mem_mb_s = reserved_mem_mb_s - class1_over_mem_mb_s`.

### 3.2 Grouping and Ranked Reclaim List

- Default primary group key: `(user, job_name or command_hash)` serialized as `"{user}/{task}"`, fallback `"unknown"`. Secondary rollups compute by `account`, `partition`, and `user`.
- Composite rank score: `reclaim_score = reclaimable_core_hours + mem_weight * reclaimable_gb_hours` (`mem_weight` default `0.25`).
- OOM groups zero `reclaimable_gb_hours` so hazardous memory capacity is never ranked as savings.
- Top-5 evidence jobs per group are extracted ordered by `(-job_waste_score, job_id)`.

---

## 4. Rightsizing Recommendations Specification

- **Sample Floor & OOM Priority**: Non-OOM groups with fewer than `min_samples` (default `5`) jobs emit `None` across recommendations with action `below_sample_floor`. Any group containing `OUT_OF_MEMORY` bypasses `min_samples` and escalates memory to `ceil(max(oom_base) * oom_multiplier)` (default `1.5`), where `oom_base` is `observed_max_rss`, falling back to max `req_mem_mb`, falling back to `4000`, always floored at `observed_max_rss`, with `recommendation_direction = "increase"` and `recommendation_action = "oom_increase_mem"`.
- **Memory**: For non-OOM cohorts, `recommended_req_mem_mb = max(ceil(P99(max_rss_mb | COMPLETED) * 1.2), observed_max_rss)` across all states (falling back to `ceil(observed_max_rss * 1.2)` if no completed job records RSS).
- **CPU**: `recommended_cpus = clamp(ceil(P99(cpu_time_used_s / run_s | COMPLETED) * 1.2), 1, observed_max_cpus)`. Groups whose median runtime (or all runtimes) is strictly under `min_run_s` (default `120` s) emit `recommended_cpus = None`.
- **Timeout**: Groups with `TIMEOUT` incidents recommend `recommended_time_limit_s = ceil(P99(run_s | COMPLETED) * 1.5)` (falling back to all-state max runtime * `1.5` or `3600` s).
- **Early Failures & Result Caching**: Cohorts exhibiting early failures (`run_s <= 60`) list failure share and sample exit codes; cohorts where `group_waste_share >= threshold`, `trace_waste_share >= threshold`, or `cache_hits > 0` emit result cache hit-rate recommendations.

---

## 5. Simulator, Calibration, and Reporting Specification

- **Cluster Model**: Homogeneous YAML (`cluster_name`/`name`, `node_count`/`nodes`, `cores_per_node`, `mem_mb_per_node`), partitioned YAML (`partitions.<name>.{nodes, cores_per_node, mem_mb_per_node}`), or automatic inference from trace peaks (`min 16 nodes, 32 cores/node, 131072 MB/node`).
- **Scheduling Policy**: Deterministic FCFS ordered by `(submit_time, job_id)` with single shadow reservation at queue head and bounded `max_test = 50` non-delaying EASY backfill (satisfying either `current_time + expected_walltime <= res_time` or disjoint nodes relative to the head reservation, where `expected_walltime = req_time_s` if positive else `max(1, ceil(run_s * 1.2))`). Oversized jobs exceeding per-node hardware envelope clamp to node bounds.
- **Six Replay Scenarios**: `baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, and `all`.
- **Calibration**: Evaluates `baseline` simulated wait vs recorded `wait_s` using `median_absolute_error_s`, `spearman_rank_correlation`, `mean_absolute_error_s`, and `p95_absolute_error_s`.
- **Reports**: Deterministic JSON (`_round_floats(..., digits=6)` with sorted keys), Markdown (with conditionals hiding empty early-failure or zero-hit cache tables and declaring SWF Class 4 `"not available"`), and CSV reclaim tables.

---

## 6. CLI, Makefile, and Benchmark Interface

- **CLI Entrypoints**: `rcwa` (`version`, `synth`, `ingest`, `attribute`, `recommend`, `simulate`, `calibrate`, `report`, `run`) and `rcwa-wrap`.
- **Makefile Targets**: `all`, `setup`, `lint`, `typecheck`, `test`, `data`, `synth`, `run`, `calibrate`, `bench`, `bench-smoke`, `goldens`, `docker`.
- **Benchmark Suite (`bench/run.py`)**: Evaluates ten metrics (reclaim shares, G1 conservation, G2 violations, per-class recall/precision against `.truth.parquet`, wait shifts, SWF calibration error, sacct/SWF/simulation throughput, peak RSS, and attribution coverage) alongside hardware telemetry captured by [`bench/hardware.py`](../bench/hardware.py).
