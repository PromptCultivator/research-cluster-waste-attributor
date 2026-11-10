"""Tests verifying CLI report outputs against golden reference fixtures."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcwa.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "trace_rel,golden_prefix",
    [
        ("sacct/multiday_cluster.txt", "golden_report"),
        ("swf/sample_workload.swf", "golden_swf_report"),
    ],
)
@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_cli_report_matches_golden_fixture(
    fixtures_dir: Path,
    tmp_path: Path,
    trace_rel: str,
    golden_prefix: str,
    fmt: str,
) -> None:
    """Verify that rcwa report on fixture traces matches the committed golden fixture."""
    trace_path = fixtures_dir / trace_rel
    ext = "md" if fmt == "markdown" else fmt
    golden_file = fixtures_dir / "golden" / f"{golden_prefix}.{ext}"
    assert golden_file.exists(), f"Golden file not found: {golden_file}"

    out_file = tmp_path / f"output.{ext}"
    res = runner.invoke(
        app, ["report", str(trace_path), "--format", fmt, "--output", str(out_file)]
    )
    assert res.exit_code == 0, f"rcwa report failed: {res.stdout}"

    expected_bytes = golden_file.read_bytes()
    actual_bytes = out_file.read_bytes()

    assert (
        actual_bytes == expected_bytes
    ), f"Generated {fmt} report for {trace_rel} does not match {golden_file.name}"


def test_swf_report_class4_not_available(fixtures_dir: Path, tmp_path: Path) -> None:
    """Verify SWF trace explicitly marks Class 4 recomputation as 'not available'."""
    trace_path = fixtures_dir / "swf" / "sample_workload.swf"
    out_json = tmp_path / "swf_report.json"
    out_md = tmp_path / "swf_report.md"

    res_json = runner.invoke(
        app, ["report", str(trace_path), "--format", "json", "--output", str(out_json)]
    )
    assert res_json.exit_code == 0

    res_md = runner.invoke(
        app, ["report", str(trace_path), "--format", "markdown", "--output", str(out_md)]
    )
    assert res_md.exit_code == 0

    data = json.loads(out_json.read_text())
    assert data["waste_classification"]["class4_status"] == "not available"
    assert data["waste_classification"]["class4_redundant_core_hours"] == 0.0
    assert data["waste_classification"]["class4_redundant_gb_hours"] == 0.0

    # Ensure no cache hits or recommendations are produced for SWF traces
    for item in data.get("result_cache", []):
        assert item.get("cache_hits", 0) == 0
        assert item.get("reclaim_core_hours", 0.0) == 0.0
        assert item.get("recommended") is False

    md_text = out_md.read_text()
    assert "| Class 4: Redundant Recomputation | not available | - | not available | - |" in md_text
    assert "## Result Cache Recommendations" not in md_text
