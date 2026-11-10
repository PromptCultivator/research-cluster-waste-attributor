# Simulator Calibration Engine

## 1. Overview

The calibration engine (`rcwa/calibrate.py`) evaluates the alignment between the simulator's `baseline` scenario replay and the real queue wait times recorded in historical traces. Because counterfactual scenario projections depend directly on the fidelity of the simulation baseline, calibration error metrics define the empirical bounds on projected wait time improvements.

---

## 2. Calibration Metrics

The calibration engine calculates two statistical divergence metrics across all jobs:

### 2.1 Median Absolute Wait Error (MAE)

Measures the typical absolute difference between simulated wait times and observed wait times:
$$\text{MAE} = \operatorname{median}\left( \left| \text{wait\_s}_{\text{sim}, i} - \text{wait\_s}_{\text{real}, i} \right| \right)$$

This metric quantifies the absolute time bias introduced by unmodeled cluster dynamics (such as network topology, node maintenance, or fair-share priorities).

### 2.2 Spearman Rank Correlation ($\rho_s$)

Measures whether the relative ordering of queue dispatch in the simulation matches real historical priority ordering:
$$\rho_s = 1 - \frac{6 \sum d_i^2}{n(n^2 - 1)}$$
where $d_i = \operatorname{rank}(\text{wait\_s}_{\text{sim}, i}) - \operatorname{rank}(\text{wait\_s}_{\text{real}, i})$.

A high rank correlation ($\rho_s \to 1$) indicates that relative job queueing dynamics and contention bottlenecks are reproduced faithfully.

---

## 3. Reporting and Scenario Error Bounds

When scenario deltas are reported (e.g. median wait reduction of 42% under `all`), the report presents the baseline calibration MAE and Spearman correlation alongside the projected improvement:

```markdown
| Scenario | Median Wait (s) | P95 Wait (s) | Utilization (%) | Daily Throughput |
|---|---|---|---|---|
| Historical Baseline | 420 | 3,120 | 64.2% | 1,420 |
| Simulated Baseline  | 390 (MAE: 35s, rho: 0.88) | 2,980 | 65.1% | 1,435 |
| All Recommendations | 210 (-50.0%) | 1,450 (-53.5%) | 78.4% | 1,780 |
```

If the baseline calibration exhibits significant divergence (e.g. $\rho_s < 0.50$ due to heavy external scheduling constraints), operators are notified that scenario projections reflect idealized backfill potential rather than exact operational promises.
