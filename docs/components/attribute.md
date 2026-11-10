# Waste Attribution Engine

## 1. Overview

The attribution engine (`rcwa/attribute.py`) partitions every reserved core-second and megabyte-second into four non-overlapping waste classes, utilized capacity, or unattributed metrics. The engine strictly enforces **Guarantee G1 (Conservation)**, ensuring no capacity is double-counted or lost in rounding.

---

## 2. Waste Classification Taxonomy

1. **Class 1: Memory Over-Request**
   Memory allocated above the job's peak resident set size ($MaxRSS$).
   $$\text{over\_mem\_mb\_s} = \max(0, \text{req\_mem\_mb} - \text{max\_rss\_mb}) \times \text{run\_s}$$

2. **Class 2: Idle Reserved CPU**
   Core allocation unused during execution.
   $$\text{idle\_core\_s} = \max(0, \text{reserved\_core\_s} - \text{cpu\_time\_used\_s})$$

3. **Class 3: Failed and Retried Work**
   Entire reservation of jobs terminated abnormally (`FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `PREEMPTED`, or `CANCELLED` after starting). Sub-labels include:
   - `oom`: Out-of-memory termination.
   - `timeout`: Exceeded wallclock time limit.
   - `early_failure`: Failed within 60 seconds ($\text{run\_s} \le 60$).
   - `cancelled_after_start`: User cancelled after compute began ($\text{run\_s} > 0$).
   - `node_fail`: Machine failure.
   - `other_failure`: Generic application abort.

4. **Class 4: Redundant Recomputation**
   Entire reservation of successful jobs that executed the same command on identical inputs as an earlier successful run within `recompute_window` (default 30 days).

---

## 3. Precedence Cascade Hierarchy

To prevent double-counting across overlapping causes (e.g. an idle CPU in a job that ultimately timed out), attribution executes via a single-pass precedence hierarchy:

```
[ Job Record ]
       │
       ▼
[ Is State in FAILED, TIMEOUT, OOM, NODE_FAIL, PREEMPTED, or CANCELLED (run_s > 0)? ]
       ├── YES ──► Class 3 (Failed Work)
       │           Entire reservation assigned to Class 3.
       │           Sub-label assigned. Evaluation finishes.
       │
       └── NO (COMPLETED)
            │
            ▼
       [ Does (command_hash, input_hash) match an earlier COMPLETED job within window? ]
            ├── YES ──► Class 4 (Redundant Recomputation)
            │           Entire reservation assigned to Class 4. Evaluation finishes.
            │
            └── NO (Unique Successful Job)
                 │
                 ▼
            [ Dimension-Specific Partitioning ]
                 ├─ Core Dimension:
                 │    If cpu_time_used_s is null:
                 │        core_unattributed = reserved_core_s
                 │    Else:
                 │        idle_core_s = max(0, reserved_core_s - cpu_time_used_s)
                 │        used_core_s = reserved_core_s - idle_core_s
                 │        idle_core_s assigned to Class 2.
                 │
                 └─ Memory Dimension:
                      If max_rss_mb is null:
                          mem_unattributed = reserved_mem_mb_s
                      Else:
                          over_mem_mb_s = max(0, req_mem_mb - max_rss_mb) * run_s
                          used_mem_mb_s = reserved_mem_mb_s - over_mem_mb_s
                          over_mem_mb_s assigned to Class 1.
```

---

## 4. Guarantee G1: Conservation Identity

For every job record $i$, conservation holds across both resource dimensions without integer deviation:

### Core Dimension:
$$\text{reserved\_core\_s}_i \equiv \text{used\_core\_s}_i + \text{class2\_core\_s}_i + \text{class3\_core\_s}_i + \text{class4\_core\_s}_i + \text{unattributed\_core\_s}_i$$

### Memory Dimension:
$$\text{reserved\_mem\_mb\_s}_i \equiv \text{used\_mem\_mb\_s}_i + \text{class1\_mem\_mb\_s}_i + \text{class3\_mem\_mb\_s}_i + \text{class4\_mem\_mb\_s}_i + \text{unattributed\_mem\_mb\_s}_i$$

Cluster-wide totals reported in summary tables are exact column sums of these per-job values. Automated regression tests recompute table sums from individual records to guarantee zero discrepancies.
