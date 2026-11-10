"""Tests for Guarantee G3 (Determinism) across reports and attribution."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcwa.adapters.sacct import parse_sacct
from rcwa.attribute import attribute_trace
from rcwa.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "trace_rel",
    [
        "sacct/multiday_cluster.txt",
        "sacct/sacct_standard_26col.txt",
        "swf/sample_workload.swf",
    ],
)
@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_guarantee_g3_report_byte_determinism(
    fixtures_dir: Path,
    tmp_path: Path,
    trace_rel: str,
    fmt: str,
) -> None:
    """Guarantee G3: two independent runs on identical trace inputs produce byte-identical reports."""
    trace_file = fixtures_dir / trace_rel
    ext = "md" if fmt == "markdown" else fmt

    out1 = tmp_path / f"run1.{ext}"
    out2 = tmp_path / f"run2.{ext}"

    res1 = runner.invoke(app, ["report", str(trace_file), "--format", fmt, "--output", str(out1)])
    assert res1.exit_code == 0, f"Run 1 failed: {res1.stdout}"

    res2 = runner.invoke(app, ["report", str(trace_file), "--format", fmt, "--output", str(out2)])
    assert res2.exit_code == 0, f"Run 2 failed: {res2.stdout}"

    bytes1 = out1.read_bytes()
    bytes2 = out2.read_bytes()

    assert bytes1 == bytes2, f"Byte mismatch detected for {trace_rel} in format {fmt}"


def test_guarantee_g3_attribution_table_determinism(fixtures_dir: Path) -> None:
    """Guarantee G3: attribution parquet table outputs are byte-identical across runs."""
    trace_file = fixtures_dir / "sacct" / "multiday_cluster.txt"

    df1 = parse_sacct(trace_file)
    attr1 = attribute_trace(df1)

    df2 = parse_sacct(trace_file)
    attr2 = attribute_trace(df2)

    assert attr1.equals(attr2), "Attribution dataframe outputs differ between runs"
