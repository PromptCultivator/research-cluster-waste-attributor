# Canonical Job Record and Schema

## 1. Overview

`rcwa/model.py` defines the unified in-memory representation shared across every pipeline stage of `research-cluster-waste-attributor` (`rcwa`). Records parsed from Slurm `sacct` exports (`source = "sacct"`) and Standard Workload Format logs (`source = "swf"`) normalize into a single 27-column schema exposed through three interfaces:

- **Polars Schema (`POLARS_CANONICAL_SCHEMA`)**: Vectorized columnar dtype mapping evaluated eagerly for fast CLI ingestion and batch attribution.
- **Apache Arrow Schema (`CANONICAL_ARROW_SCHEMA`)**: Strict nullable/non-nullable schema constructed lazily via `get_canonical_arrow_schema()`, `to_canonical_arrow()`, and `from_canonical_arrow()`.
- **Pydantic v2 Record (`CanonicalJobRecord`)**: Row-level validation model computing `reserved_core_s` and `reserved_mem_mb_s` via a post-validation model validator when omitted.

---

## 2. Canonical Schema Fields (27 Columns)

| Field Name | Polars Type | PyArrow Type | Nullable | Description |
|---|---|---|---|---|
| `job_id` | `String` | `string` | No | Unique job or decomposed task identifier. |
| `parent_job_id` | `String` | `string` | Yes | Parent job identifier for array tasks (`12345_0`) or pack components (`12345+0`). |
| `source` | `String` | `string` | No | Ingest adapter source identifier (`"sacct"` or `"swf"`). |
| `user` | `String` | `string` | No | Submitting username or numeric SWF user ID (`"unknown"` fallback). |
| `account` | `String` | `string` | Yes | Slurm billing account or SWF group ID. |
| `partition` | `String` | `string` | Yes | Scheduler partition/queue name or SWF queue/partition ID. |
| `job_name` | `String` | `string` | Yes | User-supplied Slurm job name (`null` in SWF). |
| `command_hash` | `String` | `string` | Yes | SHA-256 of normalized command/`SubmitLine`/`JobName`, or SWF executable number. |
| `input_hash` | `String` | `string` | Yes | Composite SHA-256 of declared input files (`RCWA_INPUT_HASH` or sidecar JSON). |
| `submit_time` | `Datetime("ms", "UTC")` | `timestamp("s", tz="UTC")` | No | Job submission timestamp in UTC. |
| `start_time` | `Datetime("ms", "UTC")` | `timestamp("s", tz="UTC")` | Yes | Execution start timestamp in UTC (`null` when unstarted). |
| `end_time` | `Datetime("ms", "UTC")` | `timestamp("s", tz="UTC")` | Yes | Execution end timestamp in UTC (`null` when active or unstarted). |
| `wait_s` | `Int64` | `int64` | No | Queue delay in seconds (`max(0, start_time - submit_time)`). |
| `run_s` | `Int64` | `int64` | No | Elapsed execution duration in seconds (`max(0, elapsed)`). |
| `state` | `String` | `string` | No | Normalized canonical execution state (`JobState` enum string). |
| `exit_code` | `Int32` | `int32` | Yes | Exit status integer (`null` in SWF or when unavailable). |
| `req_cpus` | `Int32` | `int32` | No | Requested CPU cores. |
| `alloc_cpus` | `Int32` | `int32` | No | Allocated CPU cores (`>= 1` after normalization). |
| `cpu_time_used_s` | `Float64` | `float64` | Yes | Cumulative CPU core-seconds consumed across allocated cores. |
| `req_mem_mb` | `Int64` | `int64` | Yes | Total requested memory across allocation in megabytes. |
| `max_rss_mb` | `Int64` | `int64` | Yes | Peak resident set size observed across execution steps in megabytes. |
| `req_gpus` | `Int32` | `int32` | No | Requested GPU device count extracted from TRES (default `0`). |
| `alloc_gpus` | `Int32` | `int32` | No | Allocated GPU device count extracted from TRES (default `0`). |
| `nodes` | `Int32` | `int32` | No | Count of allocated physical nodes (default `1`). |
| `node_list` | `String` | `string` | Yes | Assigned scheduler node list expression. |
| `reserved_core_s` | `Int64` | `int64` | No | Reserved CPU core-seconds: `max(0, alloc_cpus * run_s)`. |
| `reserved_mem_mb_s` | `Int64` | `int64` | Yes | Reserved memory MB-seconds (`max(0, req_mem_mb * run_s)` when `req_mem_mb` is present; normalized to `0` during attribution). |

---

## 3. Canonical Execution States (`JobState`)

`JobState` defines ten canonical states normalized from scheduler-specific status strings and numeric codes:

| State Value | Meaning | Attribution Disposition |
|---|---|---|
| `COMPLETED` | Finished with exit code `0` / SWF status `1` | Evaluated for Class 4, Class 2, Class 1, and Utilized |
| `FAILED` | Non-zero exit or `BOOT_FAIL` / SWF status `0` | Class 3 (`early_failure` or `other_failure`) |
| `TIMEOUT` | Wallclock limit reached or `DEADLINE` | Class 3 (`early_failure` or `timeout`) |
| `OUT_OF_MEMORY` | Killed by cgroup/kernel OOM handler | Class 3 (`early_failure` or `oom`); triggers G2 escalation |
| `NODE_FAIL` | Terminated due to compute node failure | Class 3 (`early_failure` or `node_fail`) |
| `CANCELLED` | Terminated by `CANCELLED*` / `REVOKED` / SWF status `5` | Class 3 if `run_s > 0` or `run_s == 0`; otherwise zero-reservation |
| `PREEMPTED` | Preempted by scheduler priority | Class 3 (`early_failure` or `other_failure`) |
| `RUNNING` | Still running at trace export time | Excluded prior to attribution; counted in Data Quality |
| `PENDING` | Still queued at trace export time | Excluded prior to attribution; counted in Data Quality |
| `OTHER` | Any other unmapped scheduler state string or code | Retained (`Class 3` only if `run_s == 0`) |

---

## 4. Exported Utilities and Lazy Loading

- `empty_canonical_df()`: Returns a zero-row `pl.DataFrame` matching `POLARS_CANONICAL_SCHEMA`.
- `get_canonical_arrow_schema()`: Returns the cached singleton `pyarrow.Schema` (`CANONICAL_ARROW_SCHEMA`).
- `to_canonical_arrow(data)`: Converts a Polars `DataFrame` or Arrow `Table` to the strict 27-field Arrow schema, casting columns where needed and raising `ValueError` if a non-nullable field is missing.
- `from_canonical_arrow(table)`: Converts a canonical Arrow `Table` back into a `pl.DataFrame` cast to `POLARS_CANONICAL_SCHEMA`.
- `__getattr__(name)`: Lazily initializes `CANONICAL_ARROW_SCHEMA` and `CanonicalJobRecord` so fast CLI subcommands avoid importing `pyarrow` and `pydantic` until accessed.
