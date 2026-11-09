# ADR 005: Single-Process Columnar Processing with Polars

## Status
Accepted

## Context
Processing millions of scheduler accounting rows requires high data ingestion speed and expressive vector operations. External cluster dependencies or distributed query engines introduce operational overhead and reproducibility challenges.

## Options
1. **Single-Process Polars**: Use Polars and Apache Arrow in a single Python process, leveraging multi-threaded vector execution on workstation hardware.
2. **Distributed Engine (Apache Spark / Ray Data)**: Distribute tabular processing across a cluster of worker nodes.
3. **Relational Database (DuckDB / SQLite)**: Store records in an embedded relational SQL engine.

## Decision
Adopt Option 1: Single-Process Polars. Polars provides predictable performance without external daemon processes, network sockets, or container runtimes. The pipeline runs locally from a single command invocation, ensuring reproducible execution on development workstations.

## Measured or Expected Cost
Maximum trace volume is bounded by available physical RAM on the executing machine. Ingestion memory usage is tracked and reported during benchmarks to verify bounds.
