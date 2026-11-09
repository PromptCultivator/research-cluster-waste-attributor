"""Tier 3 Cross-Feature Combination: INT-06 Simulator Calibration MAE & Spearman.

Verifies end-to-end integration across:
- Baseline EASY-backfill simulation on historical trace
- Extraction of historical wait times from trace records
- Computation of Median Absolute Error (MAE) and Spearman rank correlation
- Inclusion of calibration metrics in output report
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize("trace_name", ["calibration_reference.swf"])
def test_int06_calibration_pipeline_execution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """INT-06: Execute calibration pipeline and verify MAE and Spearman correlation outputs via CLI."""
    trace_path = fixtures_dir / "swf" / trace_name
    calib_out = isolated_workspace / "calib_results.json"

    result = run_cli([
        "calibrate",
        str(trace_path),
        "--output", str(calib_out),
    ])
    assert result.exit_code == 0
    assert calib_out.exists()

    data = json.loads(calib_out.read_text())
    assert "median_absolute_error_s" in data
    assert "spearman_rank_correlation" in data

    mae = data["median_absolute_error_s"]
    spearman = data["spearman_rank_correlation"]

    assert mae >= 0.0
    assert -1.0 <= spearman <= 1.0


@pytest.mark.parametrize("cluster_fixture", ["homogeneous_cluster.yaml", "heterogeneous_cluster.yaml"])
def test_int06_calibration_across_cluster_topologies(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    cluster_fixture: str,
):
    """INT-06: Verify calibration execution across cluster configurations via calibrate CLI."""
    trace_path = fixtures_dir / "swf" / "calibration_reference.swf"
    cluster_path = fixtures_dir / "clusters" / cluster_fixture
    calib_out = isolated_workspace / f"calib_{cluster_fixture}.json"

    res = run_cli([
        "calibrate",
        str(trace_path),
        "--cluster", str(cluster_path),
        "--output", str(calib_out),
    ])
    assert res.exit_code == 0
    assert calib_out.exists()
