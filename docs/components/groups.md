# Job Grouping and Reclaim Ranking

## 1. Overview

[`rcwa/groups.py`](../../rcwa/groups.py) implements `group_jobs(attributed_df, policy=None, group_keys=None)`, `generate_secondary_rollups(attributed_df, policy=None)`, and `export_group_metrics(df, path, format="parquet")` under `GROUP_METRICS_SCHEMA`.

---

## 2. Grouping Keys and Secondary Rollups

### 2.1 Primary Cohort Key

Configured under `grouping.group_keys` in policy YAML (`policies/default.yaml`):
- Default keys: `["user", "command_hash_or_job_name"]`, rendered as `"{user}/{task}"`.
- `command_hash_or_job_name` prefers non-empty **`job_name`** first, falling back to **`command_hash`**, then `"unknown"`.
- Custom `group_keys` (single column or arbitrary list) join non-empty string values with `/` (`"unknown"` fallback).

### 2.2 Secondary Rollups

`generate_secondary_rollups` computes three additional aggregated tables over `group_jobs` using single keys:
- `account`: Billing project or SWF group ID.
- `partition`: Cluster partition or SWF queue.
- `user`: Individual user summaries.

---

## 3. Reclaim Scoring, OOM Memory Zeroing, and Sample Flagging

For each cohort, `1 GB-hour = 1024 * 3600 MB-seconds` (`3,686,400` MB-s). `group_jobs` computes:
- `has_oom`: `(state == "OUT_OF_MEMORY") | (class3_sub_label == "oom")` across any job in the group.
- `reclaimable_core_hours = class2_idle_core_hours + class4_recompute_core_hours`.
- `reclaimable_gb_hours`: **`0.0` when `has_oom` is true** (Guarantee G2 protection preventing memory reclamation on OOM cohorts); otherwise `class1_over_mem_gb_hours + class4_recompute_gb_hours`.
- `reclaim_score` (and duplicate alias column `score`):
  $$\text{reclaim\_score} = \text{reclaimable\_core\_hours} + w_{\text{mem}} \times \text{reclaimable\_gb\_hours}$$
  where $w_{\text{mem}}$ (`attribution.mem_weight_core_hours_per_gb_hour`) defaults to `0.25`.
- `sample_count_ok`: Boolean `job_count >= min_samples` (default `5`). While downstream [`rcwa/recommend.py`](../../rcwa/recommend.py) withholds resource reductions when `sample_count_ok` is `False` (unless `has_oom` holds), `group_jobs` includes every cohort sorted deterministically by `(-reclaim_score, group)`.
- Cluster Shares: `cluster_reserved_core_share` (`group_reserved_core_hours / cluster_total`) and `cluster_waste_score_share` (`reclaim_score / cluster_total_score`).

---

## 4. Top-5 Evidence Extraction and CSV Export

- Per-job waste score computes `(class2_idle_core_s + class3_core_s + class4_core_s) / 3600.0 + mem_weight * (class1_over_mem_mb_s + class3_mem_mb_s + class4_mem_mb_s) / (1024.0 * 3600.0)`.
- Within each group, jobs sort by `(-_job_waste_score, job_id)` and record the top 5 identifiers into `evidence_job_ids` (`List(String)`).
- `export_group_metrics` serializes directly to Parquet, or converts `evidence_job_ids` into semicolon-delimited strings (`";"`) when exporting CSV.
