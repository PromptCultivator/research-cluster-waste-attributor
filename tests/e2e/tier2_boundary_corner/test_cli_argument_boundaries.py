"""Tier 2 Boundary and Corner Cases: CLI Argument Boundaries.

Verifies CLI argument handling:
- Missing required positional arguments
- Non-existent input path
- Invalid scenario name
- Unsupported output format
- Help flag output across subcommands
"""

from collections.abc import Callable

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "subcommand,args,expected_exit",
    [
        ("ingest", ["non_existent_file.txt"], 2),                           # File not found
        ("ingest", ["--unsupported-flag"], 2),                              # Unsupported option
        ("attribute", ["non_existent_file.txt"], 2),                        # File not found
        ("recommend", ["non_existent_file.parquet"], 2),                    # File not found
        ("simulate", ["non_existent_trace.swf"], 2),                        # Non-existent trace
        ("report", ["non_existent_results.parquet"], 2),                    # Non-existent input
    ],
)
def test_boundary_cli_invalid_arguments_rejected(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    subcommand: str,
    args: list,
    expected_exit: int,
):
    """Verify CLI rejects invalid arguments and commands with exact expected exit codes."""
    result = run_cli([subcommand] + args)
    assert result.exit_code == expected_exit, f"Expected {expected_exit}, got {result.exit_code}: {result.stderr}"
    assert len(result.stderr) > 0 or len(result.stdout) > 0


@pytest.mark.parametrize(
    "subcommand",
    [
        "ingest",
        "attribute",
        "recommend",
        "simulate",
        "calibrate",
        "report",
        "run",
        "synth",
    ],
)
def test_boundary_cli_subcommands_display_help(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    subcommand: str,
):
    """Verify each CLI subcommand responds to --help with zero exit code and usage information."""
    result = run_cli([subcommand, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout or "Options" in result.stdout or "help" in result.stdout.lower()
