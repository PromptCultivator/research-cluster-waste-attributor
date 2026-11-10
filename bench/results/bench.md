# Research Cluster Waste Attributor — Benchmark Results

## Hardware and Environment
```
CPU Model: Intel(R) Xeon(R) Platinum 8481C
Physical Cores: 2
RAM: 7.76 GB
Operating System: Linux 6.12.105+
Python Version: 3.11.2 (polars=1.14.0, pyarrow=18.1.0, numpy=2.1.3, pydantic=2.10.3)
Commit Hash: 7b4c0d8cbccd1bc46f4889fc081793442a21fb6f
```

## Summary Metrics
- Trace Scale: 20k jobs (20000.0 records)
- Benchmark Runs: 1
- Guarantee G1 Conservation: EXACT
- Guarantee G2 Guardrail Violations: 0.0
- Attribution Coverage: 96.23%
- Reclaimable Core-Hours Share: 72.95%
- Reclaimable GB-Hours Share: 76.12%
- SACCT Ingestion Throughput: 34610.4 jobs/s
- SWF Ingestion Throughput: 90618.1 jobs/s
- Simulation Baseline Throughput: 90486.8 jobs/s
- Peak Resident Memory: 310.77 MB

## Recall and Precision against Planted Ground Truth
| Waste Class | Recall | Precision |
|---|---|---|
| Class 1: Memory Over-Request | 1.0000 | 0.4800 |
| Class 2: Idle Reserved CPU | 1.0000 | 0.4000 |
| Class 3: Failed & Retried Work | 1.0000 | 1.0000 |
| Class 4: Redundant Recomputation | 0.8000 | 0.2300 |

## Simulation and Calibration
- Median Wait Change (Scenario 'all' vs Baseline): 61851.0 s
- P95 Wait Change (Scenario 'all' vs Baseline): 103929.4 s
- Historical Trace Calibration Error (MAE): 12.0 s
- Historical Trace Rank Correlation (Spearman rho): 0.0
