# Discrete-Event EASY-Backfill Simulator

## 1. Overview

[`rcwa/simulate.py`](../../rcwa/simulate.py) replays canonical job traces through an event-driven FCFS scheduler with single-reservation EASY backfill to estimate queue wait-time, makespan, and utilization deltas across counterfactual rightsizing and caching scenarios while enforcing **Guarantee G4 (Simulator Validity)**.

---

## 2. Cluster Topology Configuration

`load_cluster_config` and `infer_cluster_from_trace` construct `ClusterConfig` and physical `NodeState` pools via `create_nodes`:
- **Homogeneous YAML** (`clusters/example.yaml`, `homogeneous_cluster.yaml`): Sets `total_nodes` (`node_count` or `nodes`), `cores_per_node`, and `mem_mb_per_node`.
- **Heterogeneous Partitioned YAML** (`heterogeneous_cluster.yaml`): Parses `partitions.<name>.{nodes, cores_per_node, mem_mb_per_node}` and filters node placement to matching job `partition` values (falling back across all cluster nodes if no node matches).
- **Trace Peak Inference (`infer_cluster_from_trace`)**: Used when `--cluster` is omitted: provisions `16` homogeneous nodes with `cores_per_node = max(32, max_cpus)` and `mem_mb_per_node = max(131072, max_mem)`.

---

## 3. EASY-Backfill Algorithm and Placement Rules

Jobs sort deterministically by `(submit_time, job_id)`. At each simulation timestamp `current_time`:

```text
[ Event Heap ] ──► Drain all events at <= current_time:
                     1. EVENT_COMPLETION (0): return allocated cores & mem to NodeStates
                     2. EVENT_ARRIVAL    (1): append to FIFO wait_queue
                     │
                     ▼
[ FCFS Queue Head ] ─► Clamp oversized head to nodes_needed * max_node_{cores,mem}
                     ├── Fits free nodes now? ──► Start job, record sim_start/wait/end, push completion
                     │
                     └── Blocked? ──► compute_head_reservation -> (res_time, res_nodes)
                                      Scan first 50 queued candidates (max_test = 50):
                                        If candidate fits free nodes now AND
                                          (current_time + expected_walltime <= res_time   -- cond_a
                                           OR cand_nodes is disjoint from res_nodes)      -- cond_b
                                        ──► Backfill candidate immediately!
```

Key deterministic mechanics:
- `expected_walltime = req_time_s` when positive, else `max(1, ceil(run_s * 1.2))`.
- Completions always process before arrivals at equal timestamps (`EVENT_COMPLETION = 0 < EVENT_ARRIVAL = 1`).
- Head requests exceeding hardware capacity clamp to `(nodes_needed * max_node_cores, nodes_needed * max_node_mem)` to prevent infinite queue deadlocks.
- Backfill lookahead bounds scanning to the first `50` waiting candidates (`bf_max_job_test` convention).
- Output DataFrame returns integer epoch seconds (`submit_time`, `sim_start`, `sim_end`, `sim_wait_s`, `run_s`) ordered by original trace index alongside summary metrics (`median_wait_s`, `p95_wait_s`, `mean_wait_s`, `makespan_s`, `core_utilization`, `mem_utilization`, `jobs_completed_per_day`).

---

## 4. Six Counterfactual Replay Scenarios

`prepare_scenario_jobs` transforms job specifications per scenario:

| Scenario Name | Job Resource Transformation | Execution Duration Model |
|---|---|---|
| `baseline` | Unmodified trace requests (`alloc_cpus`, `req_mem_mb`). | Observed `run_s` |
| `mem_rightsized` | Sets `req_mem_mb` to group recommendation from `recommend_jobs`. | Observed `run_s` |
| `cpu_rightsized_none` | Sets `alloc_cpus` to group recommendation. | Observed `run_s` unchanged |
| `cpu_rightsized_proportional` (aliases `cpu_rightsized_prop`, `cpu_rightsized`) | Sets `alloc_cpus = new_cpus` from recommendation. | Scales `run_s = max(1, ceil(run_s * (old_cpus / new_cpus)))` when `(cpu_time_used_s / run_s) > new_cpus`; otherwise unchanged |
| `cache_dedup` | Drops jobs marked redundant recomputation (`is_recompute` or `class4_core_s > 0`). | Omitted from replay |
| `all` | Applies `mem_rightsized`, `cpu_rightsized_proportional`, and `cache_dedup` together. | Scaled runtime on remaining jobs |

---

## 5. Guarantee G4: Simulator Validity

Every replay maintains and passes automated G4 invariants ([`tests/unit/test_simulate.py`](../../tests/unit/test_simulate.py)):
1. Every eligible scenario job schedules exactly once.
2. Causality holds: $\text{sim\_start} \ge \text{submit\_time}$ and $\text{sim\_end} = \text{sim\_start} + \text{run\_s}$.
3. At every active event timestamp, total allocated cores and memory never exceed any node or cluster hardware limit.
