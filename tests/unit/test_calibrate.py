"""Unit test suite for simulator calibration metrics."""

from pathlib import Path

import polars as pl
import pytest

from rcwa.calibrate import calibrate_trace, compute_calibration_metrics


def test_calibration_metrics_perfect_alignment() -> None:
    """Verify MAE is 0.0 and Spearman correlation is 1.0 when simulated wait equals historical wait."""
    sim_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "sim_wait_s": [10, 20, 30, 40],
        }
    )
    hist_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "wait_s": [10, 20, 30, 40],
        }
    )
    metrics = compute_calibration_metrics(sim_df, hist_df)
    assert metrics["median_absolute_error_s"] == 0.0
    assert metrics["mean_absolute_error_s"] == 0.0
    assert metrics["spearman_rank_correlation"] == 1.0
    assert metrics["job_count"] == 4


def test_calibration_metrics_constant_offset() -> None:
    """Verify MAE captures constant time offset while rank correlation remains 1.0."""
    sim_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "sim_wait_s": [25, 35, 45, 55],
        }
    )
    hist_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "wait_s": [10, 20, 30, 40],
        }
    )
    metrics = compute_calibration_metrics(sim_df, hist_df)
    assert metrics["median_absolute_error_s"] == 15.0
    assert metrics["mean_absolute_error_s"] == 15.0
    assert metrics["spearman_rank_correlation"] == 1.0


def test_calibration_metrics_inverted_ranking() -> None:
    """Verify Spearman correlation is -1.0 when rankings are completely inverted."""
    sim_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "sim_wait_s": [40, 30, 20, 10],
        }
    )
    hist_df = pl.DataFrame(
        {
            "job_id": ["1", "2", "3", "4"],
            "wait_s": [10, 20, 30, 40],
        }
    )
    metrics = compute_calibration_metrics(sim_df, hist_df)
    assert metrics["spearman_rank_correlation"] == -1.0


def test_calibration_metrics_empty() -> None:
    """Verify calibration metrics on empty DataFrames return zeroed structure."""
    sim_df = pl.DataFrame(schema={"job_id": pl.String, "sim_wait_s": pl.Int64})
    hist_df = pl.DataFrame(schema={"job_id": pl.String, "wait_s": pl.Int64})
    metrics = compute_calibration_metrics(sim_df, hist_df)
    assert metrics["median_absolute_error_s"] == 0.0
    assert metrics["spearman_rank_correlation"] == 0.0
    assert metrics["job_count"] == 0


def test_calibrate_trace_end_to_end() -> None:
    """Verify calibrate_trace executes on a fixture trace and returns calibration metrics."""
    trace_path = Path("tests/fixtures/swf/calibration_reference.swf")
    metrics = calibrate_trace(trace_path)
    assert "median_absolute_error_s" in metrics
    assert "spearman_rank_correlation" in metrics
    assert metrics["job_count"] == 8
    assert metrics["median_absolute_error_s"] >= 0.0


def test_calibrate_trace_missing_file() -> None:
    """Verify calibrate_trace raises FileNotFoundError when target trace is missing."""
    with pytest.raises(FileNotFoundError):
        calibrate_trace("nonexistent_trace.swf")
