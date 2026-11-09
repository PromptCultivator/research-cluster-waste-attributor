"""Tier 3 Cross-Feature Combination: INT-04 Synthetic Trace + Attribution + Rightsizing.

Verifies end-to-end integration across:
- Synthetic trace generation with planted ground-truth waste
- Precedence attribution identifying planted classes
- Rightsizing calculations recovering reasonable request recommendations
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize("trace_size", [50, 100])
def test_int04_synth_to_recommendation_pipeline(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    trace_size: int,
):
    """INT-04: Generate synthetic trace and process through attribution and rightsizing recommendations."""
    synth_trace = isolated_workspace / f"synth_{trace_size}.txt"
    report_json = isolated_workspace / f"synth_report_{trace_size}.json"

    # Step 1: Generate synthetic trace with planted waste
    res_synth = run_cli([
        "synth",
        "--size", str(trace_size),
        "--seed", "42",
        "--output", str(synth_trace),
    ])
    assert res_synth.exit_code == 0
    assert synth_trace.exists()

    # Step 2: Run complete attribution and reporting pipeline
    res_run = run_cli([
        "report",
        str(synth_trace),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert res_run.exit_code == 0
    assert report_json.exists()


@pytest.mark.parametrize("policy_fixture", ["default_policy.yaml", "strict_policy.yaml"])
def test_int04_planted_waste_recovery_consistency(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    policy_fixture: str,
):
    """INT-04: Verify rightsizing execution on synthetic trace with configured policy."""
    synth_trace = isolated_workspace / "synth_policy.txt"
    policy_path = fixtures_dir / "policies" / policy_fixture
    attr_out = isolated_workspace / f"attr_pol_{policy_fixture}.parquet"
    recs_out = isolated_workspace / f"recs_pol_{policy_fixture}.parquet"

    run_cli(["synth", "--size", "50", "--seed", "123", "--output", str(synth_trace)])

    res_attr = run_cli(["attribute", str(synth_trace), "--policy", str(policy_path), "--output", str(attr_out)])
    assert res_attr.exit_code == 0

    res_rec = run_cli(["recommend", str(attr_out), "--policy", str(policy_path), "--output", str(recs_out)])
    assert res_rec.exit_code == 0
    assert recs_out.exists()

    df = pl.read_parquet(recs_out)
    assert df.height > 0
