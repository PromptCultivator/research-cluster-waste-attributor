"""Unit tests for conservation waste attribution engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf
from rcwa.attribute import attribute_trace, export_attributed_records
from rcwa.model import empty_canonical_df

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_attribute_empty_df() -> None:
    """Verify attribution engine handles empty DataFrame safely."""
    df = empty_canonical_df()
    res = attribute_trace(df)
    assert res.height == 0
    assert "used_core_s" in res.columns
    assert "class2_idle_core_s" in res.columns
    assert "class3_core_s" in res.columns
    assert "class4_core_s" in res.columns
    assert "unattributed_core_s" in res.columns


def test_attribute_excludes_running_and_pending() -> None:
    """Verify RUNNING and PENDING jobs are excluded from attribution."""
    trace_file = FIXTURES_DIR / "sacct" / "sacct_running_pending.txt"
    df = parse_sacct(trace_file)
    res = attribute_trace(df)

    states = res.select("state").to_series().to_list()
    assert "RUNNING" not in states
    assert "PENDING" not in states
    assert res.height == 1


def test_attribute_class3_sub_labels() -> None:
    """Verify Class 3 assignments and exact sub-label categorization."""
    trace_file = FIXTURES_DIR / "sacct" / "sacct_standard_26col.txt"
    df = parse_sacct(trace_file)
    res = attribute_trace(df)

    expected_labels = {
        "1002": "other_failure",  # FAILED, run_s = 900s > 60s
        "1003": "timeout",  # TIMEOUT, run_s = 7200s
        "1004": "oom",  # OUT_OF_MEMORY, run_s = 300s
        "1005": "cancelled_after_start",  # CANCELLED, run_s = 1200s
        "1006": "node_fail",  # NODE_FAIL, run_s = 2700s
        "1007": "other_failure",  # PREEMPTED, run_s = 1800s
        "1008": "other_failure",  # FAILED, run_s = 300s
        "1010": "early_failure",  # FAILED, run_s = 30s <= 60s
    }

    for job_id, expected_label in expected_labels.items():
        row = res.filter(pl.col("job_id") == job_id)
        assert row.height == 1
        assert row.select("class3_sub_label").item() == expected_label
        assert row.select("class3_core_s").item() == row.select("reserved_core_s").item()
        assert row.select("class3_mem_mb_s").item() == row.select("reserved_mem_mb_s").item()
        assert row.select("used_core_s").item() == 0
        assert row.select("used_mem_mb_s").item() == 0


def test_attribute_class4_recomputation() -> None:
    """Verify Class 4 declared-input recomputation detection and command-only flag."""
    pairs_file = FIXTURES_DIR / "recompute" / "recompute_pairs.txt"
    df_pairs = parse_sacct(pairs_file)
    res_pairs = attribute_trace(df_pairs)

    row_1601 = res_pairs.filter(pl.col("job_id") == "1601")
    row_1602 = res_pairs.filter(pl.col("job_id") == "1602")

    assert row_1601.select("class4_core_s").item() == 0
    assert row_1601.select("recompute_confidence").item() is None

    assert row_1602.select("class4_core_s").item() == row_1602.select("reserved_core_s").item()
    assert row_1602.select("recompute_confidence").item() == "declared_inputs"
    assert row_1602.select("possible_recompute").item() is False
    assert row_1602.select("used_core_s").item() == 0

    cmd_file = FIXTURES_DIR / "recompute" / "recompute_command_only.txt"
    df_cmd = parse_sacct(cmd_file)
    res_cmd = attribute_trace(df_cmd)

    row_1701 = res_cmd.filter(pl.col("job_id") == "1701")
    row_1702 = res_cmd.filter(pl.col("job_id") == "1702")

    assert row_1701.select("possible_recompute").item() is False
    assert row_1702.select("possible_recompute").item() is True
    assert row_1702.select("recompute_confidence").item() == "command_only"
    assert row_1702.select("class4_core_s").item() == 0


def test_attribute_swf_not_available() -> None:
    """Verify SWF trace recomputation confidence is reported as not_available."""
    swf_file = FIXTURES_DIR / "swf" / "standard_with_headers.swf"
    df_swf = parse_swf(swf_file)
    res_swf = attribute_trace(df_swf)

    conf_list = res_swf.select("recompute_confidence").to_series().to_list()
    for conf in conf_list:
        assert conf == "not_available"


def test_attribute_precedence_hierarchy() -> None:
    """Verify precedence hierarchy: failed > recompute > idle CPU / over memory."""
    base_time = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Job 1: completed
    # Job 2: identical input/command hash as Job 1, but FAILED -> must be Class 3, NOT Class 4
    # Job 3: identical input/command hash as Job 1, completed with low CPU -> must be Class 4, NOT Class 2
    rows = [
        {
            "job_id": "1",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "acc",
            "partition": "part",
            "job_name": "task",
            "command_hash": "cmd_hash",
            "input_hash": "input_hash",
            "submit_time": base_time,
            "start_time": base_time,
            "end_time": base_time + timedelta(seconds=1000),
            "wait_s": 0,
            "run_s": 1000,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 3500.0,
            "req_mem_mb": 8000,
            "max_rss_mb": 4000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 4000,
            "reserved_mem_mb_s": 8000000,
        },
        {
            "job_id": "2",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "acc",
            "partition": "part",
            "job_name": "task",
            "command_hash": "cmd_hash",
            "input_hash": "input_hash",
            "submit_time": base_time + timedelta(seconds=2000),
            "start_time": base_time + timedelta(seconds=2000),
            "end_time": base_time + timedelta(seconds=3000),
            "wait_s": 0,
            "run_s": 1000,
            "state": "FAILED",
            "exit_code": 1,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 100.0,
            "req_mem_mb": 8000,
            "max_rss_mb": 2000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 4000,
            "reserved_mem_mb_s": 8000000,
        },
        {
            "job_id": "3",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "acc",
            "partition": "part",
            "job_name": "task",
            "command_hash": "cmd_hash",
            "input_hash": "input_hash",
            "submit_time": base_time + timedelta(seconds=4000),
            "start_time": base_time + timedelta(seconds=4000),
            "end_time": base_time + timedelta(seconds=5000),
            "wait_s": 0,
            "run_s": 1000,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 100.0,  # 3900 idle core-s if Class 2
            "req_mem_mb": 8000,
            "max_rss_mb": 2000,
            "req_gpus": 0,
            "alloc_gpus": 0,
            "nodes": 1,
            "node_list": "node1",
            "reserved_core_s": 4000,
            "reserved_mem_mb_s": 8000000,
        },
    ]

    df = pl.DataFrame(rows)
    res = attribute_trace(df)

    # Job 2: FAILED -> Class 3 takes precedence over Class 4
    row_2 = res.filter(pl.col("job_id") == "2")
    assert row_2.select("class3_core_s").item() == 4000
    assert row_2.select("class4_core_s").item() == 0
    assert row_2.select("class2_idle_core_s").item() == 0

    # Job 3: Recompute -> Class 4 takes precedence over Class 2
    row_3 = res.filter(pl.col("job_id") == "3")
    assert row_3.select("class4_core_s").item() == 4000
    assert row_3.select("class2_idle_core_s").item() == 0
    assert row_3.select("used_core_s").item() == 0


def test_export_attributed_records_roundtrip(tmp_path: Path) -> None:
    """Verify exporting attributed records to parquet and csv format."""
    trace_file = FIXTURES_DIR / "sacct" / "sacct_standard_26col.txt"
    df = parse_sacct(trace_file)
    res = attribute_trace(df)

    parquet_out = tmp_path / "attr.parquet"
    csv_out = tmp_path / "attr.csv"

    export_attributed_records(res, parquet_out, format="parquet")
    export_attributed_records(res, csv_out, format="csv")

    assert parquet_out.exists()
    assert csv_out.exists()

    df_p = pl.read_parquet(parquet_out)
    assert df_p.height == res.height

    df_c = pl.read_csv(csv_out)
    assert df_c.height == res.height
