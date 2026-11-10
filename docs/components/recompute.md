# Recomputation Detection and Input Hashing Wrapper

## 1. Overview

Research workloads frequently re-execute identical data processing pipelines, unit backtests, or model parameter sweeps without caching intermediate results. The recomputation detection component (`rcwa/recompute.py` and `rcwa/wrap.py`) provides an external mechanism to identify duplicate computations through cryptographic hashing of declared inputs and normalized command-line invocations.

---

## 2. CLI Invocation Wrapper (`rcwa-wrap`)

Because operating-system tracing tools (e.g. `ptrace`, eBPF) impose runtime latency, `rcwa-wrap` operates transparently at submission time without kernel instrumentation:

```bash
rcwa-wrap --inputs data/a.parquet,config.yaml --big-file-mode size_mtime -- python train.py --lr 0.01
```

### 2.1 Hashing Strategy

1. **Content Hashing**:
   By default, declared input files are hashed using SHA-256 over their byte content.
2. **Big File Mode (`size_mtime`)**:
   For files exceeding a configurable size threshold, reading full content introduces I/O latency. In `size_mtime` mode, the wrapper computes SHA-256 over:
   $$\text{file\_path} \parallel \text{file\_size\_bytes} \parallel \text{mtime\_nanoseconds}$$
3. **Missing File Resilience**:
   If a declared input file is missing or unreadable, the wrapper records `"missing:<path>"` in the hash digest rather than halting the job.
4. **Command Normalization**:
   The command line is normalized before hashing:
   - Strips absolute path prefixes matching configurable regular expressions (e.g. `/home/user/workspace/` $\to$ `./`).
   - Alphabetically sorts independent `--flag=value` options.

### 2.2 Hash Persistence

The combined SHA-256 digest is published to two locations:
- **Slurm Comment**:
  Executed via `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>`.
- **Sidecar JSON File**:
  Written to `$RCWA_DIR/<job_id>.json`.

The ingestion adapter inspects the Slurm `Comment` field first, falling back to sidecar JSON files if available.

---

## 3. Duplicate Detection Logic

During trace processing, jobs are evaluated for redundant execution:

```
[ Job Record (state == COMPLETED) ]
                 │
                 ▼
[ Has input_hash AND command_hash? ]
       ├── YES ──► Scan prior COMPLETED jobs within recompute_window (default 30 days)
       │           matching identical (command_hash, input_hash).
       │           If match exists:
       │               Attributed to Class 4 (Redundant Recomputation).
       │               confidence = "declared_inputs"
       │
       └── NO (Only command_hash matches)
                   │
                   ▼
           Identified as "possible_recompute".
           confidence = "command_only"
           NOT counted in Class 4 reclaim totals.
```

By enforcing declared input verification, the system prevents false-positive duplicate attribution on parameterized jobs where script parameters remain fixed but input datasets differ.
