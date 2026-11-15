# Rightsizing Recommendations and Safety Guardrails

## 1. Overview

[`rcwa/recommend.py`](../../rcwa/recommend.py) implements `recommend_jobs(attributed_df, policy=None, grouped_df=None, trace_path=None)` and `export_recommendations(recommendations_df, output_path, format="parquet")` under the 33-column `RECOMMENDATIONS_SCHEMA`. It computes percentile memory, CPU, and timeout limits while strictly enforcing **Guarantee G2 (Safety Guardrails)**.

---

## 2. Guardrail Priority Order and Formulas

### 2.1 Sample Floor vs OOM Priority (`DEC-010`)

Each group cohort first checks `sample_count_ok = (job_count >= min_samples)` (default `5`) and `has_oom = any(state == "OUT_OF_MEMORY" or class3_sub_label == "oom")`:
- **OOM Overrides Sample Floor**: If `has_oom` is `True`, escalation executes regardless of `job_count`.
- **Small Sample Guardrail**: If `not sample_count_ok and not has_oom`, all numeric recommendations (`recommended_req_mem_mb`, `recommended_cpus`, `recommended_time_limit_s`) return `None`, `recommendation_direction = "none"`, and `recommendation_action = "below_sample_floor"`.

### 2.2 Memory Recommendations

Let `observed_max_rss` denote peak positive `max_rss_mb` observed across **all** jobs in the cohort regardless of terminal state:
- **OOM Escalation (`has_oom == True`)**:
  $$\text{oom\_base} = \text{observed\_max\_rss} \quad (\text{fallback } \max(\text{req\_mem\_mb}) \to 4000)$$
  $$\text{recommended\_req\_mem\_mb} = \max\left(\left\lceil \text{oom\_base} \times \text{oom\_multiplier} \right\rceil,\ \text{observed\_max\_rss}\right)$$
  Defaults: `oom_multiplier = 1.5`, `recommendation_direction = "increase"`, `recommendation_action = "oom_increase_mem"`. Upstream `group_jobs` zeros `reclaimable_gb_hours` so OOM cohorts never count toward reclaimable memory savings.
- **Standard Rightsizing (`has_oom == False`)**:
  $$\text{recommended\_req\_mem\_mb} = \max\left(\left\lceil \text{P99}(\text{max\_rss\_mb} \mid \text{COMPLETED}) \times \text{safety\_factor} \right\rceil,\ \text{observed\_max\_rss}\right)$$
  where `percentile = 0.99` and `safety_factor = 1.2`. If no completed job records positive RSS but failed runs do, uses `ceil(observed_max_rss * safety_factor)`; otherwise returns `None`.

### 2.3 CPU Core Recommendations

- **Short-Job Guardrail**: Cohorts whose median duration or all job durations fall strictly under `min_run_s` (default `120` s) emit `recommended_cpus = None` because short startups skew `cpu_time_used_s / run_s` measurements.
- **Percentile Target**: Over positive rates from `COMPLETED` jobs (`cpu_time_used_s / run_s`):
  $$\text{recommended\_cpus} = \operatorname{clamp}\left(\left\lceil \text{P99}(\text{rate} \mid \text{COMPLETED}) \times \text{cpu\_safety\_factor} \right\rceil,\ 1,\ \text{observed\_max\_cpus}\right)$$
  Defaults: `percentile = 0.99`, `safety_factor = 1.2`.

### 2.4 Timeout Limit Recommendations

Cohorts with any `TIMEOUT` or `class3_sub_label == "timeout"` receive:
$$\text{recommended\_time\_limit\_s} = \left\lceil \text{P99}(\text{run\_s} \mid \text{COMPLETED}) \times \text{timeout\_multiplier} \right\rceil$$
(default `multiplier = 1.5`), falling back to `ceil(max(all_runtimes) * multiplier)`, or `3600` seconds if all durations are `0`. Non-timeout cohorts emit `None`.

---

## 3. Directions, Actions, Export, and Verification

Comparing recommended limits against cohort medians (`typical_req_mem`, `typical_alloc_cpus`) assigns:
- `recommendation_direction`: `"increase"`, `"decrease"`, `"keep"`, or `"none"`.
- `recommendation_action`: `"oom_increase_mem"`, `"below_sample_floor"`, `"decrease_req_mem_and_cpu"`, `"decrease_req_mem"`, `"decrease_cpu"`, `"increase_resources"`, `"keep_resources"`, or `"none"`.
- `export_recommendations` exports Parquet or CSV (joining `evidence_job_ids` lists with `;` in CSV).

**Guarantee G2 Property Verification**: [`tests/property/test_safety_guardrails.py`](../../tests/property/test_safety_guardrails.py) exercises `recommend_jobs` across randomized Hypothesis batches and `10,000` generated job cohorts, verifying zero violations of memory RSS floors, OOM escalation/zeroing, sample-floor withholding, and `[1, observed_max_cpus]` clamping.
