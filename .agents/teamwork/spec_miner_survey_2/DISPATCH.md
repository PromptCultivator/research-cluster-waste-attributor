# DISPATCH: Spec Miner 2 (Attribution, Recommendations, Guardrails, Simulator, Calibration)

## Identity
- Archetype: teamwork_preview_spec_miner
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_2
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
Investigate the authoritative sources:
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
- /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md

Extract exhaustive, structured requirements for:
1. Waste Attribution & Conservation Partition (Section 6.1):
   - Precedence order (Class 3, Class 4, Class 2, Class 1)
   - Exact mathematical formulas for integer seconds and MB-seconds
   - Sub-labels for Class 3, retry chain definitions and windows
   - Class 4 criteria, confidence levels (declared_inputs vs command_only), window
   - Class 2 and Class 1 formulas, handling of null metrics (unattributed labels)
   - Guarantee G1 definition and test requirement
2. Ranked Reclaim List (Section 6.2):
   - Group-level metrics, sorting formulas (mem_weight_core_hours_per_gb_hour), top 5 evidence job IDs, secondary rollups.
3. Recommendations with Guardrails (Section 7):
   - Memory recommendation formulas (p99 * 1.2, max observed across states floor, OOM increase rule)
   - CPU recommendation formulas (clamp, p99 * 1.2, min run_s check)
   - Timeouts, early failures, recomputation cache hit rate recommendations
   - Guarantee G2 definition and property test requirements (Hypothesis)
4. Scheduler Simulator & Calibration (Section 8):
   - Cluster model and inference, FCFS + EASY backfill algorithm details, tie-breaking
   - Scenarios: baseline, mem_rightsized, cpu_rightsized (none vs proportional), cache_dedup, all
   - Calibration metrics (median absolute error, Spearman correlation)
   - Guarantee G4 definition and tests
   - Performance targets (1M jobs in pure Python in under 15 min)

Write your complete findings to `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_2/handoff.md`.


## 2026-11-09T21:58:30Z
[Message] timestamp=2026-11-09T21:58:30Z sender=ac651b2c817627dbf13ef854add4b9ee priority=MESSAGE_PRIORITY_HIGH content=You are Spec Miner 2 for research-cluster-waste-attributor. Read your assignment in /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_2/DISPATCH.md and investigate /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md and /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md. Focus on the 4 waste classes, conservation partition (G1), ranked reclaim lists, recommendations with guardrails (G2), EASY-backfill simulator (G4), calibration, and performance goals. Write your structured report to /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_2/handoff.md and notify me via send_message when complete.
