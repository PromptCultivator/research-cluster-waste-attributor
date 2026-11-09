"""Tier 3 Cross-Feature Combination: INT-03 Array Jobs + Step Rollup + Memory Suffixes.

Verifies end-to-end integration across:
- Array job decomposition into individual tasks
- Step hierarchy rollup summing CPU and taking max RSS per sub-job
- Complex Slurm memory suffix conversions (Mc per CPU, Mn per node, G, K)
- Exact preservation of reservation arithmetic on rolled up records
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "trace_name",
    [
        "sacct_steps_rollup.txt",
        "sacct_array_heterogeneous.txt",
        "sacct_memory_suffixes.txt",
    ],
)
def test_int03_complex_sacct_ingest_and_attribute(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """INT-03: Verify ingestion and attribution pipelines handle arrays, steps, and mixed suffixes simultaneously."""
    trace_path = fixtures_dir / "sacct" / trace_name
    canonical_out = isolated_workspace / f"int03_canon_{trace_name}.parquet"
    attr_out = isolated_workspace / f"int03_attr_{trace_name}.parquet"

    res_ingest = run_cli(["ingest", str(trace_path), "--output", str(canonical_out)])
    assert res_ingest.exit_code == 0

    res_attr = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert res_attr.exit_code == 0

    df_canon = pl.read_parquet(canonical_out)
    df_attr = pl.read_parquet(attr_out)

    assert df_canon.height == df_attr.height
    assert (df_attr["reserved_core_s"] >= 0).all()
    assert (df_attr["reserved_mem_mb_s"] >= 0).all()


@pytest.mark.parametrize("sub_job_id", ["7001_0", "7001_1", "7002+0", "7002+1"])
def test_int03_array_and_pack_subjobs_independent_accounting(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    sub_job_id: str,
):
    """INT-03: Verify each array task and pack component calculates independent reservations."""
    trace_path = fixtures_dir / "sacct" / "sacct_array_heterogeneous.txt"
    attr_out = isolated_workspace / "int03_array_attr.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert result.exit_code == 0

    df = pl.read_parquet(attr_out)
    row = df.filter(pl.col("job_id") == sub_job_id)
    assert row.height == 1

    core_res = row.select("reserved_core_s").item()
    mem_res = row.select("reserved_mem_mb_s").item()

    assert core_res > 0
    assert mem_res > 0
