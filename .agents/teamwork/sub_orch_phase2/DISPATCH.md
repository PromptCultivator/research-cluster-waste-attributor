# DISPATCH: Sub-Orchestrator Phase 2 (Attribution)

## Identity
- Archetype: teamwork_sub_orchestrator
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/sub_orch_phase2
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
You are the Sub-Orchestrator for Milestone M2: Phase 2 — Attribution of `research-cluster-waste-attributor`.
Read your assignment in `SCOPE.md`, `PROJECT.md`, `docs/SPEC.md`, and `ORIGINAL_REQUEST.md`.

Execute the Iteration Loop (Explorers -> Worker -> Reviewers -> Challengers -> Forensic Auditor -> Gate) to deliver Phase 2.
Stop when the Gate passes, write `handoff.md`, and notify parent using the format in SPEC §15.

## Scope Summary
1. `rcwa/attribute.py`:
   - Implement the one-pass precedence partition for every job in integer seconds (`reserved_core_s`) and MB-seconds (`reserved_mem_mb_s`):
     1. Class 3 (Failed and retried work): states `FAILED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, `PREEMPTED`, or (`CANCELLED` and `run_s > 0`). Sub-labels: `oom`, `timeout`, `early_failure` (run_s <= 60), `other_failure`, `cancelled_after_start`, `node_fail`.
     2. Class 4 (Redundant recomputation): state `COMPLETED` matching earlier `COMPLETED` job within `recompute_window` (default 30d) by `(command_hash, input_hash)` (`confidence = declared_inputs`). Missing `input_hash` with matching `command_hash` labeled `possible_recompute` (`confidence = command_only`), NOT counted in Class 4 totals. SWF traces report recomputation as "not available", never estimated.
     3. Class 2 (Idle reserved CPU): `idle_core_s = max(0, reserved_core_s - cpu_time_used_s)`, `used_core_s = reserved_core_s - idle_core_s`. Null `cpu_time_used_s` -> `unattributed_missing_cpu_time`.
     4. Class 1 (Memory over-request): `over_mem_mb_s = max(0, req_mem_mb - max_rss_mb) * run_s`, `used_mem_mb_s = reserved_mem_mb_s - over_mem_mb_s`. Null `max_rss_mb` -> `unattributed_missing_rss`.
   - Exclusions: `RUNNING` and `PENDING` excluded from attribution, recorded in data-quality metrics. `run_s = 0` kept (early failures) with 0 consumption.
2. Guarantee G1:
   - Exact integer conservation test: for every job and dimension, `reserved = used + class1_or_2 + class3 + class4 + unattributed` holds exactly.
   - Verify trace-level sums match per-job table sums.
3. `rcwa/retries.py`:
   - Detect retry chains: subsequent matching job by same user with same `command_hash` (or `job_name`) submitted within `retry_window` (default 24h) after a failed job is marked `retry_of = parent_job_id`. Aggregates chain cost.
4. `rcwa/groups.py`:
   - Group by configurable key (default `(user, command_hash or job_name)`). Secondary rollups by `account`, `partition`, `user`.
   - Ranked reclaim list scoring: `reclaimable_core_hours + mem_weight * reclaimable_gb_hours`. Identify top-5 evidence job IDs per group.
5. Export & Verification:
   - Output per-job and group tables to Parquet and CSV.
   - Acceptance: G1 conservation holds exactly on fixtures and on a 20,000-row synthetic trace.
   - Full test suite, lint, typecheck passing. Zero prohibited words.
