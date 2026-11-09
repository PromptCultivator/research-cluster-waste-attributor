# Phase 1 Report: Adapters and Canonical Record

## 1. Phase Number and Summary
Phase 1 (Milestone M1): Ingestion of Slurm `sacct` pipe-delimited records and SWF traces into canonical PyArrow and Polars tables with step hierarchy rollup, unit normalization, and high-throughput execution now works.

## 2. Commands Run, Test Count, Coverage, Lint, and Typecheck
- `python3 -m ruff check .` — exit 0, passed with 0 errors.
- `python3 -m ruff format --check .` — exit 0, all files formatted.
- `python3 -m pyright` — exit 0, 0 errors, 0 warnings.
- `python3 -m pytest` — exit 0, 261 passed in 14.52s, 92.13% line coverage (coverage gate >= 85% satisfied).
- `python3 -m pytest tests/unit/test_sacct_benchmark.py -s` — exit 0, 1 passed in 3.41s.
- `python3 -m pytest tests/unit/test_forbidden_words.py` — exit 0, 1 passed in 0.20s.

## 3. Measured Numbers Produced in This Phase
- Throughput on 100,000 synthetic `sacct` rows: **31,017.5 jobs/second** (wall-clock parse time: 3.224 seconds) produced by `python3 -m pytest tests/unit/test_sacct_benchmark.py -s`.
- Test suite line coverage: **92.13%** produced by `python3 -m pytest`.
- Prohibited vocabulary occurrences: **0** produced by `python3 -m pytest tests/unit/test_forbidden_words.py` and repository-wide regex scan.

## 4. Decisions Made That Were Not in the Spec
- **DEC-005**: Click 8.5.1 Compatibility Bridges: Implemented compatibility shims in `rcwa/__init__.py` for Typer argument metavars and required parameter checks under Click 8.5+.
- **DEC-006**: Lazy Schema and Model Initialization for Sub-Second CLI Ingestion: Configured module-level `__getattr__` and `TYPE_CHECKING` guards in `rcwa/model.py` to prevent redundant Arrow schema and Pydantic model compilation during rapid CLI execution.

## 5. Open Questions for the Human
- Question: When `cpu_time_used_s` exceeds `reserved_core_s` due to hyperthreading or multi-threading spikes, should `idle_core_s` be clamped to 0 with `used_core_s = reserved_core_s`?  
  *Default*: Yes, clamp `idle_core_s = max(0, reserved_core_s - cpu_time_used_s)` and `used_core_s = min(reserved_core_s, int(round(cpu_time_used_s)))` so that `reserved_core_s == used_core_s + idle_core_s` holds exactly for Guarantee G1.

## 6. Next Phase's First Three Steps
1. Implement `rcwa/attribute.py` with the one-pass precedence cascade (Class 3 -> Class 4 -> Class 2 / Class 1 -> Used / Unattributed) enforcing Guarantee G1.
2. Implement `rcwa/retries.py` to detect retry chains for failed or timed out jobs submitted within `retry_window` (default 24h).
3. Implement `rcwa/groups.py` to aggregate attributed jobs by `(user, command_hash or job_name)` with secondary account/partition rollups and calculate reclaim scores with top-5 evidence jobs.
