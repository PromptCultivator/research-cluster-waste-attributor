# DISPATCH: Sub-Orchestrator Phase 1 (Adapters and Canonical Record)

## Identity
- Archetype: teamwork_sub_orchestrator
- Working Directory: /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/sub_orch_phase1
- Parent Conversation ID: ac651b2c817627dbf13ef854add4b9ee

## Mission
You are the Sub-Orchestrator for Milestone M1: Phase 1 — Adapters and Canonical Record of `research-cluster-waste-attributor`.
Read your assignment in `SCOPE.md`, `PROJECT.md`, `docs/SPEC.md`, and `ORIGINAL_REQUEST.md`.

Execute the Iteration Loop (Explorers -> Worker -> Reviewers -> Challengers -> Forensic Auditor -> Gate) to deliver Phase 1.
Stop when the Gate passes, write `handoff.md`, and notify parent using the format in SPEC §15.

## Scope Summary
- `rcwa/model.py`: Canonical job record (Arrow schema and Pydantic v2 model) matching SPEC §5.3:
  - 22 fields + calculated fields (`reserved_core_s = alloc_cpus * run_s`, `reserved_mem_mb_s = req_mem_mb * run_s`).
  - Strict nullability, data types, and canonical state enum: `{COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER}`.
- `rcwa/normalize.py`:
  - Elapsed and TotalCPU duration parsing (`D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`).
  - Memory suffix parsing (`4000M`, `4000Mc` per-cpu, `4000Mn` per-node, `G`, `Gc`, `Gn`, `K`, `Kc`, `Kn`, `?`/unknown).
  - State qualifier stripping (e.g. `CANCELLED by 1234` -> `CANCELLED`) and mapping to canonical enum.
  - TRES string parsing (`ReqTRES`, `AllocTRES` -> GPU counts, node counts).
- `rcwa/adapters/sacct.py`:
  - Slurm `sacct` export parser: pipe-delimited with header; empty fields tolerated; unknown extra columns ignored with warning.
  - Step rollup: `max_rss_mb = max over steps`, `cpu_time_used_s = sum of TotalCPU over steps excluding .extern`. Parent carries allocations.
  - Array jobs (`12345_7`) and heterogeneous job components (`12345+0`): treat each as a job, record `parent_job_id`. Steps roll up to sub-job.
  - Comment parsing for `RCWA_INPUT_HASH=<hex>`.
- `rcwa/adapters/swf.py`:
  - Standard Workload Format parser: 18 whitespace-separated fields.
  - Header pragmas: `; UnixStartTime`, `; MaxProcs`, `; MaxNodes`, `; Note`.
  - Multipliers: memory is KB per processor -> multiply by `alloc_cpus` / 1024 for job total MB; CPU time is average per processor -> multiply by `alloc_cpus`.
  - Missing values (-1) mapped to `None`.
  - `executable number` -> `command_hash`.
  - SWF has no declared inputs: `input_hash = None`, recomputation reported as "not available".
- Fixtures under `tests/fixtures/`:
  - Sacct fixture files covering every single parser requirement in SPEC §5.1.
  - SWF fixture file covering header pragmas and 18 fields in SPEC §5.2.
- 100k-row throughput benchmark:
  - Generate or stream a 100,000-row synthetic sacct export and measure parse throughput in jobs/s.
- Maintain test coverage >= 85%, clean lint (`ruff`), clean typecheck (`pyright`).
- Update `docs/AI-ASSISTANCE.md` with every file/function written.
- Prohibited words: ZERO tolerance for "simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", "cutting-edge".
