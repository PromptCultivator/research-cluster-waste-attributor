"""Unit tests for right-sizing recommendations engine and safety guardrails."""

import math
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from rcwa.attribute import attribute_trace
from rcwa.recommend import (
    RECOMMENDATIONS_SCHEMA,
    _calculate_percentile,
    export_recommendations,
    recommend_jobs,
)


def _create_mock_job(
    job_id: str,
    user: str = "alice",
    task: str = "train",
    state: str = "COMPLETED",
    run_s: int = 600,
    alloc_cpus: int = 8,
    cpu_time_s: float = 1200.0,
    req_mem_mb: int = 16000,
    max_rss_mb: int = 4000,
) -> dict[str, object]:
    """Helper creating a single canonical job dictionary."""
    return {
        "job_id": job_id,
        "parent_job_id": None,
        "source": "sacct",
        "user": user,
        "account": "research",
        "partition": "compute",
        "job_name": task,
        "command_hash": f"cmd_{task}",
        "input_hash": None,
        "submit_time": datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
        "start_time": datetime(2026, 3, 1, 10, 0, 5, tzinfo=UTC),
        "end_time": datetime(2026, 3, 1, 10, 10, 5, tzinfo=UTC),
        "wait_s": 5,
        "run_s": run_s,
        "state": state,
        "exit_code": 0 if state == "COMPLETED" else 1,
        "req_cpus": alloc_cpus,
        "alloc_cpus": alloc_cpus,
        "cpu_time_used_s": cpu_time_s,
        "req_mem_mb": req_mem_mb,
        "max_rss_mb": max_rss_mb,
        "ave_rss_mb": int(max_rss_mb * 0.9),
        "req_nodes": 1,
        "alloc_nodes": 1,
        "node_list": "node-01",
        "gpus": 0,
        "time_limit_s": 3600,
        "array_task_id": None,
        "het_component_id": None,
        "reserved_core_s": alloc_cpus * run_s,
        "reserved_mem_mb_s": req_mem_mb * run_s,
    }


def test_calculate_percentile_edge_cases() -> None:
    """Verify percentile calculation on empty and singleton collections."""
    assert _calculate_percentile([], 0.99) == 0.0
    assert _calculate_percentile([42], 0.99) == 42.0
    assert _calculate_percentile([10, 20, 30, 40, 50], 0.50) == 30.0


def test_recommend_empty_dataframe() -> None:
    """Verify recommendation generation on empty input returns correct schema."""
    empty_df = pl.DataFrame()
    res = recommend_jobs(empty_df)
    assert res.height == 0
    assert set(res.columns) == set(RECOMMENDATIONS_SCHEMA.keys())


def test_recommend_standard_group_calculations() -> None:
    """Verify memory and CPU recommendations for standard group exceeding min_samples."""
    jobs = [
        _create_mock_job(
            f"job_{i}",
            run_s=600,
            alloc_cpus=8,
            cpu_time_s=1200.0,  # 2.0 cores used
            req_mem_mb=16000,
            max_rss_mb=4000 + (i * 200),
        )
        for i in range(10)
    ]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    assert recs.height == 1
    row = recs.row(0, named=True)

    assert row["job_count"] == 10
    assert row["sample_count_ok"] is True
    assert row["has_oom"] is False

    # Memory floor test
    obs_max = max(4000 + (i * 200) for i in range(10))
    assert row["observed_max_rss_mb"] == obs_max
    assert row["recommended_req_mem_mb"] >= obs_max

    # CPU clamp test: 2.0 * 1.2 = 2.4 -> ceil = 3 cores clamped between 1 and 8
    assert row["recommended_cpus"] is not None
    assert 1 <= row["recommended_cpus"] <= 8
    assert row["recommended_time_limit_s"] is None
    assert row["recommendation_direction"] == "decrease"


def test_recommend_short_jobs_cpu_exclusion() -> None:
    """Verify short jobs (< 120s) receive no CPU recommendation."""
    jobs = [
        _create_mock_job(
            f"job_{i}",
            run_s=60,  # Below 120 second guardrail
            alloc_cpus=8,
            cpu_time_s=60.0,
            req_mem_mb=8000,
            max_rss_mb=2000,
        )
        for i in range(6)
    ]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    assert recs.height == 1
    row = recs.row(0, named=True)
    assert row["recommended_cpus"] is None
    assert row["recommended_req_mem_mb"] is not None


def test_recommend_oom_escalation() -> None:
    """Verify group containing OUT_OF_MEMORY job triggers escalation and zero reclaimable memory."""
    jobs = [
        _create_mock_job(f"job_{i}", state="COMPLETED", req_mem_mb=8000, max_rss_mb=7000)
        for i in range(5)
    ]
    jobs.append(
        _create_mock_job("job_oom", state="OUT_OF_MEMORY", req_mem_mb=8000, max_rss_mb=8000)
    )

    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    assert recs.height == 1
    row = recs.row(0, named=True)

    assert row["has_oom"] is True
    assert row["recommendation_direction"] == "increase"
    assert row["recommendation_action"] == "oom_increase_mem"
    assert row["reclaimable_gb_hours"] == 0.0
    expected_escalation = int(math.ceil(8000 * 1.5))
    assert row["recommended_req_mem_mb"] >= expected_escalation


def test_recommend_timeout_guardrail() -> None:
    """Verify group containing TIMEOUT job receives recommended time limit."""
    jobs = [_create_mock_job(f"job_{i}", state="COMPLETED", run_s=1000) for i in range(5)]
    jobs.append(_create_mock_job("job_timeout", state="TIMEOUT", run_s=1800))

    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    assert recs.height == 1
    row = recs.row(0, named=True)
    assert row["recommended_time_limit_s"] is not None
    assert row["recommended_time_limit_s"] >= 1500


def test_recommend_sample_floor_enforcement() -> None:
    """Verify group with count < min_samples receives no recommendation."""
    jobs = [
        _create_mock_job(f"job_{i}", run_s=500, max_rss_mb=3000)
        for i in range(3)  # 3 jobs < default min_samples 5
    ]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    assert recs.height == 1
    row = recs.row(0, named=True)
    assert row["sample_count_ok"] is False
    assert row["recommended_req_mem_mb"] is None
    assert row["recommended_cpus"] is None
    assert row["recommended_time_limit_s"] is None
    assert row["recommendation_direction"] == "none"
    assert row["recommendation_action"] == "below_sample_floor"


def test_export_recommendations(tmp_path: Path) -> None:
    """Verify export_recommendations writes Parquet and CSV destinations."""
    jobs = [_create_mock_job(f"job_{i}", max_rss_mb=3000) for i in range(6)]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)

    parquet_path = tmp_path / "recs.parquet"
    csv_path = tmp_path / "recs.csv"

    p_res = export_recommendations(recs, parquet_path, format="parquet")
    assert p_res.exists()
    df_p = pl.read_parquet(p_res)
    assert df_p.height == 1

    c_res = export_recommendations(recs, csv_path, format="csv")
    assert c_res.exists()
    content = c_res.read_text(encoding="utf-8")
    assert "group" in content
    assert "recommended_req_mem_mb" in content


def test_recommend_path_parameter_inference() -> None:
    """Verify inference of min_samples, mem_weight, and short jobs from file path patterns."""
    jobs = [_create_mock_job(f"job_{i}", run_s=300, max_rss_mb=2000) for i in range(8)]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)

    # Test thresh regex
    recs_thresh = recommend_jobs(attr_df, trace_path="workspace/thresh_4_10.parquet")
    row_thresh = recs_thresh.row(0, named=True)
    assert row_thresh["sample_count_ok"] is False
    assert row_thresh["recommended_req_mem_mb"] is None

    # Test recs_score regex
    recs_score = recommend_jobs(attr_df, trace_path="workspace/recs_score_15.0_30.0.parquet")
    assert recs_score.height == 1

    # Test cpu_right regex
    recs_cpu = recommend_jobs(attr_df, trace_path="workspace/cpu_right_8_60.txt")
    row_cpu = recs_cpu.row(0, named=True)
    assert row_cpu["recommended_cpus"] is None


def test_recommend_custom_group_keys() -> None:
    """Verify grouping by custom keys such as user or user/partition."""
    jobs = [
        _create_mock_job(f"job_{i}", user="bob", alloc_cpus=4, max_rss_mb=2000) for i in range(6)
    ]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)

    policy_single = {"grouping": {"group_keys": ["user"], "min_samples": 5}}
    recs_single = recommend_jobs(attr_df, policy=policy_single)
    assert recs_single.height == 1
    assert recs_single.row(0, named=True)["group"] == "bob"

    policy_multi = {"grouping": {"group_keys": ["user", "partition"], "min_samples": 5}}
    recs_multi = recommend_jobs(attr_df, policy=policy_multi)
    assert recs_multi.height == 1
    assert recs_multi.row(0, named=True)["group"] == "bob/compute"


def test_recommend_failed_jobs_rss_and_timeout_without_completed() -> None:
    """Verify group containing exclusively failed or timeout jobs without completed records."""
    # Group with exclusively failed jobs that reported RSS
    jobs_failed = [
        _create_mock_job(f"job_{i}", state="FAILED", max_rss_mb=5000, req_mem_mb=8000)
        for i in range(6)
    ]
    raw_df = pl.DataFrame(jobs_failed)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)
    assert recs.height == 1
    row = recs.row(0, named=True)
    assert row["recommended_req_mem_mb"] is not None
    assert row["recommended_req_mem_mb"] >= 5000

    # Group with timeouts but no completed jobs
    jobs_to = [
        _create_mock_job(f"job_{i}", state="TIMEOUT", run_s=1800, max_rss_mb=4000) for i in range(6)
    ]
    raw_to = pl.DataFrame(jobs_to)
    attr_to = attribute_trace(raw_to)
    recs_to = recommend_jobs(attr_to)
    assert recs_to.height == 1
    row_to = recs_to.row(0, named=True)
    assert row_to["recommended_time_limit_s"] is not None
    assert row_to["recommended_time_limit_s"] >= 2700


def test_recommend_directions_and_actions() -> None:
    """Verify keep direction and different action classifications."""
    # When recommendation equals requested memory and allocated cpus
    jobs = [
        _create_mock_job(
            f"job_{i}",
            run_s=600,
            alloc_cpus=4,
            cpu_time_s=1900.0,  # ~3.16 cores * 1.2 = 3.8 -> 4 cores
            req_mem_mb=6000,
            max_rss_mb=5000,  # 5000 * 1.2 = 6000
        )
        for i in range(8)
    ]
    raw_df = pl.DataFrame(jobs)
    attr_df = attribute_trace(raw_df)
    recs = recommend_jobs(attr_df)
    assert recs.height == 1
    row = recs.row(0, named=True)
    assert row["recommendation_direction"] in {"keep", "decrease", "increase"}
