# System Input Acquisition Guide

This guide details how to obtain, generate, and configure inputs for `research-cluster-waste-attributor` (`rcwa`).

---

## 1. Supported Input Formats

`rcwa` ingests batch accounting traces from four primary sources:

1. **Slurm Accounting Logs (`sacct`)**: Production job records exported directly from Slurm database clusters.
2. **Standard Workload Format (SWF)**: Standard supercomputer traces from the Parallel Workloads Archive.
3. **Synthetic Traces (`rcwa synth`)**: Deterministic generated traces with planted ground-truth waste categories for testing and validation.
4. **Declared Input Hashes (`rcwa-wrap`)**: Runtime checksum metadata used to detect redundant workflow executions.

---

## 2. Production Slurm Export (`sacct`)

### 2.1 The Standard Export Command

To extract accounting records from a production Slurm cluster, use the `sacct` utility with pipe-delimited output (`-P`), all-users query (`-a`), and megabyte units (`--units=M`):

```bash
sacct -a -P --units=M \
  -S 2026-01-01T00:00:00 \
  -E 2026-02-01T00:00:00 \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine \
  > cluster_trace.sacct
```

### 2.2 Mandatory Column Reference

The ingestion parser requires exactly these 26 fields in the header:

| Field Name | Type | Description |
|---|---|---|
| `JobIDRaw` | String | Raw integer job identifier without step extensions. |
| `JobID` | String | Job identifier including step suffixes (`12345`, `12345.batch`, `12345_0`). |
| `User` | String | User name of the job submitter. |
| `Account` | String | Slurm billing account or group project. |
| `Partition` | String | Slurm partition/queue name. |
| `QOS` | String | Quality of service assigned to the job. |
| `JobName` | String | User-specified job title or script name. |
| `Submit` | Timestamp | Timestamp when the job was submitted to the queue. |
| `Eligible` | Timestamp | Timestamp when the job became eligible for scheduling. |
| `Start` | Timestamp | Timestamp when execution started on compute nodes. |
| `End` | Timestamp | Timestamp when execution terminated. |
| `Elapsed` | Duration | Elapsed wallclock run time (`D-HH:MM:SS`, `HH:MM:SS`, or `MM:SS`). |
| `State` | String | Job termination state (e.g., `COMPLETED`, `FAILED`, `OUT_OF_MEMORY`). |
| `ExitCode` | String | Return code format (`return_code:signal`). |
| `ReqCPUS` | Integer | Requested CPU core count. |
| `AllocCPUS` | Integer | Allocated CPU core count. |
| `ReqMem` | String | Requested memory with unit suffix (e.g., `8000M`, `4G`, `2000Mc`). |
| `MaxRSS` | String | Maximum resident set size observed across execution steps. |
| `AveRSS` | String | Average resident set size observed across execution steps. |
| `TotalCPU` | Duration | Accumulated CPU execution time across all cores. |
| `CPUTimeRAW` | Integer | Total allocated CPU time in seconds (`AllocCPUS * Elapsed`). |
| `ReqTRES` | String | Trackable resource request strings (CPU, memory, node, GPU counts). |
| `AllocTRES` | String | Allocated trackable resource strings. |
| `NodeList` | String | List of assigned compute node hostnames. |
| `Comment` | String | Slurm job comment field containing input hashes or user notes. |
| `SubmitLine` | String | Original submission command line or script path. |

### 2.3 Step Hierarchy and Array Jobs

- **Step Rollup**: Slurm records resource limits on the parent record (`12345`), while memory (`MaxRSS`) and CPU consumption (`TotalCPU`) appear on step records (`12345.batch`, `12345.0`). The `rcwa` parser automatically aggregates child step metrics into the parent allocation record, excluding PAM/cgroup setup overhead from `.extern` steps.
- **Array Jobs**: Array tasks (e.g., `12345_0`, `12345_1`) and heterogeneous pack jobs (`12345+0`) are decomposed into independent job records while preserving `parent_job_id`.

### 2.4 Practical Export Recommendations

- **Date Chunking**: For large clusters with millions of historical jobs, run `sacct` queries in 1-month or 1-week intervals to avoid database gateway timeouts:
  ```bash
  sacct -a -P --units=M -S 2026-01-01 -E 2026-01-08 --format=... > week1.sacct
  ```
- **Partition Filtering**: Focus on specific compute partitions by adding the `-r` option:
  ```bash
  sacct -a -P --units=M -r compute,gpu -S 2026-01-01 -E 2026-02-01 --format=... > gpu_partition.sacct
  ```

---

## 3. Public Supercomputer Traces (SWF)

For testing and comparative research without a live Slurm deployment, the repository provides automated downloads for public traces from the Parallel Workloads Archive.

### 3.1 Automated Download

Execute the project download script:

```bash
make data
# Or directly via Python:
python3 scripts/download_data.py
```

This retrieves the following reference traces into `data/raw/`:
- **CEA-Curie** (`data/raw/CEA-Curie-2011-2.swf.gz`): Bullx cluster log with 93,312 compute cores across 5,544 nodes (773,138 job records).
- **SDSC-SP2** (`data/raw/SDSC-SP2-1998-4.2-cln.swf.gz`): IBM SP2 supercomputer log with 128 nodes (73,496 job records).

### 3.2 Direct SWF Ingestion

`rcwa` parses both uncompressed (`.swf`) and gzip-compressed (`.swf.gz`) trace files directly:

```bash
rcwa ingest data/raw/CEA-Curie-2011-2.swf.gz --output data/out/curie.parquet
```

---

## 4. Synthetic Trace Generation (`rcwa synth`)

When benchmarking algorithms or running unit tests with known ground truth, generate synthetic traces using `rcwa synth`.

### 4.1 CLI Command

```bash
rcwa synth \
  --size 20k \
  --seed 42 \
  --faults default \
  --output data/raw/synthetic_20k.sacct \
  --ground-truth data/raw/synthetic_truth.parquet
```

### 4.2 Makefile Shortcut

```bash
make synth SIZE=20k SEED=1
```

Supported size presets include `20k`, `100k`, and `1M`.

### 4.3 Planted Waste Classes

The synthetic generator injects calibrated amounts of each waste category:
- **Class 1 (Memory Over-Request)**: Jobs with requested memory exceeding measured peak RSS.
- **Class 2 (Idle Allocated CPU)**: Multi-threaded allocations with single-threaded execution.
- **Class 3 (Failed/Retried Work)**: Jobs marked `FAILED`, `TIMEOUT`, or `OUT_OF_MEMORY` with linked resubmissions.
- **Class 4 (Redundant Recomputation)**: Repeated jobs executing identical commands on identical declared input files.

The accompanying ground-truth Parquet file enables exact calculation of recall and precision metrics.

---

## 5. Declared Input Tracking (`rcwa-wrap`)

Class 4 waste detection attributes compute capacity spent re-executing completed workloads on unchanged data. To capture these relationships, wrap command invocations at submission time.

### 5.1 Using `rcwa-wrap` in Slurm Job Scripts

Add `rcwa-wrap` to your `sbatch` batch submission script:

```bash
#!/bin/bash
#SBATCH --job-name=data_transform
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G

# Execute workload via the wrapper
rcwa-wrap \
  --input data/source_records.parquet \
  --input configs/pipeline_config.yaml \
  --big-file-mode size_mtime \
  -- python transform.py --mode full --output data/processed.parquet
```

### 5.2 How Hashes Are Stored

`rcwa-wrap` calculates a deterministic checksum combining input files and normalized command flags, then records it via two mechanisms:
1. **Slurm Comment Update**: Executes `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>`. When `sacct` exports the `Comment` column, the hash is ingested directly.
2. **Local Sidecar File**: Writes a JSON metadata document to `$RCWA_DIR/<job_id>.json` (default: `~/.rcwa/sidecars/<job_id>.json`) for environments where `scontrol update` is restricted.

---

## 6. Configuration Inputs

`rcwa` relies on two configuration files to guide simulation and rightsizing.

### 6.1 Cluster Topology (`clusters/*.yaml`)

Specifies hardware capacities for the queue simulator:

```yaml
# clusters/example.yaml
name: "research_cluster"
nodes: 64
cpus_per_node: 32
mem_mb_per_node: 131072
default_walltime_s: 86400
backfill_policy: "easy"
```

### 6.2 Policy Configuration (`policies/*.yaml`)

Configures safety guardrails and percentile targets:

```yaml
# policies/default.yaml
grouping:
  primary_keys: ["user", "command_hash"]
  fallback_key: "job_name"
  secondary_rollups: ["account", "partition"]
  min_samples: 5

rightsizing:
  memory:
    percentile: 99
    safety_multiplier: 1.2
    floor_at_historical_max: true
    oom_escalation_multiplier: 1.5
  cpu:
    percentile: 99
    safety_multiplier: 1.2
    short_job_threshold_s: 120

recompute:
  window_hours: 168
  cache_simulation: true
```
