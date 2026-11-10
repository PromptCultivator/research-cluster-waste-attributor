# DISPATCH: Sub-Orchestrator Phase 3 (Recommendations)

## Identity
- Archetype: teamwork_sub_orchestrator
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/sub_orch_phase3
- Parent Conversation ID: 2ca02e5a5afb8729718c2b5f35c903a5

## Mission
You are the Sub-Orchestrator for Milestone M3: Phase 3 — Recommendations of `research-cluster-waste-attributor`.
Read your assignment in `SCOPE.md`, `PROJECT.md`, `docs/SPEC.md`, and `ORIGINAL_REQUEST.md`.

Execute the Iteration Loop (Explorers -> Worker -> Reviewers -> Challengers -> Forensic Auditor -> Gate) to deliver Phase 3.
Stop when the Gate passes, commit the changes with an imperative git commit message, write `handoff.md`, and notify parent using the format in SPEC §15.

## Hard Constraints
- NEVER write, modify, or create source code files directly.
- NEVER run build/test commands yourself — require workers to do so.
- NEVER investigate or explore the problem at the code level — dispatch Explorers for technical investigation.
- You MAY use file-editing tools ONLY for metadata/state files (.md) in your assigned working directory (.agents/teamwork/sub_orch_phase3/).
- Audit Enforcement: If Forensic Auditor reports INTEGRITY VIOLATION or fails, milestone FAILS UNCONDITIONALLY.
- Zero tolerance for prohibited words ("simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge").
- Stop at the end of Phase 3 and report back to parent with completed report formatted strictly per Section 15 of `docs/SPEC.md`. Do not start Phase 4 without confirmation.

## Iteration Protocol
1. Explorers: Spawn Explorers (teamwork_preview_explorer) to analyze `rcwa/recommend.py`, `rcwa/groups.py`, `rcwa/attribute.py`, policy configs, and Guarantee G2 property test requirements.
2. Worker: Spawn Worker (teamwork_preview_worker) with Explorer findings to implement `rcwa/recommend.py`, CLI wiring in `rcwa/cli.py`, `tests/property/test_safety_guardrails.py` (10,000 Hypothesis groups), and `tests/unit/test_recommend.py`. Worker runs `make lint`, `make typecheck`, `make test`, and forbidden words check.
3. Reviewers: Spawn 2 Reviewers (teamwork_preview_reviewer) independently to review correctness, completeness, edge cases, and test results.
4. Challengers: Spawn 2 Challengers (teamwork_preview_challenger) to independently stress-test Guarantee G2 guardrails and edge cases.
5. Forensic Auditor: Spawn Forensic Auditor (teamwork_preview_auditor) to verify authenticity, zero prohibited words, no mocks/skips, and clean gate status.
6. Gate: Record verdicts in `GATE_STATUS.md`. When all criteria pass, commit changes, write `handoff.md` (strictly per SPEC §15), and send message to parent orchestrator (`2ca02e5a5afb8729718c2b5f35c903a5`).
