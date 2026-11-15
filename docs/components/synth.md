# Synthetic Trace Generator

## 1. Overview

[`rcwa/synth.py`](../../rcwa/synth.py) generates deterministic 26-column Slurm `sacct` pipe-delimited traces paired with per-job planted ground-truth Parquet tables for benchmarking, property validation, and precision/recall evaluation.

---

## 2. API and CLI Interface

### Exported Functions
- `parse_trace_size(size_val: int | str) -> int`: Parses integer strings or `k`/`M`/`G` magnitude suffixes (`"20k" -> 20000`, `"1M" -> 1000000`).
- `generate_synthetic_trace(size="20k", seed=1, faults="default") -> tuple[str, pl.DataFrame]`: Returns `(sacct_text, truth_df)` deterministically using `random.Random(seed)`.
- `write_synthetic_trace(output_path, sacct_text, truth_df=None, ground_truth_path=None) -> None`: Writes `.sacct` trace and `.truth.parquet` (or custom path) to disk.

### CLI Usage

```bash
rcwa synth --size 20k --seed 1 --faults default --output data/raw/synth_20k.sacct --ground-truth data/raw/synth_20k.truth.parquet
```

Fault profiles (`--faults`):
- `default`: Balanced mix of normal runs, planted waste Classes 1–4, retry resubmissions, unattributed missing-metric rows, and trailing active `RUNNING` rows.
- `all_waste`: Cycles evenly through `class1`, `class2`, `class3_fail`, and `class4_dup`.
- `no_waste`: Generates normal high-utilization runs only (`cpu_util` 85%–98%, `max_rss` 75%–95%).

---

## 3. Workload Generation Mechanics

1. **User & Partition Profiles**: Cycles across 8 user/account/partition profiles (`alice` through `heidi`, partitions `compute`, `fatmem`, and `gpu` with `,gres/gpu=1` TRES entries), rotating 4 subgroups per profile (`i // 50 % 4`).
2. **Monotonic Submit Stagger (`DEC-015`)**: Submits jobs monotonically at 35-second increments starting from `2026-03-01T08:00:00Z` (`wait_s` sampled in `[2, 60]`), preventing artificial arrival stampedes in simulation benchmarks.
3. **Planted Categories (`fault_type`)**:
   - `normal` (`true_class = 0`): Balanced utilization (`75%–95%` RSS, `85%–98%` CPU) with `RCWA_INPUT_HASH` comments stored in `completed_cache` for future duplicates.
   - `class1_mem` (`true_class = 1`): Low peak RSS (`10%–25%` of `req_mem_mb`) paired with high CPU efficiency.
   - `class2_cpu` (`true_class = 2`): At least `4` allocated CPUs running ~1 active core (`cpu_used_s = run_s * 0.95`).
   - `class3_fail`, `class3_timeout`, `class3_oom`, `class3_early` (`true_class = 3`): Abnormal terminations (`FAILED`, `TIMEOUT` at `7200s`, `OUT_OF_MEMORY` with `exit_code = 0:125`, and `15s` early failure); `class3_fail` enqueues failure records for subsequent `retry_success` jobs (`is_retry = True`).
   - `class4_dup` (`true_class = 4`, `is_recompute = True`): Replays command and `RCWA_INPUT_HASH` matching an earlier completed run.
   - `unattributed` (`true_class = -1`): `COMPLETED` runs with blank `MaxRSS`, `AveRSS`, and `TotalCPU`.
   - `active_running` (`true_class = -2`): `RUNNING` rows in the final trace tail with `End = Unknown`.

---

## 4. Ground-Truth Schema (`.truth.parquet`)

Each row in the emitted truth DataFrame includes 17 audit columns:
`job_id`, `true_class`, `planted_fault_type`, `planted_is_recompute`, `planted_is_retry`, `is_recompute`, `is_retry`, `user`, `job_name`, `command_hash`, `input_hash`, `req_cpus`, `alloc_cpus`, `req_mem_mb`, `max_rss_mb`, `run_s`, and `state`.
