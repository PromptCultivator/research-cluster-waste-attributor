"""Tier 4 Guarantee Suite: G4 Simulator Validity Exhaustive Verification.

Mathematical Guarantee G4:
- Every job appears exactly once in the schedule per scenario
- Job simulation start timestamp >= submit timestamp (sim_start >= submit_time)
- Aggregate node capacity (cores and memory) is respected at every simulated timestep
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "trace_name",
    [
        "standard_with_headers.swf",
        "sample_workload.swf",
        "calibration_reference.swf",
    ],
)
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
def test_guarantee_g4_schedule_validity_all_scenarios(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
    scenario: str,
):
    """Enforce G4: verify schedule validity and capacity compliance across traces and scenarios via simulate CLI."""
    trace_path = fixtures_dir / "swf" / trace_name
    sim_out = isolated_workspace / f"g4_suite_{trace_name}_{scenario}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--scenario", scenario,
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0, f"Simulation failed: {result.stderr}"

    df = pl.read_parquet(sim_out)
    jobs = df.to_dicts()

    valid = InvariantValidators.verify_g4_schedule_validity(
        scheduled_jobs=jobs,
        total_nodes=16,
        cores_per_node=32,
        mem_mb_per_node=131072,
    )
    assert valid, f"Guarantee G4 violated on {trace_name} scenario {scenario}"


@pytest.mark.parametrize("scenario", ["baseline", "mem_rightsized", "all"])
def test_guarantee_g4_sim_start_after_submit_invariance(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario: str,
):
    """Enforce G4: strictly verify that sim_start >= submit_time for every scheduled job via simulate CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    sim_out = isolated_workspace / f"g4_timing_{scenario}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--scenario", scenario,
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0

    df = pl.read_parquet(sim_out)
    diff = df["sim_start"] - df["submit_time"]
    assert (diff >= 0).all(), f"Found jobs scheduled before submit time in scenario {scenario}"
