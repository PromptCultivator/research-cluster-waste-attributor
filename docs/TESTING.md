# Testing and Verification Infrastructure

## 1. Testing Principles

`research-cluster-waste-attributor` enforces deterministic, offline verification across both internal unit/property suites and an opaque-box CLI end-to-end (E2E) test harness:

1. **Opaque-Box CLI Boundary**: E2E tests exercise the compiled CLI entrypoints (`rcwa`, `rcwa-wrap`) and public file formats (Parquet, Slurm pipe-delimited text, SWF, JSON, CSV, Markdown) via real subprocess invocations rather than mocks.
2. **Exact Conservation Discipline**: Conservation identities are verified in exact integer core-seconds (`core_s`) and megabyte-seconds (`mb_s`) per row and across aggregate sums with zero tolerance for rounding error.
3. **Hermetic Offline Execution**: All test suites execute strictly against committed fixtures in [`tests/fixtures/`](../tests/fixtures/) and deterministic generators without external network access.

---

## 2. Suite Hierarchy and Layout

The test tree separates fast coverage-gated developer suites from comprehensive opaque-box CLI integration suites:

```text
tests/
├── fixtures/                          # 40 committed offline test datasets across 10 directories
│   ├── clusters/                      # Homogeneous and multi-partition cluster YAML topologies
│   ├── edge/                          # Zero-byte, header-only, truncated, corrupted, extreme traces
│   ├── golden/                        # Reference Markdown, JSON, and CSV outputs (sacct & SWF)
│   ├── guardrails/                    # Small sample floor cohorts and OUT_OF_MEMORY test cases
│   ├── policies/                      # Default and strict YAML rightsizing policies
│   ├── recompute/                     # Verified input-hash duplicate pairs & command-only cohorts
│   ├── retries/                       # Multi-hop job failure and retry chains
│   ├── sacct/                         # Slurm pipe-delimited exports (steps, arrays, suffixes, states)
│   ├── sidecars/                      # rcwa-wrap JSON sidecar metadata fixture
│   └── swf/                           # Standard Workload Format traces and header pragmas
├── unit/                              # 21 unit test modules covering every package component
├── property/                          # Hypothesis property checks (G2 across 10,000 generated cohorts)
├── golden/                            # Golden fixture regression and G3 byte-determinism checks
└── e2e/                               # 28 opaque-box CLI suites across Tiers 1-4 (610 test invocations)
    ├── conftest.py                    # Subprocess harnesses, isolated workspaces, G1-G4 validators
    ├── tier1_feature_coverage/        # 7 modules (341 tests): ingest, G1, G2, wrap, sim, reports, G3
    ├── tier2_boundary_corner/         # 6 modules (92 tests): edge inputs, CLI validation, tolerances
    ├── tier3_cross_feature/           # 8 modules (38 tests): end-to-end feature compositions
    └── tier4_real_world/              # 7 modules (139 tests): multi-day workloads & G1-G4 verification
```

---

## 3. Running Tests

### Standard Suite (Coverage Gated at 85%)

The default configuration in [`pyproject.toml`](../pyproject.toml) executes the 24 standard modules (`tests/unit/`, `tests/property/`, `tests/golden/` — `389` tests) and asserts at least 85% line and branch coverage on `rcwa/`:

```bash
make test
```

### E2E Opaque-Box Suite (`tests/e2e/`)

Run with `-o addopts=""` to disable unit-level coverage thresholds across subprocess calls:

```bash
# Discover all 610 E2E test invocations
pytest tests/e2e/ -o addopts="" --collect-only

# Run the complete E2E suite
pytest tests/e2e/ -o addopts=""

# Run individual tiers
pytest tests/e2e/tier1_feature_coverage/ -o addopts=""
pytest tests/e2e/tier2_boundary_corner/ -o addopts=""
pytest tests/e2e/tier3_cross_feature/ -o addopts=""
pytest tests/e2e/tier4_real_world/ -o addopts=""
```

### Vocabulary Compliance & Golden Regeneration

- [`tests/unit/test_forbidden_words.py`](../tests/unit/test_forbidden_words.py) scans source, config, test, and Markdown documentation files across the repository for the nine prohibited terms.
- `make goldens` regenerates all six committed golden report fixtures (`sacct` and `swf` across Markdown, JSON, CSV) and displays `git diff tests/fixtures/golden/`.

---

## 4. Subprocess CLI Harness (`tests/e2e/conftest.py`)

Fixtures exported by [`tests/e2e/conftest.py`](../tests/e2e/conftest.py):
- `run_cli`: Runs `python -m rcwa.cli <args>` in a child subprocess with `PYTHONPATH` configured, capturing `exit_code`, `stdout`, `stderr`, combined `output`, and monotonic `duration_s`.
- `run_wrap_cli`: Runs `python -m rcwa.wrap <args>` in a child subprocess for input hashing, sidecar emission, and wrapped command exit propagation tests.
- `isolated_workspace`: Provisions a per-test directory under `tmp_path` so concurrent tests never collide on sidecars or output artifacts.
- `validators` (`InvariantValidators`): Independent assertions checking Guarantee G1 exact integer partition, G2 safety invariants, G3 byte equality, and G4 causal/capacity schedule validity across all timestamps.
- `require_rcwa`: Verifies availability of functional `rcwa` pipeline modules before executing tests.

---

## 5. Complete Fixture Catalog (`40` Files)

| Category | Fixture Path | Purpose |
|---|---|---|
| Slurm `sacct` | [`sacct/sacct_standard_26col.txt`](../tests/fixtures/sacct/sacct_standard_26col.txt) | Standard 26-column pipe-delimited Slurm export |
| Slurm `sacct` | [`sacct/sacct_empty_optional_fields.txt`](../tests/fixtures/sacct/sacct_empty_optional_fields.txt) | Empty optional fields converting to `null` |
| Slurm `sacct` | [`sacct/sacct_unknown_columns.txt`](../tests/fixtures/sacct/sacct_unknown_columns.txt) | Unmapped columns triggering `UserWarning` without failure |
| Slurm `sacct` | [`sacct/sacct_reordered_headers.txt`](../tests/fixtures/sacct/sacct_reordered_headers.txt) | Permuted 26-column header order verification |
| Slurm `sacct` | [`sacct/sacct_trailing_delimiters.txt`](../tests/fixtures/sacct/sacct_trailing_delimiters.txt) | Trailing pipe delimiters on header and rows |
| Slurm `sacct` | [`sacct/sacct_steps_rollup.txt`](../tests/fixtures/sacct/sacct_steps_rollup.txt) | Step hierarchy with `.batch`, `.0`, and `.extern` steps |
| Slurm `sacct` | [`sacct/sacct_array_heterogeneous.txt`](../tests/fixtures/sacct/sacct_array_heterogeneous.txt) | Array (`10001_0`) and heterogeneous (`10002+0`) job decomposition |
| Slurm `sacct` | [`sacct/sacct_memory_suffixes.txt`](../tests/fixtures/sacct/sacct_memory_suffixes.txt) | `M`, `Mc`, `Mn`, `G`, `Gc`, `Gn`, `K`, `Kc`, `Kn`, and `?` suffixes |
| Slurm `sacct` | [`sacct/sacct_durations_states.txt`](../tests/fixtures/sacct/sacct_durations_states.txt) | `D-HH:MM:SS`, `MM:SS.mmm`, and state qualifiers |
| Slurm `sacct` | [`sacct/sacct_running_pending.txt`](../tests/fixtures/sacct/sacct_running_pending.txt) | Active `RUNNING` and `PENDING` rows excluded from attribution |
| Slurm `sacct` | [`sacct/sacct_unattributed_missing.txt`](../tests/fixtures/sacct/sacct_unattributed_missing.txt) | Missing `MaxRSS` or `TotalCPU` for unattributed classification |
| Slurm `sacct` | [`sacct/multiday_cluster.txt`](../tests/fixtures/sacct/multiday_cluster.txt) | Multi-day cluster workload across 5 users |
| SWF | [`swf/standard_with_headers.swf`](../tests/fixtures/swf/standard_with_headers.swf) | 18-field SWF trace with header pragmas |
| SWF | [`swf/missing_fields.swf`](../tests/fixtures/swf/missing_fields.swf) | `-1` missing sentinels in SWF columns |
| SWF | [`swf/status_variations.swf`](../tests/fixtures/swf/status_variations.swf) | SWF status codes `1`, `0`, `5`, and `99` |
| SWF | [`swf/sample_workload.swf`](../tests/fixtures/swf/sample_workload.swf) | Multi-job SWF workload for simulator and report regression |
| SWF | [`swf/calibration_reference.swf`](../tests/fixtures/swf/calibration_reference.swf) | Historical wait times for simulator calibration tests |
| Edge | [`edge/empty_file.txt`](../tests/fixtures/edge/empty_file.txt) | 0-byte Slurm file |
| Edge | [`edge/header_only.txt`](../tests/fixtures/edge/header_only.txt) | 26-column header with zero data rows |
| Edge | [`edge/empty_swf.swf`](../tests/fixtures/edge/empty_swf.swf) | 0-byte SWF file |
| Edge | [`edge/malformed_row_short.txt`](../tests/fixtures/edge/malformed_row_short.txt) | Truncated lines with fewer than 26 columns |
| Edge | [`edge/corrupted_timestamps.txt`](../tests/fixtures/edge/corrupted_timestamps.txt) | Inverted and unparseable ISO timestamp strings |
| Edge | [`edge/extreme_durations.txt`](../tests/fixtures/edge/extreme_durations.txt) | Multi-year and sub-millisecond elapsed durations |
| Edge | [`edge/corrupted_binary.bin`](../tests/fixtures/edge/corrupted_binary.bin) | Raw binary file triggering decode rejection |
| Clusters | [`clusters/homogeneous_cluster.yaml`](../tests/fixtures/clusters/homogeneous_cluster.yaml) | 16-node uniform cluster specification |
| Clusters | [`clusters/heterogeneous_cluster.yaml`](../tests/fixtures/clusters/heterogeneous_cluster.yaml) | 3-partition (`compute`, `fatmem`, `gpu`) heterogeneous topology |
| Policies | [`policies/default_policy.yaml`](../tests/fixtures/policies/default_policy.yaml) | Default attribution windows and 1.2x rightsizing guardrails |
| Policies | [`policies/strict_policy.yaml`](../tests/fixtures/policies/strict_policy.yaml) | Strict policy (`min_samples: 10`, `safety_factor: 1.5`, `oom_multiplier: 2.0`) |
| Recompute | [`recompute/recompute_pairs.txt`](../tests/fixtures/recompute/recompute_pairs.txt) | Identical `(command_hash, input_hash)` duplicate executions |
| Recompute | [`recompute/recompute_command_only.txt`](../tests/fixtures/recompute/recompute_command_only.txt) | Matching commands lacking `input_hash` (`possible_recompute`) |
| Retries | [`retries/retry_chains.txt`](../tests/fixtures/retries/retry_chains.txt) | Multi-hop failed job resubmission sequences |
| Guardrails | [`guardrails/group_sample_sizes.txt`](../tests/fixtures/guardrails/group_sample_sizes.txt) | Cohorts testing sample counts 1, 4, 5, and 20 |
| Guardrails | [`guardrails/oom_groups.txt`](../tests/fixtures/guardrails/oom_groups.txt) | Cohorts triggering `OUT_OF_MEMORY` escalation |
| Sidecars | [`sidecars/sample_sidecar.json`](../tests/fixtures/sidecars/sample_sidecar.json) | Hash metadata payload formatted by `rcwa-wrap` |
| Golden | [`golden/golden_report.md`](../tests/fixtures/golden/golden_report.md) | Reference Markdown report (`multiday_cluster.txt`) |
| Golden | [`golden/golden_report.json`](../tests/fixtures/golden/golden_report.json) | Reference JSON report (`multiday_cluster.txt`) |
| Golden | [`golden/golden_report.csv`](../tests/fixtures/golden/golden_report.csv) | Reference CSV reclaim table (`multiday_cluster.txt`) |
| Golden | [`golden/golden_swf_report.md`](../tests/fixtures/golden/golden_swf_report.md) | Reference Markdown report (`sample_workload.swf`) |
| Golden | [`golden/golden_swf_report.json`](../tests/fixtures/golden/golden_swf_report.json) | Reference JSON report (`sample_workload.swf`) |
| Golden | [`golden/golden_swf_report.csv`](../tests/fixtures/golden/golden_swf_report.csv) | Reference CSV reclaim table (`sample_workload.swf`) |

---

## 6. Mathematical Verification Formulas

- **Guarantee G1 (Conservation)**:
  For every evaluated job $j$ and across trace column sums:
  $$\text{reserved\_core\_s}(j) = \text{used\_core\_s}(j) + \text{class2\_idle\_core\_s}(j) + \text{class3\_core\_s}(j) + \text{class4\_core\_s}(j) + \text{unattributed\_core\_s}(j)$$
  $$\text{reserved\_mem\_mb\_s}(j) = \text{used\_mem\_mb\_s}(j) + \text{class1\_over\_mem\_mb\_s}(j) + \text{class3\_mem\_mb\_s}(j) + \text{class4\_mem\_mb\_s}(j) + \text{unattributed\_mem\_mb\_s}(j)$$
- **Guarantee G2 (Safety Guardrails)**:
  - Peak floor across all states: $\text{recommended\_req\_mem\_mb} \ge \max_{\text{all}}(\text{max\_rss\_mb})$.
  - OOM escalation (overrides `min_samples`): $\text{recommended\_req\_mem\_mb} = \lceil \max(\text{oom\_base}) \times \text{oom\_multiplier} \rceil$ and $\text{reclaimable\_gb\_hours} = 0.0$.
  - Sample floor for non-OOM groups: $|G| < \text{min\_samples} \implies$ all recommendations are `None` with action `below_sample_floor`.
- **Guarantee G3 (Byte Determinism)**:
  Identical input traces, policies, and cluster files yield $\text{OutputBytes}(\text{Run}_1) = \text{OutputBytes}(\text{Run}_2)$ across Markdown, JSON, CSV, and Parquet outputs.
- **Guarantee G4 (Simulator Validity)**:
  Every job schedules once per scenario (`|ScheduledJobs| = |EligibleTraceJobs|`), respects submission causality ($\text{sim\_start} \ge \text{submit\_time}$), and never exceeds cluster or per-node core and memory limits at any active event timestamp.

---

## 7. E2E Tier Coverage Matrix

| Tier / Module | Primary Scope |
|---|---|
| `tier1_feature_coverage/test_f04_f09_sacct_ingest.py` | 26-column `sacct` parsing, step rollups, array/pack decomposition, durations, memory suffixes, states, TRES |
| `tier1_feature_coverage/test_f10_f14_swf_canonical.py` | 18-field SWF parsing, pragmas, per-processor conversions, 27-field schema, active job filtering, throughput |
| `tier1_feature_coverage/test_f15_f21_attribution_g1.py` | Precedence cascade, Class 3 sub-labels, retry linkage, Classes 1–2, unattributed metrics, G1 invariants |
| `tier1_feature_coverage/test_f22_f28_reclaim_recommendations_g2.py` | Grouping keys, secondary rollups, weighted reclaim scoring, memory/CPU/timeout recommendations, G2 guardrails |
| `tier1_feature_coverage/test_f29_f34_wrap_recompute.py` | `rcwa-wrap` hashing, non-blocking missing files, Class 4 detection, `command_only`, cache simulation, SWF gating |
| `tier1_feature_coverage/test_f35_f40_simulator_calibration_g4.py` | Cluster YAML loading/inference, EASY backfill, all 6 scenarios, calibration MAE/Spearman, G4 validity |
| `tier1_feature_coverage/test_f41_f44_reports_determinism_g3.py` | Markdown/JSON/CSV rendering, Data Quality accounting, golden matches, G3 determinism |
| `tier2_boundary_corner/*` (6 modules) | Sample-size thresholds, CLI errors, extreme/corrupted inputs, empty/header-only traces, null metrics, `rcwa-wrap` flags |
| `tier3_cross_feature/*` (8 modules) | OOM retry guardrails, `rcwa-wrap` sidecar Class 4 propagation, array/step suffixes, synth accuracy, scenarios, calibration, determinism, heterogeneous backfill |
| `tier4_real_world/*` (7 modules) | Full CLI pipeline runs, degraded data resilience, multiday workloads, dedicated G1–G4 verification suites |
