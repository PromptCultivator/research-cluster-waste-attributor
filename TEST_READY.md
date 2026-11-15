# Test Suite Readiness and Verification Summary

## 1. Suite Inventory

The `research-cluster-waste-attributor` verification suite spans unit tests, Hypothesis property tests, golden report comparisons, and an opaque-box CLI end-to-end (E2E) suite backed by offline fixtures.

| Suite | Scope | Modules | Collected Cases | Network Required |
|---|---|---|---|---|
| Unit (`tests/unit/`) | Normalization, adapters, attribution, G1, retries, grouping, recomputation, recommendations, simulator, calibration, reporting, synthetic generator, scaffold, vocabulary gate | 21 | 389 (combined standard suite) | No |
| Property (`tests/property/`) | Guarantee G2 across 10,000 Hypothesis-generated job cohorts | 1 | Included in 389 above | No |
| Golden (`tests/golden/`) | Guarantee G3 byte-determinism and exact regression against 6 committed Slurm/SWF golden fixtures | 2 | Included in 389 above | No |
| E2E Tier 1 (`tests/e2e/tier1_feature_coverage/`) | Opaque-box CLI feature coverage (`sacct`, `swf`, attribution, guardrails, `rcwa-wrap`, simulator, reporting) | 7 | 341 | No |
| E2E Tier 2 (`tests/e2e/tier2_boundary_corner/`) | Boundary, truncated, binary, extreme, missing-metric, and CLI error conditions | 6 | 92 | No |
| E2E Tier 3 (`tests/e2e/tier3_cross_feature/`) | Cross-feature integrations (`INT-01` through `INT-08`) | 8 | 38 | No |
| E2E Tier 4 (`tests/e2e/tier4_real_world/`) | Multi-day cluster traces, degraded inputs, and G1–G4 suites | 7 | 139 | No |
| **Total E2E** | Complete opaque-box CLI suite (`tests/e2e/`) | **28** | **610** | **No** |
| **Total Fixtures** | Committed test datasets (`tests/fixtures/`) | **10 dirs** | **40 files** | **No** |

---

## 2. Running the Suites

### Standard CI Verification (`>= 85%` Branch & Line Coverage Gate)

The default [`pyproject.toml`](pyproject.toml) configuration executes `tests/unit/`, `tests/property/`, and `tests/golden/` while enforcing `cov-fail-under=85`:

```bash
make test
# Equivalent:
python -m pytest
```

### E2E Opaque-Box Suite (`tests/e2e/`)

Override default `addopts` when invoking `tests/e2e/` directly because E2E subprocess invocations run in external child processes:

```bash
# Discover all E2E test cases without executing
pytest tests/e2e/ -o addopts="" --collect-only

# Execute full E2E suite
pytest tests/e2e/ -o addopts=""

# Execute individual tiers
pytest tests/e2e/tier1_feature_coverage/ -o addopts=""
pytest tests/e2e/tier2_boundary_corner/ -o addopts=""
pytest tests/e2e/tier3_cross_feature/ -o addopts=""
pytest tests/e2e/tier4_real_world/ -o addopts=""
```

### Static Quality & Smoke Gates

```bash
make lint         # ruff check . && ruff format --check .
make typecheck    # pyright
make bench-smoke  # 20k synthetic trace end-to-end invariant check (G1 exact, 0 G2 violations)
```

---

## 3. Compliance Audits

- **Zero-Network Hermetic Execution**: All unit, property, golden, and E2E suites operate exclusively on committed files under [`tests/fixtures/`](tests/fixtures/) and deterministic synthetic data generated at test runtime.
- **Prohibited Vocabulary Check**: [`tests/unit/test_forbidden_words.py`](tests/unit/test_forbidden_words.py) scans all source, configuration, test, and Markdown documentation files (including `README.md`, `PROJECT.md`, `TEST_READY.md`, and `docs/`) to ensure zero occurrences of the nine excluded terms.

For detailed harness fixtures, mathematical verification formulas, and the complete 40-file fixture catalog, see [`docs/TESTING.md`](docs/TESTING.md).
