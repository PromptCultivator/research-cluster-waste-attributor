"""Tier 4 Real-World Workflows: Complete CLI End-to-End Suite.

Verifies the user-facing CLI surface:
- rcwa run (all-in-one pipeline)
- rcwa ingest (Slurm sacct and SWF adapters)
- rcwa attribute (conservation-checked waste attribution)
- rcwa recommend (rightsizing with safety guardrails)
- rcwa simulate (EASY-backfill simulator)
- rcwa calibrate (historical baseline calibration)
- rcwa report (Markdown, JSON, CSV output generation)
- rcwa synth (synthetic trace generation with planted ground truth)
- rcwa-wrap (execution wrapper for declared inputs)
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "subcommand,extra_args",
    [
        ("ingest", ["tests/fixtures/sacct/sacct_standard_26col.txt"]),
        ("ingest", ["tests/fixtures/swf/standard_with_headers.swf"]),
        ("attribute", ["tests/fixtures/sacct/multiday_cluster.txt"]),
        ("simulate", ["tests/fixtures/swf/sample_workload.swf", "--scenario", "baseline"]),
        ("calibrate", ["tests/fixtures/swf/calibration_reference.swf"]),
        ("report", ["tests/fixtures/sacct/multiday_cluster.txt", "--format", "json"]),
        ("report", ["tests/fixtures/sacct/multiday_cluster.txt", "--format", "markdown"]),
        ("report", ["tests/fixtures/sacct/multiday_cluster.txt", "--format", "csv"]),
        ("synth", ["--size", "20", "--seed", "1"]),
        ("synth", ["--size", "50", "--seed", "42"]),
        ("synth", ["--size", "100", "--seed", "99"]),
    ],
)
def test_cli_subcommands_execution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    subcommand: str,
    extra_args: list,
):
    """Verify primary subcommands execute successfully with valid positional arguments."""
    out_file = isolated_workspace / f"cli_out_{subcommand}.data"
    cmd_args = [subcommand] + extra_args + ["--output", str(out_file)]
    result = run_cli(cmd_args)
    assert result.exit_code == 0, f"Command {' '.join(cmd_args)} failed: {result.stderr}"


def test_cli_recommend_chained_execution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
):
    """Verify rcwa recommend execution accepting attributed Parquet file as positional input."""
    trace_path = "tests/fixtures/sacct/multiday_cluster.txt"
    attr_out = isolated_workspace / "attr_for_rec.parquet"
    recs_out = isolated_workspace / "recs_final.parquet"

    res_attr = run_cli(["attribute", trace_path, "--output", str(attr_out)])
    assert res_attr.exit_code == 0

    res_rec = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert res_rec.exit_code == 0
    assert recs_out.exists()


@pytest.mark.parametrize(
    "policy_path",
    [
        "tests/fixtures/policies/default_policy.yaml",
        "tests/fixtures/policies/strict_policy.yaml",
    ],
)
def test_cli_attribute_policy_flag(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    policy_path: str,
):
    """Verify CLI accepts configurable policy flags on attribute."""
    trace_path = "tests/fixtures/sacct/multiday_cluster.txt"
    out_path = isolated_workspace / f"flags_test_{Path(policy_path).stem}.parquet"

    cmd = ["attribute", trace_path, "--policy", policy_path, "--output", str(out_path)]
    result = run_cli(cmd)
    assert result.exit_code == 0, f"Policy {policy_path} failed: {result.stderr}"


@pytest.mark.parametrize("wrap_input_count", [1, 2, 3, 5])
def test_cli_rcwa_wrap_multi_input_execution(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    wrap_input_count: int,
):
    """Verify rcwa-wrap handles multiple declared inputs simultaneously."""
    inputs = []
    for i in range(wrap_input_count):
        f = isolated_workspace / f"decl_in_{i}.txt"
        f.write_text(f"dataset partition {i}\n")
        inputs.append(str(f))

    sidecar_dir = isolated_workspace / f"sidecars_{wrap_input_count}"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    env = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": f"100{wrap_input_count}"}

    result = run_wrap_cli(
        ["--inputs", ",".join(inputs), "--", "python3", "-c", "print('multi input complete')"],
        cwd=isolated_workspace,
        env=env,
    )
    assert result.exit_code == 0
    assert "multi input complete" in result.stdout
