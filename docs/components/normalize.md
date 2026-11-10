# Normalization Engine

## 1. Overview

The normalization engine (`rcwa/normalize.py`) standardizes diverse string representations, heterogeneous duration formats, and varying memory units into canonical numeric values. Consistent normalization is necessary to prevent integer truncation errors and ensure Guarantee G1 conservation holds across all accounting records.

---

## 2. Duration and Timestamp Normalization

Schedulers format elapsed times and CPU consumption in multiple representations:
- `D-HH:MM:SS` (e.g. `2-04:30:15` = 189,015 seconds)
- `HH:MM:SS` (e.g. `01:15:30` = 4,530 seconds)
- `MM:SS.mmm` (e.g. `12:34.500` = 754.5 seconds)
- `SS.mmm` (e.g. `45.120` = 45.12 seconds)
- Integer seconds (e.g. `3600`)

### Normalization Logic

```python
def parse_duration_seconds(val: str | None) -> float | None:
    # Handles days, hours, minutes, seconds, and millisecond fractions
    # Returns float seconds or None if unparseable / missing
```

Timestamps in ISO-8601 (`YYYY-MM-DDTHH:MM:SS`) or Slurm's standard date format (`YYYY-MM-DDTHH:MM:SS`) are parsed into UTC Unix seconds.

---

## 3. Memory Specification Normalization

Slurm reports memory requests and resident set sizes with distinct unit prefixes and allocation semantics:

### 3.1 Requested Memory (`ReqMem`)

The `ReqMem` field contains numeric values followed by optional unit and scope indicators:
- Unit Suffixes: `K` (Kilobytes), `M` (Megabytes), `G` (Gigabytes), `T` (Terabytes), `P` (Petabytes). Default unit in `sacct --units=M` is Megabytes.
- Scope Flags:
  - `c` (Per-CPU): Multiplied by `alloc_cpus` to determine total job memory.
  - `n` (Per-Node): Multiplied by `nodes` count to determine total job memory.
  - No flag: Treated as total job memory.

Example Conversions:
- `4000Mc` with `alloc_cpus = 4` $\to 4000 \times 4 = 16,000\text{ MB}$.
- `16G` with `alloc_cpus = 8` $\to 16 \times 1024 = 16,384\text{ MB}$.
- `64Gn` with `nodes = 2` $\to 64 \times 1024 \times 2 = 131,072\text{ MB}$.

### 3.2 Resident Set Size (`MaxRSS`, `AveRSS`)

Step RSS values represent consumed physical RAM:
- Scaled to integer megabytes:
  - `K` $\to \text{round}(K / 1024)$
  - `M` $\to \text{round}(M)$
  - `G` $\to \text{round}(G \times 1024)$
  - `T` $\to \text{round}(T \times 1024 \times 1024)$

Negative values or unparseable strings are normalized to `null`.

---

## 4. State String Normalization

Slurm appends qualifiers to state indicators (e.g., `CANCELLED by 1002`, `CANCELLED+`). The normalization engine strips qualifier suffixes to map raw strings to canonical states:

- `CANCELLED*` $\to$ `CANCELLED`
- `OUT_OF_MEMORY*` $\to$ `OUT_OF_MEMORY`
- `TIMEOUT*` $\to$ `TIMEOUT`
- `NODE_FAIL*` $\to$ `NODE_FAIL`
- `PREEMPTED*` $\to$ `PREEMPTED`
- `COMPLETED*` $\to$ `COMPLETED`
- `FAILED*` $\to$ `FAILED`

---

## 5. TRES (Trackable Resource) String Parsing

Slurm allocates compound resources via `ReqTRES` and `AllocTRES` formatted as comma-separated key-value pairs:
`cpu=16,mem=64G,node=2,billing=16,gres/gpu=4`

The parser extracts:
- `cpu`: Integer core count.
- `mem`: Memory capacity, converted via standard memory rules.
- `node`: Physical node count.
- `gres/gpu` or `gpu`: Total GPU device count.
