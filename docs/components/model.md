# Canonical Job Record and Schema

## 1. Overview

The Canonical Job Record serves as the unified in-memory data representation for `rcwa`. Regardless of whether input traces originate from Slurm accounting exports (`sacct`), Standard Workload Format logs (`SWF`), or containerized orchestration systems, records are normalized into this consistent schema before processing by attribution, grouping, and simulation engines.

The canonical representation provides three interchangeable interfaces:
- **PyArrow Table Schema**: Strictly typed, columnar representation optimized for zero-copy Parquet serialization and cross-process exchange.
- **Polars Schema**: Vectorized tabular structure executing batch calculations and grouping operations.
- **Pydantic Model (`CanonicalJobRecord`)**: Row-level validation model enforcing field constraints, type conversions, and boundary checks.

---

## 2. Canonical Schema Fields

Each job record conforms to the following attributes:

| Field Name | Type | Nullable | Description |
|---|---|---|---|
| `job_id` | String | No | Unique identifier for the job or task component. |
| `parent_job_id` | String | Yes | Identifier of parent job for array tasks (`12345_0`) or pack job components (`12345+0`). |
| `source` | String | No | Input format source: `"sacct"`, `"swf"`, `"k8s"`, or `"ray"`. |
| `user` | String | No | Submitting user account or user identifier. |
| `account` | String | Yes | Slurm bank account, charge project, or group name. |
| `partition` | String | Yes | Scheduler queue or partition designation. |
| `job_name` | String | Yes | User-provided submission script or executable name. |
| `command_hash` | String | Yes | Hash or normalized signature of the command line. For SWF, the executable index. |
| `input_hash` | String | Yes | SHA-256 digest of declared input files generated via `rcwa-wrap`. |
| `submit_time` | Timestamp[s, UTC] | No | Unix timestamp when the job entered the scheduler queue. |
| `start_time` | Timestamp[s, UTC] | Yes | Unix timestamp when execution began on compute nodes (`null` for cancelled while pending). |
| `end_time` | Timestamp[s, UTC] | Yes | Unix timestamp when the job concluded (`null` for active states). |
| `wait_s` | Int64 | No | Queue delay in seconds: $\max(0, \text{start\_time} - \text{submit\_time})$. |
| `run_s` | Int64 | No | Wallclock execution elapsed time in seconds: $\max(0, \text{end\_time} - \text{start\_time})$. |
| `state` | String / Enum | No | Canonical terminal state (see Section 3). |
| `exit_code` | Int32 | Yes | Primary process exit status (e.g. 0 for success, 127 for not found). |
| `req_cpus` | Int32 | No | Number of processor cores requested at submission. |
| `alloc_cpus` | Int32 | No | Number of processor cores allocated by the scheduler. |
| `cpu_time_used_s`| Float64 | Yes | Cumulative CPU core-seconds consumed across active threads. |
| `req_mem_mb` | Int64 | Yes | Total requested RAM in megabytes across the job allocation. |
| `max_rss_mb` | Int64 | Yes | Peak resident set size (RAM) consumed during job execution in megabytes. |
| `req_gpus` | Int32 | No | Number of accelerator devices requested. |
| `alloc_gpus` | Int32 | No | Number of accelerator devices allocated. |
| `nodes` | Int32 | No | Count of discrete physical host nodes allocated. |
| `node_list` | String | Yes | Hostnames or condensed node list assigned by the scheduler. |
| `reserved_core_s`| Int64 | No | Derived total core capacity: $\text{alloc\_cpus} \times \text{run\_s}$. |
| `reserved_mem_mb_s` | Int64 | No | Derived memory capacity: $\text{req\_mem\_mb} \times \text{run\_s}$. |

---

## 3. Canonical Execution States

Scheduler-specific termination reasons map into ten discrete canonical states:

```
+------------------------------------------------------------------------------------+
|                               CANONICAL STATES                                     |
+-------------------+----------------------------------------------------------------+
| COMPLETED         | Job finished with exit code 0 or successful scheduler status.  |
| FAILED            | Application exit status != 0 or unhandled script exception.    |
| TIMEOUT           | Terminated by scheduler for exceeding requested wallclock.    |
| OUT_OF_MEMORY     | Killed by Linux OOM killer or scheduler memory cgroup.        |
| NODE_FAIL         | Terminated due to physical hardware or host kernel failure.    |
| CANCELLED         | Terminated via user or administrative intervention.            |
| PREEMPTED         | Evicted by scheduler to make room for higher-priority work.    |
| RUNNING           | Job active at the time of trace export (excluded from waste).  |
| PENDING           | Job queued at the time of trace export (excluded from waste).  |
| OTHER             | Unrecognized or unmapped scheduler state string.               |
+-------------------+----------------------------------------------------------------+
```

---

## 4. Special Handling Rules

1. **Active and Pending Jobs**:
   - Jobs in `RUNNING` or `PENDING` states lack terminal metrics (`run_s` is indefinite, `max_rss_mb` is incomplete).
   - These records are excluded from waste attribution and simulation replay.
   - Counts are preserved and displayed in the report's Data Quality Accounting section.

2. **Early Failures with Zero Runtime**:
   - Jobs where `run_s == 0` (e.g., immediate script syntax errors, missing execution environments) are preserved.
   - They are attributed to Class 3 (Failed Work) with 0 core-seconds and 0 megabyte-seconds of consumption, ensuring failure event counts remain accurate in group statistics.

3. **Sub-Second Lazy Evaluation**:
   - `rcwa/model.py` utilizes module-level lazy property evaluation for PyArrow schema compilation and Pydantic model initialization.
   - This design prevents unnecessary type compilation overhead during rapid CLI argument validation and parsing routines.
