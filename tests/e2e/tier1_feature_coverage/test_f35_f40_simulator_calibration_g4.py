"""Tier 1 Feature Coverage: F35 through F40 (Simulator, Scenarios, Calibration, and Guarantee G4).

Features:
- F35: Cluster topology loading and trace peak inference
- F36: EASY-backfill discrete-event simulation engine
- F37: Simulation scenarios (baseline, mem_rightsized, cpu_rightsized, cache_dedup, all)
- F38: Calibration metrics (median absolute error and Spearman correlation)
- F39: Guarantee G4 simulator validity invariants across scenarios
- F40: Simulation throughput verification
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "cluster_file,expected_exit",
    [
        ("homogeneous_cluster.yaml", 0),
        ("heterogeneous_cluster.yaml", 0),
    ],
)
def test_f35_cluster_spec_loading(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    cluster_file: str,
    expected_exit: int,
):
    """F35: Test loading cluster topology specification via simulate CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    cluster_path = fixtures_dir / "clusters" / cluster_file
    sim_out = isolated_workspace / f"sim_spec_{cluster_file}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--cluster", str(cluster_path),
        "--scenario", "baseline",
        "--output", str(sim_out),
    ])
    assert result.exit_code == expected_exit


@pytest.mark.parametrize("trace_name", ["standard_with_headers.swf", "sample_workload.swf"])
def test_f35_cluster_topology_inference(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """F35: Verify cluster topology inference from trace maximum allocation peaks when no cluster is provided."""
    trace_path = fixtures_dir / "swf" / trace_name
    sim_out = isolated_workspace / f"sim_infer_{trace_name}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--scenario", "baseline",
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0
    assert sim_out.exists()


@pytest.mark.parametrize(
    "scenario",
    [
        "baseline",
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cache_dedup",
        "all",
    ],
)
def test_f36_f37_simulation_scenarios(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario: str,
):
    """F36, F37: Replay workload through EASY-backfill scheduler across each scenario via CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    sim_out = isolated_workspace / f"sim_{scenario}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--scenario", scenario,
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0, f"Simulation scenario '{scenario}' failed: {result.stderr}"
    assert sim_out.exists()

    df = pl.read_parquet(sim_out)
    assert df.height > 0
    assert "sim_start" in df.columns
    assert "sim_wait_s" in df.columns


@pytest.mark.parametrize("trace_name", ["calibration_reference.swf", "sample_workload.swf"])
def test_f38_calibration_mae_and_spearman(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """F38: Verify median absolute error and Spearman rank correlation calibration metrics via calibrate CLI."""
    trace_path = fixtures_dir / "swf" / trace_name
    calib_out = isolated_workspace / f"calib_{trace_name}.json"

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


@pytest.mark.parametrize(
    "scenario",
    [
        "baseline",
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cache_dedup",
        "all",
    ],
)
def test_f39_guarantee_g4_simulation_validity(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario: str,
):
    """F39: Enforce Guarantee G4: completeness, temporal ordering, and capacity limits across all 5+ scenarios."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    sim_out = isolated_workspace / f"g4_sim_{scenario}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--scenario", scenario,
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0

    df = pl.read_parquet(sim_out)
    jobs = df.to_dicts()

    valid = InvariantValidators.verify_g4_schedule_validity(
        scheduled_jobs=jobs,
        total_nodes=16,
        cores_per_node=32,
        mem_mb_per_node=131072,
    )
    assert valid, f"Guarantee G4 violated in scenario {scenario}"


@pytest.mark.parametrize("job_count,max_duration_seconds", [(10, 5.0), (20, 10.0)])
def test_f40_simulation_throughput_benchmark(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    job_count: int,
    max_duration_seconds: float,
):
    """F40: Verify EASY-backfill simulation event loop execution speed on workload traces via simulate CLI."""
    import time

    lines = ["; MaxProcs: 256", "; MaxNodes: 16"]
    for i in range(1, job_count + 1):
        lines.append(f"{i} {i * 10} 0 60 4 60 4096 4 100 4096 1 1 1 1 -1 -1 -1 -1")
    swf_file = isolated_workspace / f"bench_sim_{job_count}.swf"
    sim_out = isolated_workspace / f"bench_sim_{job_count}.parquet"
    swf_file.write_text("\n".join(lines) + "\n")

    start = time.perf_counter()
    result = run_cli(["simulate", str(swf_file), "--scenario", "baseline", "--output", str(sim_out)])
    duration = time.perf_counter() - start

    assert result.exit_code == 0
    assert duration <= max_duration_seconds
