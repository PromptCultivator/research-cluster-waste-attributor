# ADR 002: Declared Inputs for Recomputation Detection

## Status
Accepted

## Context
Redundant recomputation occurs when identical jobs produce duplicate outputs from identical inputs. Identifying duplicates requires tracking what input files each job consumed. Batch schedulers like Slurm record job command names but not file descriptors or input data versions.

## Options
1. **Explicit Declared Input Hashing (`rcwa-wrap`)**: Hash user-declared input files via a lightweight CLI wrapper, recording composite hashes in scheduler comments and sidecar metadata.
2. **System Call Interception (eBPF / ptrace / LD_PRELOAD)**: Trace open/read system calls dynamically during execution to log accessed files.
3. **Command-Only Matching**: Rely strictly on executable names and argument strings without validating input file contents.

## Decision
Adopt Option 1: Explicit Declared Input Hashing. The `rcwa-wrap` utility computes sha256 checksums (or size and mtime descriptors for large files) for explicitly declared paths, normalizes command flags, records the hash via Slurm comment updates and sidecar JSON files, and executes the child command. Command-only matches without input hashes are categorized under `possible_recompute` with lower confidence and excluded from Class 4 totals.

## Measured or Expected Cost
Jobs executed without `rcwa-wrap` cannot be attributed to Class 4 with high confidence. This limitation is accounted for in data-quality and attribution coverage metrics rather than inferred heuristically.
