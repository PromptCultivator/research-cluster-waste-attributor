"""Tier 2 Boundary and Corner Cases: Empty and Truncated Inputs.

Verifies system handling of:
- Zero-byte files
- Header-only files
- Truncated rows with column counts below schema requirements
- Empty SWF traces
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "fixture_name,expected_exit",
    [
        ("empty_file.txt", 0),
        ("header_only.txt", 0),
        ("malformed_row_short.txt", 0),
    ],
)
def test_boundary_sacct_empty_and_short_inputs(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
    expected_exit: int,
):
    """Verify sacct ingest handles 0-byte, header-only, and short rows without unhandled crashes."""
    trace_path = fixtures_dir / "edge" / fixture_name
    out_path = isolated_workspace / f"edge_{fixture_name}.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == expected_exit
    assert out_path.exists()

    df = pl.read_parquet(out_path)
    if fixture_name in ("empty_file.txt", "header_only.txt"):
        assert df.height == 0


@pytest.mark.parametrize("swf_fixture", ["empty_swf.swf"])
def test_boundary_swf_empty_trace(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    swf_fixture: str,
):
    """Verify SWF parser handles zero-byte files gracefully without unhandled exceptions."""
    trace_path = fixtures_dir / "edge" / swf_fixture
    out_path = isolated_workspace / f"edge_{swf_fixture}.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()

    df = pl.read_parquet(out_path)
    assert df.height == 0


@pytest.mark.parametrize(
    "truncated_line",
    [
        "1001|1001|alice|quant|compute",
        "1002|1002",
        "1003",
        "",
        "||||||||||",
    ],
)
def test_boundary_truncated_sacct_rows(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    truncated_line: str,
):
    """Verify sacct row parser detects and tolerates rows with insufficient columns via CLI."""
    trace_file = isolated_workspace / f"trunc_{hash(truncated_line)}.txt"
    out_file = isolated_workspace / f"trunc_{hash(truncated_line)}.parquet"

    header = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
    trace_file.write_text(header + truncated_line + "\n")

    result = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()


@pytest.mark.parametrize("line_count", [0, 1, 5])
def test_boundary_header_only_pipeline_run(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    line_count: int,
):
    """Verify report execution on header-only inputs generates an empty summary report."""
    trace_path = fixtures_dir / "edge" / "header_only.txt"
    out_report = isolated_workspace / f"header_only_report_{line_count}.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(out_report),
    ])
    assert result.exit_code == 0
    assert out_report.exists()
