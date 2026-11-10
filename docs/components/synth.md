# Synthetic Trace Generator

## 1. Overview

The synthetic trace generator (`rcwa/synth.py`) generates realistic batch-scheduler accounting traces containing planted waste patterns, known ground truth labels, and configurable fault injection profiles. It serves as the primary verification tool for pipeline benchmarks, test suites, and regression testing under Guarantee G1, G2, and G4.

---

## 2. Generation Engine Capabilities

The generator synthesizes multi-day cluster traces parameterized by workload volume and random seed:

```bash
rcwa synth --size 20k --seed 1 --faults default --output data/raw/synth_20k.sacct
```

### 2.1 Planted Waste Profiles

The generator injects known waste categories across configured user groups:

1. **Over-Requested Memory**:
   Simulates jobs requesting 64 GB of memory while internal resident size never exceeds 8 GB ($MaxRSS \approx 8\text{ GB}$).
2. **Idle Reserved Multi-Core**:
   Simulates jobs allocating 16 or 32 CPU cores while executing single-threaded python scripts ($\text{cpu\_time\_used\_s} \approx \text{run\_s}$).
3. **Out-of-Memory Terminations & Resubmissions**:
   Injects `OUT_OF_MEMORY` exit events where jobs allocate 4 GB and attempt to allocate 6 GB, followed by a resubmission with 8 GB.
4. **Wallclock Timeouts**:
   Simulates jobs whose elapsed time reaches the requested time limit exactly, triggering `TIMEOUT` terminations.
5. **Early Aborts**:
   Injects failures within 10–30 seconds of execution representing configuration or syntax errors.
6. **Redundant Recomputations**:
   Produces pairs of identical jobs matching both command lines and declared input file digests.

### 2.2 Ground Truth Emission

When generating traces, the synthetic generator produces an accompanying ground-truth metadata artifact recording:
- Exact injected waste per job in core-seconds and megabyte-seconds.
- Planted waste category labels.
- Planted retry chain links.
- Known duplicate execution pairs.

This enables benchmark test suites to measure exact precision and recall metrics across all four attribution classes during verification runs.
