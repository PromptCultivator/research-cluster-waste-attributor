# Discrete-Event EASY-Backfill Simulator

## 1. Overview

The scheduler simulator (`rcwa/simulate.py`) evaluates the system-wide effects of right-sizing recommendations before changes are applied in production. By replaying historical job arrival traces through an EASY-backfill scheduling loop across counterfactual scenarios, the simulator quantifies shifts in queue delays, makespan, and node utilization.

---

## 2. Cluster Architecture Model

The cluster is modeled as $N$ identical physical compute nodes:
- `cores_per_node`: Total processor cores available per node.
- `mem_mb_per_node`: Total RAM available per node in megabytes.

Node specifications are loaded from cluster YAML definitions (e.g. `clusters/example.yaml`) or inferred from peak allocations observed in the input trace.

---

## 3. EASY-Backfill Scheduling Algorithm

The simulator implements a deterministic event-driven loop with an event heap and per-node free-capacity indices:

```
[ Event Heap: Job Arrivals and Completions ]
                     │
                     ▼
         [ Advance to Next Event Time ]
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
  [ Release Resources ]     [ Enqueue Arriving Jobs ]
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
        [ Can Head Job Start Now? ]
         ├── YES ──► Allocate Nodes -> Start Job -> Push Completion Event
         │
         └── NO  ──► Reserve Earliest Feasible Start Time for Head Job
                     │
                     ▼
        [ Scan Subsequent Queued Jobs for Backfilling ]
         For each queued candidate:
             Can candidate fit on available nodes now?
             AND does candidate finish BEFORE head job reservation time?
                 ├── YES ──► Backfill Immediately!
                 └── NO  ──► Remain in Queue
```

### Determinism Rules:
- Ties at equal submission times are broken deterministically by `(submit_time, job_id)`.
- No pseudo-random scheduling choices exist. Identical traces yield byte-identical schedules.

---

## 4. Replay Scenarios

The simulator re-executes the trace through six distinct scenarios:

| Scenario Name | Description | Runtime Model |
|---|---|---|
| `baseline` | Replays original requested resources without alteration. | Observed `run_s` |
| `mem_rightsized` | Memory requests set to recommended `req_mem_mb`. | Observed `run_s` |
| `cpu_rightsized_none` | CPU requests set to recommended `cpus`. | Runtime unchanged (`run_s`) |
| `cpu_rightsized_prop` | CPU requests set to recommended `cpus`. | Runtime scales proportionally: $\text{run\_s} \times \frac{\text{alloc\_cpus}}{\text{rec\_cpus}}$ when measured utilization exceeded new allocation. |
| `cache_dedup` | Removes redundant recomputation jobs (Class 4). | Omitted from replay |
| `all` | Combines memory and CPU rightsizing with cache deduplication. | Scaled runtime model |

---

## 5. Guarantee G4: Simulator Validity

Simulation runs enforce Guarantee G4 across all scenarios:
1. Every input job schedules exactly once.
2. Scheduled start time is never earlier than job arrival:
   $$\text{sim\_start} \ge \text{submit\_time}$$
3. Aggregate assigned capacity on any node never exceeds physical node limits at any point in simulated time:
   $$\sum_{j \in \text{active}(n, t)} \text{cores}_j \le \text{cores\_per\_node}$$
   $$\sum_{j \in \text{active}(n, t)} \text{mem}_j \le \text{mem\_mb\_per\_node}$$
