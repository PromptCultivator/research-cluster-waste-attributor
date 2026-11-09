"""Tier 4 Guarantee Suite: G3 Determinism Exhaustive Verification.

Mathematical Guarantee G3:
Identical inputs produce byte-identical report outputs across independent runs.
Verification must test across Markdown, JSON, and CSV output formats.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "trace_name",
    [
        "sacct_standard_26col.txt",
        "multiday_cluster.txt",
        "sacct_steps_rollup.txt",
    ],
)
@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_guarantee_g3_multi_format_byte_determinism(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
    fmt: str,
):
    """Enforce G3: verify byte-identical output across formats and diverse input traces via report CLI."""
    trace_path = fixtures_dir / "sacct" / trace_name
    ext = "md" if fmt == "markdown" else fmt

    out1 = isolated_workspace / f"det_{trace_name}_run1.{ext}"
    out2 = isolated_workspace / f"det_{trace_name}_run2.{ext}"

    res1 = run_cli(["report", str(trace_path), "--format", fmt, "--output", str(out1)])
    res2 = run_cli(["report", str(trace_path), "--format", fmt, "--output", str(out2)])

    assert res1.exit_code == 0
    assert res2.exit_code == 0

    bytes1 = out1.read_bytes()
    bytes2 = out2.read_bytes()

    assert InvariantValidators.verify_g3_determinism(bytes1, bytes2), f"Determinism failure on {trace_name} format {fmt}"


@pytest.mark.parametrize("seed_val", [42, 99, 1234])
def test_guarantee_g3_synthetic_generation_determinism(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    seed_val: int,
):
    """Enforce G3: verify synthetic generator produces byte-identical traces for identical seeds."""
    out1 = isolated_workspace / f"synth_det1_{seed_val}.txt"
    out2 = isolated_workspace / f"synth_det2_{seed_val}.txt"

    res1 = run_cli(["synth", "--size", "50", "--seed", str(seed_val), "--output", str(out1)])
    res2 = run_cli(["synth", "--size", "50", "--seed", str(seed_val), "--output", str(out2)])

    assert res1.exit_code == 0
    assert res2.exit_code == 0

    assert InvariantValidators.verify_g3_determinism(out1.read_bytes(), out2.read_bytes())
