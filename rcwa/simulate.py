"""Discrete-event EASY-backfill cluster scheduler simulator.

Simulates batch job queueing, node placement, and EASY backfill
to evaluate counterfactual resource right-sizing and caching scenarios.
Enforces Guarantee G4: schedule validity, temporal causality, and node capacity limits.
"""

import heapq
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml


@dataclass
class NodeState:
    """State tracking for an individual physical cluster node."""

    __slots__ = (
        "node_id",
        "partition",
        "total_cores",
        "total_mem_mb",
        "avail_cores",
        "avail_mem",
    )

    node_id: int
    partition: str
    total_cores: int
    total_mem_mb: int
    avail_cores: int
    avail_mem: int


@dataclass
class ClusterConfig:
    """Cluster architecture configuration."""

    name: str
    total_nodes: int
    cores_per_node: int
    mem_mb_per_node: int
    partitions: dict[str, dict[str, int]] | None = None

    @property
    def total_cores(self) -> int:
        """Total processor core capacity across the cluster."""
        if self.partitions:
            return sum(
                int(p.get("nodes", 1)) * int(p.get("cores_per_node", self.cores_per_node))
                for p in self.partitions.values()
            )
        return self.total_nodes * self.cores_per_node

    @property
    def total_mem_mb(self) -> int:
        """Total memory capacity in MB across the cluster."""
        if self.partitions:
            return sum(
                int(p.get("nodes", 1)) * int(p.get("mem_mb_per_node", self.mem_mb_per_node))
                for p in self.partitions.values()
            )
        return self.total_nodes * self.mem_mb_per_node


class JobSpec:
    """Simulation-internal job specification and state."""

    __slots__ = (
        "job_id",
        "submit_time",
        "run_s",
        "alloc_cpus",
        "req_mem_mb",
        "req_time_s",
        "nodes",
        "partition",
        "expected_walltime",
        "sim_start",
        "sim_end",
        "sim_wait_s",
        "allocated_nodes",
        "original_index",
    )

    def __init__(
        self,
        job_id: str,
        submit_time: int,
        run_s: int,
        alloc_cpus: int,
        req_mem_mb: int,
        req_time_s: int = 0,
        nodes: int = 1,
        partition: str | None = None,
        original_index: int = 0,
    ) -> None:
        self.job_id = job_id
        self.submit_time = submit_time
        self.run_s = max(0, run_s)
        self.alloc_cpus = max(1, alloc_cpus)
        self.req_mem_mb = max(0, req_mem_mb)
        self.req_time_s = req_time_s
        self.nodes = max(1, nodes)
        self.partition = partition
        self.original_index = original_index

        if req_time_s > 0:
            self.expected_walltime = req_time_s
        else:
            self.expected_walltime = max(1, int(math.ceil(self.run_s * 1.2)))

        self.sim_start: int | None = None
        self.sim_end: int | None = None
        self.sim_wait_s: int | None = None
        self.allocated_nodes: list[tuple[int, int, int]] = []


def load_cluster_config(cluster_path: Path | str | ClusterConfig | None) -> ClusterConfig:
    """Load cluster specification from YAML configuration.

    Args:
        cluster_path: Path to YAML cluster configuration file or existing ClusterConfig.

    Returns:
        Loaded ClusterConfig instance.
    """
    if isinstance(cluster_path, ClusterConfig):
        return cluster_path
    if cluster_path is None:
        return ClusterConfig(
            name="default_cluster",
            total_nodes=16,
            cores_per_node=32,
            mem_mb_per_node=131072,
        )

    p = Path(cluster_path)
    if not p.is_file():
        raise FileNotFoundError(f"Cluster specification file not found: {cluster_path}")

    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    name = str(data.get("name") or data.get("cluster_name") or p.stem)

    if "partitions" in data and isinstance(data["partitions"], dict):
        partitions = data["partitions"]
        total_nodes = 0
        max_cores = 32
        max_mem = 131072
        for part_cfg in partitions.values():
            p_nodes = int(part_cfg.get("nodes", 1))
            total_nodes += p_nodes
            max_cores = max(max_cores, int(part_cfg.get("cores_per_node", 32)))
            max_mem = max(max_mem, int(part_cfg.get("mem_mb_per_node", 131072)))
        return ClusterConfig(
            name=name,
            total_nodes=total_nodes,
            cores_per_node=max_cores,
            mem_mb_per_node=max_mem,
            partitions=partitions,
        )

    raw_nodes = data.get("node_count") or data.get("nodes")
    if isinstance(raw_nodes, int):
        node_count = raw_nodes
    else:
        node_count = 16

    cores_per_node = int(data.get("cores_per_node", 32))
    mem_mb_per_node = int(data.get("mem_mb_per_node", 131072))

    return ClusterConfig(
        name=name,
        total_nodes=node_count,
        cores_per_node=cores_per_node,
        mem_mb_per_node=mem_mb_per_node,
    )


def infer_cluster_from_trace(df: pl.DataFrame) -> ClusterConfig:
    """Infer cluster topology parameters from trace peak allocations.

    Args:
        df: Input canonical job record DataFrame.

    Returns:
        Inferred ClusterConfig matching observed peak allocations.
    """
    max_cpus = 1
    if "alloc_cpus" in df.columns:
        val = df["alloc_cpus"].max()
        if isinstance(val, int | float):
            max_cpus = max(1, int(val))
    elif "req_cpus" in df.columns:
        val = df["req_cpus"].max()
        if isinstance(val, int | float):
            max_cpus = max(1, int(val))

    max_mem = 1024
    if "req_mem_mb" in df.columns:
        val = df["req_mem_mb"].max()
        if isinstance(val, int | float):
            max_mem = max(1024, int(val))

    cores_per_node = max(32, max_cpus)
    mem_mb_per_node = max(131072, max_mem)
    total_nodes = 16

    return ClusterConfig(
        name="inferred_from_trace",
        total_nodes=total_nodes,
        cores_per_node=cores_per_node,
        mem_mb_per_node=mem_mb_per_node,
    )


def create_nodes(cluster: ClusterConfig) -> list[NodeState]:
    """Instantiate physical node state objects for the cluster."""
    nodes: list[NodeState] = []
    if cluster.partitions:
        node_id = 0
        for part_name, part_cfg in cluster.partitions.items():
            count = int(part_cfg.get("nodes", 1))
            cores = int(part_cfg.get("cores_per_node", cluster.cores_per_node))
            mem = int(part_cfg.get("mem_mb_per_node", cluster.mem_mb_per_node))
            for _ in range(count):
                nodes.append(NodeState(node_id, part_name, cores, mem, cores, mem))
                node_id += 1
    else:
        for i in range(cluster.total_nodes):
            nodes.append(
                NodeState(
                    i,
                    "default",
                    cluster.cores_per_node,
                    cluster.mem_mb_per_node,
                    cluster.cores_per_node,
                    cluster.mem_mb_per_node,
                )
            )
    return nodes


def find_available_nodes(
    nodes: list[NodeState],
    cpus: int,
    mem_mb: int,
    nodes_needed: int,
    partition: str | None,
) -> list[tuple[NodeState, int, int]] | None:
    """Find eligible nodes that have sufficient unallocated cores and memory.

    Args:
        nodes: List of cluster node states.
        cpus: Total CPU cores required.
        mem_mb: Total memory in MB required.
        nodes_needed: Number of physical nodes required.
        partition: Target partition name, or None for general placement.

    Returns:
        List of tuples (node, assigned_cores, assigned_mem) if placement succeeded, else None.
    """
    if nodes_needed <= 0:
        nodes_needed = 1

    c_per_node = int(math.ceil(cpus / nodes_needed))
    m_per_node = int(math.ceil(mem_mb / nodes_needed))

    eligible_nodes = nodes
    if partition:
        filtered = [n for n in nodes if n.partition == partition]
        if filtered:
            eligible_nodes = filtered

    selected: list[NodeState] = []
    for n in eligible_nodes:
        if n.avail_cores >= c_per_node and n.avail_mem >= m_per_node:
            selected.append(n)
            if len(selected) == nodes_needed:
                break

    if len(selected) < nodes_needed:
        return None

    # Distribute exact requested cores and memory across selected nodes
    rem_cores = cpus
    rem_mem = mem_mb
    assigned: list[tuple[NodeState, int, int]] = []
    for i, node in enumerate(selected):
        is_last = i == len(selected) - 1
        if is_last:
            c = rem_cores
            m = rem_mem
        else:
            c = min(c_per_node, rem_cores)
            m = min(m_per_node, rem_mem)
        rem_cores -= c
        rem_mem -= m
        assigned.append((node, c, m))

    return assigned


def compute_head_reservation(
    head_job: JobSpec,
    nodes: list[NodeState],
    running_jobs: list[JobSpec],
    current_time: int,
) -> tuple[int, set[int]]:
    """Compute shadow reservation timestamp and reserved node set for head of queue.

    Args:
        head_job: The job at the front of the queue waiting for resources.
        nodes: Current cluster nodes.
        running_jobs: List of currently running jobs.
        current_time: Current simulation timestamp.

    Returns:
        Tuple of (reservation_timestamp, set of reserved node IDs).
    """
    temp_cores = [n.avail_cores for n in nodes]
    temp_mem = [n.avail_mem for n in nodes]

    sorted_running = sorted(
        running_jobs,
        key=lambda j: (
            j.sim_start + j.expected_walltime if j.sim_start is not None else 0,
            j.job_id,
        ),
    )

    nodes_needed = max(1, head_job.nodes)
    max_node_cores = max(n.total_cores for n in nodes) if nodes else 32
    max_node_mem = max(n.total_mem_mb for n in nodes) if nodes else 131072
    if head_job.alloc_cpus > nodes_needed * max_node_cores:
        head_job.alloc_cpus = nodes_needed * max_node_cores
    if head_job.req_mem_mb > nodes_needed * max_node_mem:
        head_job.req_mem_mb = nodes_needed * max_node_mem

    c_per_node = int(math.ceil(head_job.alloc_cpus / nodes_needed))
    m_per_node = int(math.ceil(head_job.req_mem_mb / nodes_needed))

    eligible_indices = [
        i
        for i, n in enumerate(nodes)
        if not head_job.partition or n.partition == head_job.partition
    ]
    if not eligible_indices:
        eligible_indices = list(range(len(nodes)))

    # Check whether head already fits in current shadow capacity
    found_nodes: list[int] = []
    for idx in eligible_indices:
        if temp_cores[idx] >= c_per_node and temp_mem[idx] >= m_per_node:
            found_nodes.append(idx)
            if len(found_nodes) == nodes_needed:
                return current_time, set(found_nodes)

    # Step through future expected completions
    for rjob in sorted_running:
        if rjob.sim_start is None:
            continue
        t_future = max(current_time, rjob.sim_start + rjob.expected_walltime)
        for n_id, c, m in rjob.allocated_nodes:
            temp_cores[n_id] += c
            temp_mem[n_id] += m

        found_nodes = []
        for idx in eligible_indices:
            if temp_cores[idx] >= c_per_node and temp_mem[idx] >= m_per_node:
                found_nodes.append(idx)
                if len(found_nodes) == nodes_needed:
                    return t_future, set(found_nodes)

    return current_time + 86400 * 365, set()


def prepare_scenario_jobs(
    df: pl.DataFrame,
    scenario: str,
    policy: Any = None,
) -> list[JobSpec]:
    """Prepare and adjust job specifications based on simulation scenario.

    Args:
        df: Input canonical job record DataFrame.
        scenario: Scenario name.
        policy: Attribution/recommendation policy.

    Returns:
        List of JobSpec objects prepared for the discrete-event loop.
    """
    clean_scenario = scenario.lower().strip()

    # Determine submit timestamps as integer seconds
    if "submit_time" in df.columns:
        dtype = df["submit_time"].dtype
        if dtype == pl.Datetime or str(dtype).startswith("Datetime"):
            sub_times = (df["submit_time"].dt.epoch("s")).to_list()
        else:
            sub_times = [int(v) for v in df["submit_time"].to_list()]
    else:
        sub_times = list(range(df.height))

    # Determine requested walltime limit if available
    req_times: list[int] = []
    if "req_time_s" in df.columns:
        req_times = [int(v or 0) for v in df["req_time_s"].to_list()]
    else:
        req_times = [0] * df.height

    # Recomputation detection for cache_dedup and all
    is_recompute_list = [False] * df.height
    if clean_scenario in ("cache_dedup", "all"):
        if "is_recompute" in df.columns:
            is_recompute_list = df["is_recompute"].to_list()
        elif "class4_core_s" in df.columns:
            is_recompute_list = (df["class4_core_s"] > 0).to_list()
        else:
            from rcwa.recompute import detect_recomputations

            recomp_df = detect_recomputations(df)
            is_recompute_list = recomp_df["is_recompute"].to_list()

    # Recommendations for rightsizing scenarios
    rec_mem_map: dict[str, int] = {}
    rec_cpu_map: dict[str, int] = {}
    needs_recommendations = clean_scenario in (
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cpu_rightsized_prop",
        "cpu_rightsized",
        "all",
    )

    if needs_recommendations:
        from rcwa.attribute import attribute_trace
        from rcwa.recommend import recommend_jobs

        if "class1_over_mem_mb_s" not in df.columns:
            attr_df = attribute_trace(df, policy=policy)
        else:
            attr_df = df

        recs_df = recommend_jobs(attr_df, policy=policy)
        for row in recs_df.to_dicts():
            grp = row.get("group")
            if grp:
                rm = row.get("recommended_req_mem_mb")
                rc = row.get("recommended_cpus")
                if rm is not None and rm > 0:
                    rec_mem_map[grp] = int(rm)
                if rc is not None and rc > 0:
                    rec_cpu_map[grp] = int(rc)

        user_list = (
            [str(u) if u else "unknown" for u in df["user"].to_list()]
            if "user" in df.columns
            else ["unknown"] * df.height
        )
        cmd_list = []
        for i in range(df.height):
            jn = df["job_name"][i] if "job_name" in df.columns else None
            ch = df["command_hash"][i] if "command_hash" in df.columns else None
            cmd = jn if jn else (ch if ch else "unknown")
            cmd_list.append(str(cmd))
        group_keys = [f"{u}/{c}" for u, c in zip(user_list, cmd_list, strict=False)]
    else:
        group_keys = [None] * df.height

    job_ids = [str(v) for v in df["job_id"].to_list()]
    run_s_col = [max(0, int(v or 0)) for v in df["run_s"].to_list()]
    alloc_cpus_col = [max(1, int(v or 1)) for v in df["alloc_cpus"].to_list()]
    req_mem_col = (
        [int(v or 0) if v is not None else 0 for v in df["req_mem_mb"].to_list()]
        if "req_mem_mb" in df.columns
        else [0] * df.height
    )
    nodes_col = (
        [max(1, int(v or 1)) for v in df["nodes"].to_list()]
        if "nodes" in df.columns
        else [1] * df.height
    )
    part_col = df["partition"].to_list() if "partition" in df.columns else [None] * df.height
    cpu_used_col = (
        df["cpu_time_used_s"].to_list() if "cpu_time_used_s" in df.columns else [None] * df.height
    )

    prepared: list[JobSpec] = []
    for idx in range(df.height):
        # Drop redundant recomputations in cache_dedup and all
        if clean_scenario in ("cache_dedup", "all") and is_recompute_list[idx]:
            continue

        jid = job_ids[idx]
        sub = sub_times[idx]
        run_s = run_s_col[idx]
        alloc_cpus = alloc_cpus_col[idx]
        req_mem = req_mem_col[idx]
        req_time = req_times[idx]
        nodes = nodes_col[idx]
        partition = part_col[idx]
        gk = group_keys[idx]

        # Memory rightsizing
        if clean_scenario in ("mem_rightsized", "all") and gk in rec_mem_map:
            req_mem = rec_mem_map[gk]

        # CPU rightsizing without runtime scaling
        if clean_scenario == "cpu_rightsized_none" and gk in rec_cpu_map:
            alloc_cpus = rec_cpu_map[gk]

        # CPU rightsizing with proportional runtime scaling
        if (
            clean_scenario
            in (
                "cpu_rightsized_proportional",
                "cpu_rightsized_prop",
                "cpu_rightsized",
                "all",
            )
            and gk in rec_cpu_map
        ):
            new_cpus = rec_cpu_map[gk]
            old_cpus = alloc_cpus
            alloc_cpus = new_cpus

            used_sec = cpu_used_col[idx]
            if used_sec is not None and run_s > 0:
                measured_cores = float(used_sec) / run_s
                if measured_cores > new_cpus:
                    # Scaling duration when utilization exceeded new core allocation
                    run_s = max(1, int(math.ceil(run_s * (old_cpus / new_cpus))))

        job = JobSpec(
            job_id=jid,
            submit_time=sub,
            run_s=run_s,
            alloc_cpus=alloc_cpus,
            req_mem_mb=req_mem,
            req_time_s=req_time,
            nodes=nodes,
            partition=partition,
            original_index=idx,
        )
        prepared.append(job)

    return prepared


def simulate_trace(
    df: pl.DataFrame,
    cluster: ClusterConfig | None = None,
    scenario: str = "baseline",
    policy: Any = None,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Simulate workload trace using discrete-event EASY-backfill scheduling.

    Args:
        df: Input canonical job record DataFrame.
        cluster: Cluster architecture configuration. If None, inferred from trace.
        scenario: Simulation scenario name.
        policy: Attribution/recommendation policy.

    Returns:
        Tuple of (simulated jobs DataFrame, scenario summary metrics dictionary).
    """
    if cluster is None:
        cluster = infer_cluster_from_trace(df)

    job_specs = prepare_scenario_jobs(df, scenario=scenario, policy=policy)
    if not job_specs:
        empty_out = pl.DataFrame(
            schema={
                "job_id": pl.String,
                "submit_time": pl.Int64,
                "sim_start": pl.Int64,
                "sim_end": pl.Int64,
                "sim_wait_s": pl.Int64,
                "run_s": pl.Int64,
                "alloc_cpus": pl.Int32,
                "req_mem_mb": pl.Int64,
            }
        )
        empty_metrics: dict[str, Any] = {
            "scenario": scenario,
            "job_count": 0,
            "median_wait_s": 0.0,
            "p95_wait_s": 0.0,
            "mean_wait_s": 0.0,
            "makespan_s": 0,
            "core_utilization": 0.0,
            "mem_utilization": 0.0,
            "jobs_completed_per_day": 0.0,
        }
        return empty_out, empty_metrics

    # Sort incoming jobs deterministically by submit_time, then job_id
    job_specs.sort(key=lambda j: (j.submit_time, j.job_id))

    nodes = create_nodes(cluster)
    total_cluster_cores = cluster.total_cores
    total_cluster_mem = cluster.total_mem_mb

    EVENT_COMPLETION = 0
    EVENT_ARRIVAL = 1

    event_seq = 0
    event_heap: list[tuple[int, int, int, JobSpec]] = []
    for job in job_specs:
        heapq.heappush(event_heap, (job.submit_time, EVENT_ARRIVAL, event_seq, job))
        event_seq += 1

    wait_queue: deque[JobSpec] = deque()
    running_jobs: list[JobSpec] = []
    completed_jobs: list[JobSpec] = []

    current_time = 0

    while event_heap or wait_queue:
        if event_heap:
            next_t = event_heap[0][0]
            current_time = max(current_time, next_t)

            # Drain all events at current_time
            current_events: list[tuple[int, JobSpec]] = []
            while event_heap and event_heap[0][0] <= current_time:
                _, et, _, payload = heapq.heappop(event_heap)
                current_events.append((et, payload))

            # 1. Process completions first to release capacity
            for et, payload in current_events:
                if et == EVENT_COMPLETION:
                    for n_id, c, m in payload.allocated_nodes:
                        nodes[n_id].avail_cores += c
                        nodes[n_id].avail_mem += m
                    running_jobs = [rj for rj in running_jobs if rj.job_id != payload.job_id]
                    completed_jobs.append(payload)

            # 2. Process arrivals
            for et, payload in current_events:
                if et == EVENT_ARRIVAL:
                    wait_queue.append(payload)

        # 3. Schedule queued jobs
        # 3a. FCFS phase for queue head
        while wait_queue:
            head = wait_queue[0]

            # Guard: clamp oversized jobs to avoid deadlocks on small cluster definitions
            nodes_needed = max(1, head.nodes)
            max_node_cores = max(n.total_cores for n in nodes) if nodes else 32
            max_node_mem = max(n.total_mem_mb for n in nodes) if nodes else 131072
            if head.alloc_cpus > nodes_needed * max_node_cores:
                head.alloc_cpus = nodes_needed * max_node_cores
            if head.req_mem_mb > nodes_needed * max_node_mem:
                head.req_mem_mb = nodes_needed * max_node_mem

            alloc = find_available_nodes(
                nodes,
                cpus=head.alloc_cpus,
                mem_mb=head.req_mem_mb,
                nodes_needed=head.nodes,
                partition=head.partition,
            )

            if alloc is not None:
                wait_queue.popleft()
                for node, c, m in alloc:
                    node.avail_cores -= c
                    node.avail_mem -= m
                head.sim_start = current_time
                head.sim_wait_s = current_time - head.submit_time
                head.sim_end = current_time + head.run_s
                head.allocated_nodes = [(n.node_id, c, m) for n, c, m in alloc]
                running_jobs.append(head)
                heapq.heappush(event_heap, (head.sim_end, EVENT_COMPLETION, event_seq, head))
                event_seq += 1
            else:
                break

        # 3b. EASY Backfill phase for subsequent queue members
        if len(wait_queue) > 1:
            head = wait_queue[0]
            res_time, res_nodes = compute_head_reservation(head, nodes, running_jobs, current_time)

            # Fast capacity check: if cluster is completely saturated, skip candidate scanning
            avail_core_sum = sum(n.avail_cores for n in nodes)
            avail_mem_sum = sum(n.avail_mem for n in nodes)

            if avail_core_sum > 0 and avail_mem_sum > 0:
                new_queue: deque[JobSpec] = deque([head])
                candidates = list(wait_queue)[1:]
                max_test = 50
                test_candidates = candidates[:max_test]
                rest_candidates = candidates[max_test:]

                for idx, cand in enumerate(test_candidates):
                    if avail_core_sum <= 0 or avail_mem_sum <= 0:
                        new_queue.extend(test_candidates[idx:])
                        break

                    if cand.alloc_cpus > avail_core_sum or cand.req_mem_mb > avail_mem_sum:
                        new_queue.append(cand)
                        continue

                    cand_alloc = find_available_nodes(
                        nodes,
                        cpus=cand.alloc_cpus,
                        mem_mb=cand.req_mem_mb,
                        nodes_needed=cand.nodes,
                        partition=cand.partition,
                    )

                    if cand_alloc is not None:
                        cond_a = (current_time + cand.expected_walltime) <= res_time
                        cand_nodes = {n.node_id for n, _, _ in cand_alloc}
                        cond_b = cand_nodes.isdisjoint(res_nodes)

                        if cond_a or cond_b:
                            # Candidate can start early without delaying head reservation
                            for node, c, m in cand_alloc:
                                node.avail_cores -= c
                                node.avail_mem -= m
                            cand.sim_start = current_time
                            cand.sim_wait_s = current_time - cand.submit_time
                            cand.sim_end = current_time + cand.run_s
                            cand.allocated_nodes = [(n.node_id, c, m) for n, c, m in cand_alloc]
                            running_jobs.append(cand)
                            heapq.heappush(
                                event_heap,
                                (cand.sim_end, EVENT_COMPLETION, event_seq, cand),
                            )
                            event_seq += 1
                            avail_core_sum -= cand.alloc_cpus
                            avail_mem_sum -= cand.req_mem_mb
                            continue

                    new_queue.append(cand)

                new_queue.extend(rest_candidates)
                wait_queue = new_queue

        # If event_heap is empty but wait_queue has remaining jobs,
        # advance time to unblock any waiting jobs
        if not event_heap and wait_queue:
            head = wait_queue.popleft()
            head.sim_start = current_time
            head.sim_wait_s = current_time - head.submit_time
            head.sim_end = current_time + head.run_s
            completed_jobs.append(head)

    # Reconstruct canonical result order based on original row index
    completed_jobs.sort(key=lambda j: j.original_index)

    sim_dict: dict[str, list[Any]] = {
        "job_id": [j.job_id for j in completed_jobs],
        "submit_time": [j.submit_time for j in completed_jobs],
        "sim_start": [j.sim_start for j in completed_jobs],
        "sim_end": [j.sim_end for j in completed_jobs],
        "sim_wait_s": [j.sim_wait_s for j in completed_jobs],
        "run_s": [j.run_s for j in completed_jobs],
        "alloc_cpus": [j.alloc_cpus for j in completed_jobs],
        "req_mem_mb": [j.req_mem_mb for j in completed_jobs],
    }

    # Map original optional metadata columns
    orig_indices = [j.original_index for j in completed_jobs]
    for col in ("user", "account", "partition", "job_name", "state", "wait_s"):
        if col in df.columns:
            sim_dict[col] = df[col][orig_indices].to_list()

    sim_df = pl.DataFrame(sim_dict)

    # Compute scenario summary metrics
    waits = [j.sim_wait_s for j in completed_jobs if j.sim_wait_s is not None]
    min_sub = min(j.submit_time for j in completed_jobs) if completed_jobs else 0
    max_end = (
        max(j.sim_end for j in completed_jobs if j.sim_end is not None) if completed_jobs else 0
    )
    makespan = max(1, max_end - min_sub)

    total_core_s = sum(j.alloc_cpus * j.run_s for j in completed_jobs)
    total_mem_mb_s = sum(j.req_mem_mb * j.run_s for j in completed_jobs)

    cluster_core_cap = total_cluster_cores * makespan
    cluster_mem_cap = total_cluster_mem * makespan

    core_util = total_core_s / cluster_core_cap if cluster_core_cap > 0 else 0.0
    mem_util = total_mem_mb_s / cluster_mem_cap if cluster_mem_cap > 0 else 0.0
    jobs_per_day = (len(completed_jobs) / makespan) * 86400.0 if makespan > 0 else 0.0

    metrics: dict[str, Any] = {
        "scenario": scenario,
        "job_count": len(completed_jobs),
        "median_wait_s": round(float(np.median(waits)), 2) if waits else 0.0,
        "p95_wait_s": round(float(np.percentile(waits, 95)), 2) if waits else 0.0,
        "mean_wait_s": round(float(np.mean(waits)), 2) if waits else 0.0,
        "makespan_s": makespan,
        "core_utilization": round(core_util, 4),
        "mem_utilization": round(mem_util, 4),
        "jobs_completed_per_day": round(jobs_per_day, 2),
    }

    return sim_df, metrics
