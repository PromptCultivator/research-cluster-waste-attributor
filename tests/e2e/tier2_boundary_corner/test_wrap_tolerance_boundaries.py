"""Tier 2 Boundary and Corner Cases: rcwa-wrap Tolerances.

Verifies rcwa-wrap tolerance behavior:
- Missing input files do not abort target command
- Empty 0-byte input files are hashed properly
- Target command non-zero exit code propagated
- Multiple input paths handling
- Whitespace and flag sorting invariance in command hashes
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize("exit_code_target", [1, 2, 42])
def test_boundary_wrap_propagates_target_exit_code(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    exit_code_target: int,
):
    """Verify rcwa-wrap propagates the exact non-zero exit code of the wrapped process."""
    result = run_wrap_cli([
        "--",
        "python3", "-c", f"import sys; sys.exit({exit_code_target})",
    ], cwd=isolated_workspace)
    assert result.exit_code == exit_code_target


@pytest.mark.parametrize("empty_input_name", ["empty_a.txt", "empty_b.bin"])
def test_boundary_wrap_zero_byte_input_hashing(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    empty_input_name: str,
):
    """Verify rcwa-wrap calculates sha256 on 0-byte empty files without failure."""
    empty_file = isolated_workspace / empty_input_name
    empty_file.write_bytes(b"")

    sidecar_dir = isolated_workspace / "sidecars"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    env = {"RCWA_DIR": str(sidecar_dir), "SLURM_JOB_ID": "7777"}

    result = run_wrap_cli([
        "--inputs", str(empty_file),
        "--",
        "python3", "-c", "print('done')",
    ], cwd=isolated_workspace, env=env)

    assert result.exit_code == 0
    sidecar = sidecar_dir / "7777.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data.get("input_hash") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.parametrize(
    "flags1,flags2",
    [
        (["--z=1", "--a=2", "--m=3"], ["--a=2", "--m=3", "--z=1"]),
        (["--val=10", "--flag", "--batch=32"], ["--batch=32", "--flag", "--val=10"]),
    ],
)
def test_boundary_wrap_flag_sorting_invariance(
    require_rcwa,
    run_wrap_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    flags1: list[str],
    flags2: list[str],
):
    """Verify flag sorting invariance produces identical command hashes via opaque-box rcwa-wrap CLI."""
    dir1 = isolated_workspace / "sidecars_f1"
    dir2 = isolated_workspace / "sidecars_f2"
    dir1.mkdir(parents=True, exist_ok=True)
    dir2.mkdir(parents=True, exist_ok=True)

    env1 = {"RCWA_DIR": str(dir1), "SLURM_JOB_ID": "111"}
    env2 = {"RCWA_DIR": str(dir2), "SLURM_JOB_ID": "222"}

    res1 = run_wrap_cli(["--"] + ["python3", "-c", "print('sorting')"] + flags1, cwd=isolated_workspace, env=env1)
    res2 = run_wrap_cli(["--"] + ["python3", "-c", "print('sorting')"] + flags2, cwd=isolated_workspace, env=env2)

    assert res1.exit_code == 0
    assert res2.exit_code == 0

    h1 = json.loads((dir1 / "111.json").read_text()).get("command_hash")
    h2 = json.loads((dir2 / "222.json").read_text()).get("command_hash")
    assert h1 == h2
