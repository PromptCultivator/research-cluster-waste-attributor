# DISPATCH: Sub-Orchestrator Phase 1 (Adapters and Canonical Record)

## Identity
- Archetype: teamwork_sub_orchestrator
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/sub_orch_phase1_gen2
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
You are the Sub-Orchestrator for Milestone M1: Phase 1 — Adapters and Canonical Record of `research-cluster-waste-attributor`.
Read your assignment in `SCOPE.md`, `PROJECT.md`, `docs/SPEC.md`, and `ORIGINAL_REQUEST.md`.

Execute the Iteration Loop (Explorers -> Worker -> Reviewers -> Challengers -> Forensic Auditor -> Gate) to deliver Phase 1.
Stop when the Gate passes, write `handoff.md`, and notify parent using the format in SPEC §15.

## Scope Summary
1. `rcwa/model.py`:
   - Canonical job record Arrow schema (`pyarrow.schema`) and Pydantic v2 model matching SPEC §5.3:
     22 fields + calculated fields (`reserved_core_s = alloc_cpus * run_s`, `reserved_mem_mb_s = req_mem_mb * run_s`).
   - Strict data types, nullability, and canonical state enum:
     `{COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER}`.
2. `rcwa/normalize.py`:
   - Duration parsing for `Elapsed` and `TotalCPU` (`D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`) -> integer and float seconds.
   - Memory suffix parsing for `ReqMem`: `4000M`, `4000Mc` (per-CPU: base * alloc_cpus), `4000Mn` (per-node: base * nodes), `G`/`Gc`/`Gn` (*1024), `K`/`Kc`/`Kn` (/1024), `?`/unknown -> null.
   - State qualifier stripping (e.g., `CANCELLED by 1234` -> `CANCELLED`) and canonical enum mapping.
   - TRES parsing for `ReqTRES` and `AllocTRES` -> GPU counts (`req_gpus`, `alloc_gpus`) and node counts.
   - Wait time calculation: `wait_s = max(0, start_time - submit_time)` when available.
3. `rcwa/adapters/sacct.py`:
   - Pipe-delimited parser with header; empty fields supported; extra columns ignored with warning.
   - Step hierarchy rollup: `max_rss_mb = max over steps`, `cpu_time_used_s = sum over steps excluding .extern`. Parent carries allocations.
   - Array jobs (`12345_7`) and heterogeneous job components (`12345+0`): each treated as an individual job with `parent_job_id`. Steps roll up to sub-job.
   - Comment field parsing for `RCWA_INPUT_HASH=<hex>`.
4. `rcwa/adapters/swf.py`:
   - Standard Workload Format parser for 18 whitespace-separated fields.
   - Header pragmas: `; UnixStartTime`, `; MaxProcs`, `; MaxNodes`, `; Note`.
   - Multipliers: memory is KB per processor -> multiply by `alloc_cpus` / 1024 for job total MB; CPU time is average per processor -> multiply by `alloc_cpus`.
   - Missing values (-1) mapped to `None`.
   - `executable number` -> `command_hash`.
   - SWF has no declared inputs: `input_hash = None`, recomputation reported as "not available".
5. Fixtures under `tests/fixtures/`:
   - Cover every single parser requirement from SPEC §5.1 and §5.2.
6. 100k-row throughput benchmark:
   - Generate a 100,000-row synthetic sacct export and measure parse throughput in jobs/s.
7. Verification:
   - All tests pass (`make test`), test coverage >= 85%, `make lint` clean, `make typecheck` clean.
   - Update `docs/AI-ASSISTANCE.md` with every file/function written.
   - Zero prohibited words: "simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge".
