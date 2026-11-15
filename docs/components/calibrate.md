# Simulator Calibration Engine

## 1. Overview

[`rcwa/calibrate.py`](../../rcwa/calibrate.py) compares simulated queue wait times (`sim_wait_s` from `scenario="baseline"`) against historical trace wait times (`wait_s`) to measure how closely the simplified FCFS + EASY-backfill model matches recorded scheduler behavior.

---

## 2. Exported API and Metrics (`compute_calibration_metrics`)

`compute_calibration_metrics(sim_df, historical_df)` inner-joins simulated and historical tables on `job_id` and returns five rounded summary fields (`round(..., 4)`):

- `median_absolute_error_s`: $\operatorname{median}\left(\left| \text{sim\_wait\_s}_i - \text{wait\_s}_i \right|\right)$ — resistant to extreme outliers while capturing typical wait bias.
- `mean_absolute_error_s`: $\operatorname{mean}\left(\left| \text{sim\_wait\_s}_i - \text{wait\_s}_i \right|\right)$.
- `p95_absolute_error_s`: 95th percentile of absolute wait errors.
- `spearman_rank_correlation`: Pearson correlation over Polars `.rank()` columns of `sim_wait_s` and `wait_s`, quantifying rank-ordering fidelity between simulated and historical queues.
- `job_count`: Count of matched job records evaluated.

### Degenerate Input Handling
- Empty join (`job_count == 0`): Returns `0.0` across all metrics and `job_count = 0`.
- Single job (`job_count < 2`): Returns `spearman_rank_correlation = 1.0`.
- Zero variance (`std(sim_waits) == 0` or `std(real_waits) == 0`): Returns `1.0` if both wait vectors are identical element-wise, else `0.0`.
- NaN correlation guards map `NaN` to `0.0`.

---

## 3. End-to-End Trace Calibration (`calibrate_trace`)

```python
calibrate_trace(trace_path: Path | str, cluster_path: Path | str | None = None) -> dict[str, Any]
```

Loads `.swf`, `.swf.gz`, `.parquet`, or `sacct` traces, loads YAML topology (or calls `infer_cluster_from_trace`), runs `simulate_trace(..., scenario="baseline")`, and computes calibration metrics via `compute_calibration_metrics`. Accessible via CLI as `rcwa calibrate <trace> [--cluster <yaml>] [--output <json>]`.

### Benchmark Interpretation Note

Because the EASY-backfill model intentionally omits fair-share decay, preemption, maintenance reservations, and network constraints (`ADR 004`), calibration outputs bound prediction confidence rather than claiming exact historical reproduction. For example, on the committed 10-job fixture (`sample_workload.swf`) evaluated in [`bench/results/bench.md`](../../bench/results/bench.md), ample cluster capacity produces uniform zero simulated waits alongside non-zero historical waits, yielding `median_absolute_error_s = 12.0` seconds and `spearman_rank_correlation = 0.0`.
