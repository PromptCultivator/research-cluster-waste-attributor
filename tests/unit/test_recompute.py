"""Unit tests for redundant recomputation detection, sidecars, and result cache."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from rcwa.model import empty_canonical_df
from rcwa.recompute import (
    detect_recomputations,
    evaluate_recomputation_accuracy,
    load_sidecar,
    load_sidecars_from_dir,
    merge_sidecars,
    simulate_result_cache,
)


def test_load_sidecar(tmp_path: Path) -> None:
    """Verify loading single sidecar JSON file with edge cases."""
    assert load_sidecar(tmp_path / "nonexistent.json") == {}

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json at all", encoding="utf-8")
    assert load_sidecar(bad_json) == {}

    valid_json = tmp_path / "101.json"
    valid_json.write_text(
        json.dumps({"job_id": "101", "input_hash": "hash_in", "command_hash": "hash_cmd"}),
        encoding="utf-8",
    )
    res = load_sidecar(valid_json)
    assert res.get("job_id") == "101"
    assert res.get("input_hash") == "hash_in"
    assert res.get("command_hash") == "hash_cmd"


def test_load_sidecars_from_dir(tmp_path: Path) -> None:
    """Verify scanning directory for sidecars."""
    assert load_sidecars_from_dir(tmp_path / "missing_dir") == {}

    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()

    (sidecar_dir / "201.json").write_text(
        json.dumps({"job_id": "201", "input_hash": "hash_201"}),
        encoding="utf-8",
    )
    (sidecar_dir / "202.json").write_text(
        json.dumps({"job_id": "202", "input_hash": "hash_202"}),
        encoding="utf-8",
    )

    indexed = load_sidecars_from_dir(sidecar_dir)
    assert len(indexed) == 2
    assert "201" in indexed
    assert "202" in indexed
    assert indexed["201"]["input_hash"] == "hash_201"


def test_merge_sidecars(tmp_path: Path) -> None:
    """Verify merging sidecar attributes into canonical DataFrame."""
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    (sidecar_dir / "301.json").write_text(
        json.dumps({"job_id": "301", "input_hash": "sidecar_in", "command_hash": "sidecar_cmd"}),
        encoding="utf-8",
    )

    from typing import Any

    base_df = empty_canonical_df()
    row: dict[str, Any] = {col: None for col in base_df.columns}
    row.update(
        {
            "job_id": "301",
            "source": "sacct",
            "user": "alice",
            "state": "COMPLETED",
            "req_cpus": 4,
            "alloc_cpus": 4,
            "run_s": 3600,
            "wait_s": 10,
            "submit_time": datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
            "input_hash": None,
            "command_hash": None,
        }
    )
    df = pl.DataFrame([row], schema=base_df.schema)

    merged = merge_sidecars(df, sidecar_dir=sidecar_dir)
    assert merged["input_hash"][0] == "sidecar_in"
    assert merged["command_hash"][0] == "sidecar_cmd"


def test_detect_recomputations_empty() -> None:
    """Verify detection on empty DataFrame."""
    df = empty_canonical_df()
    res = detect_recomputations(df)
    assert res.height == 0
    assert "is_recompute" in res.columns
    assert "possible_recompute" in res.columns
    assert "recompute_confidence" in res.columns


def test_detect_recomputations_exact_duplicates() -> None:
    """Verify duplicate jobs with declared inputs are flagged with declared_inputs confidence."""
    t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(days=2)

    rows = [
        {
            "job_id": "101",
            "source": "sacct",
            "user": "alice",
            "state": "COMPLETED",
            "req_cpus": 4,
            "alloc_cpus": 4,
            "run_s": 3600,
            "wait_s": 5,
            "submit_time": t0,
            "start_time": t0 + timedelta(seconds=5),
            "end_time": t0 + timedelta(seconds=3605),
            "command_hash": "cmd_alpha",
            "input_hash": "inp_alpha",
            "reserved_core_s": 14400,
            "reserved_mem_mb_s": 57600000,
        },
        {
            "job_id": "102",
            "source": "sacct",
            "user": "alice",
            "state": "COMPLETED",
            "req_cpus": 4,
            "alloc_cpus": 4,
            "run_s": 3600,
            "wait_s": 10,
            "submit_time": t1,
            "start_time": t1 + timedelta(seconds=10),
            "end_time": t1 + timedelta(seconds=3610),
            "command_hash": "cmd_alpha",
            "input_hash": "inp_alpha",
            "reserved_core_s": 14400,
            "reserved_mem_mb_s": 57600000,
        },
    ]
    df = pl.DataFrame(rows)
    res = detect_recomputations(df, recompute_window_s=2592000)

    row_101 = res.filter(pl.col("job_id") == "101")
    row_102 = res.filter(pl.col("job_id") == "102")

    assert row_101["is_recompute"][0] is False
    assert row_101["possible_recompute"][0] is False
    assert row_101["recompute_confidence"][0] is None

    assert row_102["is_recompute"][0] is True
    assert row_102["possible_recompute"][0] is False
    assert row_102["recompute_confidence"][0] == "declared_inputs"
    assert row_102["recomputed_from_job_id"][0] == "101"


def test_detect_recomputations_window_expiration() -> None:
    """Verify duplicate beyond recompute window is not flagged as recomputation."""
    t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    # 35 days later (default window is 30 days)
    t1 = t0 + timedelta(days=35)

    rows = [
        {
            "job_id": "201",
            "source": "sacct",
            "user": "alice",
            "state": "COMPLETED",
            "run_s": 3600,
            "wait_s": 5,
            "submit_time": t0,
            "end_time": t0 + timedelta(seconds=3600),
            "command_hash": "cmd_beta",
            "input_hash": "inp_beta",
        },
        {
            "job_id": "202",
            "source": "sacct",
            "user": "alice",
            "state": "COMPLETED",
            "run_s": 3600,
            "wait_s": 5,
            "submit_time": t1,
            "end_time": t1 + timedelta(seconds=3600),
            "command_hash": "cmd_beta",
            "input_hash": "inp_beta",
        },
    ]
    df = pl.DataFrame(rows)
    res = detect_recomputations(df, recompute_window_s=30 * 86400)

    row_202 = res.filter(pl.col("job_id") == "202")
    assert row_202["is_recompute"][0] is False
    assert row_202["possible_recompute"][0] is False


def test_detect_recomputations_command_only() -> None:
    """Verify command-only match flags possible_recompute without is_recompute."""
    t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(days=1)

    rows = [
        {
            "job_id": "301",
            "source": "sacct",
            "user": "bob",
            "state": "COMPLETED",
            "run_s": 1800,
            "wait_s": 5,
            "submit_time": t0,
            "end_time": t0 + timedelta(seconds=1800),
            "command_hash": "cmd_gamma",
            "input_hash": None,
        },
        {
            "job_id": "302",
            "source": "sacct",
            "user": "bob",
            "state": "COMPLETED",
            "run_s": 1800,
            "wait_s": 5,
            "submit_time": t1,
            "end_time": t1 + timedelta(seconds=1800),
            "command_hash": "cmd_gamma",
            "input_hash": None,
        },
    ]
    df = pl.DataFrame(rows)
    res = detect_recomputations(df, recompute_window_s=2592000)

    row_302 = res.filter(pl.col("job_id") == "302")
    assert row_302["is_recompute"][0] is False
    assert row_302["possible_recompute"][0] is True
    assert row_302["recompute_confidence"][0] == "command_only"


def test_detect_recomputations_swf_unavailability() -> None:
    """Verify SWF trace jobs report recompute confidence as not_available."""
    rows = [
        {
            "job_id": "1",
            "source": "swf",
            "user": "user1",
            "state": "COMPLETED",
            "run_s": 100,
            "wait_s": 5,
            "submit_time": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            "end_time": datetime(2026, 1, 1, 0, 1, 40, tzinfo=UTC),
            "command_hash": "exe_1",
            "input_hash": None,
        },
        {
            "job_id": "2",
            "source": "swf",
            "user": "user1",
            "state": "COMPLETED",
            "run_s": 100,
            "wait_s": 5,
            "submit_time": datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
            "end_time": datetime(2026, 1, 1, 0, 3, 40, tzinfo=UTC),
            "command_hash": "exe_1",
            "input_hash": None,
        },
    ]
    df = pl.DataFrame(rows)
    res = detect_recomputations(df)

    assert res["is_recompute"].to_list() == [False, False]
    assert res["possible_recompute"].to_list() == [False, False]
    assert res["recompute_confidence"].to_list() == ["not_available", "not_available"]


def test_simulate_result_cache() -> None:
    """Verify result cache simulation calculates hit rates and reclaimable hours."""
    rows = [
        {
            "job_id": "401",
            "user": "carol",
            "command_hash": "cmd_cache",
            "state": "COMPLETED",
            "is_recompute": False,
            "reserved_core_s": 3600,
            "reserved_mem_mb_s": 3600000,
            "class4_core_s": 0,
            "class4_mem_mb_s": 0,
        },
        {
            "job_id": "402",
            "user": "carol",
            "command_hash": "cmd_cache",
            "state": "COMPLETED",
            "is_recompute": True,
            "reserved_core_s": 3600,
            "reserved_mem_mb_s": 3600000,
            "class4_core_s": 3600,
            "class4_mem_mb_s": 3600000,
        },
    ]
    df = pl.DataFrame(rows)
    recs = simulate_result_cache(df, cache_threshold_waste_share=0.05)

    assert len(recs) == 1
    rec = recs[0]
    assert rec["cache_hits"] == 1
    assert rec["total_completed_jobs"] == 2
    assert rec["hit_rate"] == 0.5
    assert rec["reclaimable_core_hours"] == 1.0
    assert rec["recommended"] is True


def test_evaluate_recomputation_accuracy_exact() -> None:
    """Verify accuracy evaluation computes exact 1.0 recall and precision for planted duplicates."""
    det_df = pl.DataFrame(
        [
            {"job_id": "1", "is_recompute": False},
            {"job_id": "2", "is_recompute": True},
            {"job_id": "3", "is_recompute": True},
            {"job_id": "4", "is_recompute": False},
        ]
    )
    truth_df = pl.DataFrame(
        [
            {"job_id": "1", "planted_is_recompute": False},
            {"job_id": "2", "planted_is_recompute": True},
            {"job_id": "3", "planted_is_recompute": True},
            {"job_id": "4", "planted_is_recompute": False},
        ]
    )

    metrics = evaluate_recomputation_accuracy(det_df, truth_df)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1_score"] == 1.0
    assert metrics["true_positives"] == 2.0
    assert metrics["false_positives"] == 0.0
    assert metrics["false_negatives"] == 0.0


def test_recompute_coverage_edges(tmp_path: Path) -> None:
    """Verify alternative evaluation columns and edge conditions."""
    # Test fallback evaluation with class4_core_s and true_class
    det_df = pl.DataFrame(
        [{"job_id": "1", "class4_core_s": 3600}, {"job_id": "2", "class4_core_s": 0}]
    )
    truth_df = pl.DataFrame([{"job_id": "1", "true_class": 4}, {"job_id": "2", "true_class": 1}])
    metrics = evaluate_recomputation_accuracy(det_df, truth_df)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0

    # Test merge_sidecars when sidecar_dir does not exist
    df = empty_canonical_df()
    merged = merge_sidecars(df, sidecar_dir=tmp_path / "nonexistent_sidecars")
    assert merged.height == 0

    # Test simulate_result_cache on empty DataFrame
    assert simulate_result_cache(empty_canonical_df()) == []

    # Test simulate_result_cache with group_key already provided
    custom_df = pl.DataFrame(
        [
            {
                "group_key": "grp1",
                "state": "COMPLETED",
                "class4_core_s": 3600,
                "class4_mem_mb_s": 3600000,
                "reserved_core_s": 3600,
            }
        ]
    )
    custom_recs = simulate_result_cache(custom_df)
    assert len(custom_recs) == 1
    assert custom_recs[0]["group"] == "grp1"

    # Test detect_recomputations on non-completed states
    failed_rows = [
        {
            "job_id": "501",
            "source": "sacct",
            "state": "FAILED",
            "command_hash": "c1",
            "input_hash": "i1",
            "submit_time": datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
        },
        {
            "job_id": "502",
            "source": "sacct",
            "state": "FAILED",
            "command_hash": "c1",
            "input_hash": "i1",
            "submit_time": datetime(2026, 3, 1, 11, 0, 0, tzinfo=UTC),
        },
    ]
    failed_res = detect_recomputations(pl.DataFrame(failed_rows))
    assert failed_res["is_recompute"].to_list() == [False, False]
