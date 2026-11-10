# Scope: Milestone M2 (Phase 2 — Attribution)

## Objective
Implement the 4-class waste attribution engine, Guarantee G1 conservation invariant, retry chain detection, job grouping, ranked reclaim scoring, and Parquet/CSV table exports in accordance with `docs/SPEC.md §4, §5.4, §6.1, §6.2, §14`.

## Files Owned
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/attribute.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/groups.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/retries.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_attribute.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_groups.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_retries.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_conservation.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/fixtures/` (attribution fixtures)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/AI-ASSISTANCE.md` (append entries)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/DECISIONS.md` (append entries if needed)

## Acceptance Criteria
1. Conservation G1 holds exactly on all fixtures and on a 20,000-row synthetic trace in integer seconds and MB-seconds.
2. Per-job and group attribution tables can be exported to Parquet and CSV.
3. Precedence hierarchy (Class 3 -> Class 4 -> Class 2/Class 1 -> Used/Unattributed) strictly applied without double-counting.
4. Retry chains identified across `retry_window` (default 24h) with `retry_of` links.
5. Groups ranked by reclaimable core-hours + weighted GB-hours, with top-5 evidence job IDs.
6. `make lint` (`ruff`) and `make typecheck` (`pyright`) pass cleanly with 0 errors.
7. `make test` passes with >= 85% coverage.
8. Zero prohibited words detected.
9. Quality gate passes with Reviewers APPROVE, Challengers APPROVE, Auditor CLEAN.
