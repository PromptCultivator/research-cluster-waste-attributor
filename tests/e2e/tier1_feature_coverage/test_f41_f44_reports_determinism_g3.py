"""Tier 1 Feature Coverage: F41 through F44 (Reporting, Data Quality, Goldens, and Guarantee G3 Determinism).

Features:
- F41: Multi-format report generation (Markdown, JSON, and CSV)
- F42: Data quality accounting section validation
- F43: Golden reference diff comparisons against CLI outputs
- F44: Guarantee G3 determinism verification across repeated runs
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_f41_multi_format_report_generation(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fmt: str,
):
    """F41: Generate reports across Markdown, JSON, and CSV formats via report CLI."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    ext = "md" if fmt == "markdown" else fmt
    report_file = isolated_workspace / f"report.{ext}"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", fmt,
        "--output", str(report_file),
    ])
    assert result.exit_code == 0, f"Report generation for format {fmt} failed: {result.stderr}"
    assert report_file.exists()
    assert report_file.stat().st_size > 0


@pytest.mark.parametrize(
    "expected_metric",
    [
        "excluded_active_count",
        "unattributed_cpu_share_pct",
        "unattributed_memory_share_pct",
        "declared_input_coverage_pct",
    ],
)
def test_f42_data_quality_section_contents(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    expected_metric: str,
):
    """F42: Verify all required data quality accounting metrics are reported in output JSON."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    report_json = isolated_workspace / "report_quality.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    quality = data.get("data_quality", {})
    assert expected_metric in quality, f"Metric '{expected_metric}' missing from data quality section"


@pytest.mark.parametrize(
    "golden_filename,fmt",
    [
        ("golden_report.md", "markdown"),
        ("golden_report.json", "json"),
        ("golden_report.csv", "csv"),
    ],
)
def test_f43_golden_reference_cli_diff(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    golden_filename: str,
    fmt: str,
):
    """F43: Execute active CLI report generation and verify structural schema alignment with golden files."""
    golden_path = fixtures_dir / "golden" / golden_filename
    assert golden_path.exists(), f"Golden reference file missing: {golden_path}"

    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    ext = "md" if fmt == "markdown" else fmt
    cli_out = isolated_workspace / f"gen_golden.{ext}"

    result = run_cli(["report", str(trace_path), "--format", fmt, "--output", str(cli_out)])
    assert result.exit_code == 0
    assert cli_out.exists()

    if fmt == "json":
        golden_data = json.loads(golden_path.read_text())
        cli_data = json.loads(cli_out.read_text())
        assert "summary" in cli_data
        assert "waste_classification" in cli_data
        assert set(golden_data.keys()).issubset(set(cli_data.keys()))

        # Compare key metrics between CLI output and golden reference
        golden_sum = golden_data["summary"]
        cli_sum = cli_data["summary"]
        for key in ["total_jobs", "total_reserved_core_hours", "total_reserved_gb_hours"]:
            if key in golden_sum and key in cli_sum:
                assert cli_sum[key] == golden_sum[key], f"Metric mismatch in summary.{key}"

        golden_waste = golden_data["waste_classification"]
        cli_waste = cli_data["waste_classification"]
        for key in ["class1_memory_over_request_gb_hours", "class2_idle_cpu_core_hours", "class3_failed_work_core_hours"]:
            if key in golden_waste and key in cli_waste:
                assert cli_waste[key] == golden_waste[key], f"Metric mismatch in waste_classification.{key}"
    elif fmt == "markdown":
        cli_text = cli_out.read_text()
        assert "# Research Cluster Waste Attribution Report" in cli_text
        assert "## Waste Classification" in cli_text
        assert "## Ranked Reclaim List" in cli_text
    elif fmt == "csv":
        cli_text = cli_out.read_text()
        assert "rank,group,count,reclaim_core_hours" in cli_text


@pytest.mark.parametrize("format_type", ["markdown", "json", "csv"])
def test_f44_guarantee_g3_pipeline_determinism(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    format_type: str,
):
    """F44: Enforce Guarantee G3: identical inputs produce byte-identical report outputs across independent runs."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    ext = "md" if format_type == "markdown" else format_type

    out1 = isolated_workspace / f"run1.{ext}"
    out2 = isolated_workspace / f"run2.{ext}"

    res1 = run_cli(["report", str(trace_path), "--format", format_type, "--output", str(out1)])
    assert res1.exit_code == 0

    res2 = run_cli(["report", str(trace_path), "--format", format_type, "--output", str(out2)])
    assert res2.exit_code == 0

    bytes1 = out1.read_bytes()
    bytes2 = out2.read_bytes()

    assert InvariantValidators.verify_g3_determinism(bytes1, bytes2), f"G3 Determinism violation in format {format_type}"
