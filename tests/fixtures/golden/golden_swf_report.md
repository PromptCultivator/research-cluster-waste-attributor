# Research Cluster Waste Attribution Report

## Summary
- Total Jobs: 10
- Evaluated Jobs: 10
- Excluded Jobs (RUNNING/PENDING): 0
- Total Reserved Core-Hours: 3.78
- Total Used Core-Hours: 3.09
- Total Reserved GB-Hours: 10.49
- Total Used GB-Hours: 5.24

## Waste Classification
| Waste Class | Core-Hours | Share % | GB-Hours | Share % |
|---|---|---|---|---|
| Class 1: Memory Over-Request | - | - | 5.24 | 49.95% |
| Class 2: Idle Reserved CPU | 0.68 | 17.99% | - | - |
| Class 3: Failed & Retried Work | 0.00 | 0.00% | 0.00 | 0.00% |
| Class 4: Redundant Recomputation | not available | - | not available | - |
| Used | 3.09 | 81.75% | 5.24 | 49.95% |
| Unattributed Missing | 0.00 | 0.00% | 0.00 | 0.00% |

## Ranked Reclaim List
| Rank | Group | Count | Reclaim Core-Hours | Reclaim GB-Hours | Score | Recommendation | Evidence Job IDs |
|---|---|---|---|---|---|---|---|
| 1 | 1/1 | 3 | 0.28 | 2.81 | 0.98 | None (< min_samples) | 7, 3, 1 |
| 2 | 3/3 | 2 | 0.13 | 1.11 | 0.41 | None (< min_samples) | 4, 8 |
| 3 | 2/2 | 3 | 0.17 | 0.74 | 0.35 | None (< min_samples) | 2, 5, 9 |
| 4 | 4/4 | 2 | 0.11 | 0.58 | 0.25 | None (< min_samples) | 10, 6 |

## Data Quality Accounting
- Active Jobs Excluded: 0
- Unattributed CPU Share: 0.00%
- Unattributed Memory Share: 0.00%
- Declared Input Coverage: 0.00%

## Simulation Scenarios
| Scenario | Median Wait (s) | P95 Wait (s) | Makespan (s) | Core Utilization % | Memory Utilization % | Jobs/Day |
|---|---|---|---|---|---|---|
| baseline | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |
| mem_rightsized | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |
| cpu_rightsized_none | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |
| cpu_rightsized_proportional | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |
| cache_dedup | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |
| all | 0.0 | 0.0 | 440 | 6.0% | 4.2% | 1963.64 |

## Calibration Metrics
- Historical Baseline Calibration Error:
  - Median Absolute Error: 10.00 s
  - Spearman Rank Correlation: 0.000
