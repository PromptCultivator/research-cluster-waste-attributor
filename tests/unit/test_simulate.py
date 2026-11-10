"""Unit test suite for discrete-event EASY-backfill simulator and Guarantee G4."""

from pathlib import Path

import polars as pl
import pytest

from rcwa.simulate import (
    ClusterConfig,
    create_nodes,
    find_available_nodes,
    infer_cluster_from_trace,
    load_cluster_config,
    simulate_trace,
)


def _build_test_trace(n_jobs: int = 10) -> pl.DataFrame:
    """Build a deterministic test trace for simulation tests."""
    rows = []
    for i in range(n_jobs):
        sub = 1000 + i * 30
        run = 60 + (i % 3) * 30
        rows.append(
            {
                "job_id": f"job_{i}",
                "source": "sacct",
                "user": f"user_{i % 3}",
                "job_name": f"task_{i % 2}",
                "command_hash": f"cmd_{i % 2}",
                "input_hash": f"hash_{i % 2}",
                "submit_time": sub,
                "start_time": sub,
                "end_time": sub + run,
                "run_s": run,
                "wait_s": 0,
                "alloc_cpus": 4 if i % 2 == 0 else 8,
                "req_mem_mb": 4096 if i % 2 == 0 else 8192,
                "cpu_time_used_s": 30.0,
                "max_rss_mb": 2048,
                "nodes": 1,
                "partition": "compute" if i % 2 == 0 else "gpu",
                "state": "COMPLETED",
                "reserved_core_s": 240,
                "reserved_mem_mb_s": 245760,
            }
        )
    return pl.DataFrame(rows)


def brute_force_verify_schedule(
    sim_df: pl.DataFrame,
    cluster: ClusterConfig,
) -> bool:
    """Brute-force second-by-second capacity and causality validator for small traces."""
    jobs = sim_df.to_dicts()
    if not jobs:
        return True

    min_time = min(int(j["submit_time"]) for j in jobs)
    max_time = max(int(j["sim_end"]) for j in jobs)

    # 1. Causality check
    for j in jobs:
        if int(j["sim_start"]) < int(j["submit_time"]):
            return False
        if int(j["sim_end"]) < int(j["sim_start"]):
            return False

    # 2. Second-by-second capacity check
    max_cores = cluster.total_cores
    max_mem = cluster.total_mem_mb

    for t in range(min_time, max_time + 1):
        active_cores = 0
        active_mem = 0
        for j in jobs:
            if int(j["sim_start"]) <= t < int(j["sim_end"]):
                active_cores += int(j["alloc_cpus"])
                active_mem += int(j["req_mem_mb"])
        if active_cores > max_cores or active_mem > max_mem:
            return False

    return True


def test_cluster_config_loading(tmp_path: Path) -> None:
    """Verify cluster YAML configuration parsing for homogeneous and heterogeneous topologies."""
    # Default fallback
    cfg_default = load_cluster_config(None)
    assert cfg_default.total_nodes == 16
    assert cfg_default.cores_per_node == 32
    assert cfg_default.mem_mb_per_node == 131072
    assert cfg_default.total_cores == 512

    # Homogeneous YAML
    homo_file = tmp_path / "homo.yaml"
    homo_file.write_text(
        "name: test_homo\nnode_count: 8\ncores_per_node: 16\nmem_mb_per_node: 65536\n"
    )
    cfg_homo = load_cluster_config(homo_file)
    assert cfg_homo.total_nodes == 8
    assert cfg_homo.cores_per_node == 16
    assert cfg_homo.total_cores == 128
    assert cfg_homo.total_mem_mb == 8 * 65536

    # Heterogeneous YAML
    het_file = tmp_path / "het.yaml"
    het_content = (
        "name: test_het\n"
        "partitions:\n"
        "  standard:\n"
        "    nodes: 4\n"
        "    cores_per_node: 16\n"
        "    mem_mb_per_node: 32768\n"
        "  fat:\n"
        "    nodes: 2\n"
        "    cores_per_node: 32\n"
        "    mem_mb_per_node: 131072\n"
    )
    het_file.write_text(het_content)
    cfg_het = load_cluster_config(het_file)
    assert cfg_het.total_nodes == 6
    assert cfg_het.total_cores == (4 * 16 + 2 * 32)
    assert cfg_het.total_mem_mb == (4 * 32768 + 2 * 131072)

    # Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_cluster_config(tmp_path / "nonexistent.yaml")


def test_infer_cluster_from_trace() -> None:
    """Verify inference of cluster node parameters from observed trace allocations."""
    df = pl.DataFrame(
        {
            "alloc_cpus": [4, 64, 16],
            "req_mem_mb": [1024, 262144, 4096],
        }
    )
    inferred = infer_cluster_from_trace(df)
    assert inferred.cores_per_node == 64
    assert inferred.mem_mb_per_node == 262144
    assert inferred.total_nodes == 16


def test_node_allocation_and_release() -> None:
    """Verify node search, multi-node placement, and resource release."""
    cluster = ClusterConfig(name="c", total_nodes=2, cores_per_node=8, mem_mb_per_node=16384)
    nodes = create_nodes(cluster)

    # Single-node fit
    alloc1 = find_available_nodes(nodes, cpus=4, mem_mb=4096, nodes_needed=1, partition=None)
    assert alloc1 is not None
    assert len(alloc1) == 1
    node_sel, c, m = alloc1[0]
    node_sel.avail_cores -= c
    node_sel.avail_mem -= m
    assert node_sel.avail_cores == 4
    assert node_sel.avail_mem == 12288

    # Second allocation fits on same node
    alloc2 = find_available_nodes(nodes, cpus=4, mem_mb=4096, nodes_needed=1, partition=None)
    assert alloc2 is not None
    assert alloc2[0][0].node_id == node_sel.node_id

    # Third allocation must go to second node
    alloc2[0][0].avail_cores -= alloc2[0][1]
    alloc2[0][0].avail_mem -= alloc2[0][2]
    alloc3 = find_available_nodes(nodes, cpus=4, mem_mb=4096, nodes_needed=1, partition=None)
    assert alloc3 is not None
    assert alloc3[0][0].node_id == 1

    # Overcapacity returns None
    alloc_too_big = find_available_nodes(
        nodes, cpus=32, mem_mb=65536, nodes_needed=1, partition=None
    )
    assert alloc_too_big is None


def test_easy_backfill_candidate_selection() -> None:
    """Verify that EASY backfill allows short candidates to jump the queue without delaying head reservation."""
    # Cluster: 1 node with 8 cores, 16384 MB
    cluster = ClusterConfig(
        name="single_node", total_nodes=1, cores_per_node=8, mem_mb_per_node=16384
    )

    # Trace:
    # Job 1: runs for 100s, uses 6 cores (leaves 2 cores free)
    # Job 2: arrives at 10s, needs 8 cores (head of queue, blocked until t=100s)
    # Job 3: arrives at 20s, needs 2 cores, runs for 30s (fits on remaining 2 cores and finishes before t=100s)
    rows = [
        {
            "job_id": "j1",
            "submit_time": 0,
            "run_s": 100,
            "alloc_cpus": 6,
            "req_mem_mb": 4096,
            "wait_s": 0,
        },
        {
            "job_id": "j2",
            "submit_time": 10,
            "run_s": 50,
            "alloc_cpus": 8,
            "req_mem_mb": 8192,
            "wait_s": 0,
        },
        {
            "job_id": "j3",
            "submit_time": 20,
            "run_s": 30,
            "alloc_cpus": 2,
            "req_mem_mb": 2048,
            "wait_s": 0,
        },
    ]
    df = pl.DataFrame(rows)
    sim_df, metrics = simulate_trace(df, cluster=cluster, scenario="baseline")

    j1 = sim_df.filter(pl.col("job_id") == "j1").to_dicts()[0]
    j2 = sim_df.filter(pl.col("job_id") == "j2").to_dicts()[0]
    j3 = sim_df.filter(pl.col("job_id") == "j3").to_dicts()[0]

    assert j1["sim_start"] == 0
    assert j1["sim_end"] == 100

    # j3 backfills at submit_time 20s because it fits on 2 cores and finishes at 50s <= 100s (reservation time of j2)
    assert j3["sim_start"] == 20
    assert j3["sim_end"] == 50
    assert j3["sim_wait_s"] == 0

    # j2 starts at 100s as scheduled by its reservation
    assert j2["sim_start"] == 100
    assert j2["sim_end"] == 150
    assert j2["sim_wait_s"] == 90


def test_easy_backfill_delayer_blocked() -> None:
    """Verify that a candidate that would delay the head reservation is NOT backfilled."""
    cluster = ClusterConfig(
        name="single_node", total_nodes=1, cores_per_node=8, mem_mb_per_node=16384
    )

    # Job 1: runs until t=100s, uses 6 cores
    # Job 2: arrives at 10s, needs 8 cores (reservation at t=100s)
    # Job 3: arrives at 20s, needs 2 cores, runs for 120s (would finish at t=140s > 100s, delaying j2!)
    rows = [
        {
            "job_id": "j1",
            "submit_time": 0,
            "run_s": 100,
            "alloc_cpus": 6,
            "req_mem_mb": 4096,
            "wait_s": 0,
        },
        {
            "job_id": "j2",
            "submit_time": 10,
            "run_s": 50,
            "alloc_cpus": 8,
            "req_mem_mb": 8192,
            "wait_s": 0,
        },
        {
            "job_id": "j3",
            "submit_time": 20,
            "run_s": 120,
            "alloc_cpus": 2,
            "req_mem_mb": 2048,
            "wait_s": 0,
        },
    ]
    df = pl.DataFrame(rows)
    sim_df, _ = simulate_trace(df, cluster=cluster, scenario="baseline")

    j2 = sim_df.filter(pl.col("job_id") == "j2").to_dicts()[0]
    j3 = sim_df.filter(pl.col("job_id") == "j3").to_dicts()[0]

    # j2 starts at t=100s as reserved
    assert j2["sim_start"] == 100

    # j3 cannot backfill because it would exceed reservation time 100s; starts after j2 finishes at 150s
    assert j3["sim_start"] >= 100


def test_all_scenarios_execution() -> None:
    """Verify simulation execution across all six scenarios."""
    df = _build_test_trace(n_jobs=12)
    cluster = ClusterConfig(
        name="test_cluster", total_nodes=4, cores_per_node=16, mem_mb_per_node=65536
    )

    scenarios = [
        "baseline",
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cache_dedup",
        "all",
    ]

    for sc in scenarios:
        sim_df, metrics = simulate_trace(df, cluster=cluster, scenario=sc)
        assert sim_df.height > 0
        assert "sim_start" in sim_df.columns
        assert "sim_end" in sim_df.columns
        assert "sim_wait_s" in sim_df.columns
        assert metrics["job_count"] == sim_df.height
        assert metrics["makespan_s"] > 0
        assert 0.0 <= metrics["core_utilization"] <= 1.0
        assert 0.0 <= metrics["mem_utilization"] <= 1.0
        assert (sim_df["sim_start"] >= sim_df["submit_time"]).all()
        assert (sim_df["sim_end"] >= sim_df["sim_start"]).all()


def test_brute_force_schedule_verification() -> None:
    """Verify schedule validity on a small trace using independent second-by-second capacity checker."""
    df = _build_test_trace(n_jobs=8)
    cluster = ClusterConfig(name="tiny", total_nodes=2, cores_per_node=16, mem_mb_per_node=65536)

    sim_df, _ = simulate_trace(df, cluster=cluster, scenario="baseline")
    assert brute_force_verify_schedule(sim_df, cluster)


def test_guarantee_g4_invariants() -> None:
    """Verify Guarantee G4: completeness, temporal ordering, and capacity limits."""
    df = _build_test_trace(n_jobs=15)
    cluster = ClusterConfig(
        name="g4_cluster", total_nodes=4, cores_per_node=16, mem_mb_per_node=65536
    )

    sim_df, _ = simulate_trace(df, cluster=cluster, scenario="baseline")

    # 1. Completeness: every input job scheduled exactly once
    assert sim_df.height == df.height
    assert len(set(sim_df["job_id"].to_list())) == df.height

    # 2. Causality: sim_start >= submit_time for every job
    assert (sim_df["sim_start"] >= sim_df["submit_time"]).all()

    # 3. Capacity: at every event timestamp, concurrent cores and memory <= cluster totals
    critical_times = set(sim_df["sim_start"].to_list()) | set(sim_df["sim_end"].to_list())
    jobs = sim_df.to_dicts()

    for t in critical_times:
        active_cores = sum(j["alloc_cpus"] for j in jobs if j["sim_start"] <= t < j["sim_end"])
        active_mem = sum(j["req_mem_mb"] for j in jobs if j["sim_start"] <= t < j["sim_end"])
        assert active_cores <= cluster.total_cores
        assert active_mem <= cluster.total_mem_mb


def test_empty_trace_simulation() -> None:
    """Verify simulation on an empty trace returns empty result structure gracefully."""
    empty_df = pl.DataFrame(
        schema={
            "job_id": pl.String,
            "submit_time": pl.Int64,
            "run_s": pl.Int64,
            "alloc_cpus": pl.Int32,
            "req_mem_mb": pl.Int64,
        }
    )
    sim_df, metrics = simulate_trace(empty_df)
    assert sim_df.height == 0
    assert metrics["job_count"] == 0
    assert metrics["makespan_s"] == 0


def test_all_scenarios_on_20k_trace() -> None:
    """Acceptance: verify all simulation scenarios execute across a 20,000-job trace."""
    n_jobs = 20000
    rows = []
    for i in range(n_jobs):
        sub = i * 5
        run = 30 + (i % 10) * 15
        rows.append(
            {
                "job_id": f"j20k_{i}",
                "source": "sacct",
                "user": f"u_{i % 20}",
                "job_name": f"cmd_{i % 10}",
                "command_hash": f"cmd_{i % 10}",
                "input_hash": f"inp_{i % 25}",
                "submit_time": sub,
                "start_time": sub,
                "end_time": sub + run,
                "run_s": run,
                "wait_s": 0,
                "alloc_cpus": 2 if i % 2 == 0 else 4,
                "req_mem_mb": 2048 if i % 2 == 0 else 4096,
                "cpu_time_used_s": float(run * 1.5),
                "max_rss_mb": 1024,
                "nodes": 1,
                "partition": "compute",
                "state": "COMPLETED",
                "reserved_core_s": run * 4,
                "reserved_mem_mb_s": run * 4096,
            }
        )
    df = pl.DataFrame(rows)
    cluster = ClusterConfig(
        name="cluster_20k", total_nodes=32, cores_per_node=32, mem_mb_per_node=131072
    )

    scenarios = [
        "baseline",
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cache_dedup",
        "all",
    ]

    for sc in scenarios:
        sim_df, metrics = simulate_trace(df, cluster=cluster, scenario=sc)
        assert sim_df.height > 0
        assert (sim_df["sim_start"] >= sim_df["submit_time"]).all()
        assert (sim_df["sim_end"] >= sim_df["sim_start"]).all()
        assert metrics["makespan_s"] > 0
        assert metrics["core_utilization"] >= 0.0
        assert metrics["mem_utilization"] >= 0.0
