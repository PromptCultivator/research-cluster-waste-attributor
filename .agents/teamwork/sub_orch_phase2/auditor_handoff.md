# Forensic Audit Report: Milestone M2 (Phase 2 — Attribution)

## Audit Summary
- **Target Milestone**: M2 (Phase 2 — Attribution)
- **Target Components**: `rcwa/attribute.py`, `rcwa/retries.py`, `rcwa/groups.py`, `tests/unit/test_conservation.py`, `tests/unit/test_adversarial_attribution_challenger.py`
- **Binary Verdict**: **PASS**

---

## 1. Prohibited Vocabulary Audit
- **Rule Reference**: SPEC.md §1 rule 2, §13 line 243.
- **Automated Scanner**:
  - Command: `python3 tests/unit/test_forbidden_words.py`
  - Output: Exit code 0 (1 passed)
- **Independent Regular Expression Audit**:
  - Target terms: Checked against the 9 prohibited words specified in SPEC.md §13 line 243.
  - Scope: All repository files across source, tests, documentation, policies, clusters, excluding external build artifacts and root specification documents (`SPEC.md`, `PROJECT.md`, `ORIGINAL_REQUEST.md`, `test_forbidden_words.py`).
  - Result: 0 occurrences detected across entire codebase.

---

## 2. Automated Repository Verification Checks
- **Linter Gate (`make lint`)**:
  - Command: `.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .`
  - Output: `All checks passed! 25 files already formatted`
  - Status: PASSED (0 errors, exit code 0).
- **Type Checker Gate (`make typecheck`)**:
  - Command: `.venv/bin/python -m pyright`
  - Output: `0 errors, 0 warnings, 0 informations`
  - Status: PASSED (exit code 0).
- **Test Suite & Coverage Gate (`make test`)**:
  - Command: `.venv/bin/python -m pytest`
  - Results: 310 passed, 0 failures, 6 warnings in 13.57s.
  - Test Coverage: 90.89% total statement coverage (exceeds >= 85% requirement).
  - Status: PASSED (exit code 0).
- **Guarantee G1 Conservation Suite**:
  - Command: `.venv/bin/python -m pytest tests/unit/test_conservation.py -v --no-cov`
  - Results: 15 passed in 1.15s.
  - Coverage:
    - 8 standard fixtures (`sacct_standard_26col.txt`, `multiday_cluster.txt`, `sacct_durations_states.txt`, `sacct_unattributed_missing.txt`, `standard_with_headers.swf`, `sample_workload.swf`, `status_variations.swf`, `missing_fields.swf`).
    - 20,000-row synthetic trace exercising all 10 states, durations, null metrics, multi-hop retries, and recomputation patterns.
    - Exact integer conservation verified row-by-row and trace-wide with 0 difference.
  - Status: PASSED (exit code 0).
- **Full Build Pipeline (`make all`)**:
  - Includes lint, typecheck, test, and bench-smoke (`rcwa version`, `rcwa-wrap --version`, `rcwa synth --size 20k --seed 1 --runs 1`).
  - Status: PASSED (exit code 0).

---

## 3. Code Integrity and Truthfulness Audit
- **Mock and Skip Verification**:
  - Grepped all unit tests for `@pytest.mark.skip`, `@pytest.mark.xfail`, `unittest.mock`, `pytest_mock`.
  - Found 0 mocked skips, 0 monkeypatches, and 0 bypassed assertions.
- **Attribution Logic Verification (`rcwa/attribute.py`)**:
  - Single-pass precedence hierarchy strictly enforced:
    1. Class 3 (Failed and retried work): states `FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `PREEMPTED`, `CANCELLED` (run_s > 0), or run_s == 0. Sub-labels correctly categorized (`early_failure`, `oom`, `timeout`, `node_fail`, `cancelled_after_start`, `other_failure`).
    2. Class 4 (Redundant recomputation): pairs matching earlier `(command_hash, input_hash)` within 30-day window (`recompute_window_s`). SWF traces marked `not_available`. Command-only matches set `possible_recompute=True` without consuming Class 4 totals.
    3. Class 2 (Idle reserved CPU) and Class 1 (Memory over-request) computed against observed metrics with null values directed to unattributed counters.
  - Exact integer conservation holds unconditionally:
    - `reserved_core_s == used_core_s + class2_idle_core_s + class3_core_s + class4_core_s + unattributed_core_s`
    - `reserved_mem_mb_s == used_mem_mb_s + class1_over_mem_mb_s + class3_mem_mb_s + class4_mem_mb_s + unattributed_mem_mb_s`
- **Retry Chain Verification (`rcwa/retries.py`)**:
  - Enforces temporal causality (resubmission submit_time >= failure effective end time).
  - 1-to-1 deterministic earliest candidate resubmission claiming.
  - Resolves multi-hop chains to root failure and aggregates cumulative chain costs.
- **Job Grouping and Reclaim Scoring (`rcwa/groups.py`)**:
  - Aggregates by primary keys (`user`, `command_hash_or_job_name`) and secondary rollups (`account`, `partition`, `user`).
  - Safety guardrail: Groups with observed `OUT_OF_MEMORY` or `oom` sub-labels set `reclaimable_gb_hours = 0.0`.
  - Top-5 evidence job sampling identifies high-waste job IDs per group with deterministic tie-breaking.
  - Exports validated for both Parquet and CSV representations.

---

## 4. Documentation and Decision Tracking Audit
- **AI Assistance Ledger (`docs/AI-ASSISTANCE.md`)**:
  - Cataloged all Phase 2 files: `rcwa/retries.py`, `rcwa/attribute.py`, `rcwa/groups.py`, `tests/unit/test_retries.py`, `tests/unit/test_attribute.py`, `tests/unit/test_groups.py`, `tests/unit/test_conservation.py`.
- **Architectural Decisions Log (`docs/DECISIONS.md`)**:
  - Documented DEC-007 (Conservation Precedence Hierarchy Implementation).
  - Documented DEC-008 (Non-Null Memory Reservation Normalization for Conservation Arithmetic).
  - Documented DEC-009 (1-to-1 Temporal Earliest Candidate Claiming for Retry Chains).

---

## 5. Final Binary Verdict
**Verdict**: **PASS**
