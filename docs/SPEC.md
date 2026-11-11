# Build prompt: `research-cluster-waste-attributor`

How to use this file: save it as `docs/SPEC.md` in an empty repository.
Everything below specifies the system requirements, architecture, and design constraints.

---

## 1. Role and working rules

You are building a small, self-contained, open-source Python repository that reads batch-scheduler accounting data from a research compute cluster, attributes wasted CPU and memory to four causes, produces a ranked list of what can be reclaimed and how, and simulates the effect of the recommendations on queue wait before anyone changes a limit. The readers are engineers who run research clusters at quantitative trading firms. The repository is a showcase of engineering judgment: conservation guarantees, measured numbers, explicit assumptions, and documented trade-offs matter more than feature count.

Rules that apply to every phase:

1. Work in the phases of section 14, in order. After each phase, run the full test suite, then stop and report. Do not begin the next phase without confirmation.
2. Never fabricate a number. README result cells stay `TBD` until `make bench` has produced them on the machine named in the README. Statistics about a trace come from code you ran on it. If a command fails, report the failure and its output.
3. Never reference any company's internal systems, metrics, code, or data. Public traces and generated traces only.
4. Do not add a dependency outside section 11 without stopping to ask. Pin exact versions.
5. No network access in tests. CI runs on committed synthetic fixtures only. Downloads happen only in `make data`.
6. Small commits with imperative messages naming what changed and why. No squashing, no history rewriting.
7. Each decision in section 12 gets an ADR in `docs/adr/` (context, options, decision, measured or expected cost). Decisions not listed there get an ADR too and a mention in the phase report.
8. Maintain code documentation: verify every module and function upon review.
9. Prefer plain code over frameworks. One repository, one `make` target per task, runs on a laptop. One language (Python). If a performance target in section 9 is missed, stop and report before proposing a compiled component.
10. When the specification is ambiguous, pick the option that keeps a guarantee checkable by a test, record it in `docs/DECISIONS.md`, and continue.

## 2. Project summary

Research clusters reserve CPU cores and memory per job from what users request, not from what jobs use. Four causes separate reservation from use: memory requested far above the job's peak resident size, cores reserved while the job runs mostly single-threaded, work lost to jobs that fail or time out and are resubmitted, and successful jobs that recompute a result another job already produced from the same inputs. This kit ingests scheduler accounting records (Slurm `sacct` exports and Standard Workload Format traces in v1), partitions every reserved core-hour and gigabyte-hour into exactly one of those four classes or "used", ranks groups of jobs by what is reclaimable, recommends right-sized requests with safety guardrails, and replays the trace through a scheduler simulator to report the change in queue wait and throughput if the recommendations were applied.

## 3. Goals and non-goals

Goals:

- One command turns an accounting export into a report with a ranked reclaim list.
- Four guarantees, each enforced by a named test and stated in the README: (G1) conservation — for every job, reserved resources equal used plus the attributed waste, with no double counting; (G2) safety — no memory recommendation below the group's observed peak times a safety factor, no decrease for a group that had an out-of-memory kill, no recommendation for a group below the minimum sample size; (G3) determinism — identical inputs produce byte-identical outputs; (G4) simulator validity — every job is scheduled exactly once per scenario, never before its submit time, never above node capacity.
- Measured numbers: reclaimable core-hours and GB-hours as a share of the trace; per-class recall and precision against planted ground truth; simulated median and p95 queue-wait change per scenario; simulator calibration error against the trace's real wait times; attribution coverage; ingest and simulation throughput; peak memory.

Non-goals (do not build): a scheduler plugin or live rescheduling; GPU utilization attribution (GPU counts are ingested and reported but not attributed); node topology, preemption, or fair-share modeling in the simulator; a web UI; any external model-based or neural component; Kubernetes and Ray adapters are optional Phase 8 work.

## 4. Repository layout

```
research-cluster-waste-attributor/
  README.md
  LICENSE                      Apache-2.0
  pyproject.toml               license = "Apache-2.0"; pinned deps; console scripts `rcwa`, `rcwa-wrap`
  Makefile                     targets in section 10
  Dockerfile                   python:3.12-slim; runs `make test` by default
  .github/workflows/ci.yml     lint, typecheck, tests with coverage gate, bench smoke
  rcwa/
    __init__.py
    cli.py                     typer app
    config.py                  Pydantic models: policy, cluster spec, simulator settings
    model.py                   canonical job record (Arrow schema + Pydantic)
    adapters/
      sacct.py                 Slurm sacct export parser (pipe-delimited)
      swf.py                   Standard Workload Format parser
      k8s.py                   Phase 8, optional
      ray.py                   Phase 8, optional
    normalize.py               unit, time, state, array-job and step roll-up
    attribute.py               the four waste classes and the conservation partition
    groups.py                  job grouping (user, account, partition, command hash)
    recommend.py               right-sizing with guardrails
    recompute.py               duplicate detection from declared input hashes
    retries.py                 failure and retry chain detection
    simulate.py                EASY-backfill cluster simulator and scenarios
    calibrate.py               simulator calibration against real waits
    report.py                  Markdown, JSON, CSV outputs
    wrap.py                    `rcwa-wrap`: records declared input hashes for a job
    synth.py                   synthetic trace generator with planted waste
  policies/default.yaml
  clusters/example.yaml
  data/                        gitignored: raw/, out/, results/
  tests/  unit/  property/  golden/  fixtures/
  bench/  run.py  hardware.py  results/
  docs/   SPEC.md  DECISIONS.md  DATA.md  adr/
```

## 5. Inputs and canonical job record

### 5.1 Slurm `sacct` export

Document the export command in the README and accept its output as input:

```
sacct -a -P --units=M -S <start> -E <end> \
  --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine
```

Parser requirements, each with a test:

- Pipe-delimited with a header; fields may be empty. Unknown extra columns are ignored with a warning.
- Steps (`12345.batch`, `12345.0`, `12345.extern`) carry `MaxRSS`, `AveRSS`, and `TotalCPU`; the parent row carries the allocation. Roll steps up to the job: `max_rss_mb = max over steps`, `cpu_time_used_s = sum of TotalCPU over steps excluding .extern`.
- Array jobs `12345_7` and heterogeneous job components: treat each as a job; record `parent_job_id`.
- `Elapsed` and `TotalCPU` formats: `D-HH:MM:SS`, `HH:MM:SS`, `MM:SS.mmm`.
- `ReqMem` forms: `4000M`, `4000Mc` (per CPU; multiply by allocated CPUs), `4000Mn` (per node; multiply by nodes), `?`; with `--units=M` values are in MB. Handle `G` and `K` suffixes too.
- `State` strings include qualifiers (`CANCELLED by 1234`); map to the canonical set below. `OUT_OF_MEMORY` is its own state.
- `ReqTRES` and `AllocTRES` such as `cpu=8,mem=32000M,node=1,billing=8,gres/gpu=2`: parse GPU counts.
- `Comment` may hold `RCWA_INPUT_HASH=<hex>` written by `rcwa-wrap` (section 5.5).

### 5.2 Standard Workload Format (SWF)

Parse the 18 whitespace-separated fields: job number, submit time, wait time, run time, allocated processors, average CPU time used, used memory (KB per processor), requested processors, requested time, requested memory (KB per processor), status, user id, group id, executable number, queue number, partition number, preceding job number, think time. Honor the header's `UnixStartTime`, `MaxProcs`, `MaxNodes`, and `Note` lines; record them in `docs/DATA.md` output for each trace. Missing values are `-1`. Status: 1 completed, 0 failed, 5 cancelled, others as documented in the header. Memory is per processor: multiply by allocated processors for the job total. `executable number` becomes `command_hash`. SWF has no declared inputs, so recomputation attribution is reported as "not available" for SWF traces, never estimated.

### 5.3 Canonical job record (Arrow schema and Pydantic model)

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

Rows with `state in {RUNNING, PENDING}` are excluded from attribution and counted in the report's data-quality section. Rows with `run_s = 0` are kept (early failures) and attributed to class 3 with zero consumption.

### 5.4 Grouping

A group key is configurable in the policy; default `(user, command_hash or job_name)`. Secondary roll-ups by `account` and `partition`. Groups below `min_samples` (default 5) receive no recommendation.

### 5.5 Declared inputs: `rcwa-wrap`

Recomputation detection needs to know what a job read. Provide a wrapper:

```
rcwa-wrap --inputs data/a.parquet,config.yaml --big-file-mode size_mtime -- python train.py --lr 0.01
```

It hashes each declared input (sha256 of contents by default; `size_mtime` mode for files over a configurable size), combines them with the normalized command line into `input_hash`, and records it in two places when available: `scontrol update JobId=$SLURM_JOB_ID Comment=RCWA_INPUT_HASH=<hex>` and a sidecar `$RCWA_DIR/<job_id>.json`. The adapter reads either. The wrapper then executes the command and exits with its exit code. Tests cover hashing, normalization of the command line (strip absolute path prefixes configurable by regex, sort `--flag=value` pairs), and failure modes (missing input file: record `missing` and continue, never block the job).

## 6. Waste attribution

### 6.1 The four classes and the conservation partition

For each job, partition `reserved_core_s` and `reserved_mem_mb_s` with this precedence, applied once, so that no second of reservation lands in two classes:

1. Class 3, failed and retried work: if `state in {FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, PREEMPTED}` or (`CANCELLED` and `run_s > 0`), the job's entire reservation in both dimensions is class 3. Sub-labels: `oom`, `timeout`, `early_failure` (run_s ≤ 60), `other_failure`, `cancelled_after_start`, `node_fail`. Retry chains: a later job by the same user with the same `command_hash` (or `job_name` when no hash) submitted within `retry_window` (default 24 h) after a failed job is marked `retry_of`; the chain's total cost is reported, and the retried job itself is attributed normally.
2. Class 4, redundant recomputation: if `state = COMPLETED` and another `COMPLETED` job with the same `(command_hash, input_hash)` ended earlier within `recompute_window` (default 30 days), the later job's entire reservation in both dimensions is class 4 (`confidence = declared_inputs`). When `input_hash` is missing and only `command_hash` matches, the job is listed under `possible_recompute` with `confidence = command_only` and is NOT counted in class 4 totals.
3. Class 2, idle reserved CPU (core dimension): `idle_core_s = max(0, reserved_core_s − cpu_time_used_s)`; `used_core_s = reserved_core_s − idle_core_s`. If `cpu_time_used_s` is null, the job's core reservation is labeled `unattributed_missing_cpu_time` and counted in coverage, not in class 2.
4. Class 1, memory over-request (memory dimension): `over_mem_mb_s = max(0, req_mem_mb − max_rss_mb) × run_s`; `used_mem_mb_s = reserved_mem_mb_s − over_mem_mb_s`. Null `max_rss_mb` → `unattributed_missing_rss`.

G1 test: for every job and each dimension, `reserved = used + class1_or_2 + class3 + class4 + unattributed` exactly, in integer seconds and MB-seconds. Totals in the report are sums of these per-job values; a test recomputes the totals from the per-job table.

### 6.2 Ranked reclaim list

For each group: reserved and used core-hours and GB-hours; waste per class; share of cluster total; recommended action (section 7); confidence; evidence (five job ids with the largest waste). Sorted by reclaimable core-hours plus a configurable memory weight (`mem_weight_core_hours_per_gb_hour`, default from the cluster spec's core-to-memory ratio). Also roll-ups by user, account, partition.

## 7. Recommendations with guardrails

- Memory: recommended `req_mem_mb = ceil(p99(max_rss_mb over the group's COMPLETED jobs) × safety_factor)` with `safety_factor` default 1.2; never below `max(max_rss_mb)` observed in the group across all states; if any job in the group has `state = OUT_OF_MEMORY` in the window, the recommendation direction is `increase` to `ceil(max observed × 1.5)` and the group is excluded from reclaimable memory totals.
- CPU: recommended `cpus = clamp(ceil(p99(cpu_time_used_s / run_s) × safety_factor), 1, alloc_cpus)`; groups whose jobs have `run_s < 120` get no CPU recommendation (utilization is unreliable on short jobs).
- Timeouts: recommend `time_limit = ceil(p99(run_s of COMPLETED jobs) × 1.5)` for groups with timeouts.
- Early failures: no resource recommendation; the report lists the group with its failure share and sample exit codes.
- Recomputation: recommend a result cache keyed by `(command_hash, input_hash)` for groups where class 4 exceeds a threshold; report the hit rate the cache would have had.
- G2 tests: for randomly generated groups (Hypothesis), the memory recommendation is never below the observed maximum times the safety factor; OOM groups never receive a decrease; groups below `min_samples` receive nothing.

## 8. Simulator

- Model: a cluster of `N` identical nodes with `cores_per_node` and `mem_mb_per_node` (from `clusters/<name>.yaml`, or inferred from the trace as the maximum allocation seen, with the inference reported). Jobs arrive at `submit_time`, request `(cpus, mem_mb, nodes)`, and run for `run_s`. Scheduling: FCFS with EASY backfill (a later job may start early if it does not delay the first queued job's reservation), using the trace's `requested time` when present and `run_s × 1.2` otherwise. Deterministic: ties broken by `(submit_time, job_id)`; no randomness.
- Scenarios, each a full replay: `baseline` (original requests); `mem_rightsized`; `cpu_rightsized` under two runtime models, `none` (runtime unchanged) and `proportional` (runtime scales by `old_cpus / new_cpus` when the job's measured utilization exceeded the new allocation); `cache_dedup` (class 4 jobs removed); `all`. Each scenario reports median and p95 wait, makespan, core and memory utilization, and jobs completed per simulated day.
- Calibration (`rcwa calibrate`): run `baseline` on a real trace and compare simulated wait per job with the trace's recorded wait. Report median absolute error and the Spearman correlation. The README states the calibration error next to every scenario result, because a scenario delta is only as trustworthy as the baseline fit.
- G4 tests: every job appears once in every scenario's schedule; `sim_start ≥ submit_time`; per-timestep capacity checks on a sampled set of timestamps; a brute-force checker on small traces.
- Performance target: 1,000,000 jobs through `baseline` in under 15 minutes on a laptop in pure Python with a heap-based event loop and a per-node free-capacity index. If the target is missed, report the profile and stop.

## 9. Benchmark

`make bench SIZE=1M RUNS=5 SEED=1` runs the pipeline on a synthetic trace with planted waste and writes `bench/results/bench.csv` and `bench/results/bench.md`:

| Metric | How measured |
| --- | --- |
| Reclaimable core-hours and GB-hours as share of trace | from the per-job attribution table |
| Per-class recall and precision | planted ground truth from `rcwa synth` |
| Conservation check | G1 over the whole trace; must hold exactly |
| Guardrail violations | count; must be 0 |
| Simulated median and p95 wait change per scenario | `simulate` vs `baseline` |
| Simulator calibration error | on the two real SWF traces (`make data`): median absolute wait error, Spearman correlation |
| Ingest throughput | jobs/s for sacct and SWF parsers, single process |
| Simulation throughput | jobs/s for `baseline` |
| Peak resident memory | max RSS of the process tree |
| Attribution coverage | share of reserved core-s and mem-s attributed to a class or to used, vs unattributed |

5 runs; median and min–max. `bench/hardware.py` records CPU model, cores, RAM, OS, Python and library versions, and the git commit; the README copies this block verbatim. CI runs `make bench-smoke` (`SIZE=20k RUNS=1`) and asserts completion, G1 exact, zero guardrail violations.

## 10. Makefile targets

```
make setup        venv + pinned deps
make lint         ruff check, ruff format --check
make typecheck    pyright
make test         pytest with coverage gate (85% lines)
make data         download two SWF traces chosen from the Parallel Workloads Archive index; record URLs, header notes, and the archive's usage conditions in docs/DATA.md
make synth        rcwa synth --size $(SIZE) --seed $(SEED) --faults default
make run          rcwa ingest + attribute + recommend + simulate + report on $(TRACE)
make calibrate    rcwa calibrate on the real traces
make bench        full benchmark (SIZE, RUNS, SEED)
make bench-smoke  SIZE=20k RUNS=1
make goldens      regenerate golden reports (shows a diff)
make docker       build and run `make test` in the image
```

## 11. Allowed dependencies (pin exact versions)

Runtime: `polars`, `pyarrow`, `numpy`, `pydantic>=2`, `typer`, `pyyaml`. Development: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `pyright`. `duckdb` only if you measure that a Polars aggregation misses the throughput target, with the measurement recorded. Nothing else without asking. No external model clients. No telemetry.

## 12. ADRs to write

1. `001-conservation-partition.md`: precedence failed → duplicate → idle CPU / over-requested memory, each second attributed once. Optimizes exact, auditable totals; costs visibility into idle CPU inside failed jobs (listed as a sub-label, not a class).
2. `002-declared-inputs-for-recomputation.md`: hash declared inputs through `rcwa-wrap`, never trace execution. Optimizes applicability to any scheduler and zero overhead on jobs; costs missed recomputation for jobs without declarations, reported as coverage.
3. `003-percentile-rightsizing-with-guardrails.md`: p99 × 1.2, minimum samples, OOM groups only increase. Optimizes safety of recommendations; costs reclaimable capacity left unclaimed, quantified as the gap between p99 and p50 sizing.
4. `004-easy-backfill-simulator.md`: FCFS plus EASY backfill on identical nodes, calibrated against real waits. Optimizes a checkable baseline; ignores topology, preemption, fair share, GPUs; the calibration error is the stated bound on scenario deltas.
5. `005-single-process-polars.md`: one process, Polars. Optimizes one-command reproducibility; bounds trace size by memory, measured and reported.

## 13. README requirements

Sections, in order, in short plain sentences:

1. Title and one sentence on what the kit does.
2. Status line: `design complete` → `benchmarked on <hardware>` once numbers exist.
3. Results table (section 9) with `TBD` until measured, plus the hardware block.
4. Quick start: the export command for `sacct`, `make data` for public traces, `make run`.
5. Problem: three or four sentences on why reserved and used resources diverge on research clusters and why changing limits without a simulation is risky.
6. How it works: pipeline diagram (ASCII), canonical record, the four classes and the precedence rule, grouping, recommendations and guardrails, `rcwa-wrap`, the simulator and its scenarios, calibration.
7. Guarantees: G1–G4 with the names of the tests that enforce them.
8. Benchmark method.
9. Design decisions: a table of the five ADRs with "optimizes" and "costs" columns.
10. Limits and follow-ups: the non-goals, and the simulator's known omissions.
11. Related work: Slurm `sreport` and `sacct` reporting, XDMoD, Kubecost (state only what their public documentation says; omit anything unsure). One sentence on the differentiator: a conservation-checked attribution across four causes, recomputation detection from declared inputs, and a calibrated simulation of the recommendations in one tool.
12. Data: the two public traces with URLs and usage conditions from `docs/DATA.md`; what is committed (synthetic fixtures only).
13. License: Apache-2.0.

Do not use the words "simply", "robust", "seamless", "best", "optimal", "clean", "minimal", "powerful", or "cutting-edge" anywhere in the repository.

## 14. Phased delivery

Each phase ends with all tests green, lint and typecheck passing, a commit, and a report (section 15).

- **Phase 0 — Scaffold.** Layout, `pyproject.toml` (pinned deps, `license = "Apache-2.0"`, console scripts), `LICENSE` with the current year and the owner's name (ask if not given), Makefile, Dockerfile, CI workflow, README skeleton with `TBD` placeholders, `docs/DECISIONS.md`, `docs/DATA.md` (empty template), ADR files with titles, `policies/default.yaml`, `clusters/example.yaml`. Acceptance: `make test` passes on a trivial test; CI config validates.
- **Phase 1 — Adapters and canonical record.** `model.py`, `normalize.py`, `adapters/sacct.py`, `adapters/swf.py`, fixtures covering every parser requirement in section 5. Acceptance: all parser tests pass; a 100,000-row synthetic sacct export parses at a measured jobs/s you report.
- **Phase 2 — Attribution.** `attribute.py`, `groups.py`, `retries.py`, G1 test. Acceptance: conservation holds exactly on fixtures and on a 20k synthetic trace; per-job and group tables written as Parquet and CSV.
- **Phase 3 — Recommendations.** `recommend.py` with guardrails, G2 property tests. Acceptance: Hypothesis finds no guardrail violation in 10,000 generated groups.
- **Phase 4 — Recomputation.** `wrap.py` (`rcwa-wrap`), `recompute.py`, sidecar and Comment readers. Acceptance: planted duplicates are found with exact recall and precision; command-only matches are listed but not counted.
- **Phase 5 — Simulator and calibration.** `simulate.py`, `calibrate.py`, G4 tests, brute-force checker on small traces. Acceptance: all scenarios run on the 20k trace; the 1M-job performance target is measured and reported (met or not).
- **Phase 6 — Report.** `report.py`, ranked reclaim list, data-quality section, golden tests. Acceptance: golden reports render for the synthetic trace and for the SWF fixture; G3 determinism test passes (two runs, byte-identical outputs).
- **Phase 7 — Synthetic generator, data, benchmark, ADRs, README.** `synth.py` with every planted-waste type and a ground-truth file; `make data` for two public SWF traces with `docs/DATA.md` filled from their headers and the archive's usage conditions; `bench/run.py`, `bench/hardware.py`; the five ADRs; README results filled only from `bench/results/` after the human confirms the run and the machine. Acceptance: `make bench-smoke` passes in CI; the 1M-job cells may remain `TBD` until the human runs them.
- **Phase 8 (optional, only if asked).** `adapters/k8s.py` over a documented CSV schema (pod, owner job, requests, limits, max usage from a metrics export, phase, restarts) with a `kubectl`-based exporter script; `adapters/ray.py` over Ray job state exports; a Prometheus text-format exporter of the class totals.

## 15. Phase report format

At the end of each phase, report in this order and nothing else:

1. Phase number and one line on what now works.
2. Commands run with exit status; test count, coverage percentage, lint and typecheck status.
3. Measured numbers produced in this phase, each with the command that produced it.
4. Decisions made that were not in the spec, each with its `DECISIONS.md` entry.
5. Open questions for the human, each with the default you will take if unanswered.
6. The next phase's first three steps.

## 16. Definition of done

- `git clone`, `make setup`, `make test` pass on a fresh machine in under 10 minutes with no network beyond package installation.
- `make data && make run TRACE=data/raw/<trace>.swf` produces a report with a ranked reclaim list and scenario table on a real public trace, with calibration error stated.
- An `sacct` export in the documented format runs through the same command.
- README results contain numbers only from `bench/results/` runs on the hardware named in the README.
- G1–G4 are each enforced by a named test and described in the README.
- Five ADRs exist with measured or stated costs; `docs/DATA.md` records trace sources and usage conditions; documentation records project configuration and decisions.
- No fabricated figure, no employer reference, no banned word.
