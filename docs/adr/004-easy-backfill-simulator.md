# ADR 004: EASY-Backfill Queue Simulator with Trace Calibration

## Status
Accepted

## Context
Rightsizing allocations alters packing density and queue wait times non-linearly across mixed job sizes. Operators need an auditable counterfactual replay that measures queue impact and discloses fidelity error against historical scheduler waits.

## Options
1. **Deterministic Event-Driven FCFS with EASY Backfill**: Implement a self-contained heap-driven scheduler simulator supporting homogeneous or partitioned YAML cluster configurations, automatic trace-peak cluster inference, single shadow reservation, bounded backfill lookahead, six replay scenarios, and historical calibration.
2. **Slurm Emulator Fork / Daemon Execution**: Spawn modified `slurmctld` daemons in simulation mode with site plugin configurations.
3. **Analytical Queueing Approximations**: Approximate wait shifts with closed-form `M/M/c` or `G/G/c` equations.

## Decision
Adopt Option 1: Deterministic Event-Driven FCFS with EASY Backfill (implemented in [`rcwa/simulate.py`](../../rcwa/simulate.py) and [`rcwa/calibrate.py`](../../rcwa/calibrate.py)). At each simulation timestamp, completions free node resources before arrivals enqueue ordered by `(submit_time, job_id)`. When the queue head cannot start immediately, `compute_head_reservation` projects a future shadow reservation and scans up to `50` queued candidates (`max_test = 50`) for backfill whenever a candidate fits within `(current_time + expected_walltime <= res_time)` or targets nodes disjoint from the reserved node set. Every job schedules once, satisfies `sim_start >= submit_time`, and respects per-node capacity bounds (Guarantee G4). Calibration compares `baseline` simulated wait times against recorded `wait_s` using Median Absolute Error and Spearman rank correlation.

## Measured or Expected Cost
Switch/rack network topology, job preemption, fair-share priority decay, dependency holds, and GPU device scheduling are excluded from the simulator model. Published calibration error explicitly scopes the accuracy envelope of counterfactual wait-time deltas across all six scenarios (`baseline`, `mem_rightsized`, `cpu_rightsized_none`, `cpu_rightsized_proportional`, `cache_dedup`, `all`).
