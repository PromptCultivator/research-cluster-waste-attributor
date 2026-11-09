# DISPATCH: Explorer 1 (Tooling, Architecture, Constraints, Benchmarks, Reports, ADRs, Phases)

## Identity
- Archetype: teamwork_preview_explorer
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/explorer_survey_1
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
Investigate the authoritative sources:
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md

Extract exhaustive, structured requirements for:
1. System Rules & Hard Constraints (Sections 1, 3, 11, 13, 16):
   - Strict dependencies (polars, pyarrow, numpy, pydantic>=2, typer, pyyaml, pytest, pytest-cov, hypothesis, ruff, pyright)
   - Banned words list: "simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge"
   - AI-ASSISTANCE.md format and requirements
   - DECISIONS.md format and requirements
   - DATA.md format and requirements
2. Makefile Targets & CI (Section 10):
   - All 13 makefile targets (setup, lint, typecheck, test, data, synth, run, calibrate, bench, bench-smoke, goldens, docker)
   - Test coverage threshold (85% lines)
3. Benchmark & Hardware (Section 9):
   - Benchmark metrics, bench/run.py, bench/hardware.py
   - Hardware block format for README
4. ADRs & Documentation (Sections 12, 13):
   - Five required ADRs and their specific content / trade-offs
   - README structure, 14 sections in order
5. Phased Delivery & Acceptance Criteria (Sections 14, 15):
   - Exact definitions and acceptance criteria for Phase 0 through Phase 7
   - Phase reporting format (Section 15)
   - Definition of done (Section 16)

Write your complete findings to `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/explorer_survey_1/handoff.md`.


## 2026-11-09T21:58:30Z
[Message] sender=ac651b2c817627dbf13ef854add4b9ee
You are Explorer 1 for research-cluster-waste-attributor. Read your assignment in /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/explorer_survey_1/DISPATCH.md and investigate /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md and /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md. Focus on project architecture, toolchain, Makefile targets, allowed dependencies, banned words, ADRs, documentation, benchmark specifications, and phased delivery acceptance criteria. Write your structured report to /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/explorer_survey_1/handoff.md and notify me via send_message when complete.
