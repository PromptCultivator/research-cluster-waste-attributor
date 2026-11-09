# ADR 003: Percentile Rightsizing with Safety Guardrails

## Status
Accepted

## Context
Recommending lower CPU or memory reservations can recover cluster capacity, but aggressive reductions risk causing out-of-memory (OOM) failures or performance degradation. Engineers need high confidence that recommended limits will not interrupt active workflows.

## Options
1. **Conservative Percentile Rightsizing with Hard Guardrails**: Use the 99th percentile of observed peak RSS multiplied by a 1.2 safety factor, with hard floors at the historical maximum observed RSS, mandatory upward adjustments for groups with OOM failures, and exclusion of small groups below a minimum sample size.
2. **Aggressive Median Rightsizing**: Recommend 50th or 75th percentile limits to maximize recovered capacity, accepting a risk of occasional retries.
3. **Machine Learning Predictors**: Train regression models to dynamically estimate per-job resource envelopes.

## Decision
Adopt Option 1: Conservative Percentile Rightsizing with Hard Guardrails. Recommended requests are bounded:
- Memory: `req_mem_mb = ceil(p99(max_rss_mb) * 1.2)`, floored at `max(max_rss_mb)` across all completed executions.
- OOM Protection: Any group encountering an OOM failure receives an upward recommendation of `ceil(max_observed * 1.5)` and is excluded from reclaimable memory totals.
- Small Sample Guardrail: Groups with fewer than `min_samples` (default 5) receive no reduction recommendation.

## Measured or Expected Cost
Significant headroom remains unharvested compared to median consumption. This safety margin is explicitly quantified and reported as the difference between 99th and 50th percentile sizing.
