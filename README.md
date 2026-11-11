# Research Cluster Waste Attributor (`rcwa`)

[![CI](https://github.com/PromptCultivator/research-cluster-waste-attributor/actions/workflows/ci.yml/badge.svg)](https://github.com/PromptCultivator/research-cluster-waste-attributor/actions)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code Style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

> Research computing clusters routinely suffer from idle capacity because researchers request conservative CPU and memory allocations to avoid job timeouts and out-of-memory crashes. `research-cluster-waste-attributor` (`rcwa`) ingests cluster accounting logs, partitions reserved resource waste into four conservation classes, and recommends safe, rightsized limits with built-in guardrails. It pairs these recommendations with an event-driven EASY-backfill queue simulator to forecast wait-time impacts before scheduling changes go live.

## ✨ Features

- **Exact Conservation Accounting (Guarantee G1)**: Decomposes reserved core-seconds and memory MB-seconds into four mutually exclusive categories: Class 1 Memory Over-request, Class 2 Idle CPU, Class 3 Failed/Retried Work, and Class 4 Redundant Recomputation. Reserved resources always equal used plus waste plus unattributed amounts with zero discrepancy.
- **Safety-Guarded Rightsizing (Guarantee G2)**: Recommends safe 99th-percentile resource requests with safety margins. Guarantees that limits are never reduced below historical peak usage, automatically increases memory for out-of-memory jobs, and preserves limits for low-sample groups.
- **EASY-Backfill Queue Simulator (Guarantee G4)**: Simulates queue behavior using First-Come-First-Served scheduling with non-delaying backfill reservations. Replays workloads under baseline, memory-rightsized, CPU-rightsized, and deduplicated scenarios.
- **Declared Input & Command Hashing (`rcwa-wrap`)**: Includes a lightweight job wrapper that computes SHA-256 and size/mtime hashes for declared inputs and commands to detect duplicate pipeline executions.
- **High-Throughput Analytics**: Leverages Polars and PyArrow for in-memory columnar processing, parsing and attributing tens of thousands of batch accounting records per second.
- **Automated Wait-Time Calibration**: Compares simulated baseline wait times against historical cluster logs, reporting Mean Absolute Error and Spearman rank correlation.
- **Multi-Format Export**: Generates ranked reclaim summaries and scenario metrics in Markdown, JSON, and CSV formats.

## 🚀 Getting Started

### Prerequisites

- **Python**: Version 3.11 or higher
- **Package Manager**: `pip` (v23.0+) and the standard `venv` module
- **Build Tools**: `make` and a standard POSIX shell environment
- **Version Control**: `git`

### Installation

Clone the repository and install the package along with its development dependencies:

```bash
# Clone the repository
git clone https://github.com/PromptCultivator/research-cluster-waste-attributor.git
cd research-cluster-waste-attributor

# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade package manager and install in editable mode
pip install --upgrade pip
pip install -e ".[dev]"
```

### Running the Project

Run the end-to-end attribution and simulation pipeline on the included multi-day test trace:

```bash
# Execute the full pipeline via the CLI entrypoint
rcwa run tests/fixtures/sacct/multiday_cluster.txt --output-dir data/out

# Or run using the Makefile shortcut
make run TRACE=tests/fixtures/sacct/multiday_cluster.txt
```

Generated outputs will be saved to `data/out/`:
- `canonical.parquet`: Normalized job records
- `attributed.parquet`: Per-job waste attribution classifications
- `recommendations.csv`: Rightsized CPU and memory limits per job group
- `report.md`: Markdown summary report with ranked reclaim opportunities

### Obtaining Input Data

You can provide accounting traces from production clusters or use built-in dataset sources:

- **Slurm Production Export**: Export completed jobs with standard `sacct` fields:
  ```bash
  sacct -a -P --units=M -S 2026-01-01 -E 2026-02-01 \
    --format=JobIDRaw,JobID,User,Account,Partition,QOS,JobName,Submit,Eligible,Start,End,Elapsed,State,ExitCode,\
  ReqCPUS,AllocCPUS,ReqMem,MaxRSS,AveRSS,TotalCPU,CPUTimeRAW,ReqTRES,AllocTRES,NodeList,Comment,SubmitLine > trace.sacct
  ```
- **Public Supercomputer Traces**: Download real-world traces from the Parallel Workloads Archive:
  ```bash
  make data
  ```
- **Synthetic Trace Generation**: Generate a calibrated synthetic trace with planted waste categories:
  ```bash
  make synth SIZE=20k SEED=1
  ```

For complete instructions on column requirements, step rollups, and input hashing via `rcwa-wrap`, consult the [System Input Acquisition Guide](docs/INPUTS.md).

## 💻 Usage & Code Examples

### 1. End-to-End Pipeline

Analyze a cluster trace, calculate reclaim potential, and evaluate queue impacts in one command:

```bash
rcwa run trace.sacct \
  --cluster clusters/example.yaml \
  --policy policies/default.yaml \
  --output-dir data/out
```

### 2. Step-by-Step Execution

You can run individual pipeline stages independently:

```bash
# Ingest raw Slurm sacct export or SWF trace to canonical Parquet
rcwa ingest trace.sacct --output data/out/canonical.parquet

# Attribute waste across the four conservation classes
rcwa attribute data/out/canonical.parquet --output data/out/attributed.parquet

# Generate rightsized resource limits with safety guardrails
rcwa recommend data/out/attributed.parquet --output data/out/recommendations.csv

# Simulate queue wait times under rightsized limits
rcwa simulate data/out/canonical.parquet --scenario all --output data/out/sim_metrics.json

# Render a human-readable Markdown report
rcwa report data/out/canonical.parquet --format markdown --output data/out/report.md
```

### 3. Tracking Declared Inputs with `rcwa-wrap`

To detect redundant recomputations (Class 4 waste), wrap your batch scripts to hash input files before execution:

```bash
# Compute input checksums and launch the job script
rcwa-wrap --input data/train.csv --input data/params.json -- python train.py --epochs 20
```

### 4. Python API Example

Inspect attributed waste and rightsizing recommendations directly in Python:

```python
import polars as pl
from rcwa.attribute import attribute_trace
from rcwa.recommend import recommend_jobs

# Read canonical trace records
df = pl.read_parquet("data/out/canonical.parquet")

# Attribute waste and generate recommendations
attributed_df = attribute_trace(df)
recommendations_df = recommend_jobs(attributed_df)

# View top rightsizing recommendations
print(recommendations_df.select(["group_id", "rec_mem_mb", "rec_cpus", "direction"]).head(5))
```

### 5. Report Output Preview

The pipeline generates visual summary tables highlighting reclaimable core-hours, memory savings, and queue wait times:

![Pipeline Execution and Waste Attribution Report Demo](docs/assets/report_preview.png)
*(Run `rcwa report <trace>` to render the complete interactive summary in your terminal, or inspect `data/out/report.md`.)*

## 📁 Project Structure

```text
research-cluster-waste-attributor/
├── .github/          # CI/CD workflows and automated test pipelines
├── bench/            # Benchmark harness and hardware telemetry collection
├── clusters/         # Cluster topology definitions (node counts, sockets, RAM)
├── data/             # Working directory for raw traces and analysis outputs
├── docs/             # Technical specifications and Architectural Decision Records (ADRs)
├── policies/         # Guardrail thresholds, percentile targets, and cost weights
├── rcwa/             # Core Python package source code
│   └── adapters/     # Parsers for Slurm sacct and Standard Workload Format (SWF)
├── scripts/          # Helper utilities for trace downloads and synthetic generation
├── tests/            # Test suites (unit, property, golden, and integration)
│   └── fixtures/     # Sample Slurm sacct logs and SWF workload fixtures
├── Dockerfile        # Container image definition for isolated runs
├── LICENSE           # Apache 2.0 open-source license
├── Makefile          # Developer task commands (lint, test, synth, bench)
└── pyproject.toml    # Project metadata, pinned dependencies, and tool settings
```

- `rcwa/`: Contains the primary attribution engine, safety-guarded rightsizing algorithms, EASY-backfill queue simulator, and Typer CLI command definitions.
- `rcwa/adapters/`: Provides ingestion parsers that normalize raw Slurm pipe exports and SWF traces into uniform Arrow schemas.
- `policies/`: Stores YAML configurations defining sample-size minimums, safety multipliers, and cost coefficients.
- `clusters/`: Specifies node counts and per-node CPU/memory capacities required for accurate scheduler simulation.
- `bench/`: Houses performance benchmarks measuring ingest throughput, peak memory usage, and attribution accuracy against ground-truth datasets.
- `docs/adr/`: Records design decisions for conservation partitioning, input hashing, and single-process Polars processing.

## 🤝 Contributing

Contributions to improve waste attribution accuracy, add scheduler adapters, or extend simulation capabilities are welcome.

1. **Fork & Branch**: Fork the repository on GitHub and create a dedicated branch (`git checkout -b feature/my-feature`).
2. **Implement & Test**: Add your changes and run the full validation suite:
   ```bash
   make lint       # Check formatting and linting rules with Ruff
   make typecheck  # Run static type checks with Pyright
   make test       # Execute unit, property, and golden regression tests
   ```
3. **Submit a PR**: Commit your changes with concise messages, push your branch, and open a Pull Request describing your solution and test coverage.

## 📄 License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for details.
