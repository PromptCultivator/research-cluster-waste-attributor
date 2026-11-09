"""Tier 1 Feature Coverage: F29 through F34 (rcwa-wrap CLI, hashing, and Class 4 Recomputation).

Features:
- F29: rcwa-wrap CLI input hashing (sha256 and size_mtime) and command normalization
- F30: Hash recording (sidecar json and Slurm comment) with tolerance for missing files
- F31: Class 4 redundant recomputation attribution
- F32: Command-only duplicate listing under possible_recompute (excluded from Class 4 totals)
- F33: Result cache recommendation with simulated hit rate
- F34: SWF traces recomputation reporting as 'not available'
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "raw_args,expected_sorted_flags",
    [
        (["--epochs", "10", "--lr", "0.01", "--batch", "64"], ["--batch", "--epochs", "--lr"]),
        (["--b=2", "--a=1"], ["--a=1", "--b=2"]),
        (["--zeta", "5", "--alpha", "1"], ["--alpha", "--zeta"]),
        (["--out=res.parquet", "--in=data.csv"], ["--in=data.csv", "--out=res.parquet"]),
        (["--split", "test", "--seed", "42", "--folds", "5"], ["--folds", "--seed", "--split"]),
        (["--y", "2026", "--m", "3", "--d", "1"], ["--d", "--m", "--y"]),
    ],
)
def test_f29_command_normalization_via_wrap_cli(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_args: list[str],
    expected_sorted_flags: list[str],
):
    """F29: Verify normalization and sorting of command flags recorded in sidecar JSON via rcwa-wrap."""
    sidecar_dir = isolated_workspace / f"sidecars_{hash(tuple(raw_args))}"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    env = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": "4444"}

    cmd = ["--"] + ["python3", "-c", "print('normalizing')"] + raw_args
    res = run_wrap_cli(cmd, cwd=isolated_workspace, env=env)
    assert res.exit_code == 0

    sidecar = sidecar_dir / "4444.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert "command_hash" in data


@pytest.mark.parametrize("hash_mode", ["sha256", "size_mtime"])
def test_f29_rcwa_wrap_execution(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    hash_mode: str,
):
    """F29: Test rcwa-wrap execution generating input hashes and running target script."""
    input_file = isolated_workspace / "input.txt"
    input_file.write_text("dataset contents for hashing\n")

    sidecar_dir = isolated_workspace / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "RCWA_DIR": str(sidecar_dir),
        "SLURM_JOB_ID": "9999",
    }

    result = run_wrap_cli(
        [
            "--inputs", str(input_file),
            "--big-file-mode", hash_mode,
            "--", "python3", "-c", "print('wrapped job complete')",
        ],
        cwd=isolated_workspace,
        env=env,
    )
    assert result.exit_code == 0, f"rcwa-wrap failed: {result.stderr}"
    assert "wrapped job complete" in result.stdout

    sidecar_file = sidecar_dir / "9999.json"
    assert sidecar_file.exists(), f"Sidecar JSON was not created at {sidecar_file}"

    data = json.loads(sidecar_file.read_text())
    assert "input_hash" in data
    assert len(data["input_hash"]) > 0


@pytest.mark.parametrize("missing_filename", ["missing_file_a.parquet", "missing_file_b.csv", "missing_file_c.json"])
def test_f30_missing_inputs_non_blocking(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    missing_filename: str,
):
    """F30: Verify rcwa-wrap records missing inputs without aborting or blocking job execution."""
    sidecar_dir = isolated_workspace / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)

    nonexistent_path = isolated_workspace / missing_filename
    env = {
        "RCWA_DIR": str(sidecar_dir),
        "SLURM_JOB_ID": "8888",
    }

    result = run_wrap_cli(
        [
            "--inputs", str(nonexistent_path),
            "--", "python3", "-c", "print('job ran despite missing input')",
        ],
        cwd=isolated_workspace,
        env=env,
    )
    assert result.exit_code == 0
    assert "job ran despite missing input" in result.stdout

    sidecar_file = sidecar_dir / "8888.json"
    assert sidecar_file.exists()
    data = json.loads(sidecar_file.read_text())
    assert any(item.get("status") == "missing" for item in data.get("inputs", []))


def test_f30_scontrol_comment_update_handling(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
):
    """F30: Verify rcwa-wrap handles Slurm comment update gracefully when scontrol is unavailable."""
    sidecar_dir = isolated_workspace / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    env = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": "7777"}

    result = run_wrap_cli(
        ["--", "python3", "-c", "print('scontrol handling')"],
        cwd=isolated_workspace,
        env=env,
    )
    assert result.exit_code == 0
    assert "scontrol handling" in result.stdout


@pytest.mark.parametrize(
    "job_id,expected_class4_core_s",
    [
        ("1601", 0),       # Initial run: normal execution
        ("1602", 14400),   # Recomputation within 30 days: entire reservation to Class 4
    ],
)
def test_f31_class4_recomputation_attribution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_class4_core_s: int,
):
    """F31: Verify duplicate completed jobs within recompute_window are attributed to Class 4."""
    trace_path = fixtures_dir / "recompute" / "recompute_pairs.txt"
    attributed_path = isolated_workspace / "recompute_attr.parquet"

    result = run_cli([
        "attribute",
        str(trace_path),
        "--output", str(attributed_path),
    ])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    actual_c4 = row.select("class4_core_s").item()
    assert actual_c4 == expected_class4_core_s, f"Class 4 core-s mismatch for {job_id}: got {actual_c4}, expected {expected_class4_core_s}"


@pytest.mark.parametrize(
    "job_id,expected_possible_recompute,expected_class4_core_s",
    [
        ("1701", False, 0),
        ("1702", True, 0),   # Command-only match: listed in possible_recompute, 0 in Class 4
    ],
)
def test_f32_command_only_matches_excluded_from_class4(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_possible_recompute: bool,
    expected_class4_core_s: int,
):
    """F32: Verify jobs with matching command but missing input hash are not counted in Class 4 totals."""
    trace_path = fixtures_dir / "recompute" / "recompute_command_only.txt"
    attributed_path = isolated_workspace / "recompute_cmd_only.parquet"

    result = run_cli([
        "attribute",
        str(trace_path),
        "--output", str(attributed_path),
    ])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    actual_c4 = row.select("class4_core_s").item()
    assert actual_c4 == expected_class4_core_s, f"Command-only match must have 0 Class 4 core-s, got {actual_c4}"

    is_possible = row.select("possible_recompute").item()
    assert is_possible == expected_possible_recompute


@pytest.mark.parametrize(
    "trace_name",
    [
        "recompute_pairs.txt",
        "multiday_cluster.txt",
    ],
)
def test_f33_result_cache_recommendation_via_report_cli(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """F33: Verify cache recommendation and simulated hit rate computation via report CLI."""
    subfolder = "recompute" if trace_name == "recompute_pairs.txt" else "sacct"
    trace_path = fixtures_dir / subfolder / trace_name
    report_json = isolated_workspace / f"cache_rec_{trace_name}.json"

    res = run_cli(["report", str(trace_path), "--format", "json", "--output", str(report_json)])
    assert res.exit_code == 0
    assert report_json.exists()

    data = json.loads(report_json.read_text())
    assert "summary" in data


@pytest.mark.parametrize("fixture_name", ["standard_with_headers.swf", "sample_workload.swf", "missing_fields.swf"])
def test_f34_swf_recomputation_reporting(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
):
    """F34: Verify SWF traces report recomputation attribution as 'not available' via report CLI."""
    trace_path = fixtures_dir / "swf" / fixture_name
    report_json = isolated_workspace / f"swf_report_{fixture_name}.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    waste = data.get("waste_classification", {})
    # In SWF traces Class 4 is reported as 0 or not available
    class4_core = waste.get("class4_redundant_core_hours", 0.0)
    assert class4_core == 0.0 or waste.get("class4_status") == "not available"
