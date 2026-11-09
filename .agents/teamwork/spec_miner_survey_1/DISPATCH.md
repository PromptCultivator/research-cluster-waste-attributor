# DISPATCH: Spec Miner 1 (Inputs, Adapters, Canonical Record, Grouping, Declared Inputs)

## Identity
- Archetype: teamwork_preview_spec_miner
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_1
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
Investigate the authoritative sources:
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md

Extract exhaustive, structured requirements for:
1. Slurm sacct export parsing: format, column mapping, rollups (steps: .batch, .0, .extern), array jobs, time parsing, memory suffixes (M, Mc, Mn, G, K, ?), state mappings, TRES parsing, comments.
2. Standard Workload Format (SWF) parsing: 18 fields, header pragmas, missing values (-1), multiplier rules, command_hash derivation, recompute status.
3. Canonical Job Record: exact Arrow schema and Pydantic model fields, data types, nullability, calculated fields (reserved_core_s, reserved_mem_mb_s), exclusions (RUNNING, PENDING) and handling of run_s = 0.
4. Grouping: default group key, configurable policy, secondary rollups, min_samples guardrail.
5. Declared Inputs (`rcwa-wrap`): CLI options, hashing methods (sha256 vs size_mtime), command normalization, recording locations (scontrol Comment and sidecar json), fallback behavior on missing inputs.

Write your complete findings to `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_1/handoff.md`.

## 2026-11-09T21:58:30Z
You are Spec Miner 1 for research-cluster-waste-attributor. Read your assignment in /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_1/DISPATCH.md and investigate /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md and /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md. Focus on input parsing (sacct, swf), canonical record schema/model, grouping, and declared inputs (rcwa-wrap). Write your structured report to /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_1/handoff.md and notify me via send_message when complete.
