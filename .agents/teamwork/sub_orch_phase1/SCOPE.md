# Scope: Milestone M1 (Phase 1 — Adapters and Canonical Record)

## Objective
Implement the canonical data model, normalization pipeline, Slurm `sacct` parser, SWF parser, fixtures, and throughput benchmark in accordance with `docs/SPEC.md §4, §5.1, §5.2, §5.3, §14`.

## Files Owned
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/model.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/normalize.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/adapters/sacct.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/adapters/swf.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/fixtures/` (sacct and swf fixtures)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_adapters.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_normalize.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_model.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_sacct_benchmark.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/AI-ASSISTANCE.md` (append entries)
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/DECISIONS.md` (append entries if needed)

## Acceptance Criteria
1. All parser tests pass covering every requirement from SPEC §5.1 and §5.2.
2. Canonical Arrow schema and Pydantic model match SPEC §5.3 exactly.
3. 100,000-row synthetic sacct export parses at a measured jobs/s reported in the phase report.
4. `make lint` and `make typecheck` pass with 0 errors.
5. `make test` passes with >= 85% coverage.
6. Zero prohibited words detected.
7. Quality gate passes with all reviewers APPROVE, challengers APPROVE, and auditor CLEAN.
