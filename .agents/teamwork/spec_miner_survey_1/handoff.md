# Specification Mining Report: Input Parsing, Canonical Job Record, Grouping, and Declared Inputs

**Agent**: Spec Miner 1  
**Archetype**: `teamwork_preview_spec_miner`  
**Working Directory**: `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/spec_miner_survey_1`  
**Parent Conversation ID**: `ac651b2c817627dbf13ef854add4b9ee`  
**Authoritative Sources**:
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md`
- `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md`

---

## 1. Observation

Direct observations and citations from authoritative specification files:

### 1.1 Repository Layout and Dependencies (SPEC.md §4, §11)
- **Files Assigned to Feature Area 1**:
  - `rcwa/model.py`: Canonical job record (Arrow schema + Pydantic v2 model).
  - `rcwa/adapters/sacct.py`: Slurm `sacct` export parser (pipe-delimited).
  - `rcwa/adapters/swf.py`: Standard Workload Format (SWF) parser.
  - `rcwa/normalize.py`: Unit, time, state, array-job and step roll-up.
  - `rcwa/groups.py`: Job grouping (user, account, partition, command hash).
  - `rcwa/wrap.py`: `rcwa-wrap` console script; records declared input hashes for a job.
  - `policies/default.yaml`: Configurable grouping policies, sample thresholds.
- **Allowed Dependencies** (SPEC.md line 218):
  - Runtime: `polars`, `pyarrow`, `numpy`, `pydantic>=2`, `typer`, `pyyaml`.
  - Development: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `pyright`.
  - Strict rule: "Do not add a dependency outside section 11 without stopping to ask. Pin exact versions."
- **Console Scripts** (SPEC.md lines 48-52):
  - `rcwa`: main CLI typer app.
  - `rcwa-wrap`: wrapper CLI for recording declared inputs.
- **Banned Words** (SPEC.md line 247):
  - Do not use: `"simply"`, `"robust"`, `"seamless"`, `"best"`, `"optimal"`, `"clean"`, `"minimal"`, `"powerful"`, or `"cutting-edge"`.

### 1.2 Slurm `sacct` Export Format & Parsing (SPEC.md §5.1)
- **Export Command Line** (lines 92-95):
  ```bash
  sacct -a -P --units=M -S <start> -E <end> \
    --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
  ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine
  ```
- **Delimiting & Headers** (line 99):
  - Pipe-delimited (`|`) with a mandatory header row.
  - Fields may be empty strings (`""`).
  - Unknown extra columns are ignored with a warning.
- **Job Steps & Rollups** (line 100):
  - Step rows (`12345.batch`, `12345.0`, `12345.extern`, etc.) carry `MaxRSS`, `AveRSS`, and `TotalCPU`.
  - Parent row (`12345`) carries the resource allocation (`ReqCPUS`, `AllocCPUS`, `ReqMem`, `NodeList`, etc.).
  - Rollup formulas:
    - `max_rss_mb = max over steps`
    - `cpu_time_used_s = sum of TotalCPU over steps excluding .extern`
- **Array Jobs & Heterogeneous Jobs** (line 101):
  - Array jobs format: `12345_7`. Heterogeneous job components: `12345+0`, `12345+1`.
  - "treat each as a job; record `parent_job_id`".
  - Steps roll up to their respective sub-job (`12345_7.batch` rolls up to `12345_7`).
- **Time String Formats** (line 102):
  - `Elapsed` and `TotalCPU` forms: `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`.
  - Also fractional seconds in hours/days (e.g. `D-HH:MM:SS.mmm`, `HH:MM:SS.mmm`).
- **Memory String Suffixes** (line 103):
  - `ReqMem` forms:
    - `4000M`: 4000 MB total.
    - `4000Mc`: 4000 MB per CPU (multiply by `alloc_cpus`).
    - `4000Mn`: 4000 MB per node (multiply by `nodes`).
    - `?`: unknown / missing (maps to null).
    - With `--units=M`, numeric values are in MB. Handle `G` and `K` suffixes too (`G`/`Gc`/`Gn` multiplied by 1024; `K`/`Kc`/`Kn` divided by 1024).
- **State Qualifiers & Mapping** (line 104):
  - `State` strings include qualifiers (e.g. `CANCELLED by 1234`, `CANCELLED by 0`).
  - Must strip qualifiers and map to canonical enum: `{COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER}`.
  - `OUT_OF_MEMORY` is its own distinct canonical state.
- **TRES Parsing** (line 105):
  - `ReqTRES` and `AllocTRES` format: `cpu=8,mem=32000M,node=1,billing=8,gres/gpu=2`.
  - Parse GPU counts (`req_gpus`, `alloc_gpus`).
- **Comment Field** (line 106):
  - May hold `RCWA_INPUT_HASH=<hex>` written by `rcwa-wrap`.

### 1.3 Standard Workload Format (SWF) (SPEC.md §5.2)
- **18 Whitespace-Separated Fields** (line 110):
  1. Job Number (`job_id`)
  2. Submit Time (seconds offset)
  3. Wait Time (`wait_s`)
  4. Run Time (`run_s`)
  5. Allocated Processors (`alloc_cpus`)
  6. Average CPU Time Used (seconds per processor; total CPU time = `field 6 * alloc_cpus`)
  7. Used Memory (KB per processor; total MB = `used_mem_kb * alloc_cpus / 1024`)
  8. Requested Processors (`req_cpus`; if -1, defaults to `alloc_cpus`)
  9. Requested Time (seconds; used by simulator backfill)
  10. Requested Memory (KB per processor; total MB = `req_mem_kb * alloc_cpus / 1024`)
  11. Status (1 = `COMPLETED`, 0 = `FAILED`, 5 = `CANCELLED`, others as documented in header)
  12. User ID (`user`)
  13. Group ID (`account`)
  14. Executable Number (`command_hash`)
  15. Queue Number (`partition`)
  16. Partition Number
  17. Preceding Job Number (`parent_job_id` if != -1 and > 0)
  18. Think Time
- **Header Pragmas** (line 110):
  - Lines starting with `;`.
  - Must honor `; UnixStartTime`, `; MaxProcs`, `; MaxNodes`, and `; Note`.
  - Record these header pragmas in `docs/DATA.md` output for each trace.
- **Missing Values**:
  - Missing numeric values are `-1`. Map to `None` / null.
- **Recomputation Policy for SWF**:
  - "SWF has no declared inputs, so recomputation attribution is reported as 'not available' for SWF traces, never estimated."

### 1.4 Canonical Job Record (SPEC.md §5.3)
- **Exact Schema Fields and Types** (lines 114-128):
  ```
  job_id: string                 parent_job_id: string | null       source: string (sacct | swf | k8s | ray)
  user: string                   account: string | null             partition: string | null
  job_name: string | null        command_hash: string | null        input_hash: string | null
  submit_time: timestamp[s,UTC]  start_time: timestamp[s,UTC] | null  end_time: timestamp[s,UTC] | null
  wait_s: int64                  run_s: int64
  state: enum {COMPLETED, FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, CANCELLED, PREEMPTED, RUNNING, PENDING, OTHER}
  exit_code: int32 | null
  req_cpus: int32                alloc_cpus: int32                  cpu_time_used_s: float64 | null
  req_mem_mb: int64 | null       max_rss_mb: int64 | null
  req_gpus: int32                alloc_gpus: int32
  nodes: int32                   node_list: string | null
  reserved_core_s: int64 = alloc_cpus * run_s
  reserved_mem_mb_s: int64 = req_mem_mb * run_s
  ```
- **Exclusion & Zero-Run Rules** (line 130):
  - Rows with `state in {RUNNING, PENDING}` are excluded from attribution and counted in the report's data-quality section.
  - Rows with `run_s = 0` are kept (early failures) and attributed to class 3 with zero consumption.

### 1.5 Grouping (SPEC.md §5.4)
- **Default Group Key** (line 134): `(user, command_hash or job_name)`:
  - If `command_hash` is non-null and non-empty, use `command_hash`; otherwise coalesce to `job_name`.
- **Configurable Policy** (line 134): configurable in policy file (`policies/default.yaml`).
- **Secondary Rollups** (line 134): rollups by `account`, `partition`, and `user`.
- **Sample Guardrail** (line 134, §7 line 170):
  - `min_samples` default = 5.
  - Groups below `min_samples` receive NO recommendation.

### 1.6 Declared Inputs: `rcwa-wrap` (SPEC.md §5.5)
- **CLI Invocation** (line 141):
  ```bash
  rcwa-wrap --inputs data/a.parquet,config.yaml --big-file-mode size_mtime -- python train.py --lr 0.01
  ```
- **Hashing**:
  - Default: SHA-256 of contents for each declared input.
  - `--big-file-mode size_mtime`: for files over configurable threshold, hash `(size, mtime)`.
  - Combine declared input hashes with normalized command line into `input_hash`.
- **Command Line Normalization**:
  - Strip absolute path prefixes (configurable by regex).
  - Sort `--flag=value` and `--flag value` pairs.
- **Recording Mechanism**:
  - When `$SLURM_JOB_ID` is present: `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>`.
  - Sidecar file: `$RCWA_DIR/<job_id>.json`.
  - Adapter reads either Comment or sidecar file.
- **Failure Tolerances**:
  - Missing declared input file: record `missing` and continue; NEVER block or fail the user's job.
  - Exit code: wrapper executes the command and exits with the target command's exact exit code.

---

## 2. Logic Chain

The step-by-step reasoning linking observations to the specification blueprint:

1. **Ingest Decoupling & Normalization Pipeline**:
   - Both Slurm `sacct` exports and SWF traces originate from different systems with distinct semantics (pipe-delimited with step hierarchy vs 18-column space-delimited flat file).
   - Ingest must follow a two-tier architecture:
     1. Raw parser tier (`rcwa/adapters/sacct.py` and `rcwa/adapters/swf.py`) reading raw text/streams.
     2. Normalization tier (`rcwa/normalize.py`) converting heterogeneous units (KB/MB/GB, timestamps, elapsed strings) into canonical types.
   - Result: both adapters yield identical PyArrow tables conforming to the canonical schema defined in `rcwa/model.py`.

2. **Slurm Step Hierarchy & Rollup Strategy**:
   - Observation: Slurm exports separate rows for batch script step (`.batch`), tasks (`.0`, `.1`), and Slurm epilog/PAM step (`.extern`).
   - Logic: Parent rows contain resource reservation (`AllocCPUS`, `ReqMem`, `NodeList`), but their RSS and CPU columns are often blank or partial. Task steps carry `MaxRSS` and `TotalCPU`.
   - Formula derivation:
     - `max_rss_mb = max(step.MaxRSS for step in job_steps)`
     - `cpu_time_used_s = sum(step.TotalCPU for step in job_steps if not step_id.endswith('.extern'))`
     - `.extern` step is intentionally omitted from CPU time to prevent daemon/PAM background tasks from corrupting user CPU measurement, but if `.extern` records memory, it can be considered in maximum resident set size.
   - Single-row jobs (e.g. interactive jobs or failed before step launch) fall back directly to parent metrics if steps do not exist.

3. **Array and Heterogeneous Job Deconstruction**:
   - Observation: Array jobs appear as `12345_1`, `12345_2`; heterogeneous jobs as `12345+0`, `12345+1`.
   - Logic: In cluster scheduling and attribution, each task of an array or pack component runs independently, consumes discrete node resources, and can succeed or fail separately.
   - Rule: Treat each task (`12345_1`) and component (`12345+0`) as an individual canonical job record with `job_id = "12345_1"` and `parent_job_id = "12345"`. Steps of task 1 (`12345_1.batch`, `12345_1.0`) roll up solely to `12345_1`.

4. **Slurm Memory Suffix Multiplication**:
   - Observation: `ReqMem` values include `4000M`, `4000Mc`, `4000Mn`, `2G`, `2Gc`, `2Gn`, `500000K`, `?`.
   - Logic:
     - `M` indicates megabytes. In Slurm, binary units are used (1K = 1024, 1M = 1048576, 1G = 1024M).
     - `c` modifier is per-CPU (`--mem-per-cpu`). Must multiply base MB by `alloc_cpus`.
     - `n` modifier is per-node (`--mem`). Must multiply base MB by `nodes`.
     - No suffix or bare `M` is total memory per job.
     - `G` requires multiplying base value by 1024 before applying `c`/`n` modifiers.
     - `K` requires dividing base value by 1024 (rounding up with `ceil`) before applying `c`/`n` modifiers.
     - `?` or unparsable indicates unknown memory request, resulting in `req_mem_mb = None`.

5. **SWF Conversion Semantics**:
   - Observation: Field 7 (`Used Memory`) and Field 10 (`Requested Memory`) are in KB per allocated processor. Field 5 is `Allocated Processors`. Field 6 is `Average CPU Time Used` in seconds per processor.
   - Logic:
     - Total used memory in MB: `int(round((used_mem_kb * alloc_cpus) / 1024))`.
     - Total requested memory in MB: `int(round((req_mem_kb * alloc_cpus) / 1024))`.
     - Total CPU time used in seconds: `avg_cpu_time_s * alloc_cpus`.
     - Missing indicator `-1` maps to `None` for optional metrics (`req_mem_mb`, `max_rss_mb`, `cpu_time_used_s`).
     - If `Requested Processors` (field 8) is `-1`, fall back to `Allocated Processors` (field 5).
     - Field 14 (`Executable Number`) is integer-encoded; cast to string for `command_hash`.
     - Base submit timestamp: parse header `; UnixStartTime: <epoch>`. `submit_time = UnixStartTime + submit_time_offset`. If header is absent, default base is Unix epoch 0 (1970-01-01T00:00:00Z).
     - Because SWF provides no declared inputs or file reads, `input_hash` is always `None`, and recomputation attribution is hardcoded to "not available".

6. **Canonical Invariants and Guarantees**:
   - `reserved_core_s` = `alloc_cpus * run_s` (strictly integer `int64`).
   - `reserved_mem_mb_s` = `req_mem_mb * run_s` (if `req_mem_mb` is null, `reserved_mem_mb_s` is null or handled as 0 in attribution with `unattributed_missing_rss`).
   - Active jobs (`state in {RUNNING, PENDING}`) have undefined or non-final wallclock runtimes; they MUST be excluded from the attribution dataset and tallied in data-quality accounting.
   - Zero-runtime jobs (`run_s = 0`) represent immediate submission rejects or boot failures; they are retained in the canonical record, mapped to Class 3, and contribute 0 core-seconds and 0 MB-seconds.

7. **Grouping and Guardrails**:
   - Default grouping key combines `user` with `command_hash` (or `job_name` if hash is absent). This isolates specific workloads run by a specific user.
   - Guardrail `min_samples` (default 5): Statistical rightsizing (p99) on fewer than 5 samples has excessive variance and risks aggressive under-allocation. Setting recommendations to empty for small groups protects user jobs (Guarantee G2).

8. **`rcwa-wrap` Wrapper Design and Fault-Tolerance**:
   - Wrapper must act as a transparent decorator around any user command.
   - Normalization must eliminate spurious variances: path prefixes (`/opt/python/bin/python` vs `python`) and flag order (`--lr 0.01 --epochs 10` vs `--epochs 10 --lr 0.01`).
   - For missing declared inputs, crashing or halting the wrapper would break research workflows. The wrapper must record `"missing"` in the manifest, compute the input hash deterministically reflecting the missing file, and continue process execution.
   - When running under Slurm, `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>` embeds the hash directly into scheduler accounting. In non-Slurm or restricted environments, writing to `$RCWA_DIR/<job_id>.json` guarantees that the adapter can recover declared input hashes.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | sacct Adapter | CLI Parsing & Column Mapping | Ingest pipe-delimited sacct export with 26 mandatory columns | File path or pipe stream | Ingested raw table | Raise `ValueError` if header missing or mandatory column omitted | SPEC.md §5.1 lines 89-99 |
| 2 | sacct Adapter | Unknown Column Warning | Tolerate extra unmapped columns in sacct export | Pipe-delimited string with extra headers | Table with known columns retained; warning logged | Emit warning; do not fail parse | SPEC.md §5.1 line 99 |
| 3 | sacct Adapter | Empty Field Handling | Handle empty strings (`\|\|`) between pipe delimiters | Empty field string | `None` / Null in Arrow record | No error; gracefully casts to nullable type | SPEC.md §5.1 line 99 |
| 4 | sacct Adapter | Step Row Identification | Distinguish job steps (`.batch`, `.0`, `.extern`) from parent job records | `JobID` string | Boolean step flag, step type, base job ID | Fallback to treating as parent if pattern unmatched | SPEC.md §5.1 line 100 |
| 5 | sacct Adapter | Step RSS Rollup | Aggregate `MaxRSS` across all steps of a job using maximum | List of step `MaxRSS` values | `max_rss_mb: int64 \| null` | If all step RSS are empty/null, return `None` | SPEC.md §5.1 line 100 |
| 6 | sacct Adapter | Step CPU Rollup | Sum `TotalCPU` across steps, strictly excluding `.extern` | List of step `TotalCPU` and `JobID` values | `cpu_time_used_s: float64 \| null` | If no valid steps, return `None` | SPEC.md §5.1 line 100 |
| 7 | sacct Adapter | Array Job Decomposition | Parse array job tasks (`12345_7`) as individual jobs with parent pointer | Array `JobID` | `job_id="12345_7"`, `parent_job_id="12345"` | None; regex parses array index | SPEC.md §5.1 line 101 |
| 8 | sacct Adapter | Heterogeneous Pack Decomposition | Parse heterogeneous components (`12345+0`, `12345+1`) as individual jobs | Pack `JobID` | `job_id="12345+0"`, `parent_job_id="12345"` | None; regex parses pack index | SPEC.md §5.1 line 101 |
| 9 | sacct Adapter | Elapsed Wall-Clock Parsing | Convert `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm` into integer seconds | Elapsed string | `run_s: int64` | If invalid, return 0 or raise parse error | SPEC.md §5.1 line 102 |
| 10 | sacct Adapter | TotalCPU Duration Parsing | Convert step `TotalCPU` time strings into float seconds | Duration string | Float seconds | If invalid, return `None` | SPEC.md §5.1 line 102 |
| 11 | sacct Adapter | UTC Timestamp Normalization | Parse `Submit`, `Start`, `End` timestamps to UTC POSIX/datetime | ISO / Slurm datetime string | `timestamp[s, UTC]` or `None` | Unparseable / `Unknown` maps to `None` | SPEC.md §5.1 line 94, §5.3 |
| 12 | sacct Adapter | Wait Time Calculation | Compute queue wait seconds from start and submit times | `start_time`, `submit_time` | `wait_s: int64 = max(0, start - submit)` | If start is null, default `wait_s = 0` | SPEC.md §5.3 line 119 |
| 13 | sacct Adapter | Memory Suffix: Raw Megabytes | Parse `4000M` as direct job megabytes | `ReqMem` string ending in `M` | `req_mem_mb = 4000` | Fallback to `None` if unparseable | SPEC.md §5.1 line 103 |
| 14 | sacct Adapter | Memory Suffix: Per-CPU (`Mc`) | Multiply base MB by `alloc_cpus` for per-CPU allocations | `4000Mc`, `alloc_cpus=4` | `req_mem_mb = 16000` | Fallback to `None` if `alloc_cpus` missing | SPEC.md §5.1 line 103 |
| 15 | sacct Adapter | Memory Suffix: Per-Node (`Mn`) | Multiply base MB by node count for per-node allocations | `4000Mn`, `nodes=2` | `req_mem_mb = 8000` | Fallback to `None` if `nodes` missing | SPEC.md §5.1 line 103 |
| 16 | sacct Adapter | Memory Suffix: Gigabytes (`G`, `Gc`, `Gn`) | Multiply gigabytes by 1024 before applying per-CPU/node scaling | `4G`, `2Gc`, `1Gn` | Converted integer MB | Fallback to `None` if unparseable | SPEC.md §5.1 line 103 |
| 17 | sacct Adapter | Memory Suffix: Kilobytes (`K`, `Kc`, `Kn`) | Divide kilobytes by 1024 with ceiling rounding | `500000K` | Converted integer MB | Fallback to `None` if unparseable | SPEC.md §5.1 line 103 |
| 18 | sacct Adapter | Unknown Memory (`?`) | Translate `?` or missing `ReqMem` to null | `?`, `Unknown`, `""` | `req_mem_mb = None` | Sets field to null without crashing | SPEC.md §5.1 line 103 |
| 19 | sacct Adapter | State Qualifier Stripping | Map qualified states (`CANCELLED by 1234`) to canonical enum | Raw State string | Canonical state enum string | Unrecognized strings map to `OTHER` | SPEC.md §5.1 line 104 |
| 20 | sacct Adapter | OOM State Mapping | Isolate `OUT_OF_MEMORY` as dedicated canonical state | `OUT_OF_MEMORY` | `state = "OUT_OF_MEMORY"` | None | SPEC.md §5.1 line 104 |
| 21 | sacct Adapter | ExitCode Decomposition | Parse Slurm `return_code:signal` formatted string | ExitCode string (e.g. `0:0`, `1:0`) | `exit_code: int32 \| null` | Return `None` if empty or invalid | SPEC.md §5.1 line 93, §5.3 |
| 22 | sacct Adapter | TRES GPU Extraction | Extract GPU counts from `ReqTRES` and `AllocTRES` | TRES string | `req_gpus: int32`, `alloc_gpus: int32` | If absent, default to 0 | SPEC.md §5.1 line 105 |
| 23 | sacct Adapter | TRES / NodeList Node Count | Extract node count from TRES `node=N` or count `NodeList` | TRES string, NodeList string | `nodes: int32` (minimum 1) | Default to 1 if unparseable | SPEC.md §5.1 line 105, §5.3 |
| 24 | sacct Adapter | Comment Input Hash Extraction | Extract `RCWA_INPUT_HASH=<hex>` from `Comment` column | Comment string | `input_hash: string \| null` | If absent, return `None` | SPEC.md §5.1 line 106 |
| 25 | sacct Adapter | SubmitLine Preservation | Capture raw submit command line for fallback hashing | SubmitLine string | Stored string for `command_hash` fallback | Stored as `None` if empty | SPEC.md §5.1 line 94 |
| 26 | SWF Adapter | 18-Field Record Ingestion | Ingest whitespace-separated SWF records | SWF lines | Raw record tuples | Raise parse error if fields < 18 | SPEC.md §5.2 line 110 |
| 27 | SWF Adapter | Header Pragma Extraction | Parse `; UnixStartTime`, `; MaxProcs`, `; MaxNodes`, `; Note` | SWF header lines | Header metadata dict | Missing pragmas set to default/None | SPEC.md §5.2 line 110 |
| 28 | SWF Adapter | Metadata Documentation Export | Export parsed SWF pragmas and usage conditions to docs | Header dict | Formatted `docs/DATA.md` block | Fail audit if `DATA.md` omitted | SPEC.md §5.2, §10, §16 |
| 29 | SWF Adapter | SWF Missing Value Sentinel | Translate `-1` values across all SWF fields into nulls | Integer `-1` | `None` / Null | Field-specific null handling | SPEC.md §5.2 line 110 |
| 30 | SWF Adapter | SWF Memory Scaling | Scale memory in KB/proc by allocated processors to total MB | `used_mem_kb`, `alloc_cpus` | `max_rss_mb = round(KB * procs / 1024)` | Return `None` if KB == -1 | SPEC.md §5.2 line 110 |
| 31 | SWF Adapter | SWF Requested Memory Scaling | Scale requested memory in KB/proc to total MB | `req_mem_kb`, `alloc_cpus` | `req_mem_mb = round(KB * procs / 1024)` | Return `None` if KB == -1 | SPEC.md §5.2 line 110 |
| 32 | SWF Adapter | SWF CPU Time Scaling | Multiply average CPU time per processor by allocated CPUs | `avg_cpu_time_s`, `alloc_cpus` | `cpu_time_used_s = avg_s * alloc_cpus` | Return `None` if avg_s == -1 | SPEC.md §5.2 line 110 |
| 33 | SWF Adapter | SWF Requested Processors Fallback | Fallback requested CPUs to allocated CPUs when req is `-1` | `req_procs = -1`, `alloc_procs` | `req_cpus = alloc_cpus` | Preserves valid CPU count | SPEC.md §5.2 line 110 |
| 34 | SWF Adapter | SWF Status Code Mapping | Map SWF status codes (1: COMPLETED, 0: FAILED, 5: CANCELLED) | Status integer | Canonical state enum string | Unmapped codes map to `OTHER` | SPEC.md §5.2 line 110 |
| 35 | SWF Adapter | SWF Command Hash Mapping | Assign executable number directly to `command_hash` | Executable number integer | Stringified integer `command_hash` | If -1, `command_hash = None` | SPEC.md §5.2 line 110 |
| 36 | SWF Adapter | SWF Recompute Inactivation | Mark recompute attribution as "not available" for all SWF | SWF dataset flag | Recompute disabled, 0 recompute waste | Never estimate recompute on SWF | SPEC.md §5.2 line 110 |
| 37 | Canonical Record | Arrow Schema Definition | Formal PyArrow schema specification with 26 typed fields | Schema declaration | `pyarrow.Schema` object | Validation error on type mismatch | SPEC.md §5.3 lines 115-128 |
| 38 | Canonical Record | Pydantic Model Validation | Strict Pydantic v2 model validating job attributes | Record dictionary | `CanonicalJobRecord` instance | Validation error on invalid enum/type | SPEC.md §5.3 lines 115-128 |
| 39 | Canonical Record | Reserved Core Seconds Calculation | Calculate `reserved_core_s = alloc_cpus * run_s` | `alloc_cpus: int32`, `run_s: int64` | `reserved_core_s: int64` | Raise error if inputs negative | SPEC.md §5.3 line 126 |
| 40 | Canonical Record | Reserved Memory Seconds Calculation | Calculate `reserved_mem_mb_s = req_mem_mb * run_s` | `req_mem_mb: int64`, `run_s: int64` | `reserved_mem_mb_s: int64 \| null` | If `req_mem_mb` is null, set to null | SPEC.md §5.3 line 127 |
| 41 | Canonical Record | Active Job Exclusion | Exclude `RUNNING` and `PENDING` jobs from attribution | Canonical job records | Filtered table for attribution | Unfiltered count logged in data-quality | SPEC.md §5.3 line 130 |
| 42 | Canonical Record | Zero-Runtime Job Retention | Retain `run_s = 0` jobs and assign to Class 3 with 0 cost | Job with `run_s = 0` | Job retained; 0 core-s, 0 mem-mb-s | Do not drop or crash | SPEC.md §5.3 line 130 |
| 43 | Grouping | Default Group Key Formulation | Group jobs by `(user, coalesce(command_hash, job_name))` | Canonical job table | Group identifier column | Fallback to "unknown" if both missing | SPEC.md §5.4 line 134 |
| 44 | Grouping | Configurable Policy Grouping | Allow custom grouping field tuples via YAML policy | `policies/default.yaml` | Dynamically grouped partitions | Fallback to default on invalid config | SPEC.md §5.4 line 134 |
| 45 | Grouping | Secondary Rollup Aggregations | Generate secondary aggregations by `account`, `partition`, `user` | Attribution output table | Summary rollup tables | Handle null account/partition gracefully | SPEC.md §5.4 line 134, §6.2 |
| 46 | Grouping | Minimum Sample Guardrail | Suppress recommendations for groups with `< min_samples` (5) | Group sample count | Empty recommendation with flag | Guarantee G2 safety compliance | SPEC.md §5.4 line 134, §7 |
| 47 | `rcwa-wrap` | CLI Wrapper Command | Accept input paths, hashing mode, and command after `--` | CLI options + target command | Executed process | Pass through child exit code | SPEC.md §5.5 lines 138-144 |
| 48 | `rcwa-wrap` | Standard File Content Hashing | Hash declared input file contents using SHA-256 in chunks | Input file path | SHA-256 hex digest string | Gracefully handle IO errors | SPEC.md §5.5 line 144 |
| 49 | `rcwa-wrap` | Big-File Mode (`size_mtime`) | Hash `(size, mtime)` for files exceeding threshold | File path, size threshold | SHA-256 digest of size + mtime | Fallback to content hash if mtime fails | SPEC.md §5.5 line 144 |
| 50 | `rcwa-wrap` | Missing Input File Tolerance | Mark missing files as `"missing"` and proceed with execution | Non-existent input path | `"missing"` hash token recorded | Never block or crash the user command | SPEC.md §5.5 line 144 |
| 51 | `rcwa-wrap` | Command Path Normalization | Strip absolute path prefixes from command binary and scripts | Raw command line string | Stripped command line string | Regex configurable via policy | SPEC.md §5.5 line 144 |
| 52 | `rcwa-wrap` | Command Flag Lexicographical Sorting | Sort `--flag=value` and `--flag val` pairs alphabetically | Unsorted command arguments | Canonical sorted argument string | Preserve non-flag argument order | SPEC.md §5.5 line 144 |
| 53 | `rcwa-wrap` | Combined Input Hash Computation | SHA-256 combine sorted input hashes and normalized command | Input hash list + command | 64-character hex string `input_hash` | Deterministic byte output | SPEC.md §5.5 line 144 |
| 54 | `rcwa-wrap` | Slurm Comment Injection | Update Slurm job comment via `scontrol update` | `$SLURM_JOB_ID`, `input_hash` | Updated Slurm accounting record | Warn and continue if scontrol fails | SPEC.md §5.5 line 144 |
| 55 | `rcwa-wrap` | Sidecar JSON Persistence | Write job execution manifest to `$RCWA_DIR/<job_id>.json` | Job metadata, hashes, command | Valid JSON file on disk | Warn and continue if write fails | SPEC.md §5.5 line 144 |
| 56 | `rcwa-wrap` | Sidecar Ingest Fallback | Slurm adapter checks sidecar JSON if Comment is absent | `job_id`, `$RCWA_DIR` | Ingested `input_hash` | Fallback to null if sidecar missing | SPEC.md §5.5 line 144 |

---

## 4. Edge Cases

| # | Feature | Input | Observed / Required Behavior |
|---|---------|-------|------------------------------|
| 1 | sacct Adapter | Consecutive pipes `||` in sacct line | Field parses as `None` or empty string without index shifting or splitting misalignment. |
| 2 | sacct Adapter | Unknown column header (e.g. `CustomBilling|JobID|...`) | Parser issues a warning, strips unrecognized columns, and proceeds without error. |
| 3 | sacct Adapter | Job step `12345.extern` has `TotalCPU = 00:05:00` | Excluded from `cpu_time_used_s` sum; only `.batch`, `.0`, etc. are included. |
| 4 | sacct Adapter | Job step `12345.extern` has `MaxRSS = 500M`, steps have `300M` | `max_rss_mb` evaluates to `500` (max over all steps). |
| 5 | sacct Adapter | Job with no steps (e.g. canceled before start, or single row) | Falls back to parent row's `MaxRSS` and `TotalCPU`; if both empty, returns `None`. |
| 6 | sacct Adapter | Sub-minute elapsed time formatted as `00:15.345` | Parses fractional seconds; `run_s` rounds to `15` integer seconds. |
| 7 | sacct Adapter | Multi-day elapsed time formatted as `3-12:30:15` | Parses correctly to `3*86400 + 12*3600 + 30*60 + 15 = 304215` integer seconds. |
| 8 | sacct Adapter | `ReqMem = 2000Mc` with `AllocCPUS = 8` | Per-CPU memory request scaled to total: `2000 * 8 = 16000` MB. |
| 9 | sacct Adapter | `ReqMem = 16000Mn` with `NodeList = node[01-04]` (4 nodes) | Per-node memory request scaled to total: `16000 * 4 = 64000` MB. |
| 10 | sacct Adapter | `ReqMem = 4G` or `4Gc` | Gigabyte suffix converted: `4 * 1024 = 4096` MB total, or `4096 * alloc_cpus`. |
| 11 | sacct Adapter | `ReqMem = 500000K` | Kilobyte suffix converted with ceil: `ceil(500000 / 1024) = 489` MB. |
| 12 | sacct Adapter | `ReqMem = ?` or `Unknown` | Mapped to `req_mem_mb = None`; `reserved_mem_mb_s = None`. |
| 13 | sacct Adapter | `State = CANCELLED by 10001` or `CANCELLED by 0` | Strips qualifier suffix; canonical state becomes `CANCELLED`. |
| 14 | sacct Adapter | `State = OUT_OF_MEMORY` or `OUT_OF_MEMORY+` | Canonical state mapped specifically to `OUT_OF_MEMORY` (triggers OOM increase guardrail). |
| 15 | sacct Adapter | `State = BOOT_FAIL` or `REVOKED` or `SUSPENDED` | `BOOT_FAIL` maps to `NODE_FAIL`; unrecognized states map to `OTHER`. |
| 16 | sacct Adapter | `ExitCode = 0:15` (return code 0, killed by SIGTERM 15) | Parse `exit_code: int32` as `0` or signal-aware code; non-null integer. |
| 17 | sacct Adapter | `AllocTRES = cpu=32,mem=128G,node=2,billing=32,gres/gpu:a100=4` | Extracts `alloc_gpus = 4`, `nodes = 2`. |
| 18 | sacct Adapter | `AllocTRES = cpu=4,mem=16G,node=1` (no GPU token) | Defaults `alloc_gpus = 0`, `req_gpus = 0`. |
| 19 | sacct Adapter | `Comment = RCWA_INPUT_HASH=a1b2c3d4e5f6071829...` | Regex extracts 64-char hex string as `input_hash`. |
| 20 | sacct Adapter | Array job task with steps `12345_1.batch` | Rolled up into task `12345_1`; task recorded with `parent_job_id = "12345"`. |
| 21 | SWF Adapter | SWF line with `-1` for `Requested Memory` | Field maps to `req_mem_mb = None`. |
| 22 | SWF Adapter | SWF line with `-1` for `Average CPU Time Used` | Field maps to `cpu_time_used_s = None`. |
| 23 | SWF Adapter | SWF line with `-1` for `Requested Processors` | `req_cpus` falls back to `Allocated Processors` (field 5). |
| 24 | SWF Adapter | SWF trace header missing `; UnixStartTime` pragma | Falls back to base Unix epoch (1970-01-01T00:00:00Z) and logs warning. |
| 25 | SWF Adapter | SWF trace with status code `0` | Maps to `FAILED`. Status code `1` maps to `COMPLETED`. Status code `5` maps to `CANCELLED`. |
| 26 | SWF Adapter | Recomputation requested for SWF trace | Explicitly emits "not available"; no recomputation waste is estimated or assigned. |
| 27 | Canonical Record | Job with `state = RUNNING` or `state = PENDING` | Excluded from waste attribution; incremented in data-quality section report. |
| 28 | Canonical Record | Job with `run_s = 0` (immediate failure) | Retained in dataset; attributed to Class 3; produces `0` core-s and `0` mem-mb-s. |
| 29 | Canonical Record | `req_mem_mb = None` on a completed job | `reserved_mem_mb_s = None`; memory reservation treated as unattributed missing RSS. |
| 30 | Grouping | Job with `command_hash = None` and `job_name = "train"` | Group key evaluates to `(user, "train")`. |
| 31 | Grouping | Job with `command_hash = "abc"` and `job_name = "train"` | Group key evaluates to `(user, "abc")` (command hash takes precedence). |
| 32 | Grouping | Group contains only 4 completed jobs (`min_samples = 5`) | Recommendation is suppressed (empty); marked safe from under-allocation. |
| 33 | `rcwa-wrap` | Input file declared in `--inputs` does not exist on disk | Hash recorded as `"missing"`; wrapper DOES NOT crash; command executes normally. |
| 34 | `rcwa-wrap` | File size > threshold with `--big-file-mode size_mtime` | Skips full file read; hashes string of file size and nanosecond mtime. |
| 35 | `rcwa-wrap` | Command has arguments in different order: `--lr 0.01 --b 32` vs `--b 32 --lr 0.01` | Flag sorting produces identical normalized command string and matching `input_hash`. |
| 36 | `rcwa-wrap` | Command has absolute path: `/usr/local/bin/python script.py` | Path stripping normalizes command to `python script.py`. |
| 37 | `rcwa-wrap` | `scontrol` command fails (e.g. non-Slurm node or permission denied) | Warning emitted; falls back to writing `$RCWA_DIR/<job_id>.json`; user job continues. |
| 38 | `rcwa-wrap` | Target command exits with non-zero exit code `42` | Wrapper process terminates with exit code `42`. |
| 39 | `rcwa-wrap` | Target command terminated by `SIGINT` | Wrapper catches signal, flushes sidecar, and exits with matching signal code (130). |
| 40 | `rcwa-wrap` | No inputs declared (`--inputs ""` or flag omitted) | Wrapper hashes only the normalized command string. |

---

## 5. Caveats

1. **Slurm Version Divergence in Step Accounting**:
   - In older Slurm versions (<20.02), parent rows sometimes contained partial `MaxRSS` or cumulative CPU times. The specification explicitly dictates that step rows take precedence: `max_rss_mb` must be the maximum over all step rows, and `cpu_time_used_s` must be the sum over step rows excluding `.extern`. Only when no step rows exist should the parent row values be inspected.
2. **SWF Field 6 Semantics (Average CPU Time)**:
   - Feitelson's Standard Workload Format defines Field 6 as "Average CPU time used -- this is the average user + system CPU time used by the job, in seconds, per processor." When scaling to cluster-wide core-seconds, multiplying `field 6 * alloc_cpus` produces total consumed core-seconds, directly comparable to `reserved_core_s = alloc_cpus * run_s`.
3. **Signal Exit Codes in Slurm**:
   - Slurm `ExitCode` field contains `return_code:signal` (e.g., `0:9` indicates killed by SIGKILL, `0:15` killed by SIGTERM, `1:0` exited with 1). The canonical record specifies `exit_code: int32 | null`. If `return_code == 0` and `signal > 0`, the convention is to store `128 + signal` (POSIX standard) or record `return_code`. Storing `128 + signal` preserves the fatal signal information in a standard 32-bit integer exit code.
4. **Binary vs Decimal Prefixes**:
   - In Slurm memory configuration, `1M = 1048576 bytes` and `1G = 1024M`. The multiplier logic uses power-of-two (1024) conversions.
5. **No External Network or Proprietary Extensions**:
   - Tests and adapters must never invoke external network APIs. CI and tests run exclusively on local fixtures.

---

## 6. Conclusion

The requirements for Feature Area 1 are fully specified and checkable by automated tests:
1. **Slurm `sacct` Parser**: Can be implemented in `rcwa/adapters/sacct.py` and `rcwa/normalize.py` using Polars/Python standard string processing, respecting 26 mandatory columns, step rollups excluding `.extern`, array/heterogeneous job deconstruction, and memory unit multiplication.
2. **SWF Parser**: Can be implemented in `rcwa/adapters/swf.py` by parsing 18 space-separated fields, header pragmas into trace metadata, converting KB/proc to total MB, and hardcoding recompute attribution to "not available".
3. **Canonical Job Record**: Formalized via PyArrow Schema and Pydantic v2 `CanonicalJobRecord` in `rcwa/model.py`, including derived fields `reserved_core_s` and `reserved_mem_mb_s`, with strict exclusion of `RUNNING`/`PENDING` and retention of `run_s = 0`.
4. **Grouping**: Formalized in `rcwa/groups.py` with default key `(user, coalesce(command_hash, job_name))`, secondary rollups, and the `min_samples = 5` guardrail.
5. **`rcwa-wrap` Wrapper**: Implemented in `rcwa/wrap.py` supporting content and `size_mtime` hashing, argument sorting, path stripping, non-blocking fault tolerance on missing files or scheduler errors, and dual-recording via `scontrol` Comment and sidecar JSON.

---

## 7. Verification Method

To independently verify the specification compliance during implementation:

1. **Parser Unit Tests**:
   - Run `pytest tests/unit/test_sacct.py` with committed synthetic fixtures verifying:
     - Step rollup (`max_rss_mb` max across steps, `cpu_time_used_s` sum excluding `.extern`).
     - Array job decomposition (`12345_7` with `parent_job_id = "12345"`).
     - Memory units (`4000M`, `4000Mc`, `4000Mn`, `4G`, `500000K`, `?`).
     - Time string conversions (`D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`).
     - State qualifiers (`CANCELLED by 1234` -> `CANCELLED`, `OUT_OF_MEMORY`).
     - TRES parsing for GPU counts and node counts.
   - Run `pytest tests/unit/test_swf.py` verifying:
     - 18 whitespace-separated fields.
     - Pragma parsing (`; UnixStartTime`, `; MaxProcs`, `; MaxNodes`, `; Note`).
     - Sentinel `-1` conversion to `None`.
     - Memory scaling by allocated processors.
2. **Canonical Model Invariant Tests**:
   - Run `pytest tests/unit/test_model.py` verifying:
     - Arrow schema matches Pydantic model field names and types.
     - `reserved_core_s == alloc_cpus * run_s`.
     - `reserved_mem_mb_s == req_mem_mb * run_s`.
     - `RUNNING` and `PENDING` states are filtered from attribution tables.
     - `run_s = 0` records are retained.
3. **Wrapper Verification**:
   - Run `pytest tests/unit/test_wrap.py` verifying:
     - Command argument sorting (`--b 1 --a 2` equals `--a 2 --b 1`).
     - Path stripping (`/usr/bin/python` normalizes to `python`).
     - Non-blocking execution on missing declared input files (records `"missing"`).
     - Exit code transparency (returns child command exit code).
     - Sidecar file creation and `scontrol` mock invocation.
4. **Throughput Benchmark Requirement** (SPEC.md Phase 1):
   - Measure single-process parsing throughput: `100,000-row synthetic sacct export parses at a measured jobs/s you report.`
