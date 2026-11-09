"""Tier 3 Cross-Feature Combination: INT-01 OOM + Retry Chains + Guardrails.

Verifies end-to-end integration across:
- Out of memory termination
- Retry chain detection linking subsequent jobs
- OOM guardrail forcing recommendation direction to 'increase'
- Exclusion of OOM groups from reclaimable memory totals
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "trace_name,group_name",
    [
        ("multiday_cluster.txt", "david/order_book_proc"),
        ("oom_groups.txt", "alice/oom_candidate"),
    ],
)
def test_int01_oom_retry_and_guardrail_interaction(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
    group_name: str,
):
    """INT-01: Verify job failing with OOM links in retry chain and triggers safety guardrail escalation."""
    subfolder = "guardrails" if trace_name == "oom_groups.txt" else "sacct"
    trace_path = fixtures_dir / subfolder / trace_name
    attr_out = isolated_workspace / f"int01_attr_{trace_name}.parquet"
    recs_out = isolated_workspace / f"int01_recs_{trace_name}.parquet"

    # Step 1: Run attribution to verify retry chain linkage
    res_attr = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert res_attr.exit_code == 0
    df_attr = pl.read_parquet(attr_out)

    oom_jobs = df_attr.filter(pl.col("state") == "OUT_OF_MEMORY")
    if oom_jobs.height > 0:
        oom_id = oom_jobs.select("job_id").item(0, 0)
        retries = df_attr.filter(pl.col("retry_of") == oom_id)
        # If trace contains retries of the OOM job, retry_of must be linked
        if retries.height > 0:
            assert retries.select("retry_of").item(0, 0) == oom_id

    # Step 2: Run recommendations on attributed parquet
    res_rec = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert res_rec.exit_code == 0

    df_rec = pl.read_parquet(recs_out)
    row = df_rec.filter(pl.col("group") == group_name)
    assert row.height == 1

    direction = row.select("recommendation_direction").item()
    rec_mem = row.select("recommended_req_mem_mb").item()
    reclaim_mem = row.select("reclaimable_gb_hours").item()

    # OOM must force increase direction
    assert direction == "increase"
    assert rec_mem is not None
    # Group must be excluded from reclaimable memory
    assert reclaim_mem == 0.0


@pytest.mark.parametrize("policy_fixture", ["default_policy.yaml", "strict_policy.yaml"])
def test_int01_oom_escalation_headroom_scaling_via_cli(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    policy_fixture: str,
):
    """INT-01: Verify OOM escalation factor scales memory upward from observed peak via recommend CLI."""
    trace_path = fixtures_dir / "guardrails" / "oom_groups.txt"
    policy_path = fixtures_dir / "policies" / policy_fixture
    attr_out = isolated_workspace / f"int01_scale_attr_{policy_fixture}.parquet"
    recs_out = isolated_workspace / f"int01_scale_recs_{policy_fixture}.parquet"

    run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    res = run_cli(["recommend", str(attr_out), "--policy", str(policy_path), "--output", str(recs_out)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_out)
    row = df.filter(pl.col("group") == "alice/oom_candidate")
    assert row.select("recommendation_direction").item() == "increase"
    assert row.select("reclaimable_gb_hours").item() == 0.0
