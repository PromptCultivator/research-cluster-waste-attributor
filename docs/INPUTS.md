# System Input Acquisition and Configuration Guide

This guide explains how to export production Slurm traces, download public supercomputer workloads, generate synthetic traces, track declared input checksums with `rcwa-wrap`, and write cluster/policy YAML files.

---

## 1. Supported Input Sources

`research-cluster-waste-attributor` (`rcwa`) consumes:
1. **Slurm Accounting Logs (`sacct`)**: Pipe-delimited exports from Slurm `sacct`.
2. **Standard Workload Format (`SWF`)**: Plaintext `.swf` or gzip-compressed `.swf.gz` supercomputer workload logs.
3. **Canonical Parquet (`canonical.parquet`)**: Pre-ingested 27-field Apache Arrow/Parquet job tables.
4. **Sidecar Hash Metadata (`$RCWA_DIR/*.json`) & Comments**: Declared input checksums recorded by `rcwa-wrap`.

---

## 2. Production Slurm Export (`sacct`)

### 2.1 Standard Export Command

Export accounting records with pipe delimiters (`-P`), all users (`-a`), and megabyte memory units (`--units=M`):

```bash
sacct -a -P --units=M \
  -S 2026-01-01T00:00:00 \
  -E 2026-02-01T00:00:00 \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine \
  > cluster_trace.sacct
```

### 2.2 Slurm Field Reference (26 Fields)

Header order may vary (`parse_sacct` indexes fields dynamically by header name). Unknown extra columns emit a `UserWarning` and are skipped.

| Field Name | Description |
|---|---|
| `JobIDRaw` | Raw numeric scheduler job identifier. |
| `JobID` | Full identifier including step (`.batch`, `.0`, `.extern`), array (`_0`), or pack (`+0`) suffixes. |
| `User` | Submitter username. |
| `Account` | Billing account or research group. |
| `Partition` | Target Slurm partition/queue. |
| `QOS` | Quality of service string. |
| `JobName` | User-assigned job name. |
| `Submit` | Job submission timestamp (`YYYY-MM-DDTHH:MM:SS` or epoch). |
| `Eligible` | Scheduling eligibility timestamp. |
| `Start` | Execution start timestamp (`Unknown` or blank if never started). |
| `End` | Execution termination timestamp. |
| `Elapsed` | Wallclock run duration (`D-HH:MM:SS`, `HH:MM:SS`, `MM:SS`, or seconds). |
| `State` | Terminal or active Slurm state (e.g., `COMPLETED`, `FAILED`, `OUT_OF_MEMORY`, `CANCELLED by 1001`). |
| `ExitCode` | Exit code pair (`code:signal`). |
| `ReqCPUS` | Requested processor core count. |
| `AllocCPUS` | Allocated processor core count. |
| `ReqMem` | Memory request with optional unit (`K`/`M`/`G`/`T`/`P`) and scope suffix (`c` per CPU, `n` per node). |
| `MaxRSS` | Peak resident set size observed during execution. |
| `AveRSS` | Average resident set size observed across tasks/steps. |
| `TotalCPU` | Accumulated CPU time consumed across allocated cores. |
| `CPUTimeRAW` | Reserved CPU core-seconds (`AllocCPUS * Elapsed`). |
| `ReqTRES` | Requested trackable resources string (CPU, mem, node, `gres/gpu`, etc.). |
| `AllocTRES` | Allocated trackable resources string. |
| `NodeList` | Assigned compute node list or host range. |
| `Comment` | Slurm comment metadata (`RCWA_INPUT_HASH=<hex>` when captured via `rcwa-wrap`). |
| `SubmitLine` | Submitted command string used for `command_hash` derivation when absent from sidecars. |

### 2.3 Step Aggregation, Array Tasks, and Export Tips

- **Step Rollup**: Memory (`MaxRSS`) takes the maximum across child steps (`12345.batch`, `12345.0`), and `TotalCPU` sums across child steps while excluding `.extern*` system overhead steps. Parent counters serve as fallback when step rows lack metrics.
- **Array & Pack Jobs**: Array elements (`12345_0`, `12345_1`) and heterogeneous pack components (`10002+0`) materialize as distinct canonical rows with `parent_job_id` populated.
- **Time-Window Chunking & Partition Filtering**: For multi-million-job clusters, split exports into weekly windows or filter with `-r compute,gpu` to keep `slurmdbd` queries bounded.

---

## 3. Public Supercomputer Traces (`SWF`)

Retrieve reference traces from the Parallel Workloads Archive into `data/raw/`:

```bash
make data
# Equivalent:
python3 scripts/download_data.py
```

Downloaded archives (excluded from git via `data/.gitignore`):
- `data/raw/SDSC-SP2-1998-4.2-cln.swf.gz`: 73,496 jobs across 128 nodes.
- `data/raw/CEA-Curie-2011-2.swf.gz`: 773,138 jobs across 5,544 nodes / 93,312 cores.

`parse_swf` reads `.swf` and `.swf.gz` files directly via `rcwa ingest`, `rcwa report`, or `rcwa run`:

```bash
rcwa ingest data/raw/SDSC-SP2-1998-4.2-cln.swf.gz --output data/out/sdsc.parquet
```

---

## 4. Synthetic Trace Generation (`rcwa synth`)

Generate reproducible `sacct` traces alongside `.truth.parquet` planted-waste labels:

```bash
rcwa synth \
  --size 20k \
  --seed 42 \
  --faults default \
  --output data/raw/synthetic_20k.sacct \
  --ground-truth data/raw/synthetic_20k.truth.parquet

# Makefile shortcut (writes data/raw/synthetic_<size>_seed<seed>.sacct and .truth.parquet):
make synth SIZE=20k SEED=1
```

Options:
- `--size`: Integer count or suffix preset (`20k`, `100k`, `1M`).
- `--faults`: `default` (realistic planted classes 1–4 + retries), `all_waste` (elevated fault ratios), or `no_waste` (high efficiency baseline).

---

## 5. Declared Input Tracking (`rcwa-wrap`)

Wrap Slurm batch commands so Class 4 redundant recomputation is backed by verified input digests rather than heuristic guesses.

### 5.1 Usage in Batch Scripts

Pass `--inputs` as a comma-separated list of file paths before `--` and the target command:

```bash
#!/bin/bash
#SBATCH --job-name=data_transform
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G

export RCWA_DIR=/shared/rcwa/sidecars

rcwa-wrap \
  --inputs data/source_records.parquet,configs/pipeline_config.yaml \
  --big-file-mode size_mtime \
  --big-file-threshold 104857600 \
  -- python transform.py --mode full --output data/processed.parquet
```

Key flags:
- `--inputs`: Comma-separated list of declared input file paths.
- `--big-file-mode`: `size_mtime` (default) or `sha256`. Under `size_mtime`, files larger than `--big-file-threshold` (default `104857600` bytes / 100 MB) compute `sha256("<basename>:<bytes>:<int_mtime>")` instead of reading every byte.
- `--regex-strip`: Optional regular expression stripped from command tokens (e.g., temporary scratch directories) before computing `command_hash`.
- Unresolved paths mark `"missing"` in checksum records without interrupting execution; exit codes propagate directly from the child process (`127` when executable is missing, `126` on permission error).

### 5.2 Persistence Mechanisms

1. **Slurm Job Comment**: When `$SLURM_JOB_ID` is defined, executes `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>` (non-blocking if `scontrol` is unavailable).
2. **Sidecar JSON File**: When `$RCWA_DIR` is set, writes `$RCWA_DIR/<job_id>.json` (using `unknown.json` when `$SLURM_JOB_ID` is unset) containing `job_id`, `input_hash`, `command_hash`, and `inputs` statuses. Both `parse_sacct` (automatically when `RCWA_DIR` is set) and `merge_sidecars(df, sidecar_dir=...)` merge these digests into canonical rows.

---

## 6. Cluster and Policy YAML Configurations

### 6.1 Cluster Topology (`clusters/*.yaml`)

Supports homogeneous definitions (`clusters/example.yaml`, `tests/fixtures/clusters/homogeneous_cluster.yaml`) or multi-partition definitions (`tests/fixtures/clusters/heterogeneous_cluster.yaml`):

```yaml
# Homogeneous cluster (clusters/example.yaml)
cluster_name: "example"
node_count: 64
cores_per_node: 32
mem_mb_per_node: 131072
core_to_mem_ratio: 0.25
nodes:
  prefix: "node"
  pad_width: 3
```

```yaml
# Partitioned cluster (tests/fixtures/clusters/heterogeneous_cluster.yaml)
name: heterogeneous_cluster
partitions:
  compute:
    nodes: 32
    cores_per_node: 64
    mem_mb_per_node: 262144
  fatmem:
    nodes: 8
    cores_per_node: 64
    mem_mb_per_node: 1048576
  gpu:
    nodes: 16
    cores_per_node: 64
    mem_mb_per_node: 524288
    gpus_per_node: 4
```

When `--cluster` is omitted in CLI/Python simulation calls, `infer_cluster_from_trace` synthesizes a homogeneous cluster from peak job allocations (`16` nodes, `cores_per_node >= 32`, `mem_mb_per_node >= 131072`).

### 6.2 Attribution and Rightsizing Policy (`policies/default.yaml`)

```yaml
grouping:
  group_keys:
    - "user"
    - "command_hash_or_job_name"
  secondary_rollups:
    - "account"
    - "partition"
    - "user"
  min_samples: 5

attribution:
  retry_window_s: 86400                  # 24 hours
  recompute_window_s: 2592000            # 30 days
  early_failure_threshold_s: 60
  mem_weight_core_hours_per_gb_hour: 0.25

recommendations:
  memory:
    percentile: 0.99
    safety_factor: 1.2
    oom_multiplier: 1.5
  cpu:
    percentile: 0.99
    safety_factor: 1.2
    min_run_s: 120
  timeout:
    percentile: 0.99
    multiplier: 1.5
  recompute:
    cache_threshold_waste_share: 0.05
```
