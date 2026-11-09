# Test Readiness Declaration

## 1. Readiness Summary

The end-to-end (E2E) opaque-box test suite for `research-cluster-waste-attributor` is established and verified. The test harness discovers and parameterizes all feature scenarios without collection errors.

- **Test Suite Status**: READY FOR CONTINUOUS VERIFICATION
- **Total E2E Test Invocations Collected**: 608
- **Required Minimum Threshold**: 563 (calculated as $11 \times N + \max(5, \lfloor N/2 \rfloor) = 11 \times 49 + 24 = 563$ for $N=49$ features)
- **Margin Over Threshold**: +45 tests (+8.0%)
- **Syntax and Discovery Errors**: 0

---

## 2. Test Execution Instructions

### Complete Test Discovery
To verify successful discovery across all tiers without execution overhead:
```bash
pytest tests/e2e/ -o addopts="" --collect-only
```

### Targeted Tier Execution
To execute specific testing tiers during phase delivery:
```bash
# Tier 1: Feature Coverage (F4 - F44)
pytest tests/e2e/tier1_feature_coverage/ -o addopts=""

# Tier 2: Boundary and Corner Cases
pytest tests/e2e/tier2_boundary_corner/ -o addopts=""

# Tier 3: Cross-Feature Combinations (INT-01 through INT-08)
pytest tests/e2e/tier3_cross_feature/ -o addopts=""

# Tier 4: Real-World Workflows and Guarantees (G1 - G4)
pytest tests/e2e/tier4_real_world/ -o addopts=""
```

### Subprocess CLI Mode
The CLI invoker fixture spawns subprocess calls using Python:
```bash
python -m rcwa.cli --help
python -m rcwa.wrap --help
```

---

## 3. Milestone Pass Progression Matrix

The test suite exercises opaque-box system properties as features land across delivery phases:

| Milestone | Target Scope | Associated Test Suites | Expected Test Status |
|---|---|---|---|
| **M0** | Scaffold & Toolchain | `test_cli_argument_boundaries.py` (help checks) | PASS CLI help tests; pending modules skipped |
| **M1** | Ingest & Canonical Record | `test_f04_f09_sacct_ingest.py`, `test_f10_f14_swf_canonical.py`, `test_empty_and_truncated_inputs.py`, `test_corrupted_and_extreme_values.py` | PASS 180+ ingest and parsing tests |
| **M2** | Waste Attribution & G1 | `test_f15_f21_attribution_g1.py`, `test_guarantee_g1_conservation_suite.py` | PASS exact conservation G1 checks across all fixtures |
| **M3** | Rightsizing & G2 Safety | `test_f22_f28_reclaim_recommendations_g2.py`, `test_guarantee_g2_safety_suite.py`, `test_boundary_sample_groups.py` | PASS 100+ rightsizing and guardrail tests |
| **M4** | Recomputation & Wrap | `test_f29_f34_wrap_recompute.py`, `test_wrap_tolerance_boundaries.py`, `test_int02_wrap_sidecar_class4.py` | PASS 50+ hashing and Class 4 attribution tests |
| **M5** | Simulator & Calibration | `test_f35_f40_simulator_calibration_g4.py`, `test_int05_easy_backfill_scenarios.py`, `test_int06_calibration_spearman_mae.py`, `test_guarantee_g4_simulation_validity_suite.py` | PASS 75+ EASY-backfill and G4 validity tests |
| **M6** | Reports & Determinism G3 | `test_f41_f44_reports_determinism_g3.py`, `test_guarantee_g3_determinism_suite.py`, `test_int07_full_pipeline_determinism.py` | PASS 50+ multi-format and G3 determinism tests |
| **M7** | End-to-End Traces | `test_cli_workflow_e2e.py`, `test_multiday_cluster_workload.py`, `test_degraded_data_resilience.py` | PASS 100% of all 608 test cases |

---

## 4. Test Count Accounting

| Tier / Directory | Primary Purpose | Test Modules | Test Count |
|---|---|---|---|
| **Tier 1** | Feature Coverage (F4 - F44) | 7 modules | 341 |
| **Tier 2** | Boundary & Corner Cases | 6 modules | 90 |
| **Tier 3** | Cross-Feature Integrations (INT-01 to INT-08) | 8 modules | 38 |
| **Tier 4** | Real-World Traces & Guarantees (G1 - G4) | 7 modules | 139 |
| **Total** | Complete E2E Test Suite | 28 modules | **608** |

---

## 5. Prohibited Vocabulary Compliance Attestation

In accordance with specification guidelines, all test files, test fixtures, documentation records, docstrings, and comments were audited using automated regex validation:
- Checked prohibited terms: 9 prohibited words defined in specification Section 13.
- Target files examined: All files under `tests/fixtures/`, `tests/e2e/`, `TEST_INFRA.md`, and `TEST_READY.md`.
- Result: **0 instances detected**.
