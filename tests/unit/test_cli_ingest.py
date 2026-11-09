"""Unit tests for rcwa CLI ingest, attribute, and report commands."""

from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from rcwa import cli

runner = CliRunner()
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_cli_ingest_sacct_and_swf(tmp_path: Path) -> None:
    """Verify CLI ingest command parses sacct and SWF fixtures to parquet."""
    sacct_file = FIXTURES_DIR / "sacct" / "sacct_standard_26col.txt"
    out_sacct = tmp_path / "sacct_out.parquet"

    res_sacct = runner.invoke(cli.app, ["ingest", str(sacct_file), "--output", str(out_sacct)])
    assert res_sacct.exit_code == 0
    assert out_sacct.exists()
    df_sacct = pl.read_parquet(out_sacct)
    assert df_sacct.height == 11

    swf_file = FIXTURES_DIR / "swf" / "standard_with_headers.swf"
    out_swf = tmp_path / "swf_out.parquet"

    res_swf = runner.invoke(
        cli.app, ["ingest", str(swf_file), "--format", "swf", "--output", str(out_swf)]
    )
    assert res_swf.exit_code == 0
    assert out_swf.exists()
    df_swf = pl.read_parquet(out_swf)
    assert df_swf.height == 5


def test_cli_ingest_binary_error() -> None:
    """Verify CLI ingest rejects binary files with exit code 1."""
    bin_file = FIXTURES_DIR / "edge" / "corrupted_binary.bin"
    res = runner.invoke(cli.app, ["ingest", str(bin_file)])
    assert res.exit_code == 1


def test_cli_attribute_and_exclusions(tmp_path: Path) -> None:
    """Verify CLI attribute filters running/pending rows and labels early failures."""
    trace_file = FIXTURES_DIR / "sacct" / "sacct_running_pending.txt"
    out_attr = tmp_path / "attributed.parquet"

    res = runner.invoke(cli.app, ["attribute", str(trace_file), "--output", str(out_attr)])
    assert res.exit_code == 0
    assert out_attr.exists()

    df = pl.read_parquet(out_attr)
    assert "RUNNING" not in df["state"].to_list()
    assert "PENDING" not in df["state"].to_list()
    assert df.height == 1
    assert df["reserved_core_s"][0] == 7200


def test_cli_attribute_parquet_input(tmp_path: Path) -> None:
    """Verify CLI attribute can read an existing canonical Parquet file."""
    sacct_file = FIXTURES_DIR / "sacct" / "sacct_durations_states.txt"
    ingest_parquet = tmp_path / "ingested.parquet"
    attr_parquet = tmp_path / "attributed_from_parquet.parquet"

    runner.invoke(cli.app, ["ingest", str(sacct_file), "--output", str(ingest_parquet)])
    assert ingest_parquet.exists()

    res = runner.invoke(cli.app, ["attribute", str(ingest_parquet), "--output", str(attr_parquet)])
    assert res.exit_code == 0
    assert attr_parquet.exists()

    df = pl.read_parquet(attr_parquet)
    assert "class3_sub_label" in df.columns
    # Row 9006 is OUT_OF_MEMORY with run_s = 480s -> sub_label 'oom'
    oom_row = df.filter(pl.col("job_id") == "9006")
    assert oom_row.select("class3_sub_label").item() == "oom"


def test_cli_attribute_recompute_and_command_only(tmp_path: Path) -> None:
    """Verify CLI attribute identifies recomputed jobs and possible recompute flags."""
    recompute_file = FIXTURES_DIR / "recompute" / "recompute_pairs.txt"
    out_attr = tmp_path / "attr_recompute.parquet"

    res = runner.invoke(cli.app, ["attribute", str(recompute_file), "--output", str(out_attr)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_attr)
    row_1602 = df.filter(pl.col("job_id") == "1602")
    assert row_1602.select("class4_core_s").item() > 0

    cmd_only_file = FIXTURES_DIR / "recompute" / "recompute_command_only.txt"
    out_cmd = tmp_path / "attr_cmd_only.parquet"
    res_cmd = runner.invoke(cli.app, ["attribute", str(cmd_only_file), "--output", str(out_cmd)])
    assert res_cmd.exit_code == 0
    df_cmd = pl.read_parquet(out_cmd)
    row_1702 = df_cmd.filter(pl.col("job_id") == "1702")
    assert row_1702.select("possible_recompute").item() is True


def test_cli_report_formats(tmp_path: Path) -> None:
    """Verify report generation in markdown, json, and csv."""
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"
    md_path = tmp_path / "report.md"

    res_json = runner.invoke(cli.app, ["report", "--format", "json", "--output", str(json_path)])
    assert res_json.exit_code == 0
    assert json_path.exists()
    assert json_path.read_text(encoding="utf-8") == "{}"

    res_csv = runner.invoke(cli.app, ["report", "--format", "csv", "--output", str(csv_path)])
    assert res_csv.exit_code == 0
    assert csv_path.exists()

    res_md = runner.invoke(cli.app, ["report", "--format", "markdown", "--output", str(md_path)])
    assert res_md.exit_code == 0
    assert md_path.exists()
    assert "# Report" in md_path.read_text(encoding="utf-8")
