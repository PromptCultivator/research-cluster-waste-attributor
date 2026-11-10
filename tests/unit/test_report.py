"""Unit tests for report generation module."""

from datetime import UTC, datetime

import polars as pl

from rcwa.attribute import attribute_trace
from rcwa.model import empty_canonical_df
from rcwa.report import (
    _round_floats,
    build_report_data,
    render_csv_report,
    render_markdown_report,
)


def test_build_report_data_empty() -> None:
    """Verify building report data on empty traces."""
    empty_df = empty_canonical_df()
    attr_df = attribute_trace(empty_df)
    report = build_report_data(empty_df, attr_df)

    assert "summary" in report
    assert report["summary"]["total_jobs"] == 0
    assert "waste_classification" in report
    assert "ranked_reclaim_list" in report
    assert "data_quality" in report


def test_build_report_data_sacct_trace() -> None:
    """Verify building report data on a trace with active and completed jobs."""
    t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    rows = [
        {
            "job_id": "1",
            "source": "sacct",
            "user": "alice",
            "account": "acct1",
            "partition": "part1",
            "state": "COMPLETED",
            "req_cpus": 4,
            "alloc_cpus": 4,
            "run_s": 3600,
            "wait_s": 5,
            "submit_time": t0,
            "start_time": t0,
            "end_time": t0,
            "req_mem_mb": 16000,
            "max_rss_mb": 8000,
            "cpu_time_used_s": 7200.0,
            "reserved_core_s": 14400,
            "reserved_mem_mb_s": 57600000,
            "input_hash": "hash_alpha",
            "command_hash": "cmd_alpha",
        },
        {
            "job_id": "2",
            "source": "sacct",
            "user": "alice",
            "account": "acct1",
            "partition": "part1",
            "state": "RUNNING",
            "req_cpus": 4,
            "alloc_cpus": 4,
            "run_s": 100,
            "wait_s": 5,
            "submit_time": t0,
            "start_time": t0,
            "end_time": None,
            "req_mem_mb": 16000,
            "max_rss_mb": 8000,
            "cpu_time_used_s": 200.0,
            "reserved_core_s": 400,
            "reserved_mem_mb_s": 1600000,
            "input_hash": None,
            "command_hash": None,
        },
    ]
    df = pl.DataFrame(rows)
    attr_df = attribute_trace(df)
    report = build_report_data(df, attr_df)

    assert report["summary"]["total_jobs"] == 2
    assert report["summary"]["evaluated_jobs"] == 1
    assert report["summary"]["excluded_jobs"] == 1
    assert report["data_quality"]["excluded_active_count"] == 1

    md = render_markdown_report(report)
    assert "# Research Cluster Waste Attribution Report" in md
    assert "## Waste Classification" in md

    csv = render_csv_report(report)
    assert "rank,group,count,reclaim_core_hours" in csv


def test_build_report_data_swf_trace() -> None:
    """Verify SWF trace reports Class 4 as not available."""
    rows = [
        {
            "job_id": "1",
            "source": "swf",
            "user": "bob",
            "state": "COMPLETED",
            "req_cpus": 2,
            "alloc_cpus": 2,
            "run_s": 1000,
            "wait_s": 10,
            "submit_time": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            "start_time": datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC),
            "end_time": datetime(2026, 1, 1, 0, 16, 50, tzinfo=UTC),
            "req_mem_mb": 4000,
            "max_rss_mb": 2000,
            "cpu_time_used_s": 1000.0,
            "reserved_core_s": 2000,
            "reserved_mem_mb_s": 4000000,
            "input_hash": None,
            "command_hash": "1",
        }
    ]
    df = pl.DataFrame(rows)
    attr_df = attribute_trace(df)
    report = build_report_data(df, attr_df)

    waste = report["waste_classification"]
    assert waste.get("class4_status") == "not available"
    assert waste.get("class4_redundant_core_hours") == 0.0


def test_round_floats_structure() -> None:
    """Verify rounding floats across nested dictionary and list structures."""
    payload = {
        "float_val": 1.23456789,
        "nested": {"inner_float": 9.87654321},
        "list_vals": [3.14159265, "text", 42],
    }
    rounded = _round_floats(payload, digits=4)
    assert rounded["float_val"] == 1.2346
    assert rounded["nested"]["inner_float"] == 9.8765
    assert rounded["list_vals"][0] == 3.1416
    assert rounded["list_vals"][1] == "text"
    assert rounded["list_vals"][2] == 42
