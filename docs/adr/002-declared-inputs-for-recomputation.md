# ADR 002: Declared Inputs for Recomputation Detection

## Status
Accepted

## Context
Redundant recomputation occurs when identical workflows re-run identical executables and arguments against identical input data. Standard schedulers such as Slurm record job submission lines (`SubmitLine`) and job names (`JobName`), not filesystem reads or input dataset digests. Standard Workload Format (`SWF`) traces lack input hashes altogether.

## Options
1. **Explicit Declared Input Hashing (`rcwa-wrap`)**: Wrap batch invocations with a helper utility that hashes user-declared input paths and normalized command arguments, persisting metadata into Slurm comments and optional JSON sidecars.
2. **System Call Interception (eBPF / `ptrace` / `LD_PRELOAD`)**: Hook `open`/`read` syscalls at runtime to record all accessed paths dynamically.
3. **Command-Only Matching**: Identify duplicates solely from normalized executable names and flags without validating inputs.

## Decision
Adopt Option 1: Explicit Declared Input Hashing (implemented in [`rcwa/wrap.py`](../../rcwa/wrap.py) and [`rcwa/recompute.py`](../../rcwa/recompute.py)). `rcwa-wrap` hashes explicitly passed `--inputs` paths via streaming SHA-256 (or `sha256("<basename>:<bytes>:<int_mtime>")` when `--big-file-mode size_mtime` is active and file size exceeds `--big-file-threshold`, default `104857600` bytes), normalizes command arguments by sorting `-`/`--` flags after optional `--regex-strip` sanitization, records `Comment=RCWA_INPUT_HASH=<hex>` via `scontrol` when `$SLURM_JOB_ID` is set, and writes `$RCWA_DIR/<job_id>.json` when `$RCWA_DIR` is configured. Command-only matches lacking `input_hash` receive `possible_recompute = True` (`recompute_confidence = "command_only"`) and remain excluded from Class 4 resource totals; SWF sources explicitly mark Class 4 as `"not_available"` / `"not available"`.

## Measured or Expected Cost
Runs submitted without `rcwa-wrap` or Slurm comment/sidecar metadata cannot contribute to Class 4 totals. Attribution coverage and `"command_only"` flags expose this gap quantitatively rather than estimating speculative duplicates.
