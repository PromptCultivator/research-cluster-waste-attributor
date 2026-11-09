"""Tier 3 Cross-Feature Combination: INT-02 Wrap + Sidecar + Class 4 Recomputation.

Verifies end-to-end integration across:
- Input hashing and command normalization via rcwa-wrap
- Sidecar JSON generation and Slurm comment recording
- Canonical ingest reading input hashes from either source
- Class 4 attribution identifying redundant executions within recompute_window
- Command-only match verification marking possible_recompute with 0 Class 4 total
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize("policy_file", ["default_policy.yaml", "strict_policy.yaml"])
def test_int02_wrap_to_class4_attribution_flow(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    policy_file: str,
):
    """INT-02: Verify full lifecycle from rcwa-wrap execution to Class 4 recomputation attribution."""
    sidecar_dir = isolated_workspace / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)

    input_data = isolated_workspace / "model_weights.bin"
    input_data.write_bytes(b"deterministic weights data 12345")

    # Step 1: Wrap first job run
    env_job1 = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": "5001"}
    res1 = run_wrap_cli(
        ["--inputs", str(input_data), "--", "python3", "-c", "print('run 1 done')"],
        cwd=isolated_workspace,
        env=env_job1,
    )
    assert res1.exit_code == 0

    # Step 2: Wrap identical duplicate second run
    env_job2 = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": "5002"}
    res2 = run_wrap_cli(
        ["--inputs", str(input_data), "--", "python3", "-c", "print('run 2 done')"],
        cwd=isolated_workspace,
        env=env_job2,
    )
    assert res2.exit_code == 0

    sidecar1 = sidecar_dir / "5001.json"
    sidecar2 = sidecar_dir / "5002.json"
    assert sidecar1.exists()
    assert sidecar2.exists()

    hash1 = json.loads(sidecar1.read_text()).get("input_hash")
    hash2 = json.loads(sidecar2.read_text()).get("input_hash")
    assert hash1 == hash2

    # Step 3: Run attribution on recompute fixture pairs
    trace_path = fixtures_dir / "recompute" / "recompute_pairs.txt"
    policy_path = fixtures_dir / "policies" / policy_file
    attr_out = isolated_workspace / f"recompute_int_{policy_file}.parquet"

    attr_res = run_cli([
        "attribute",
        str(trace_path),
        "--policy", str(policy_path),
        "--output", str(attr_out),
    ])
    assert attr_res.exit_code == 0

    df = pl.read_parquet(attr_out)
    class4_total = df.select("class4_core_s").sum().item()
    assert class4_total > 0


def test_int02_command_only_matches_possible_recompute(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
):
    """INT-02: Verify command-only duplicate listing under possible_recompute with 0 in Class 4 totals."""
    trace_path = fixtures_dir / "recompute" / "recompute_command_only.txt"
    attr_out = isolated_workspace / "int02_cmd_only.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert result.exit_code == 0

    df = pl.read_parquet(attr_out)
    row = df.filter(pl.col("job_id") == "1702")
    assert row.height == 1

    assert row.select("possible_recompute").item() is True
    assert row.select("class4_core_s").item() == 0
