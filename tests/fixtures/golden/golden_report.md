# Research Cluster Waste Attribution Report

## Summary
- Total Jobs: 20
- Evaluated Jobs: 18
- Excluded Jobs (RUNNING/PENDING): 2
- Total Reserved Core-Hours: 120.00
- Total Used Core-Hours: 68.50
- Total Reserved GB-Hours: 480.00
- Total Used GB-Hours: 215.20

## Waste Classification
| Waste Class | Core-Hours | Share % | GB-Hours | Share % |
|---|---|---|---|---|
| Class 1: Memory Over-Request | - | - | 194.80 | 40.58% |
| Class 2: Idle Reserved CPU | 32.50 | 27.08% | - | - |
| Class 3: Failed & Retried Work | 15.00 | 12.50% | 60.00 | 12.50% |
| Class 4: Redundant Recomputation | 4.00 | 3.33% | 10.00 | 2.08% |
| Used | 68.50 | 57.08% | 215.20 | 44.83% |
| Unattributed Missing | 0.00 | 0.00% | 0.00 | 0.00% |

## Ranked Reclaim List
| Rank | Group | Count | Reclaim Core-Hours | Reclaim GB-Hours | Score | Recommendation | Evidence Job IDs |
|---|---|---|---|---|---|---|---|
| 1 | alice/alpha_train | 3 | 12.00 | 54.00 | 25.50 | req_mem_mb=17040M, cpus=7 | 10001, 10007, 10018 |
| 2 | david/order_book_proc | 3 | 4.00 | 0.00 | 4.00 | req_mem_mb=69000M (OOM escalation) | 10005, 10006, 10020 |
| 3 | carol/sim_portfolio | 2 | 8.00 | 24.00 | 14.00 | None (< min_samples) | 10004, 10013 |

## Data Quality Accounting
- Active Jobs Excluded: 2
- Unattributed CPU Share: 0.00%
- Unattributed Memory Share: 0.00%
- Declared Input Coverage: 65.00%

## Simulation Scenarios
| Scenario | Median Wait (s) | P95 Wait (s) | Makespan (s) | Core Utilization % | Memory Utilization % | Jobs/Day |
|---|---|---|---|---|---|---|
| baseline | 12.0 | 45.0 | 518400 | 62.4% | 54.1% | 2.57 |
| mem_rightsized | 8.0 | 32.0 | 482000 | 67.1% | 76.5% | 2.76 |
| cpu_rightsized_none | 7.0 | 28.0 | 460000 | 78.3% | 75.8% | 2.89 |
| cpu_rightsized_proportional | 9.0 | 35.0 | 490000 | 73.5% | 72.0% | 2.72 |
| cache_dedup | 10.0 | 38.0 | 495000 | 65.0% | 56.0% | 2.69 |
| all | 5.0 | 20.0 | 410000 | 82.5% | 85.0% | 3.24 |

## Calibration Metrics
- Historical Baseline Calibration Error:
  - Median Absolute Error: 4.50 s
  - Spearman Rank Correlation: 0.892
