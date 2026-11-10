# Reporting and Export Engine

## 1. Overview

The reporting engine (`rcwa/report.py`) transforms attributed records, ranked reclamation cohorts, simulation replays, and calibration diagnostics into structured human-readable and machine-readable deliverables.

The engine supports three export formats:
1. **Markdown (`.md`)**: Executive summary and detailed tables for engineering review.
2. **JSON (`.json`)**: Machine-readable data structure for automated pipeline ingestion.
3. **CSV (`.csv`)**: Tabular export of ranked cohorts for spreadsheet analysis.

The reporting engine enforces **Guarantee G3 (Determinism)**: identical trace inputs and configurations generate byte-identical output artifacts.

---

## 2. Report Sections and Structure

Generated reports include five standardized sections:

### 2.1 Executive Summary
Presents high-level workload and waste indicators:
- Total jobs analyzed, active jobs excluded, and evaluation timespan.
- Total core-hours and GB-hours reserved vs utilized.
- Total reclaimable capacity by category and percentage of cluster capacity.

### 2.2 Waste Partition by Class
Breaks down the non-overlapping allocation of cluster resources:
- Class 1: Memory Over-Request
- Class 2: Idle Reserved CPU
- Class 3: Failed and Retried Work (with sub-label breakdown: `oom`, `timeout`, `early_failure`)
- Class 4: Redundant Recomputation
- Used Capacity
- Unattributed Metrics

A summary balance check validates that all components sum exactly to 100% of reservation, reinforcing Guarantee G1.

### 2.3 Ranked Reclaim List
Presents candidate cohorts ordered by weighted reclaim score:
- Rank and Group Name (`user/command_hash_or_job_name`).
- Sample Count.
- Reclaimable Core-Hours and GB-Hours.
- Recommended Action and Resource Adjustments (`req_mem_mb`, `cpus`, `time_limit`).
- Sample Evidence (Top 5 Job IDs).

### 2.4 Scenario Impact Projections
Compares simulated replay results against historical and simulated baselines:
- Median and P95 Queue Wait Times.
- Total Cluster Makespan.
- Average Core and Memory Utilization.
- Completed Jobs per Simulated Day.
- Stated Baseline Calibration Metrics (MAE, Spearman $\rho_s$).

### 2.5 Data Quality and Diagnostics
Audits trace health and instrumentation coverage:
- Active / Incomplete Jobs (`RUNNING`, `PENDING`).
- Jobs with missing RSS or CPU time measurements.
- Early failure rate ($\le 60$s) and associated exit codes.
- Candidate recomputation matches flagged as `command_only` without declared input hashes.
