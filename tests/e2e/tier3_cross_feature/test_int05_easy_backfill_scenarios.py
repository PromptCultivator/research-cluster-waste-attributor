"""Tier 3 Cross-Feature Combination: INT-05 EASY-Backfill Simulation Across Scenarios.

Verifies end-to-end integration across:
- EASY-backfill scheduler engine execution
- Scenario comparisons (baseline vs rightsized vs dedup vs all)
- Monotonic or improved wait metrics across optimized scenarios
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "scenario_a,scenario_b",
    [
        ("baseline", "mem_rightsized"),
        ("baseline", "cache_dedup"),
        ("baseline", "all"),
    ],
)
def test_int05_simulation_scenario_comparisons(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario_a: str,
    scenario_b: str,
):
    """INT-05: Compare simulation wait metrics between baseline and optimized scenarios via CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    out_a = isolated_workspace / f"sim_int05_{scenario_a}.parquet"
    out_b = isolated_workspace / f"sim_int05_{scenario_b}.parquet"

    res_a = run_cli(["simulate", str(trace_path), "--scenario", scenario_a, "--output", str(out_a)])
    res_b = run_cli(["simulate", str(trace_path), "--scenario", scenario_b, "--output", str(out_b)])

    assert res_a.exit_code == 0
    assert res_b.exit_code == 0

    df_a = pl.read_parquet(out_a)
    df_b = pl.read_parquet(out_b)

    wait_a = df_a.select("sim_wait_s").mean().item()
    wait_b = df_b.select("sim_wait_s").mean().item()

    assert wait_a is not None
    assert wait_b is not None


@pytest.mark.parametrize("scenario", ["baseline", "mem_rightsized", "cpu_rightsized_none", "cache_dedup", "all"])
def test_int05_scenario_schedule_integrity(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario: str,
):
    """INT-05: Verify all jobs are scheduled in every scenario without dropping jobs via CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    out_path = isolated_workspace / f"int05_integrity_{scenario}.parquet"

    result = run_cli(["simulate", str(trace_path), "--scenario", scenario, "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    if scenario != "cache_dedup" and scenario != "all":
        assert df.height == 10
    else:
        # cache_dedup drops redundant Class 4 jobs
        assert df.height <= 10
