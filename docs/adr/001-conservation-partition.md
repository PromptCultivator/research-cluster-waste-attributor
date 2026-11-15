# ADR 001: Precedence-Based Conservation Partitioning

## Status
Accepted

## Context
Resource reservations in batch-scheduled research computing clusters diverge from observed consumption. To attribute this gap credibly to cluster operators and researchers, every reserved CPU core-second and memory megabyte-second must be accounted for with zero double counting or rounding drift. Individual jobs routinely exhibit overlapping inefficiencies, such as failing after several hours of low CPU utilization or re-executing duplicate runs with oversized memory requests.

## Options
1. **Strict Single-Pass Precedence Partitioning**: Evaluate each job through a mutually exclusive deterministic order: Class 3 (failed/retried work) $\to$ Class 4 (redundant recomputation) $\to$ Class 2 (idle reserved CPU) and Class 1 (memory over-request) $\to$ Utilized / Unattributed.
2. **Proportional Multi-Label Partitioning**: Split reserved core-seconds proportionally across all co-occurring waste conditions on the same job.
3. **Independent Waste Counters**: Measure idle CPU, memory over-request, failed runtime, and duplicates independently without enforcing an exact additive partition.

## Decision
Adopt Option 1: Strict Single-Pass Precedence Partitioning (implemented in [`rcwa/attribute.py`](../../rcwa/attribute.py)). Active states (`RUNNING`, `PENDING`) are excluded into data quality totals, while terminated zero-duration runs (`run_s == 0`) remain as Class 3 `early_failure`. For every evaluated job and dimension, Guarantee G1 enforces exact integer equality:

$$\text{reserved} = \text{used} + \text{waste} + \text{unattributed}$$

Failed runs allocate 100% of reserved cores and memory to Class 3 and receive one of six sub-labels (`early_failure`, `oom`, `timeout`, `node_fail`, `cancelled_after_start`, `other_failure`). Completed runs matching earlier `(command_hash, input_hash)` executions within the recompute window allocate 100% of reservations to Class 4. Remaining completed runs partition independently into `used_core_s` / `class2_idle_core_s` / `unattributed_core_s` and `used_mem_mb_s` / `class1_over_mem_mb_s` / `unattributed_mem_mb_s`.

## Measured or Expected Cost
Secondary inefficiencies inside failed or duplicate jobs (for example, low CPU efficiency during a job that later timed out) are subordinated to the higher-precedence class. Granular failure diagnosis is retained via the six `class3_sub_label` categories and retry chain cost aggregation rather than primary waste columns.
