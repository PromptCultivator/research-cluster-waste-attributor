# Handoff Report: Explorer 1 (Architecture, Toolchain, Constraints, Benchmarks, Reports, ADRs, Phases)

## 1. Observation

### 1.1 Specification and Request Documentation
- **File Paths**:
  - `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md` (279 lines)
  - `/home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/ORIGINAL_REQUEST.md` (283 lines)
- **Observations on Core Rules & Principles**:
  - `docs/SPEC.md:17`: "The readers are engineers who run research clusters at quantitative trading firms. The repository is a showcase of engineering judgment: conservation guarantees, measured numbers, explicit assumptions, and documented trade-offs matter more than feature count."
  - `docs/SPEC.md:21-30`: 10 core working rules govern execution: sequential phase progression, zero fabricated numbers (README cells stay `TBD` until measured by `make bench` on named hardware), no proprietary references, no unapproved dependencies, no network access in tests, small imperative commits, ADRs for all decisions, comprehensive `AI-ASSISTANCE.md` logging, plain code over frameworks, and testable ambiguity resolution documented in `DECISIONS.md`.
  - `docs/SPEC.md:37-44`: Four formal guarantees:
    - (G1) Conservation: For every job, reserved resources equal used plus attributed waste with no double counting (`docs/SPEC.md:41, 157`).
    - (G2) Safety: No memory recommendation below group peak times safety factor (default 1.2), no decrease for groups with an out-of-memory kill, no recommendation below sample size floor (default 5) (`docs/SPEC.md:41, 165, 170`).
    - (G3) Determinism: Identical inputs produce byte-identical outputs (`docs/SPEC.md:41, 259`).
    - (G4) Simulator validity: Every job scheduled exactly once per scenario, never before submit time, never exceeding node capacity (`docs/SPEC.md:41, 177`).
  - `docs/SPEC.md:44`: Explicit Non-Goals: "a scheduler plugin or live rescheduling; GPU utilization attribution (GPU counts are ingested and reported but not attributed); node topology, preemption, or fair-share modeling in the simulator; a web UI; any model-based (LLM) component; Kubernetes and Ray adapters are optional Phase 8 work."
  - `docs/SPEC.md:216-218`: Allowed Dependencies:
    - Runtime: `polars`, `pyarrow`, `numpy`, `pydantic>=2`, `typer`, `pyyaml`.
    - Development: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `pyright`.
    - Conditional: `duckdb` only if measured that Polars misses throughput target.
    - Prohibitions: No other packages, no LLM clients, no telemetry.
  - `docs/SPEC.md:247`: Prohibited Vocabulary List:
    "Do not use the words 'simply', 'robust', 'seamless', 'best', 'optimal', 'clean', 'minimal', 'powerful', or 'cutting-edge' anywhere in the repository."
  - `docs/SPEC.md:198-214`: Makefile Targets:
    Lists 12 command targets (`setup`, `lint`, `typecheck`, `test`, `data`, `synth`, `run`, `calibrate`, `bench`, `bench-smoke`, `goldens`, `docker`). Together with a standard default target (`all`), this forms the 13 make targets required.
  - `docs/SPEC.md:205`: Test coverage gate is strictly 85% line coverage.
  - `docs/SPEC.md:180-197`: Benchmark protocol: `make bench SIZE=1M RUNS=5 SEED=1` generating `bench/results/bench.csv` and `bench/results/bench.md` across 10 specific metrics with 5 runs reporting median and min-max. `bench/hardware.py` collects host hardware and commit data.
  - `docs/SPEC.md:220-227`: Five required ADRs in `docs/adr/`: `001-conservation-partition.md`, `002-declared-inputs-for-recomputation.md`, `003-percentile-rightsizing-with-guardrails.md`, `004-easy-backfill-simulator.md`, `005-single-process-polars.md`.
  - `docs/SPEC.md:230-246`: README structure contains 14 numbered sections in strict sequence.
  - `docs/SPEC.md:249-262`: Phased delivery from Phase 0 (Scaffold) through Phase 7 (Synthesis/Benchmark), with optional Phase 8.
  - `docs/SPEC.md:264-273`: Standard Phase Report format contains 6 specific numbered items.
  - `docs/SPEC.md:274-283`: Definition of Done verification criteria.

### 1.2 Execution Environment Observations
- Command: `python3 --version`
  - Output: `Python 3.11.2` at `/usr/bin/python3`
- Command: `which uv make docker`
  - Output: `/usr/local/bin/uv`, `/usr/bin/make`; `docker` was not found (exit code 127).
- Command: `uv python list`
  - Output indicates availability of `cpython-3.12.16-linux-x86_64-gnu` downloadable on-demand by `uv`.
- Hardware query via Python (`/proc/cpuinfo`, `/proc/meminfo`):
  - CPU Model: `Intel(R) Xeon(R) Platinum 8481C`
  - Total Cores: `2`
  - Total RAM: `8,138,460 kB` (~7.76 GiB)
  - Kernel / OS: `Linux 6.12.105+ x86_64`
- Git commit query (`git log -n 1 --oneline`):
  - Output: `b971a09 Initial commit`
- Existing repository structure:
  - Root contains `LICENSE` (Apache-2.0 standard text with `[yyyy] [name of copyright owner]` placeholders), `docs/SPEC.md`, and `.agents/teamwork/`.

### 1.3 Exact Dependency Resolution via `uv pip compile`
Executing `uv pip compile` against the exact specification dependencies resolved the following versions without conflict:
- Runtime:
  - `polars==2.1.0`
  - `pyarrow==26.0.1`
  - `numpy==2.4.6`
  - `pydantic==2.14.3`
  - `typer==0.29.0`
  - `pyyaml==6.0.3`
- Development:
  - `pytest==9.2.0`
  - `pytest-cov==7.1.0`
  - `hypothesis==6.170.15`
  - `ruff==0.17.4`
  - `pyright==1.1.414`

---

## 2. Logic Chain

### 2.1 System Rules & Hard Constraints (Sections 1, 3, 11, 13, 16)
1. **Target Audience & Tone**: The tool is designed for quantitative trading infrastructure teams. Tone must be precise, technical, objective, and backed by measurable metrics rather than marketing claims.
2. **Four Guarantees as Architectural Anchors**:
   - G1 (Conservation): Requires integer-second and MB-second conservation arithmetic (`reserved = used + class1_or_2 + class3 + class4 + unattributed`). Floating point roundoff must not introduce divergence.
   - G2 (Safety): Guardrails protect clusters from starvation and crashes: 20% safety headroom on p99 memory, strict floor preventing any recommendation below historical maximum observed RSS, hard prohibition of resource reduction following any OOM incident, and sample size floor (min 5 jobs).
   - G3 (Determinism): Data pipelines and simulators must produce identical byte outputs for identical inputs, mandating explicit tie-breaking rules and stable sort keys.
   - G4 (Simulator Validity): Every job must appear in schedule exactly once, start timestamps must respect submission times, and aggregate node resources must never be exceeded.
3. **Strict Dependency Lockdown (Section 11)**:
   - Only 6 runtime packages and 5 development packages are authorized.
   - No external web frameworks, database engines (unless `duckdb` is formally justified), or LLM libraries are permitted.
   - All versions must be pinned exactly in `pyproject.toml` and lockfiles.
4. **Prohibited Vocabulary Enforcement (Section 13)**:
   - The prohibited list contains 9 specific terms: `"simply"`, `"robust"`, `"seamless"`, `"best"`, `"optimal"`, `"clean"`, `"minimal"`, `"powerful"`, `"cutting-edge"`.
   - CI and pre-commit checks must audit repository source code, comments, docstrings, Markdown documents, and commit logs to prevent inadvertent inclusion.
5. **Transparency & Audit Records**:
   - `docs/AI-ASSISTANCE.md`: Must catalog every single authored file and function along with human verification sign-off columns.
   - `docs/DECISIONS.md`: Must record all architectural resolutions and trade-offs made during development, prioritizing testable guarantees.
   - `docs/DATA.md`: Must track provenance, header pragmas, and citation licenses for external public traces (e.g. Parallel Workloads Archive).

### 2.2 Toolchain & Repository Architecture (Sections 4, 10, 11)
1. **Repository Layout**:
   - Root configuration: `pyproject.toml`, `Makefile`, `Dockerfile`, `.github/workflows/ci.yml`, `README.md`, `LICENSE`.
   - Application package `rcwa/`: Entry point CLI (`cli.py`), configuration schemas (`config.py`), data models (`model.py`), adapters (`adapters/sacct.py`, `adapters/swf.py`), pipeline transforms (`normalize.py`, `attribute.py`, `groups.py`, `recommend.py`, `recompute.py`, `retries.py`), simulation (`simulate.py`, `calibrate.py`), output formatting (`report.py`), wrapper utility (`wrap.py`), and trace synthesizer (`synth.py`).
   - Configuration directories: `policies/default.yaml`, `clusters/example.yaml`.
   - Test suites: `tests/unit/`, `tests/property/`, `tests/golden/`, `tests/fixtures/`.
   - Benchmarking suite: `bench/run.py`, `bench/hardware.py`, `bench/results/`.
   - Documentation: `docs/SPEC.md`, `docs/DECISIONS.md`, `docs/AI-ASSISTANCE.md`, `docs/DATA.md`, `docs/adr/`.
2. **Makefile Specifications**:
   - `all`: Default target displaying target help or executing lint + test.
   - `setup`: Creates virtual environment and installs pinned dependencies.
   - `lint`: Executes `ruff check .` and `ruff format --check .`.
   - `typecheck`: Executes `pyright`.
   - `test`: Executes `pytest --cov=rcwa --cov-fail-under=85`.
   - `data`: Fetches public SWF traces and generates documentation entries in `docs/DATA.md`.
   - `synth`: Executes synthetic trace generation (`rcwa synth --size $(SIZE) --seed $(SEED) --faults default`).
   - `run`: Full pipeline execution on trace (`rcwa ingest + attribute + recommend + simulate + report on $(TRACE)`).
   - `calibrate`: Calibrates simulator parameters against historical wait times.
   - `bench`: Executes full 5-run benchmark suite (`SIZE`, `RUNS`, `SEED`).
   - `bench-smoke`: Fast smoke benchmark verification (`SIZE=20k RUNS=1`).
   - `goldens`: Recomputes and verifies golden reference outputs.
   - `docker`: Builds container and runs containerized test suite.
3. **CI Pipeline Contract**:
   - `.github/workflows/ci.yml` must execute linting, typechecking, 85% coverage tests, and bench-smoke without internet connectivity.

### 2.3 Benchmark Specifications & Hardware Documentation (Section 9)
1. **Benchmark Methodology**:
   - Pipeline executed with 5 independent runs; reports median and min-max distribution.
   - Outputs saved to `bench/results/bench.csv` and `bench/results/bench.md`.
2. **Metric Definitions**:
   - Reclaimable core-hours & GB-hours as percentage of total cluster reservation.
   - Recall and precision per waste class compared to planted ground truth.
   - Conservation G1 verification (exact integer-second match).
   - Guardrail violation tally (must be zero).
   - Simulated wait time changes (median and 95th percentile).
   - Calibration error metrics (median absolute error and Spearman rank correlation).
   - Ingest throughput (jobs per second for both parsers).
   - Simulation throughput (jobs per second for baseline scenario).
   - Process tree peak resident set size (RSS).
   - Attribution coverage percentage.
3. **Hardware Transparency**:
   - `bench/hardware.py` inspects host CPU model, socket/core topology, physical memory, operating system, Python build, installed dependency versions, and git commit SHA.
   - Verbatim hardware report embedded in Section 3 of README; no results posted until measured on designated host.

### 2.4 Architectural Decision Records & Documentation Standards (Sections 12, 13)
1. **The Five Required ADRs**:
   - `001-conservation-partition.md`: Strict precedence sequence (Class 3 Failed -> Class 4 Redundant -> Class 2 Idle Core / Class 1 Memory Over-request). Guarantees exact conservation without double-counting; trade-off is attributing unmeasured utilization of failed jobs to Class 3.
   - `002-declared-inputs-for-recomputation.md`: Cryptographic hashing of declared input files and normalized command parameters via `rcwa-wrap`. Eliminates kernel tracing overhead; trade-off is missing undocumented duplicate jobs.
   - `003-percentile-rightsizing-with-guardrails.md`: 99th percentile sizing with 1.2x headroom factor, sample size floor, and OOM escalation. Guarantees workload stability; trade-off is leaving excess capacity unclaimed relative to median sizing.
   - `004-easy-backfill-simulator.md`: First-Come First-Served scheduling with EASY backfilling across homogeneous nodes, calibrated against empirical wait times. Guarantees deterministic evaluation; trade-off is abstracting away network topology, fair-share trees, and preemption.
   - `005-single-process-polars.md`: Single-threaded and vectorized execution through Polars in-memory columnar frames. Guarantees local reproducible laptop execution; trade-off is total trace capacity constrained by host RAM.
2. **Strict 14-Section README Structure**:
   - Order: (1) Title & Mission, (2) Status Line, (3) Results Table & Hardware Block, (4) Quick Start, (5) Problem Statement, (6) Architectural Pipeline Diagram & Workflow, (7) Guarantees G1-G4, (8) Benchmark Methodology, (9) Design Decisions Table, (10) Scope Boundaries & Omissions, (11) Related Systems, (12) Data Provenance, (13) AI Assistance Declaration, (14) Apache-2.0 License.

### 2.5 Phased Delivery Roadmap & Acceptance Criteria (Sections 14, 15, 16)
1. **Phase Sequence and Gate Criteria**:
   - **Phase 0 (Scaffold)**: Scaffold repository structure, pinned `pyproject.toml`, Makefile, Dockerfile, CI, initial documentation templates, ADR stubs, default policies, example cluster configuration. Acceptance: `make test` runs and passes on trivial fixture; CI workflow passes lint validation.
   - **Phase 1 (Adapters & Canonical Record)**: Build `model.py`, `normalize.py`, `sacct.py`, and `swf.py` parser modules with fixtures covering all edge cases. Acceptance: 100% parser test passage; 100k-row synthetic sacct export parsed with reported throughput.
   - **Phase 2 (Attribution Engine)**: Implement `attribute.py`, `groups.py`, `retries.py`, and G1 test. Acceptance: Exact conservation on fixtures and 20k synthetic trace; output Parquet and CSV generated.
   - **Phase 3 (Recommendations)**: Implement `recommend.py` and G2 property tests. Acceptance: 0 violations across 10,000 Hypothesis property trials.
   - **Phase 4 (Recomputation)**: Implement `wrap.py` (`rcwa-wrap`) and `recompute.py`. Acceptance: 100% recall and precision on planted duplicates; command-only matches excluded from Class 4 totals.
   - **Phase 5 (Simulator & Calibration)**: Implement `simulate.py`, `calibrate.py`, G4 tests. Acceptance: All scenarios complete on 20k trace; 1M-job throughput measured against 15-minute threshold.
   - **Phase 6 (Reporting)**: Implement `report.py`, ranked reclaim list, data quality tables, and golden diff tests. Acceptance: Golden reports match byte-for-byte; G3 determinism verified across repeated runs.
   - **Phase 7 (Benchmarks, Trace Ingestion, Documentation)**: Implement `synth.py`, fetch public SWF traces via `make data`, execute `bench/run.py` and `bench/hardware.py`, complete 5 ADRs, update README results. Acceptance: `make bench-smoke` passes in CI.
   - **Phase 8 (Optional Extensions)**: Kubernetes and Ray adapters, Prometheus exporter.
2. **Mandatory Phase Report Structure (Section 15)**:
   - Report must provide exactly 6 numbered sections:
     1. Phase designation and functionality summary.
     2. Command outputs, exit codes, test counts, coverage percentage, lint/typecheck status.
     3. Measured performance metrics with generating commands.
     4. Ambiguity resolutions and unstated decisions logged in `docs/DECISIONS.md`.
     5. Open questions with default fallback paths.
     6. First three concrete steps for succeeding phase.
3. **Definition of Done (Section 16)**:
   - Fresh clone executes `make setup` and `make test` within 10 minutes without external network calls.
   - End-to-end execution of `make data && make run TRACE=...` produces report with calibration metrics on real trace.
   - Real `sacct` export parses and runs through pipeline.
   - All 4 guarantees (G1–G4) enforced by named unit/property tests.
   - ADRs and documentation fully written; zero prohibited words detected.

---

## 3. Caveats
1. **Local Docker Availability**:
   - The current sandbox environment does not contain a `docker` daemon (`docker` command returned 127). The Dockerfile must be written to spec (`python:3.12-slim` running `make test`), but local testing of `make docker` requires a host with Docker installed or simulated validation.
2. **Python Version Compatibility**:
   - The host system provides Python 3.11.2, whereas the Docker specification specifies `python:3.12-slim`. All dependencies resolved via `uv pip compile` support Python 3.11 and 3.12 without modification. `uv` can install Python 3.12 if isolation is requested.
3. **Phase 8 Gating**:
   - Phase 8 (Kubernetes and Ray adapters, Prometheus exporter) is explicitly classified as optional and must not be implemented unless explicitly authorized by the user.
4. **SWF Trace Limitations for Recomputation**:
   - SWF traces do not record file input hashes. Recomputation attribution for SWF traces must be reported as "not available" rather than approximated, per Section 5.2.

---

## 4. Conclusion
The repository requirements are exhaustively defined and structurally coherent. The project enforces strict software engineering standards with 4 verifiable guarantees (G1–G4), 10 precise benchmark metrics, 5 specific architectural decisions, a strictly ordered 14-section README, and a zero-tolerance policy on 9 prohibited words. All runtime and development dependencies have been verified to compile cleanly into exact pinned versions. The repository is fully prepared for Phase 0 execution.

---

## 5. Verification Method

To independently verify the observations and conclusions in this report:

1. **Verify Prohibited Words List in Specification**:
   ```bash
   grep -n "simply" /home/antigravity/PromptCultivator/research-cluster-waste-attributor/docs/SPEC.md
   ```
2. **Verify Dependency Resolution**:
   ```bash
   uv pip compile - <<< "polars pyarrow numpy 'pydantic>=2' typer pyyaml pytest pytest-cov hypothesis ruff pyright"
   ```
3. **Verify Host Environment and Hardware**:
   ```bash
   python3 -c "import platform, os, multiprocessing; print(platform.platform(), multiprocessing.cpu_count())"
   ```
4. **Audit Proposed Documents Against Prohibited Vocabulary**:
   ```bash
   # Confirms no prohibited vocabulary is present in reports (excluding explicit rule quotations)
   grep -E -i "\b(simply|robust|seamless|best|optimal|clean|minimal|powerful|cutting-edge)\b" \
     /home/antigravity/PromptCultivator/research-cluster-waste-attributor/.agents/teamwork/explorer_survey_1/handoff.md
   ```
