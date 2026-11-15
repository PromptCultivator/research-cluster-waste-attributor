# Reporting and Export Engine

## 1. Overview

[`rcwa/report.py`](../../rcwa/report.py) compiles attributed traces, cohort recommendations, early-failure summaries, result cache projections, secondary rollups, all six counterfactual simulator runs, and calibration diagnostics into deterministic structured dictionaries (`build_report_data`), human-readable Markdown (`render_markdown_report`), JSON, and tabular CSV reclaim lists (`render_csv_report`).

---

## 2. Compiled Report Structure (`build_report_data`)

```python
build_report_data(
    canonical_df: pl.DataFrame,
    attributed_df: pl.DataFrame,
    policy: Any = None,
    cluster: Any = None,
    simulation_scenarios: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    include_simulation: bool = True,
) -> dict[str, Any]
```

Compiles nine top-level keys, passed through `_round_floats(report, digits=6)` with recursively sorted dictionary keys to guarantee **Guarantee G3 (Byte Determinism)**:

1. `summary`: `total_jobs`, `evaluated_jobs`, `excluded_jobs`, `total_reserved_core_hours`, `total_used_core_hours`, `total_reserved_gb_hours`, `total_used_gb_hours`.
2. `waste_classification`: Per-class totals in core-hours and GB-hours (`class1`–`class4` and unattributed). When every record originates from `"swf"`, sets `class4_redundant_core_hours = 0.0`, `class4_redundant_gb_hours = 0.0`, and `"class4_status": "not available"`.
3. `ranked_reclaim_list`: Ordered cohorts with `rank`, `group`, `count`, `reclaim_core_hours`, `reclaim_gb_hours`, `score`, nested `recommendation` (`req_mem_mb`, `cpus`, `direction`), `recommendation_action`, and `evidence_job_ids`.
4. `data_quality`: `excluded_active_count` (`RUNNING`/`PENDING`), `unattributed_cpu_share_pct`, `unattributed_memory_share_pct`, and `declared_input_coverage_pct`.
5. `early_failure_groups`: Cohorts containing `class3_sub_label == "early_failure"`, recording `failure_count`, `total_jobs`, `failure_share`, and up to `5` unique `sample_exit_codes`.
6. `result_cache`: Group hit rates and reclaimable savings produced by `simulate_result_cache`.
7. `secondary_rollups`: Cohort metric lists computed by `user`, `account`, and `partition` (serialized in JSON).
8. `simulation_scenarios`: Automatically replays all 6 scenarios (`baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, `all`) when `include_simulation=True` and `simulation_scenarios is None`.
9. `calibration`: Baseline `median_absolute_error_s` and `spearman_rank_correlation` computed automatically when `wait_s` and `include_simulation=True` apply (`calibration is None`).

---

## 3. Output Renderers

### 3.1 `render_markdown_report(report_data)`

Produces Markdown sections in fixed order:
- `## Summary`
- `## Waste Classification` (displays `not available` for Class 4 cells when `class4_status == "not available"`)
- `## Ranked Reclaim List` (formats `None (< min_samples)` and `req_mem_mb=...M (OOM escalation)` explicitly)
- `## Data Quality Accounting`
- `## Early Failure Groups` *(omitted when `early_failure_groups` is empty)*
- `## Result Cache Recommendations` *(omitted when no group qualifies `recommended=True`)*
- `## Simulation Scenarios` *(omitted when scenarios map is empty)*
- `## Calibration Metrics` *(omitted when calibration map is empty)*

### 3.2 `render_csv_report(report_data)`

Emits RFC-compatible header and rows for the ranked reclaim table:
`rank,group,count,reclaim_core_hours,reclaim_gb_hours,score,recommendation_action,evidence_job_ids`, joining `evidence_job_ids` lists with `";"`.
