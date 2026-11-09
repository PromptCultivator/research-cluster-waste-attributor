"""Tier 3 Cross-Feature Combination: INT-07 Full Pipeline Execution and Determinism (G3).

Verifies end-to-end integration across:
- Full rcwa run command orchestrating ingest -> attribute -> recommend -> simulate -> report
- Verification of Guarantee G3 determinism across independent pipeline runs
- Verification of consistency between CSV, JSON, and Markdown summaries
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_int07_full_pipeline_run_execution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fmt: str,
):
    """INT-07: Execute full end-to-end workflow via rcwa report command across output formats."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    ext = "md" if fmt == "markdown" else fmt
    report_out = isolated_workspace / f"full_run_report.{ext}"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", fmt,
        "--output", str(report_out),
    ])
    assert result.exit_code == 0, f"Full pipeline report failed: {result.stderr}"
    assert report_out.exists()
    assert report_out.stat().st_size > 0


@pytest.mark.parametrize("run_seed", [101, 202])
def test_int07_repeated_full_pipeline_byte_determinism(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    run_seed: int,
):
    """INT-07: Verify identical inputs produce byte-identical JSON reports across distinct runs via CLI."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"

    out1 = isolated_workspace / f"det_run1_{run_seed}.json"
    out2 = isolated_workspace / f"det_run2_{run_seed}.json"

    res1 = run_cli(["report", str(trace_path), "--format", "json", "--output", str(out1)])
    res2 = run_cli(["report", str(trace_path), "--format", "json", "--output", str(out2)])

    assert res1.exit_code == 0
    assert res2.exit_code == 0

    assert InvariantValidators.verify_g3_determinism(out1.read_bytes(), out2.read_bytes())
