# Scope: E2E Testing Track

## Test Architecture
- Test suite location: `tests/e2e/` (and test fixtures under `tests/fixtures/`)
- Runner command: `pytest tests/e2e/ -v`
- Pass/Fail semantics: All tests must run with exit code 0 when implementation is present.
- Tier structure:
  - Tier 1: Feature Coverage (>=5 cases per feature)
  - Tier 2: Boundary & Corner Cases (>=5 cases per feature)
  - Tier 3: Cross-Feature Interactions (pairwise combinations)
  - Tier 4: Real-World Workload Scenarios (realistic sacct and SWF traces)

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E-1 | Test Infrastructure & Tier 1 Tests | Harness, fixtures, CLI invocation helpers, Tier 1 feature tests | none | PLANNED |
| E2E-2 | Tier 2 Boundary & Corner Tests | Malformed inputs, missing metrics, empty files, bounds, suffix edges | E2E-1 | PLANNED |
| E2E-3 | Tier 3 Cross-Feature & Tier 4 Scenarios | Pairwise interactions and realistic end-to-end workflows | E2E-2 | PLANNED |
| E2E-4 | TEST_INFRA.md & TEST_READY.md Publication | Summarize coverage matrix, runner commands, publish ready signal | E2E-3 | PLANNED |
