# Scope: Milestone M0 (Phase 0 — Scaffold)

## Objective
Establish the repository skeleton, build infrastructure, package configuration, testing framework, baseline CI, and documentation structure in accordance with `docs/SPEC.md §4, §10, §11, §12, §13, §14`.

## Files Owned
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/pyproject.toml`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/LICENSE`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/Makefile`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/Dockerfile`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.github/workflows/ci.yml`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/README.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/DECISIONS.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/AI-ASSISTANCE.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/DATA.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/adr/001-conservation-partition.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/adr/002-declared-inputs-for-recomputation.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/adr/003-percentile-rightsizing-with-guardrails.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/adr/004-easy-backfill-simulator.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/adr/005-single-process-polars.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/policies/default.yaml`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/clusters/example.yaml`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/__init__.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/cli.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/rcwa/wrap.py`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/tests/unit/test_scaffold.py`

## Acceptance Criteria
- `make setup` successfully creates virtual environment and installs pinned dependencies.
- `make lint` runs `ruff check` and `ruff format --check` and passes cleanly.
- `make typecheck` runs `pyright` and passes cleanly.
- `make test` runs pytest with coverage gate (85% lines) and passes.
- Dockerfile syntax is valid.
- Zero prohibited words exist across all created files.
- Gate passes with clean forensic audit.
