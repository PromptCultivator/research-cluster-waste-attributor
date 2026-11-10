# Research Cluster Waste Attribution Report

## Summary
- Total Jobs: 21
- Evaluated Jobs: 21
- Excluded Jobs (RUNNING/PENDING): 0
- Total Reserved Core-Hours: 153.78
- Total Used Core-Hours: 84.50
- Total Reserved GB-Hours: 609.47
- Total Used GB-Hours: 204.44

## Waste Classification
| Waste Class | Core-Hours | Share % | GB-Hours | Share % |
|---|---|---|---|---|
| Class 1: Memory Over-Request | - | - | 189.12 | 31.03% |
| Class 2: Idle Reserved CPU | 9.33 | 6.07% | - | - |
| Class 3: Failed & Retried Work | 43.95 | 28.58% | 153.42 | 25.17% |
| Class 4: Redundant Recomputation | 16.00 | 10.40% | 62.50 | 10.25% |
| Used | 84.50 | 54.95% | 204.44 | 33.54% |
| Unattributed Missing | 0.00 | 0.00% | 0.00 | 0.00% |

## Ranked Reclaim List
| Rank | Group | Count | Reclaim Core-Hours | Reclaim GB-Hours | Score | Recommendation | Evidence Job IDs |
|---|---|---|---|---|---|---|---|
| 1 | alice/alpha_train | 3 | 17.33 | 80.08 | 37.35 | None (< min_samples) | 10007, 10018, 10001 |
| 2 | carol/sim_portfolio | 2 | 2.00 | 54.20 | 15.55 | None (< min_samples) | 10004, 10013 |
| 3 | david/tick_cleanup | 1 | 1.00 | 23.44 | 6.86 | None (< min_samples) | 10012 |
| 4 | alice/feature_matrix | 1 | 1.00 | 19.53 | 5.88 | None (< min_samples) | 10010 |
| 5 | frank/mc_risk | 3 | 1.42 | 16.50 | 5.54 | None (< min_samples) | 10016, 10015, 10017 |
| 6 | eve/nn_forward | 2 | 0.83 | 13.70 | 4.26 | None (< min_samples) | 10008, 10014 |
| 7 | bob/feed_handler | 2 | 0.50 | 5.76 | 1.94 | None (< min_samples) | 10002, 10003 |
| 8 | david/order_book_proc | 3 | 0.92 | 0.00 | 0.92 | req_mem_mb=69000M (OOM escalation) | 10006, 10020, 10005 |
| 9 | carol/param_search | 2 | 0.33 | 2.27 | 0.90 | None (< min_samples) | 10009_1, 10009_0 |
| 10 | bob/latency_test | 1 | 0.00 | 0.00 | 0.00 | None (< min_samples) | 10011 |
| 11 | grace/quick_check | 1 | 0.00 | 0.00 | 0.00 | None (< min_samples) | 10019 |

## Data Quality Accounting
- Active Jobs Excluded: 0
- Unattributed CPU Share: 0.00%
- Unattributed Memory Share: 0.00%
- Declared Input Coverage: 14.29%

## Early Failure Groups
| Group | Failures | Total | Share % | Sample Exit Codes |
|---|---|---|---|---|
| grace | 1 | 1 | 100.00% | 2 |

## Result Cache Recommendations
| Group | Completed Jobs | Cache Hits | Hit Rate % | Reclaim Core-Hours | Reclaim GB-Hours |
|---|---|---|---|---|---|
| alice/4a34f906fe0e000da15f64009537e740a0fc77b64f42d28860ca0edfa361d5aa | 3 | 2 | 66.7% | 16.00 | 62.50 |
| alice/4c49fa6bfb3e62ee2533b898ed50e4e3e4b5ad0f5ae923e5c7e581cb3b60d270 | 1 | 0 | 0.0% | 0.00 | 0.00 |
| bob/0938e1c2f07f3d47a045a390a97a440181274b4f849727913b69025c3358e962 | 1 | 0 | 0.0% | 0.00 | 0.00 |
| carol/0c6813b72e4a6d1a290d281bab328506b7390550bc6de3705c693fc43b6641b6 | 2 | 0 | 0.0% | 0.00 | 0.00 |
| carol/f80fcf512377e21d489752a1ae6c84264cb4cf14fdedb03c7772dd26587d3fff | 1 | 0 | 0.0% | 0.00 | 0.00 |
| david/5aa348c15cdc56fda5ec87774168c3790e43101d5a24cfae9fabd6d9f7e8a074 | 2 | 0 | 0.0% | 0.00 | 0.00 |
| david/a8d6985c7c17f09d012a12c2a9fc7fb518463511f72d7403d1c25b3e69e26d0d | 1 | 0 | 0.0% | 0.00 | 0.00 |
| eve/25a676e318101f6708d6861837fc5994156df5e5be8023061d936915118288b8 | 2 | 0 | 0.0% | 0.00 | 0.00 |
| frank/c34c76104f02abf8df3529919f823c4212e3d767b72320aaa60bf127af5cbfe7 | 2 | 0 | 0.0% | 0.00 | 0.00 |

## Simulation Scenarios
| Scenario | Median Wait (s) | P95 Wait (s) | Makespan (s) | Core Utilization % | Memory Utilization % | Jobs/Day |
|---|---|---|---|---|---|---|
| baseline | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.45 |
| mem_rightsized | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.45 |
| cpu_rightsized_none | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.45 |
| cpu_rightsized_proportional | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.45 |
| cache_dedup | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.12 |
| all | 0.0 | 0.0 | 525600 | 0.2% | 0.2% | 3.12 |

## Calibration Metrics
- Historical Baseline Calibration Error:
  - Median Absolute Error: 10.00 s
  - Spearman Rank Correlation: 0.000
