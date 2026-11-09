# End-to-End Test Infrastructure Specification

## 1. Architectural Principles & Opaque-Box Philosophy

The testing architecture for `research-cluster-waste-attributor` (`rcwa`) enforces strict opaque-box verification derived directly from `docs/SPEC.md` and `PROJECT.md`. The design guarantees system correctness without mocking away real behavior.

Key principles:
1. **Opaque-Box Boundary**: Tests interact with the system via CLI entry points (`rcwa`, `rcwa-wrap`) and public file formats (Parquet, SWF, Slurm pipe-delimited exports, JSON, CSV, and Markdown).
2. **Real Assertions**: Tests do not use trivial assertions. Every test verifies actual CLI exit codes, stdout/stderr streams, file system artifacts, Arrow/Polars schemas, and formal mathematical conservation invariants.
3. **Graceful Milestone Adaptation**: Tests are structured so that test discovery (`pytest --collect-only`) discovers all 600+ tests without error across milestones, executing assertions against available features as each phase completes.
4. **Conservation Discipline**: All accounting arithmetic is evaluated down to the exact integer second and MB-second, verifying that no reservation is lost or double counted.

---

## 2. Test Suite Layout & Hierarchy

The test directory structure follows a four-tier progression:

```
tests/
├── fixtures/
│   ├── clusters/          # Homogeneous and heterogeneous cluster topologies
│   ├── edge/              # Zero-byte, truncated, corrupted, and extreme inputs
│   ├── golden/            # Reference Markdown, JSON, and CSV reports
│   ├── guardrails/        # Out-of-memory and sample threshold cohorts
│   ├── policies/          # Default and strict attribution policies
│   ├── recompute/         # Duplicate pairs and command-only fixtures
│   ├── retries/           # Multi-step failure retry chains
│   ├── sacct/             # Slurm pipe-delimited traces (standard, steps, arrays, suffixes)
│   ├── sidecars/          # rcwa-wrap execution metadata
│   └── swf/               # Standard Workload Format traces and header pragmas
└── e2e/
    ├── conftest.py        # Harness runners, workspace fixtures, invariant checkers
    ├── tier1_feature_coverage/
    │   ├── test_f04_f09_sacct_ingest.py
    │   ├── test_f10_f14_swf_canonical.py
    │   ├── test_f15_f21_attribution_g1.py
    │   ├── test_f22_f28_reclaim_recommendations_g2.py
    │   ├── test_f29_f34_wrap_recompute.py
    │   ├── test_f35_f40_simulator_calibration_g4.py
    │   └── test_f41_f44_reports_determinism_g3.py
    ├── tier2_boundary_corner/
    │   ├── test_boundary_sample_groups.py
    │   ├── test_cli_argument_boundaries.py
    │   ├── test_corrupted_and_extreme_values.py
    │   ├── test_empty_and_truncated_inputs.py
    │   ├── test_missing_metrics_and_exclusions.py
    │   └── test_wrap_tolerance_boundaries.py
    ├── tier3_cross_feature/
    │   ├── test_int01_oom_retry_guardrails.py
    │   ├── test_int02_wrap_sidecar_class4.py
    │   ├── test_int03_array_step_memory_suffixes.py
    │   ├── test_int04_synth_attribution_rightsizing.py
    │   ├── test_int05_easy_backfill_scenarios.py
    │   ├── test_int06_calibration_spearman_mae.py
    │   ├── test_int07_full_pipeline_determinism.py
    │   └── test_int08_heterogeneous_cluster_backfill.py
    └── tier4_real_world/
        ├── test_cli_workflow_e2e.py
        ├── test_degraded_data_resilience.py
        ├── test_guarantee_g1_conservation_suite.py
        ├── test_guarantee_g2_safety_suite.py
        ├── test_guarantee_g3_determinism_suite.py
        ├── test_guarantee_g4_simulation_validity_suite.py
        └── test_multiday_cluster_workload.py
```

---

## 3. CLI Execution Harness & Subprocess Testing

Test execution is anchored by dedicated fixtures defined in `tests/e2e/conftest.py`:

- `run_cli`: Spawns CLI invocations via `python -m rcwa.cli <args>` using Python's `subprocess.run`. It captures:
  - `exit_code`: Numeric return code.
  - `stdout` and `stderr`: Captured streams without terminal corruption.
  - `duration_s`: High-resolution execution time using monotonic clocks.
- `run_wrap_cli`: Spawns `rcwa-wrap` console wrapper testing input capture, sidecar emission, and command execution.
- `isolated_workspace`: Creates an isolated, temporary directory per test invocation for Parquet files and sidecars.
- `require_rcwa`: Guards execution when specific application modules are pending implementation in early milestones.

---

## 4. Fixture Catalog

| Category | Fixture Path | Description |
|---|---|---|
| Slurm `sacct` | `tests/fixtures/sacct/sacct_standard_26col.txt` | Standard 26-column pipe-delimited Slurm export |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_empty_optional_fields.txt` | Trace with empty optional columns |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_unknown_columns.txt` | Trace with unmapped vendor columns |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_reordered_headers.txt` | Trace with reordered 26-column header |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_trailing_delimiters.txt` | Trace with trailing pipe delimiters |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_steps_rollup.txt` | Hierarchy with `.batch`, `.0`, and `.extern` steps |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_array_heterogeneous.txt` | Array jobs (`10001_0`) and pack jobs (`10002+0`) |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_memory_suffixes.txt` | Suffixes `M`, `Mc`, `Mn`, `G`, `Gc`, `Gn`, `K`, `Kc`, `Kn`, `?` |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_durations_states.txt` | Formats `D-HH:MM:SS`, `MM:SS.mmm`, and state qualifiers |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_running_pending.txt` | Active jobs (`RUNNING`, `PENDING`) for exclusion check |
| Slurm `sacct` | `tests/fixtures/sacct/sacct_unattributed_missing.txt` | Jobs missing `MaxRSS` or `TotalCPU` |
| Slurm `sacct` | `tests/fixtures/sacct/multiday_cluster.txt` | Realistic 7-day multi-day trace across 5 users |
| SWF | `tests/fixtures/swf/standard_with_headers.swf` | 18-field Standard Workload Format with header pragmas |
| SWF | `tests/fixtures/swf/missing_fields.swf` | SWF records with `-1` missing sentinels |
| SWF | `tests/fixtures/swf/status_variations.swf` | SWF status codes 1, 0, 5, and 99 |
| SWF | `tests/fixtures/swf/sample_workload.swf` | Multi-job replay trace for queue simulator |
| SWF | `tests/fixtures/swf/calibration_reference.swf` | Workload with recorded wait times for calibration |
| Edge | `tests/fixtures/edge/empty_file.txt` | 0-byte text trace |
| Edge | `tests/fixtures/edge/header_only.txt` | 26 headers with 0 data rows |
| Edge | `tests/fixtures/edge/empty_swf.swf` | 0-byte SWF file |
| Edge | `tests/fixtures/edge/malformed_row_short.txt` | Truncated lines with fewer than 26 columns |
| Edge | `tests/fixtures/edge/corrupted_timestamps.txt` | Inverted timestamps and invalid ISO strings |
| Edge | `tests/fixtures/edge/extreme_durations.txt` | Multi-year durations and sub-millisecond durations |
| Edge | `tests/fixtures/edge/corrupted_binary.bin` | Raw binary input |
| Clusters | `tests/fixtures/clusters/homogeneous_cluster.yaml` | 16-node cluster definition |
| Clusters | `tests/fixtures/clusters/heterogeneous_cluster.yaml` | 3-partition cluster definition (standard, fatmem, gpu) |
| Policies | `tests/fixtures/policies/default_policy.yaml` | Standard rightsizing and retry thresholds |
| Policies | `tests/fixtures/policies/strict_policy.yaml` | Conservative policy with 10-sample floor and 1.5x safety |
| Recompute | `tests/fixtures/recompute/recompute_pairs.txt` | Duplicate job executions sharing input hashes |
| Recompute | `tests/fixtures/recompute/recompute_command_only.txt` | Identical commands with missing input hashes |
| Retries | `tests/fixtures/retries/retry_chains.txt` | Chained failed jobs with retry linkage |
| Guardrails | `tests/fixtures/guardrails/group_sample_sizes.txt` | Cohorts with sample sizes 1, 4, 5, and 20 |
| Guardrails | `tests/fixtures/guardrails/oom_groups.txt` | Cohorts with OUT_OF_MEMORY incidents |
| Sidecars | `tests/fixtures/sidecars/sample_sidecar.json` | Hash records generated by rcwa-wrap |
| Golden | `tests/fixtures/golden/golden_report.md` | Golden Markdown report |
| Golden | `tests/fixtures/golden/golden_report.json` | Golden JSON report structure |
| Golden | `tests/fixtures/golden/golden_report.csv` | Golden CSV reclaim ranking table |

---

## 5. Guarantee Verification Formulas

### Guarantee G1: Conservation Invariant
For every evaluated job $j$, and across cluster totals:
$$\text{reserved\_core\_s}(j) = \text{used\_core\_s}(j) + \text{class2}(j) + \text{class3\_core}(j) + \text{class4\_core}(j) + \text{unattributed\_core}(j)$$
$$\text{reserved\_mem\_mb\_s}(j) = \text{used\_mem\_mb\_s}(j) + \text{class1}(j) + \text{class3\_mem}(j) + \text{class4\_mem}(j) + \text{unattributed\_mem}(j)$$
Enforced in exact integer seconds and MB-seconds. Floating-point conversions are prohibited in conservation arithmetic.

### Guarantee G2: Recommendation Safety Guardrails
- **Peak Floor**: $\text{rec\_mem\_mb} \ge \max_{j \in \text{group}}(\text{max\_rss\_mb}(j))$.
- **Safety Headroom**: $\text{rec\_mem\_mb} = \lceil p99(\text{max\_rss\_mb}) \times \text{safety\_factor} \rceil$.
- **OOM Escalation**: If $\exists j \in \text{group}: \text{state}(j) = \text{OUT\_OF\_MEMORY}$, direction is `increase`, $\text{rec\_mem\_mb} = \lceil \max(\text{max\_rss\_mb}) \times 1.5 \rceil$, and group reclaimable memory is forced to $0$.
- **Sample Floor**: If $|\text{group}| < \text{min\_samples}$ (default 5), no recommendation is emitted ($\text{None}$).

### Guarantee G3: Byte Determinism
For identical input traces, policies, and cluster specifications:
$$\text{OutputBytes}(\text{Run}_1) \equiv \text{OutputBytes}(\text{Run}_2)$$
Enforced across Markdown, JSON, and CSV outputs through deterministic sorting and stable dictionary serialization.

### Guarantee G4: Simulator Validity
1. Schedule count invariant: $|\text{ScheduledJobs}| = |\text{UniqueTraceJobs}|$.
2. Temporal causality: $\forall j, \text{sim\_start}(j) \ge \text{submit\_time}(j)$.
3. Capacity limit invariant: For all time $t$ and nodes $n$, $\sum_{j \in \text{active}(t, n)} \text{alloc\_cpus}(j) \le \text{cores\_per\_node}$ and $\sum_{j \in \text{active}(t, n)} \text{req\_mem\_mb}(j) \le \text{mem\_mb\_per\_node}$.

---

## 6. Feature-to-Test Traceability Matrix

| Feature ID | Feature Name | Primary Test Module | Key Assertions |
|---|---|---|---|
| F4 | Slurm sacct Ingest | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | 26 columns, schema preservation, delimiter handling |
| F5 | Step Hierarchy Rollup | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | MaxRSS peak selection, TotalCPU sum without `.extern` |
| F6 | Array & Heterogeneous Jobs | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | Sub-job decomposition, parent_job_id assignment |
| F7 | Time and Duration Parsing | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | `D-HH:MM:SS`, fractional parsing, `wait_s`, `run_s` |
| F8 | Memory Suffix Parsing | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | Units `M`, `Mc`, `Mn`, `G`, `Gc`, `Gn`, `K`, `Kc`, `Kn`, `?` |
| F9 | State & TRES Parsing | `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | Qualifier stripping, OUT_OF_MEMORY mapping, GPU counts |
| F10 | SWF Format Parsing | `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | 18 whitespace fields, header pragmas extraction |
| F11 | SWF Metric Conversions | `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | KB/proc to MB total, CPU scaling, sentinel conversion |
| F12 | Canonical Job Record | `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | Arrow schema compliance, reservation arithmetic |
| F13 | Active Job Exclusions | `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | Exclusion of RUNNING/PENDING, retention of zero-runtime |
| F14 | Ingest Throughput | `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | High-throughput batch parsing evaluation |
| F15 | Attribution Precedence | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | Strict sequence: Class 3 -> Class 4 -> Class 2/1 -> Used |
| F16 | Class 3 Failed Work | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | Entire reservation attributed, 6 sub-labels verified |
| F17 | Retry Chain Linkage | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | Identification of retry submissions within 24 hours |
| F18 | Class 2 Idle CPU | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | `idle = max(0, reserved - used_cpu)`, integer second accuracy |
| F19 | Class 1 Memory Over-request | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | `over = max(0, req - max_rss) * run_s`, MB-second accuracy |
| F20 | Unattributed Labels | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | `unattributed_missing_rss`, `unattributed_missing_cpu_time` |
| F21 | Guarantee G1 Conservation | `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | Exact integer match: reserved = used + waste + unattributed |
| F22 | Job Grouping | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Group key `(user, command_hash or job_name)`, rollups |
| F23 | Ranked Reclaim Scoring | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Score formula with memory weighting, top-5 evidence jobs |
| F24 | Memory Rightsizing Floor | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | `p99 * 1.2` recommendation bounded by observed max RSS |
| F25 | OOM Escalation Guardrail | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Direction `increase` to `max * 1.5`, zero reclaimable memory |
| F26 | CPU Rightsizing Clamp | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Clamp between 1 and alloc_cpus, skip jobs < 120s |
| F27 | Timeout Recommendations | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | `p99 * 1.5` time limit recommendations on timeout cohorts |
| F28 | Guarantee G2 Safety | `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Floor guardrail, OOM escalation, min_samples floor |
| F29 | rcwa-wrap Input Hashing | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | SHA-256 and size_mtime hashing, flag sorting normalization |
| F30 | Non-Blocking Tolerances | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | Missing declared inputs recorded without blocking command |
| F31 | Class 4 Recomputation | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | Duplicate jobs within 30 days attributed to Class 4 |
| F32 | Command-Only Matches | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | Partial duplicate marked `possible_recompute`, omitted from Class 4 |
| F33 | Result Cache Recommendation | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | Cache suggestion and simulated hit rate computation |
| F34 | SWF Recomputation Disable | `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | SWF traces report recomputation as 'not available' |
| F35 | Cluster Topology Loading | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | YAML loading and automatic peak inference |
| F36 | EASY-Backfill Engine | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | FCFS shadow reservation and non-delaying backfill |
| F37 | Simulation Scenarios | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | Replay across baseline, mem, cpu (none/prop), dedup, all |
| F38 | Simulator Calibration | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | Median absolute error and Spearman rank correlation |
| F39 | Guarantee G4 Validity | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | Schedule completeness, submit order, node capacity bounds |
| F40 | Simulation Throughput | `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | Event loop execution speed verification |
| F41 | Multi-Format Reports | `tier1_feature_coverage/test_f41_f44_reports_determinism_g3.py` | Markdown, JSON, and CSV report formatting |
| F42 | Data Quality Section | `tier1_feature_coverage/test_f41_f44_reports_determinism_g3.py` | Active job exclusions and unmeasured share reporting |
| F43 | Golden Reference Tests | `tier1_feature_coverage/test_f41_f44_reports_determinism_g3.py` | Golden report comparison and schema checks |
| F44 | Guarantee G3 Determinism | `tier1_feature_coverage/test_f41_f44_reports_determinism_g3.py` | Byte-for-byte identity across repeated pipeline runs |
