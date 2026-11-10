# Scope: Milestone M3 (Phase 3 — Recommendations)

## Objective
Implement `rcwa/recommend.py` with safety guardrails (Guarantee G2), Hypothesis property tests evaluating 10,000 generated groups in `tests/property/test_safety_guardrails.py`, connect recommendation commands to `rcwa/cli.py`, and pass all quality gates per `docs/SPEC.md §7, §14`.

## Files Owned
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/recommend.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/cli.py` (recommend command wiring)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/property/test_safety_guardrails.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_recommend.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/AI-ASSISTANCE.md` (append entries)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/DECISIONS.md` (append entries if any decisions made)

## Requirements & Specifications

### 1. Recommendation Engine (`rcwa/recommend.py`)
Per SPEC §7 and §14:
- **Memory Rightsizing**:
  - `req_mem_mb = ceil(p99(max_rss_mb over the group's COMPLETED jobs) * safety_factor)` with `safety_factor` default 1.2 (from `PolicyConfig`).
  - **Floor**: Never below `max(max_rss_mb)` observed in the group across all states.
  - **OOM Escalation**: If any job in the group has `state = OUT_OF_MEMORY` in the window, recommendation direction is `increase` to `ceil(max_observed * 1.5)` (where max observed is the maximum observed memory or request across the group), and the group is excluded from reclaimable memory totals.
- **CPU Rightsizing**:
  - `cpus = clamp(ceil(p99(cpu_time_used_s / run_s) * safety_factor), 1, alloc_cpus)` where `safety_factor` default is 1.2.
  - **Short jobs exclusion**: Groups whose jobs have `run_s < 120` get no CPU recommendation (utilization is unreliable on short jobs).
- **Timeouts**:
  - Recommend `time_limit = ceil(p99(run_s of COMPLETED jobs) * 1.5)` for groups with timeouts.
- **Early Failures**:
  - No resource recommendation; report lists the group with its failure share and sample exit codes.
- **Recomputation**:
  - Recommend result cache keyed by `(command_hash, input_hash)` for groups where class 4 exceeds threshold; report hit rate the cache would have had.
- **Minimum Samples Floor**:
  - Groups below `min_samples` (default 5 from `PolicyConfig`) receive no recommendation.
- Output representation:
  - DataFrame / structured records with per-group recommendation details (action, direction, recommended cpus/mem/time_limit, floor applied, OOM escalation applied, cache recommendation, confidence, reason).

### 2. Guarantee G2 Property Tests (`tests/property/test_safety_guardrails.py`)
Per SPEC §3, §7, §14:
- Hypothesis property-based testing evaluating at least 10,000 generated groups.
- Assertions:
  - Zero guardrail violations across all 10,000 groups.
  - Memory recommendation is never below observed maximum RSS across all states.
  - OOM groups never receive a memory decrease recommendation.
  - Groups with fewer than `min_samples` receive no recommendation.

### 3. CLI Integration (`rcwa/cli.py`)
- Wire up `rcwa recommend` subcommand accepting input traces, policies, and writing recommendations to Parquet and CSV.

### 4. Acceptance Criteria
1. Hypothesis finds zero guardrail violations in 10,000 generated groups.
2. `make lint` (`ruff check .`, `ruff format --check .`) passes with exit status 0.
3. `make typecheck` (`pyright`) passes with 0 errors, 0 warnings.
4. `make test` passes with overall coverage >= 85%.
5. Zero prohibited words ("simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge").
6. Changes committed with an imperative commit message (e.g. `Implement Phase 3 recommendations and safety guardrails`).
7. Phase 3 report formatted strictly per Section 15 of `docs/SPEC.md`.
