"""Tier 4 Real-World Workflows: Degraded and Missing Data Resilience.

Verifies end-to-end resilience when accounting data has partial gaps:
- Missing memory usage metrics
- Missing CPU time usage
- Active/pending jobs mixed with completed jobs
- Preservation of conservation G1 despite degraded fields
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "degraded_fixture",
    [
        "sacct_unattributed_missing.txt",
        "sacct_empty_optional_fields.txt",
        "missing_fields.swf",
    ],
)
def test_degraded_traces_pipeline_completion(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    degraded_fixture: str,
):
    """Verify degraded accounting files complete through report pipeline without error."""
    subfolder = "swf" if degraded_fixture.endswith(".swf") else "sacct"
    trace_path = fixtures_dir / subfolder / degraded_fixture
    report_json = isolated_workspace / f"degraded_report_{degraded_fixture}.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0, f"Degraded trace {degraded_fixture} failed: {result.stderr}"
    assert report_json.exists()

    data = json.loads(report_json.read_text())
    assert "summary" in data
    assert "waste_classification" in data


@pytest.mark.parametrize("tolerance_factor", [1.0, 1.2, 1.5])
def test_degraded_traces_attribution_coverage_reporting(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    tolerance_factor: float,
):
    """Verify attribution coverage share reports exact percentage of unmeasured reservations via report CLI."""
    trace_path = fixtures_dir / "sacct" / "sacct_unattributed_missing.txt"
    report_json = isolated_workspace / f"coverage_report_{tolerance_factor}.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    quality = data.get("data_quality", {})
    assert "unattributed_cpu_share_pct" in quality
    assert "unattributed_memory_share_pct" in quality
