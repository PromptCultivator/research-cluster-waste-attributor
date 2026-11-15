# Normalization Engine

## 1. Overview

The normalization module ([`rcwa/normalize.py`](../../rcwa/normalize.py)) converts scheduler-specific duration strings, memory specifications, state qualifiers, trackable resource (`TRES`) lists, comments, exit codes, and compound job identifiers into uniform numeric and string primitives compatible with `POLARS_CANONICAL_SCHEMA`.

---

## 2. Duration and Timestamp Parsing

- `parse_duration_s(val) -> float | None`: Parses `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`, `MM:SS`, or numeric strings into non-negative float seconds (clamping negatives to `0.0`). Sentinels (`UNLIMITED`, `INVALID`, `Partition_Limit`, `Unknown`, `N/A`, `None`, `-`, empty string) return `None`.
- `parse_duration_int(val) -> int`: Converts `parse_duration_s` output into rounded integer seconds via `int(round(secs + 1e-9))` (returning `0` on `None`).
- `parse_slurm_timestamp(val) -> datetime | None`: Parses ISO-8601 strings (`datetime.fromisoformat`), attaching or converting to `UTC` timezone and returning `None` on `Unknown`, `N/A`, `NONE`, `None`, or malformed strings.

---

## 3. Memory Unit and Scope Parsing

### 3.1 Requested Memory (`parse_slurm_memory_mb`)

```python
parse_slurm_memory_mb(val: str | None, alloc_cpus: int = 1, nodes: int = 1) -> int | None
```

1. Maps missing/sentinel values (`?`, `Unknown`, `N/A`, `None`, `-`, negative values, empty strings) to `None`.
2. Strips optional scope indicator suffix (`c`/`C` for per-CPU, `n`/`N` for per-node).
3. Scales numeric value according to unit suffix (`K` $\div 1024$, default `M` $\times 1$, `G` $\times 1024$, `T` $\times 1024^2$, `P` $\times 1024^3$).
4. Multiplies per-CPU specifications by `max(1, alloc_cpus)` and per-node specifications by `max(1, nodes)`, returning `int(round(total_mb))`.

Examples:
- `4000Mc` with `alloc_cpus = 4` $\to 16,000\text{ MB}$
- `16G` $\to 16,384\text{ MB}$
- `64Gn` with `nodes = 2` $\to 131,072\text{ MB}$

### 3.2 Resident Set Size (`parse_slurm_memory_rss_mb`)

Converts observed memory counters (`MaxRSS`, `AveRSS`, and `TRES mem=...` values) with `K`/`M`/`G`/`T`/`P` suffixes into rounded integer megabytes without per-CPU/per-node scope multiplication.

---

## 4. State, Exit Code, and TRES Normalization

- **Slurm State Mapping (`map_slurm_state`)**: Strips trailing `+` modifiers and normalizes raw strings to the 10-state canonical set:
  - `COMPLETED` $\to$ `COMPLETED`
  - `FAILED`, `BOOT_FAIL` $\to$ `FAILED`
  - `TIMEOUT`, `DEADLINE` $\to$ `TIMEOUT`
  - `OUT_OF_MEMORY` $\to$ `OUT_OF_MEMORY`
  - `NODE_FAIL` $\to$ `NODE_FAIL`
  - `PREEMPTED` $\to$ `PREEMPTED`
  - `RUNNING` $\to$ `RUNNING`
  - `PENDING`, `REQUEUED` $\to$ `PENDING`
  - `CANCELLED`, `CANCELLED ...`, `REVOKED` $\to$ `CANCELLED`
  - Unrecognized / blank $\to$ `OTHER`
- **SWF Status Mapping (`map_swf_status`)**: `1 -> COMPLETED`, `0 -> FAILED`, `5 -> CANCELLED`, any other value $\to$ `OTHER`.
- **Exit Code Parsing (`parse_slurm_exit_code`)**: Splits `code:signal` expressions, returning `code` when `code != 0`, else `signal` when `signal != 0`, else `0`.
- **TRES String Parsing (`parse_tres`)**: Parses comma-separated `key=val` pairs into `{"gpus": int, "cpus": int, "nodes": int, "mem_mb": int}`. GPU extraction resolves in strict precedence order: explicit generic `gres/gpu` count $\to$ sum across typed `gres/gpu:<model>` entries $\to$ bare `gpu` count $\to$ `0`.
- **Comment Hash & Job ID Decomposition**:
  - `parse_comment_input_hash(comment)`: Matches `RCWA_INPUT_HASH=([0-9a-fA-F]+)` and returns lowercased hex digest.
  - `decompose_job_id(raw_id)`: Splits step suffix on `.` and derives `parent_job_id` before `_` (array jobs) or `+` (heterogeneous pack jobs), returning `(base_id, step_name, parent_job_id)`.
- **Schema Casting (`normalize_to_canonical`)**: Selects and casts DataFrame columns strictly to `POLARS_CANONICAL_SCHEMA`, injecting `source = source_type` or typed null columns as needed.
