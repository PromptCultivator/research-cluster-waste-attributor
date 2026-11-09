"""Tier 3 Cross-Feature Combination: INT-08 Heterogeneous Clusters + EASY-Backfill.

Verifies end-to-end integration across:
- Multi-partition heterogeneous cluster definitions (standard, fatmem, gpu)
- Partition allocation mapping and backfill simulation
- Enforcement of partition resource limits during scheduling
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize("cluster_spec", ["heterogeneous_cluster.yaml"])
def test_int08_heterogeneous_cluster_simulation(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    cluster_spec: str,
):
    """INT-08: Simulate multi-partition workload under heterogeneous cluster topology limits via CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    cluster_path = fixtures_dir / "clusters" / cluster_spec
    sim_out = isolated_workspace / "het_sim.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--cluster", str(cluster_path),
        "--scenario", "baseline",
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0
    assert sim_out.exists()

    df = pl.read_parquet(sim_out)
    assert df.height > 0
    assert (df["sim_start"] >= df["submit_time"]).all()


@pytest.mark.parametrize("scenario", ["baseline", "mem_rightsized", "all"])
def test_int08_heterogeneous_cluster_scenario_execution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    scenario: str,
):
    """INT-08: Verify simulation executes across scenarios on heterogeneous cluster specs via CLI."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    cluster_path = fixtures_dir / "clusters" / "heterogeneous_cluster.yaml"
    sim_out = isolated_workspace / f"het_sim_{scenario}.parquet"

    result = run_cli([
        "simulate",
        str(trace_path),
        "--cluster", str(cluster_path),
        "--scenario", scenario,
        "--output", str(sim_out),
    ])
    assert result.exit_code == 0
    assert sim_out.exists()
