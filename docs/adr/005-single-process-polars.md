# ADR 005: Single-Process Columnar Processing with Polars

## Status
Accepted

## Context
Processing large Slurm accounting exports and public SWF traces requires fast text ingestion and vectorized aggregations without introducing external database servers, distributed workers, or nondeterministic container networking overhead.

## Options
1. **Single-Process Polars & Apache Arrow**: Execute all tabular normalization, attribution, aggregation, and reporting inside one Python process backed by Polars (`1.14.0`) and PyArrow (`18.1.0`), lazily loading PyArrow/Pydantic objects only when needed.
2. **Distributed Engine (Apache Spark / Ray Data)**: Spin up cluster workers for batch trace transformation.
3. **Embedded Relational SQL Engine (DuckDB / SQLite)**: Offload record storage and joins to an embedded SQL runtime.

## Decision
Adopt Option 1: Single-Process Polars & Apache Arrow (declared in [`pyproject.toml`](../../pyproject.toml) and [`rcwa/model.py`](../../rcwa/model.py)). All trace transformations run deterministically in-process with zero external daemons or background network services. Lazy module-level attribute loading defers `pyarrow` and `pydantic` import costs (~240ms) during fast CLI invocations while preserving `POLARS_CANONICAL_SCHEMA` and full static type safety.

## Measured or Expected Cost
Peak dataset size is bounded by single-host physical RAM. On `Intel(R) Xeon(R) Platinum 8481C` (`bench/results/bench.md`), full 20,000-job end-to-end execution achieves `34,610.4` jobs/s `sacct` ingestion and `90,486.8` jobs/s baseline simulation while keeping peak process memory at `310.77 MB`.
