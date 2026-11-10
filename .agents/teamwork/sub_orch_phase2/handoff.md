# Phase 2 Report: Waste Attribution, Retry Chains, and Job Grouping

## 1. Phase Number and Summary
Phase 2 — Attribution: Single-pass precedence partitioning across four non-overlapping waste classes with exact integer Guarantee G1 conservation, temporal 1-to-1 failure retry chain detection, hierarchical job grouping with reclaimable scoring and evidence sampling, and Parquet/CSV exports now work.

## 2. Commands Run with Exit Status
- `make lint` (`ruff check .`, `ruff format --check .`): exit status 0 (passed across all 25 files).
- `make typecheck` (`pyright`): exit status 0 (0 errors, 0 warnings).
- `make test` (`pytest`): exit status 0 (310 passed, 90.89% line and branch coverage, exceeding >= 85% requirement).
- `python3 tests/unit/test_forbidden_words.py`: exit status 0 (0 prohibited words detected).
- `make bench-smoke`: exit status 0 (`rcwa version`, `rcwa-wrap --version`, `rcwa synth --size 20k --seed 1 --runs 1` succeeded).
- `make all`: exit status 0.

## 3. Measured Numbers Produced in This Phase
- 310 passed tests across 13 test suites (`pytest`).
- 90.89% statement and branch coverage across all package modules (`pytest --cov=rcwa`).
- 0 integer discrepancy in Guarantee G1 conservation across all 8 standard sacct/SWF fixtures (`pytest tests/unit/test_conservation.py -k test_guarantee_g1_on_fixtures`).
- 0 integer discrepancy in Guarantee G1 conservation across a 20,000-job synthetic trace with 16,000 active jobs across all 10 canonical states (`pytest tests/unit/test_conservation.py -k test_guarantee_g1_on_20k_synthetic_trace`).
- 64 passed tests in tier 1 attribution feature coverage (`pytest tests/e2e/tier1_feature_coverage/test_f15_f21_attribution_g1.py`).
- 16 passed adversarial edge-case stress tests (`pytest tests/unit/test_adversarial_attribution_challenger.py`).
- 0 occurrences of prohibited terms (`python3 tests/unit/test_forbidden_words.py`).

## 4. Decisions Made
- `DEC-007: Conservation Precedence Hierarchy Implementation`: Single-pass precedence hierarchy assigns the full reservation of failed jobs to Class 3 regardless of hash matches, eliminating double-counting and preserving Guarantee G1.
- `DEC-008: Non-Null Memory Reservation Normalization for Conservation Arithmetic`: Normalizes null memory requests to 0 megabyte-seconds in attribution arithmetic to preserve exact integer conservation identity without type errors.
- `DEC-009: 1-to-1 Temporal Earliest Candidate Claiming for Retry Chains`: Links failed jobs to subsequent resubmissions by assigning each failure to the earliest candidate resubmission (ordered by submit time ascending) to guarantee causal, deterministic multi-hop chains with cumulative chain cost accounting.

## 5. Open Questions for the Human
1. **Integer SWF Group Identifiers**: In SWF workloads, should secondary rollups format numerical user, group, and queue identifiers directly as stringified integers without prefixing?  
   *Default taken if unanswered*: Stringifies numerical IDs directly (e.g. user `"101"`, partition `"1"`).
2. **Clock Jitter Utilization Clamping**: For jobs whose measured `cpu_time_used_s` exceeds allocated CPU reservation due to accounting rounding, should used core-seconds clamp at allocated reservation?  
   *Default taken if unanswered*: Clamps used core-seconds at reserved core-seconds and sets idle core-seconds to zero, preserving exact integer conservation.

## 6. The Next Phase's First Three Steps (Phase 3 — Recommendations)
1. Implement `rcwa/recommend.py` to calculate right-sized requests for memory (p99 observed peak RSS of completed jobs multiplied by 1.2 safety factor, floor-bounded by observed max RSS across all states), CPU (p99 utilization clamped between 1 and allocated CPUs, excluding jobs with runtime < 120s), and timeouts (p99 runtime * 1.5).
2. Implement recommendation safety guardrails: OOM groups force increase recommendations (`ceil(max_observed * 1.5)`) and exclusion from reclaimable memory totals; groups with fewer than `min_samples` receive no recommendation.
3. Implement Hypothesis property-based testing in `tests/property/test_recommendations.py` to evaluate Guarantee G2 across 10,000 generated groups asserting zero guardrail violations.
