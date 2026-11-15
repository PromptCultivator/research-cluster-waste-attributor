# ADR 003: Percentile Rightsizing with Safety Guardrails

## Status
Accepted

## Context
Lowering overly generous CPU core or memory reservations reclaims idle capacity, but aggressive reductions risk triggering out-of-memory kills (`OUT_OF_MEMORY`) or severe slowdown. Recommendations require hard statistical safety bounds before operators adjust production batch limits.

## Options
1. **Conservative Percentile Rightsizing with Hard Guardrails**: Target P99 observed consumption scaled by safety multipliers, floored at all-state historical peaks, guarded by OOM escalations, minimum sample counts, and short-job CPU suppression.
2. **Median / Interquartile Rightsizing**: Target P50 or P75 usage to maximize reclaimed capacity while tolerating occasional failures.
3. **Predictive ML Estimators**: Fit per-cluster regression predictors over historical job metadata.

## Decision
Adopt Option 1: Conservative Percentile Rightsizing with Hard Guardrails (implemented in [`rcwa/recommend.py`](../../rcwa/recommend.py)). Enforcement follows a strict safety order satisfying Guarantee G2:
- **OOM Escalation Priority**: Any cohort containing an `OUT_OF_MEMORY` termination (or `class3_sub_label == "oom"`) overrides `min_samples`, sets `recommended_req_mem_mb = max(ceil(oom_base * oom_multiplier), observed_max_rss)` (default `1.5`), forces `recommendation_direction = "increase"`, and zeros `reclaimable_gb_hours`.
- **Small Sample Floor**: Non-OOM cohorts with fewer than `min_samples` (default `5`) jobs emit `None` across all recommendations with `recommendation_action = "below_sample_floor"`.
- **Non-OOM Memory Floor**: `recommended_req_mem_mb = max(ceil(P99(max_rss_mb | COMPLETED) * safety_factor), observed_max_rss)` (default `1.2`), where `observed_max_rss` spans **all** jobs in the cohort regardless of terminal state (falling back to all-state RSS when completed jobs lack RSS).
- **CPU Bounds & Short-Job Suppression**: `recommended_cpus = clamp(ceil(P99(cpu_time_used_s / run_s | COMPLETED) * 1.2), 1, observed_max_cpus)`, suppressed to `None` when cohort median duration or all job durations fall under `min_run_s` (default `120` s).
- **Timeout Escalation**: Cohorts with `TIMEOUT` events compute `recommended_time_limit_s = ceil(P99(run_s | COMPLETED) * 1.5)`.

## Measured or Expected Cost
Conservative P99 sizing and the `1.2x` headroom buffer leave recoverable tail capacity unharvested relative to median consumption. Hypothesis property tests verify zero guardrail violations across `10,000` randomized cohorts in [`tests/property/test_safety_guardrails.py`](../../tests/property/test_safety_guardrails.py).
