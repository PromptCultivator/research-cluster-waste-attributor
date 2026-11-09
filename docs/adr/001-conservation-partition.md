# ADR 001: Precedence-Based Conservation Partitioning

## Status
Accepted

## Context
Resource reservations in batch-scheduled research computing clusters diverge from actual job resource usage. To attribute this divergence credibly to operators and researchers, every reserved core-second and megabyte-second must be accounted for without gaps or double counting. Resource waste can arise from multiple concurrent mechanisms, such as an application that fails after running for hours with low CPU utilization. A partitioning strategy must assign each unit of reserved resource to exactly one category or to utilized resources.

## Options
1. **Strict Single-Pass Precedence Partitioning**: Apply a deterministic precedence order: Class 3 (failed/retried work) -> Class 4 (redundant recomputation) -> Class 2 (idle reserved CPU) and Class 1 (memory over-request) -> Used / Unattributed.
2. **Proportional Multi-Label Partitioning**: Divide wasted core-seconds proportionally across multiple co-occurring fault labels.
3. **Independent Waste Metrics**: Calculate idle CPU, memory over-request, failure losses, and recomputation independently without an exact sum constraint.

## Decision
Adopt Option 1: Strict Single-Pass Precedence Partitioning. Each second of reserved resource is evaluated once against the hierarchy, enforcing the conservation guarantee (G1):
`reserved = used + waste_class + unattributed` exactly.

## Measured or Expected Cost
Visibility into idle CPU inside failed jobs is subordinated; the entire reservation of a failed job is attributed to Class 3. Idle behavior within failed runs is tracked via sub-labels (e.g., early failure, timeout, OOM) rather than primary waste classes.
