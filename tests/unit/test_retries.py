"""Unit tests for batch job failure retry chain detection."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from rcwa.adapters.sacct import parse_sacct
from rcwa.model import empty_canonical_df
from rcwa.retries import detect_retry_chains

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_detect_retry_chains_empty() -> None:
    """Verify detect_retry_chains safely handles an empty canonical DataFrame."""
    df = empty_canonical_df()
    res = detect_retry_chains(df)
    assert res.height == 0
    assert "retry_of" in res.columns
    assert "retry_chain_id" in res.columns
    assert "retry_count" in res.columns
    assert "retry_chain_cost_core_s" in res.columns
    assert "retry_chain_cost_mem_mb_s" in res.columns


def test_detect_retry_chains_from_fixture() -> None:
    """Verify retry chain detection matches expected linkages on standard fixture."""
    fixture_path = FIXTURES_DIR / "retries" / "retry_chains.txt"
    raw_df = parse_sacct(fixture_path)
    res = detect_retry_chains(raw_df, retry_window_s=86400)

    # Job 1801: FAILED -> root of chain
    r1801 = res.filter(pl.col("job_id") == "1801")
    assert r1801.select("retry_of").item() is None
    assert r1801.select("retry_chain_id").item() == "1801"
    assert r1801.select("retry_count").item() == 0

    # Job 1802: TIMEOUT -> retry of 1801
    r1802 = res.filter(pl.col("job_id") == "1802")
    assert r1802.select("retry_of").item() == "1801"
    assert r1802.select("retry_chain_id").item() == "1801"
    assert r1802.select("retry_count").item() == 1

    # Job 1803: COMPLETED -> retry of 1802
    r1803 = res.filter(pl.col("job_id") == "1803")
    assert r1803.select("retry_of").item() == "1802"
    assert r1803.select("retry_chain_id").item() == "1801"
    assert r1803.select("retry_count").item() == 2

    # Job 1804: independent user -> not in any chain
    r1804 = res.filter(pl.col("job_id") == "1804")
    assert r1804.select("retry_of").item() is None
    assert r1804.select("retry_chain_id").item() is None
    assert r1804.select("retry_count").item() == 0
    assert r1804.select("retry_chain_cost_core_s").item() == 0

    # Chain cost verification across all participants in chain 1801
    expected_core = (
        r1801.select("reserved_core_s").item()
        + r1802.select("reserved_core_s").item()
        + r1803.select("reserved_core_s").item()
    )
    assert r1801.select("retry_chain_cost_core_s").item() == expected_core
    assert r1802.select("retry_chain_cost_core_s").item() == expected_core
    assert r1803.select("retry_chain_cost_core_s").item() == expected_core


def test_detect_retry_chains_multi_hop_linear() -> None:
    """Verify linear multi-hop chain correctly tracks hop distance and total costs."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # 4 jobs: J1 (fail) -> J2 (fail) -> J3 (fail) -> J4 (complete)
    rows = [
        {
            "job_id": "J1",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "train_task",
            "command_hash": "hash_xyz",
            "input_hash": None,
            "submit_time": base_time,
            "start_time": base_time + timedelta(seconds=10),
            "end_time": base_time + timedelta(seconds=110),
            "wait_s": 10,
            "run_s": 100,
            "state": "FAILED",
            "exit_code": 1,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 50.0,
            "req_mem_mb": 4000,
            "max_rss_mb": 2000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 400,
            "reserved_mem_mb_s": 400000,
        },
        {
            "job_id": "J2",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "train_task",
            "command_hash": "hash_xyz",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=200),
            "start_time": base_time + timedelta(seconds=210),
            "end_time": base_time + timedelta(seconds=410),
            "wait_s": 10,
            "run_s": 200,
            "state": "TIMEOUT",
            "exit_code": 0,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 100.0,
            "req_mem_mb": 4000,
            "max_rss_mb": 2000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 800,
            "reserved_mem_mb_s": 800000,
        },
        {
            "job_id": "J3",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "train_task",
            "command_hash": "hash_xyz",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=500),
            "start_time": base_time + timedelta(seconds=510),
            "end_time": base_time + timedelta(seconds=810),
            "wait_s": 10,
            "run_s": 300,
            "state": "OUT_OF_MEMORY",
            "exit_code": 125,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 150.0,
            "req_mem_mb": 4000,
            "max_rss_mb": 4000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 1200,
            "reserved_mem_mb_s": 1200000,
        },
        {
            "job_id": "J4",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "train_task",
            "command_hash": "hash_xyz",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=900),
            "start_time": base_time + timedelta(seconds=910),
            "end_time": base_time + timedelta(seconds=1310),
            "wait_s": 10,
            "run_s": 400,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 350.0,
            "req_mem_mb": 8000,
            "max_rss_mb": 4500,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 1600,
            "reserved_mem_mb_s": 3200000,
        },
    ]

    df = pl.DataFrame(rows)
    res = detect_retry_chains(df, retry_window_s=86400)

    assert res.filter(pl.col("job_id") == "J1").select("retry_of").item() is None
    assert res.filter(pl.col("job_id") == "J1").select("retry_count").item() == 0
    assert res.filter(pl.col("job_id") == "J1").select("retry_chain_id").item() == "J1"

    assert res.filter(pl.col("job_id") == "J2").select("retry_of").item() == "J1"
    assert res.filter(pl.col("job_id") == "J2").select("retry_count").item() == 1
    assert res.filter(pl.col("job_id") == "J2").select("retry_chain_id").item() == "J1"

    assert res.filter(pl.col("job_id") == "J3").select("retry_of").item() == "J2"
    assert res.filter(pl.col("job_id") == "J3").select("retry_count").item() == 2
    assert res.filter(pl.col("job_id") == "J3").select("retry_chain_id").item() == "J1"

    assert res.filter(pl.col("job_id") == "J4").select("retry_of").item() == "J3"
    assert res.filter(pl.col("job_id") == "J4").select("retry_count").item() == 3
    assert res.filter(pl.col("job_id") == "J4").select("retry_chain_id").item() == "J1"

    total_core = 400 + 800 + 1200 + 1600
    total_mem = 400000 + 800000 + 1200000 + 3200000
    for jid in ["J1", "J2", "J3", "J4"]:
        assert (
            res.filter(pl.col("job_id") == jid).select("retry_chain_cost_core_s").item()
            == total_core
        )
        assert (
            res.filter(pl.col("job_id") == jid).select("retry_chain_cost_mem_mb_s").item()
            == total_mem
        )


def test_detect_retry_chains_window_and_temporal_causality() -> None:
    """Verify jobs outside window or submitted before failure ends are not linked."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # J1 fails after running for 1000s (ends at base_time + 1000s)
    # J2 is submitted at base_time + 500s (BEFORE J1 ends -> cannot be retry of J1)
    # J3 is submitted at base_time + 100,000s (> 86400s after J1 ends -> window expired)
    rows = [
        {
            "job_id": "J1",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_a",
            "input_hash": None,
            "submit_time": base_time,
            "start_time": base_time,
            "end_time": base_time + timedelta(seconds=1000),
            "wait_s": 0,
            "run_s": 1000,
            "state": "FAILED",
            "exit_code": 1,
            "req_cpus": 2,
            "alloc_cpus": 2,
            "cpu_time_used_s": 10.0,
            "req_mem_mb": 2000,
            "max_rss_mb": 1000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 2000,
            "reserved_mem_mb_s": 2000000,
        },
        {
            "job_id": "J2",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_a",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=500),
            "start_time": base_time + timedelta(seconds=500),
            "end_time": base_time + timedelta(seconds=1500),
            "wait_s": 0,
            "run_s": 1000,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 2,
            "alloc_cpus": 2,
            "cpu_time_used_s": 500.0,
            "req_mem_mb": 2000,
            "max_rss_mb": 1000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 2000,
            "reserved_mem_mb_s": 2000000,
        },
        {
            "job_id": "J3",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_a",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=100000),
            "start_time": base_time + timedelta(seconds=100000),
            "end_time": base_time + timedelta(seconds=101000),
            "wait_s": 0,
            "run_s": 1000,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 2,
            "alloc_cpus": 2,
            "cpu_time_used_s": 500.0,
            "req_mem_mb": 2000,
            "max_rss_mb": 1000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 2000,
            "reserved_mem_mb_s": 2000000,
        },
    ]

    df = pl.DataFrame(rows)
    res = detect_retry_chains(df, retry_window_s=86400)

    # Neither J2 nor J3 qualifies as retry of J1
    assert res.filter(pl.col("job_id") == "J2").select("retry_of").item() is None
    assert res.filter(pl.col("job_id") == "J3").select("retry_of").item() is None
    assert res.filter(pl.col("job_id") == "J1").select("retry_chain_id").item() is None


def test_detect_retry_chains_one_to_one_earliest_claims() -> None:
    """Verify earliest candidate claims the failure under 1-to-1 matching rule."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # J1 fails at base_time + 100s
    # J2 submitted at base_time + 200s (claims J1)
    # J3 submitted at base_time + 300s (does not claim J1 because J1 is already claimed)
    rows = [
        {
            "job_id": "J1",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_b",
            "input_hash": None,
            "submit_time": base_time,
            "start_time": base_time,
            "end_time": base_time + timedelta(seconds=100),
            "wait_s": 0,
            "run_s": 100,
            "state": "FAILED",
            "exit_code": 1,
            "req_cpus": 1,
            "alloc_cpus": 1,
            "cpu_time_used_s": 5.0,
            "req_mem_mb": 1000,
            "max_rss_mb": 500,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 100,
            "reserved_mem_mb_s": 100000,
        },
        {
            "job_id": "J2",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_b",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=200),
            "start_time": base_time + timedelta(seconds=200),
            "end_time": base_time + timedelta(seconds=300),
            "wait_s": 0,
            "run_s": 100,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 1,
            "alloc_cpus": 1,
            "cpu_time_used_s": 50.0,
            "req_mem_mb": 1000,
            "max_rss_mb": 500,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 100,
            "reserved_mem_mb_s": 100000,
        },
        {
            "job_id": "J3",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "prod",
            "job_name": "task",
            "command_hash": "hash_b",
            "input_hash": None,
            "submit_time": base_time + timedelta(seconds=300),
            "start_time": base_time + timedelta(seconds=300),
            "end_time": base_time + timedelta(seconds=400),
            "wait_s": 0,
            "run_s": 100,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 1,
            "alloc_cpus": 1,
            "cpu_time_used_s": 50.0,
            "req_mem_mb": 1000,
            "max_rss_mb": 500,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 100,
            "reserved_mem_mb_s": 100000,
        },
    ]

    df = pl.DataFrame(rows)
    res = detect_retry_chains(df, retry_window_s=86400)

    assert res.filter(pl.col("job_id") == "J2").select("retry_of").item() == "J1"
    assert res.filter(pl.col("job_id") == "J3").select("retry_of").item() is None
