# Recomputation Detection and Input Hashing Wrapper

## 1. Overview

Research workloads routinely re-execute identical analysis pipelines or parameter sweeps without result caching. [`rcwa/wrap.py`](../../rcwa/wrap.py) (`rcwa-wrap`) captures declared input checksums and normalized command invocations at job submission time without syscall tracing, while [`rcwa/recompute.py`](../../rcwa/recompute.py) merges sidecar metadata, classifies Class 4 duplicates, simulates cache savings, and measures classification accuracy against synthetic ground truth.

---

## 2. CLI Invocation Wrapper (`rcwa-wrap`)

```bash
rcwa-wrap \
  --inputs data/a.parquet,config.yaml \
  --big-file-mode size_mtime \
  --big-file-threshold 104857600 \
  --regex-strip "/tmp/run_[0-9]+/" \
  -- python train.py --lr 0.01
```

### 2.1 Hashing and Normalization Rules (`rcwa/wrap.py`)

- **Comma-Separated Inputs (`--inputs`)**: Accepts comma-separated paths. Single-file inputs compute `hash_file` directly; multi-file inputs sort paths alphabetically and feed `f"{item}={digest}\n"` lines into SHA-256 (`compute_input_hash`). Empty `--inputs` hashes empty bytes `b""`.
- **Content vs Big-File Mode (`hash_file`)**: Reads 64 KB chunks for full SHA-256 digests unless `big_file_mode == "size_mtime"` AND `file_size > big_file_threshold` (default `104857600` bytes / 100 MB), in which case it computes:
  $$\text{SHA-256}\left(\text{"<basename>:<file\_size\_bytes>:<int\_mtime\_seconds>"}\right)$$
- **Missing File Resilience**: Unreadable or missing input paths return `"missing"` in digests (and record `{"path": inp, "status": "missing"}` in sidecar metadata) without blocking execution of the wrapped command.
- **Command Normalization (`normalize_command_line`)**: Strips optional `--regex-strip` patterns from tokens (preserving `--key=` option prefixes), leaves the executable token first, lexicographically sorts all `-`/`--` option tokens, preserves relative order among positional arguments, and computes `SHA-256` over the normalized string.
- **Exit Propagation**: Executes the child command after `--` directly via `subprocess.run` and propagates its exit code (`127` for missing executable, `126` for permission errors).

### 2.2 Checksum Persistence & Sidecar Merging

`record_hash` writes digests to:
1. **Slurm Job Comment**: When `$SLURM_JOB_ID` is defined, runs `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>` (ignoring errors if `scontrol` is absent).
2. **Sidecar JSON File**: When `$RCWA_DIR` is set, writes `$RCWA_DIR/<job_id>.json` (`unknown.json` when `$SLURM_JOB_ID` is unset) containing `job_id`, `input_hash`, optional `command_hash`, and `inputs`.

[`merge_sidecars(df, sidecar_dir=None)`](../../rcwa/recompute.py) loads sidecars via `load_sidecars_from_dir` (defaulting to `$RCWA_DIR`), matching exact `job_id` or stripped step/array prefix (`base_id`), and populates missing `input_hash` and `command_hash` fields.

---

## 3. Duplicate Detection, Cache Simulation, and Accuracy (`rcwa/recompute.py`)

### 3.1 `detect_recomputations(df, recompute_window_s=2592000)`

Evaluates rows ordered deterministically by `(submit_time or eff_end, row_index, job_id)`:

```text
[ Job Record ]
     ├── source == "swf"       ──► is_recompute = False, possible_recompute = False,
     │                             recompute_confidence = "not_available"
     ├── state != "COMPLETED"  ──► is_recompute = False, possible_recompute = False,
     │                             recompute_confidence = None
     └── state == "COMPLETED"
           ├── Match prior COMPLETED (command_hash, input_hash) with
           │   0 <= (submit_time - prev_eff_end) <= recompute_window_s (default 30 days)
           │     ──► is_recompute = True, recompute_confidence = "declared_inputs" (Class 4)
           └── Else match prior COMPLETED command_hash within window
                 ──► possible_recompute = True, recompute_confidence = "command_only"
                     (excluded from Class 4 resource totals)
```

### 3.2 `simulate_result_cache(df, cache_threshold_waste_share=0.05)`

Aggregates Class 4 core-hours, GB-hours, completed counts, and cache hits per `group_key` (or derived `user / (command_hash or job_name)`), flagging `recommended = True` whenever `group_waste_share >= threshold`, `trace_waste_share >= threshold`, or `hits > 0`.

### 3.3 `evaluate_recomputation_accuracy(detected_df, ground_truth_df)`

Joins detected Class 4 classifications against planted truth (`is_recompute_right`, `planted_is_recompute`, or `true_class == 4`) to return `precision`, `recall`, `f1_score`, `true_positives`, `false_positives`, `false_negatives`, and `true_negatives`.
