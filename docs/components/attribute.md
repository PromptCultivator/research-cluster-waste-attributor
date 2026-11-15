# Waste Attribution Engine

## 1. Overview

[`rcwa/attribute.py`](../../rcwa/attribute.py) implements `attribute_trace(canonical_df, policy=None)` and `export_attributed_records(df, path, format="parquet")`. It partitions every reserved CPU core-second and memory megabyte-second into utilized capacity, four mutually exclusive waste classes, or explicitly accounted unattributed buckets, enforcing **Guarantee G1 (Conservation)**.

---

## 2. Pre-Attribution Filtering and Policy Parameters

1. **Active Job Filtering**: Rows with `state` in `{"RUNNING", "PENDING"}` are excluded prior to attribution (and summarized under report Data Quality exclusion counts).
2. **Memory Null Normalization**: `reserved_mem_mb_s` nulls (arising from `req_mem_mb = None`) are filled with `0` (`DEC-008`) so integer arithmetic satisfies `0 == 0 + 0 + 0 + 0 + 0`.
3. **Policy Settings**: Reads `attribution` parameters from `policy` (dict, YAML path, or `policies/default.yaml`):
   - `retry_window_s` (default `86400`)
   - `recompute_window_s` (default `2592000`)
   - `early_failure_threshold_s` (default `60`)
4. **Pre-Pass Chains & Recomputation**: Executes `detect_retry_chains(df, retry_window_s)` followed by `detect_recomputations(df_with_retries, recompute_window_s)`.

---

## 3. Single-Pass Precedence Cascade

To eliminate double counting when multiple waste factors co-occur, each job evaluates through three strict tiers:

```text
[ Terminated Canonical Record (RUNNING/PENDING excluded, reserved_mem_mb_s null -> 0) ]
       │
       ▼
[ state in {FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, PREEMPTED} OR (state == CANCELLED and run_s > 0) OR (run_s == 0)? ]
       ├── YES ──► Class 3 (Failed & Retried Work)
       │           class3_core_s = reserved_core_s; class3_mem_mb_s = reserved_mem_mb_s
       │           All other partition columns = 0.
       │           Assign class3_sub_label in order:
       │             1. run_s <= early_failure_threshold_s -> "early_failure"
       │             2. state == "OUT_OF_MEMORY"           -> "oom"
       │             3. state == "TIMEOUT"                 -> "timeout"
       │             4. state == "NODE_FAIL"               -> "node_fail"
       │             5. state == "CANCELLED"               -> "cancelled_after_start"
       │             6. otherwise                          -> "other_failure"
       │
       └── NO ──► [ is_recompute == True? (non-SWF COMPLETED match on command_hash + input_hash) ]
                   ├── YES ──► Class 4 (Redundant Recomputation)
                   │           class4_core_s = reserved_core_s; class4_mem_mb_s = reserved_mem_mb_s
                   │           All other partition columns = 0.
                   │
                   └── NO ──► [ Independent Resource Dimension Partitioning ]
                               ├─ Core Dimension:
                               │    If cpu_time_used_s is null:
                               │        unattributed_core_s = reserved_core_s
                               │    Else:
                               │        rounded_cpu = max(0, int(round(cpu_time_used_s)))
                               │        class2_idle_core_s = max(0, reserved_core_s - rounded_cpu)
                               │        used_core_s = reserved_core_s - class2_idle_core_s
                               │
                               └─ Memory Dimension:
                                    If req_mem_mb is null or reserved_mem_mb_s == 0:
                                        used_mem_mb_s = class1_over_mem_mb_s = unattributed_mem_mb_s = 0
                                    Elif max_rss_mb is null:
                                        unattributed_mem_mb_s = reserved_mem_mb_s
                                    Else:
                                        over_rate = max(0, req_mem_mb - max_rss_mb)
                                        class1_over_mem_mb_s = min(reserved_mem_mb_s, over_rate * run_s)
                                        used_mem_mb_s = reserved_mem_mb_s - class1_over_mem_mb_s
```

Notice that `possible_recompute` (`command_only` matches without verified `input_hash`) and `recompute_confidence` propagate as audit metadata on every row without allocating resources to Class 4.

---

## 4. Guarantee G1 and Emitted Columns

For every attributed row $i$, exact integer conservation holds:

$$\text{reserved\_core\_s}_i \equiv \text{used\_core\_s}_i + \text{class2\_idle\_core\_s}_i + \text{class3\_core\_s}_i + \text{class4\_core\_s}_i + \text{unattributed\_core\_s}_i$$

$$\text{reserved\_mem\_mb\_s}_i \equiv \text{used\_mem\_mb\_s}_i + \text{class1\_over\_mem\_mb\_s}_i + \text{class3\_mem\_mb\_s}_i + \text{class4\_mem\_mb\_s}_i + \text{unattributed\_mem\_mb\_s}_i$$

In addition to the canonical columns and `retry_*` columns from `detect_retry_chains`, `attribute_trace` attaches:
- Core partition (`Int64`): `used_core_s`, `class2_idle_core_s` (and alias `idle_core_s`), `class3_core_s`, `class4_core_s`, `unattributed_core_s` (and alias `unattributed_cpu_s`).
- Memory partition (`Int64`): `used_mem_mb_s`, `class1_over_mem_mb_s` (and alias `over_mem_mb_s`), `class3_mem_mb_s`, `class4_mem_mb_s`, `unattributed_mem_mb_s`.
- Classification metadata: `class3_sub_label` (`String`), `possible_recompute` (`Boolean`), `recompute_confidence` (`String`).

`export_attributed_records(df, path, format="parquet")` writes attributed tables to Parquet or CSV (selected by `format` or `.csv` file extension).
