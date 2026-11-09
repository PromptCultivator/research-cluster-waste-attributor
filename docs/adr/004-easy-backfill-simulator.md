# ADR 004: EASY-Backfill Queue Simulator with Trace Calibration

## Status
Accepted

## Context
Operators cannot safely apply recommendation policies without understanding their downstream impact on queue wait times, job throughput, and cluster makespan. Schedulers in production clusters employ complex priority weighting and backfill heuristics.

## Options
1. **Deterministic FCFS with EASY Backfill**: Implement an event-driven FCFS scheduler with single-reservation EASY backfill on homogeneous nodes, with calibration against historical trace wait times.
2. **Production Scheduler Fork/Emulation**: Run an actual Slurm controller daemon in emulation mode with full multi-factor priority plugins.
3. **Queueing Theory Analytical Model**: Estimate wait time changes using theoretical M/M/c or G/G/c queueing formulas.

## Decision
Adopt Option 1: Deterministic FCFS with EASY Backfill. The simulator provides a fully reproducible and testable execution model. It guarantees that jobs never start before submit time and never exceed node capacities (G4). It runs calibration against historical trace wait times, publishing the median absolute error and Spearman correlation alongside scenario projections to bound expected prediction accuracy.

## Measured or Expected Cost
Network topology, job preemption, fair-share decay, and GPU allocation dynamics are omitted from the simulation model. Calibration error defines the verifiable confidence envelope for all reported scenario deltas.
