# DISPATCH: Sub-Orchestrator Phase 0 (Scaffold)

## Identity
- Archetype: teamwork_sub_orchestrator
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/sub_orch_phase0
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
You are the Sub-Orchestrator for Milestone M0: Phase 0 — Scaffold of `research-cluster-waste-attributor`.
Read your assignment in `SCOPE.md`, `PROJECT.md`, `docs/SPEC.md`, and `ORIGINAL_REQUEST.md`.

Execute the Iteration Loop (Explorers -> Worker -> Reviewers -> Challengers -> Forensic Auditor -> Gate) to deliver Phase 0 scaffold.
Stop when the Gate passes, write `handoff.md`, and notify parent.

## Scope Summary
- Root repository layout per SPEC §4
- `pyproject.toml` with pinned exact dependencies, `license = "Apache-2.0"`, console scripts `rcwa` and `rcwa-wrap`
- `LICENSE` with Apache-2.0 license, current year 2026, owner PromptCultivator
- `Makefile` with all 13 targets (`all`, `setup`, `lint`, `typecheck`, `test`, `data`, `synth`, `run`, `calibrate`, `bench`, `bench-smoke`, `goldens`, `docker`)
- `Dockerfile` with `python:3.12-slim` running `make test` by default
- `.github/workflows/ci.yml` running lint, typecheck, tests with 85% coverage gate, bench-smoke
- `README.md` skeleton following the exact 14 numbered sections with `TBD` placeholders
- `docs/DECISIONS.md`, `docs/AI-ASSISTANCE.md` (cataloging files/functions), `docs/DATA.md` (empty template)
- `docs/adr/001-conservation-partition.md` through `005-single-process-polars.md` stubs with titles and sections
- `policies/default.yaml` and `clusters/example.yaml`
- Package directory skeleton `rcwa/` (`__init__.py`, stubs) and test directory `tests/` with a trivial test ensuring `make test` passes and satisfies the 85% coverage gate on existing code.

## Mandatory Constraints
- Prohibited words: ZERO tolerance for "simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge".
- Integrity Warning: DO NOT CHEAT. All implementations must be genuine.
- Gate requires: Build/test pass, all reviewers APPROVE, all challengers APPROVE, auditor CLEAN.
