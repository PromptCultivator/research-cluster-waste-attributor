"""Adversarial stress and edge case verification suite for SWF ingestion and canonical records.

Tests boundary conditions, corrupted headers, status code variations, memory scaling,
CLI argument validation, and PyArrow schema fidelity.
"""

import io
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from rcwa import cli
from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf, parse_swf_with_pragmas
from rcwa.model import (
    POLARS_CANONICAL_SCHEMA,
    CanonicalJobRecord,
    JobState,
    from_canonical_arrow,
    get_canonical_arrow_schema,
    to_canonical_arrow,
)
from rcwa.normalize import map_swf_status, parse_slurm_memory_mb

runner = CliRunner()


# ============================================================================
# 1. Empty files (0 bytes) for both sacct and SWF inputs
# ============================================================================


def test_empty_file_sacct_and_swf(tmp_path: Path) -> None:
    """Verify 0-byte files produce canonical empty DataFrames across both adapters."""
    empty_sacct = tmp_path / "empty_sacct.txt"
    empty_sacct.write_text("")
    df_sacct = parse_sacct(empty_sacct)
    assert df_sacct.height == 0
    assert len(df_sacct.columns) == 27
    assert df_sacct.columns == list(POLARS_CANONICAL_SCHEMA.keys())

    empty_swf = tmp_path / "empty_trace.swf"
    empty_swf.write_text("")
    df_swf, pragmas = parse_swf_with_pragmas(empty_swf)
    assert df_swf.height == 0
    assert len(df_swf.columns) == 27
    assert df_swf.columns == list(POLARS_CANONICAL_SCHEMA.keys())
    assert pragmas == {}


def test_empty_string_and_stream_inputs() -> None:
    """Verify empty string and StringIO stream inputs return empty canonical DataFrames."""
    df_sacct_str = parse_sacct("")
    assert df_sacct_str.height == 0
    assert len(df_sacct_str.columns) == 27

    df_swf_str = parse_swf("")
    assert df_swf_str.height == 0
    assert len(df_swf_str.columns) == 27

    df_sacct_stream = parse_sacct(io.StringIO(""))
    assert df_sacct_stream.height == 0

    df_swf_stream = parse_swf(io.StringIO(""))
    assert df_swf_stream.height == 0


# ============================================================================
# 2. Malformed SWF lines (fewer or more than 18 fields)
# ============================================================================


def test_malformed_swf_fewer_than_11_fields() -> None:
    """Verify lines with fewer than 11 fields are skipped without parsing exceptions."""
    payload = "1 0 10 100 4\n" "2 0\n" "3\n" "\n" "   \n"
    df = parse_swf(payload)
    assert df.height == 0


def test_malformed_swf_intermediate_field_counts() -> None:
    """Verify lines with 11 to 17 fields parse accurately with field-level defaults."""
    # 11 fields: up to status code (no user, group, exec, queue, partition)
    line_11 = "101 0 10 100 4 50 1024000 4 200 1024000 1\n"
    df_11 = parse_swf(line_11)
    assert df_11.height == 1
    assert df_11.select("job_id").item() == "101"
    assert df_11.select("user").item() == "unknown"
    assert df_11.select("account").item() is None
    assert df_11.select("command_hash").item() is None
    assert df_11.select("partition").item() is None

    # 14 fields: includes user, group, and exec
    line_14 = "102 0 10 100 4 50 1024000 4 200 1024000 1 2001 3001 4001\n"
    df_14 = parse_swf(line_14)
    assert df_14.height == 1
    assert df_14.select("job_id").item() == "102"
    assert df_14.select("user").item() == "2001"
    assert df_14.select("account").item() == "3001"
    assert df_14.select("command_hash").item() == "4001"


def test_malformed_swf_more_than_18_fields() -> None:
    """Verify lines with extra trailing columns beyond 18 fields parse without error."""
    line_24 = (
        "103 0 10 100 4 50 1024000 4 200 1024000 1 1001 2001 3001 1 2 -1 -1 "
        "extra_field_1 extra_field_2 extra_3 extra_4 extra_5 extra_6\n"
    )
    df = parse_swf(line_24)
    assert df.height == 1
    assert df.select("job_id").item() == "103"
    assert df.select("user").item() == "1001"
    assert df.select("account").item() == "2001"
    assert df.select("command_hash").item() == "3001"


def test_corrupted_non_numeric_swf_record_raises_value_error() -> None:
    """Verify non-numeric text tokens in numeric SWF fields raise ValueError."""
    corrupted_job_id = "job_alpha 0 10 100 4 50 1024000 4 200 1024000 1"
    with pytest.raises(ValueError):
        parse_swf(corrupted_job_id)

    corrupted_submit = "104 bad_submit 10 100 4 50 1024000 4 200 1024000 1"
    with pytest.raises(ValueError):
        parse_swf(corrupted_submit)


# ============================================================================
# 3. SWF files with only comments/pragmas and no records
# ============================================================================


def test_swf_only_comments_and_pragmas() -> None:
    """Verify SWF trace containing only pragmas and comments yields empty frame."""
    content = (
        "; Version: 2.2\n"
        "; Computer: cluster-alpha\n"
        "; MaxNodes: 512\n"
        "; MaxProcs: 4096\n"
        "; UnixStartTime: 1704067200\n"
        "; Note: Cluster maintenance and benchmark notes\n"
        "; Note: Additional multi-line comment entry\n"
    )
    df, pragmas = parse_swf_with_pragmas(content)
    assert df.height == 0
    assert len(df.columns) == 27
    assert pragmas.get("Version") == "2.2"
    assert pragmas.get("Computer") == "cluster-alpha"
    assert pragmas.get("MaxNodes") == "512"
    assert pragmas.get("MaxProcs") == "4096"
    assert pragmas.get("UnixStartTime") == "1704067200"


# ============================================================================
# 4. Corrupted header pragmas
# ============================================================================


def test_corrupted_header_pragmas_fallback() -> None:
    """Verify non-numeric UnixStartTime falls back to epoch 0 without uncaught error."""
    content = (
        "; UnixStartTime: non_numeric_epoch\n"
        "; MaxProcs: invalid_procs_count\n"
        "; MaxNodes: not_a_number\n"
        "1 120 10 60 2 30 1024000 2 100 1024000 1 100 200 1 1 1 -1 -1\n"
    )
    df, pragmas = parse_swf_with_pragmas(content)
    assert df.height == 1
    assert pragmas.get("UnixStartTime") == "non_numeric_epoch"
    # Base epoch falls back to 0 -> submit_time = 1970-01-01 00:02:00+00:00
    sub_time = df.select("submit_time").item()
    assert sub_time == datetime(1970, 1, 1, 0, 2, 0, tzinfo=UTC)


# ============================================================================
# 5. Status code variations (negative, unmapped, standard)
# ============================================================================


@pytest.mark.parametrize(
    "status_code,expected_state",
    [
        (1, "COMPLETED"),
        (0, "FAILED"),
        (5, "CANCELLED"),
        (-1, "OTHER"),
        (-100, "OTHER"),
        (-999, "OTHER"),
        (2, "OTHER"),
        (3, "OTHER"),
        (4, "OTHER"),
        (99, "OTHER"),
        (None, "OTHER"),
    ],
)
def test_status_code_variations_mapping(status_code: int | None, expected_state: str) -> None:
    """Verify SWF status code mapping function handles standard, negative, and unmapped codes."""
    assert map_swf_status(status_code) == expected_state


def test_status_code_variations_in_parsed_dataframe() -> None:
    """Verify DataFrame parsing converts various status codes to valid canonical states."""
    codes = [-999, -1, 0, 1, 2, 3, 5, 99]
    lines = [f"{i+1} 0 0 10 1 -1 -1 -1 -1 -1 {c} 100 200 1 1 1 -1 -1" for i, c in enumerate(codes)]
    df = parse_swf("\n".join(lines))
    assert df.height == len(codes)
    expected_states = [
        "OTHER",
        "OTHER",
        "FAILED",
        "COMPLETED",
        "OTHER",
        "OTHER",
        "CANCELLED",
        "OTHER",
    ]
    assert df["state"].to_list() == expected_states


# ============================================================================
# 6. Memory scaling when alloc_cpus = 0 or missing
# ============================================================================


def test_swf_memory_scaling_zero_or_negative_cpus() -> None:
    """Verify SWF parser clamps alloc_cpus to >= 1 when computing memory."""
    # Field 5 is alloc_cpus = 0, field 7 is 1048576 KB/proc
    line_zero_cpus = "1 0 0 10 0 5 1048576 0 10 1048576 1 1 1 1 1 1 -1 -1\n"
    df = parse_swf(line_zero_cpus)
    assert df.height == 1
    # alloc_cpus clamped to 1
    assert df.select("alloc_cpus").item() == 1
    # max_rss_mb = 1048576 * 1 / 1024 = 1024 MB
    assert df.select("max_rss_mb").item() == 1024
    assert df.select("req_mem_mb").item() == 1024


def test_sacct_memory_scaling_zero_or_negative_cpus() -> None:
    """Verify parse_slurm_memory_mb clamps alloc_cpus and nodes to >= 1."""
    assert parse_slurm_memory_mb("4000Mc", alloc_cpus=0) == 4000
    assert parse_slurm_memory_mb("4000Mc", alloc_cpus=-5) == 4000
    assert parse_slurm_memory_mb("4000Mn", nodes=0) == 4000
    assert parse_slurm_memory_mb("4000Mn", nodes=-2) == 4000


# ============================================================================
# 7. CLI error handling on invalid trace formats or nonexistent files
# ============================================================================


def test_cli_nonexistent_trace_file() -> None:
    """Verify CLI ingest exits with code 2 on nonexistent input path."""
    res = runner.invoke(cli.app, ["ingest", "nonexistent_trace_file_xyz.txt"])
    assert res.exit_code == 2
    assert "does not exist" in res.output or "Error" in res.output


def test_cli_invalid_trace_format_option(tmp_path: Path) -> None:
    """Verify CLI ingest exits with code 2 on unsupported format option."""
    trace_file = tmp_path / "valid_dummy.txt"
    trace_file.write_text("JobID|User\n1|alice\n")
    res = runner.invoke(cli.app, ["ingest", str(trace_file), "--format", "unsupported_fmt"])
    assert res.exit_code == 2
    assert "Unsupported format" in res.output or "Error" in res.output


def test_cli_invalid_report_format_option(tmp_path: Path) -> None:
    """Verify CLI report exits with code 2 on unsupported report format option."""
    res = runner.invoke(cli.app, ["report", "--format", "unsupported_report_fmt"])
    assert res.exit_code == 2
    assert "Unsupported report format" in res.output or "Error" in res.output


# ============================================================================
# 8. Dataframe casting and Arrow schema fidelity on extreme values
# ============================================================================


def test_arrow_schema_fidelity_and_extreme_values() -> None:
    """Verify PyArrow table and Polars DataFrame schema fidelity under extreme values."""
    schema = get_canonical_arrow_schema()
    assert len(schema) == 27

    extreme_df = pl.DataFrame(
        {
            "job_id": ["ext_1", "ext_2"],
            "parent_job_id": [None, "ext_1"],
            "source": ["sacct", "swf"],
            "user": ["user_alpha", "user_beta"],
            "account": [None, "account_core"],
            "partition": [None, "partition_gpu"],
            "job_name": [None, "benchmark_job"],
            "command_hash": [None, "hash_command_123"],
            "input_hash": [None, "hash_input_456"],
            "submit_time": [
                datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC),
                datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
            ],
            "start_time": [None, datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)],
            "end_time": [None, datetime(2100, 1, 1, 0, 0, 0, tzinfo=UTC)],
            "wait_s": [0, 9223372036854775000],
            "run_s": [0, 9223372036854775000],
            "state": ["COMPLETED", "FAILED"],
            "exit_code": [0, 2147483647],
            "req_cpus": [1, 2147483647],
            "alloc_cpus": [1, 2147483647],
            "cpu_time_used_s": [0.0, 1e14],
            "req_mem_mb": [None, 9223372036854775000],
            "max_rss_mb": [None, 9223372036854775000],
            "req_gpus": [0, 2147483647],
            "alloc_gpus": [0, 2147483647],
            "nodes": [1, 2147483647],
            "node_list": [None, "node[01-99]"],
            "reserved_core_s": [0, 9223372036854775000],
            "reserved_mem_mb_s": [None, 9223372036854775000],
        },
        schema=POLARS_CANONICAL_SCHEMA,
    )

    # Convert to Arrow
    arrow_table = to_canonical_arrow(extreme_df)
    assert arrow_table.num_rows == 2
    assert arrow_table.num_columns == 27
    assert arrow_table.schema == schema

    # Convert back to Polars
    roundtrip_df = from_canonical_arrow(arrow_table)
    assert roundtrip_df.height == 2
    assert roundtrip_df.columns == extreme_df.columns
    assert roundtrip_df["job_id"].to_list() == ["ext_1", "ext_2"]
    assert roundtrip_df["alloc_cpus"].to_list() == [1, 2147483647]
    assert roundtrip_df["wait_s"].to_list() == [0, 9223372036854775000]


def test_canonical_job_record_pydantic_validation() -> None:
    """Verify CanonicalJobRecord pydantic model enforces constraints and computes fields."""
    rec = CanonicalJobRecord(
        job_id="999",
        source="swf",
        user="analyst",
        submit_time=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
        wait_s=30,
        run_s=120,
        state=JobState.OTHER,
        req_cpus=4,
        alloc_cpus=8,
        req_mem_mb=16384,
    )
    assert rec.reserved_core_s == 8 * 120
    assert rec.reserved_mem_mb_s == 16384 * 120
    assert rec.state.value == "OTHER"
