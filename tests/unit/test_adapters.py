"""Unit and integration tests for sacct and SWF trace adapters."""

import io
import warnings
from pathlib import Path

import polars as pl
import pytest

from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf, parse_swf_with_pragmas

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_sacct_standard_26col_parsing() -> None:
    """Verify standard 26-column sacct export parses all fields and step rollups."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_standard_26col.txt"
    df = parse_sacct(fixture_path)

    # 13 rows in raw file: 1001 (with .batch, .extern), 1002..1008, 1009+0, 1009+1, 1010 -> 11 unique jobs
    assert df.height == 11
    assert "job_id" in df.columns
    assert "reserved_core_s" in df.columns

    # Verify rollup on job 1001: MaxRSS max(15800M, 120M) = 15800, TotalCPU sum excluding extern = 07:30:00 = 27000s
    row_1001 = df.filter(pl.col("job_id") == "1001")
    assert row_1001.height == 1
    assert row_1001.select("max_rss_mb").item() == 15800
    assert row_1001.select("cpu_time_used_s").item() == 27000.0


def test_sacct_unknown_columns_warning() -> None:
    """Verify unknown extra columns produce a UserWarning and are omitted from canonical frame."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_unknown_columns.txt"
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        df = parse_sacct(fixture_path)

    assert df.height == 2
    assert "extrafield1" not in df.columns
    assert "customtag" not in df.columns

    user_warnings = [w for w in recorded_warnings if issubclass(w.category, UserWarning)]
    assert len(user_warnings) > 0
    assert any("Unknown column(s)" in str(w.message) for w in user_warnings)


def test_sacct_trailing_delimiters() -> None:
    """Verify lines ending with trailing delimiter are parsed accurately."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_trailing_delimiters.txt"
    df = parse_sacct(fixture_path)
    assert df.height == 2
    assert df.filter(pl.col("job_id") == "5001").height == 1
    assert df.filter(pl.col("job_id") == "5002").height == 1


def test_sacct_reordered_headers() -> None:
    """Verify column mapping is header-driven regardless of column order."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_reordered_headers.txt"
    df = parse_sacct(fixture_path)
    assert df.height == 2

    row = df.filter(pl.col("job_id") == "4001")
    assert row.select("user").item() == "alice"
    assert row.select("account").item() == "quant_research"
    assert row.select("partition").item() == "compute"


def test_sacct_steps_rollup_metrics() -> None:
    """Verify step hierarchy rollup calculates maximum RSS and sums CPU excluding .extern."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_steps_rollup.txt"
    df = parse_sacct(fixture_path)

    # Job 6001: batch(12000M, 03:00:00=10800s), 0(18000M, 02:30:00=9000s), extern(150M, 15s)
    row_6001 = df.filter(pl.col("job_id") == "6001")
    assert row_6001.select("max_rss_mb").item() == 18000
    assert row_6001.select("cpu_time_used_s").item() == 19800.0

    # Job 6002: batch(4000M, 1800s), 0(8000M, 3600s)
    row_6002 = df.filter(pl.col("job_id") == "6002")
    assert row_6002.select("max_rss_mb").item() == 8000
    assert row_6002.select("cpu_time_used_s").item() == 5400.0


def test_sacct_array_and_pack_parent_linkage() -> None:
    """Verify array jobs and pack components establish proper parent_job_id."""
    fixture_path = FIXTURES_DIR / "sacct" / "sacct_array_heterogeneous.txt"
    df = parse_sacct(fixture_path)
    assert df.height == 5

    assert df.filter(pl.col("job_id") == "7001_0").select("parent_job_id").item() == "7001"
    assert df.filter(pl.col("job_id") == "7001_1").select("parent_job_id").item() == "7001"
    assert df.filter(pl.col("job_id") == "7002+0").select("parent_job_id").item() == "7002"
    assert df.filter(pl.col("job_id") == "7002+1").select("parent_job_id").item() == "7002"


def test_sacct_io_stream_input() -> None:
    """Verify parse_sacct supports in-memory StringIO stream input."""
    payload = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        "999|999|alice|quant|compute|normal|test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|2|2|4000M|1500M||00:20:00|2400|billing=2,cpu=2,node=1|billing=2,cpu=2,node=1|node-01||sbatch run.sh\n"
    )
    stream = io.StringIO(payload)
    df = parse_sacct(stream)
    assert df.height == 1
    assert df.select("job_id").item() == "999"


def test_sacct_corrupted_binary_raises() -> None:
    """Verify binary input raises ValueError."""
    bin_path = FIXTURES_DIR / "edge" / "corrupted_binary.bin"
    with pytest.raises(ValueError, match="cannot be decoded|Binary"):
        parse_sacct(bin_path)


def test_sacct_empty_and_header_only() -> None:
    """Verify empty and header-only files return an empty canonical DataFrame."""
    empty_path = FIXTURES_DIR / "edge" / "empty_file.txt"
    assert parse_sacct(empty_path).height == 0

    header_only = FIXTURES_DIR / "edge" / "header_only.txt"
    assert parse_sacct(header_only).height == 0


def test_swf_standard_parsing_with_pragmas() -> None:
    """Verify SWF parser extracts header pragmas and calculates cluster-level metrics."""
    fixture_path = FIXTURES_DIR / "swf" / "standard_with_headers.swf"
    df, pragmas = parse_swf_with_pragmas(fixture_path)

    assert pragmas.get("UnixStartTime") == "1704067200"
    assert pragmas.get("MaxProcs") == "256"
    assert pragmas.get("MaxNodes") == "64"
    assert "Standard SWF reference trace fixture" in pragmas.get("Note", "")

    assert df.height == 5
    assert df["source"][0] == "swf"

    # Row 1: alloc_cpus=8, avg_cpu=3000 -> total cpu = 24000.0
    # used_mem = 2097152 KB/proc * 8 cpus / 1024 = 16384 MB
    # req_mem = 4194304 KB/proc * 8 cpus / 1024 = 32768 MB
    row_1 = df.filter(pl.col("job_id") == "1")
    assert row_1.select("alloc_cpus").item() == 8
    assert row_1.select("cpu_time_used_s").item() == 24000.0
    assert row_1.select("max_rss_mb").item() == 16384
    assert row_1.select("req_mem_mb").item() == 32768
    assert row_1.select("state").item() == "COMPLETED"


def test_swf_missing_sentinels_mapped_to_none() -> None:
    """Verify SWF missing value indicator -1 is converted to None for optional metrics."""
    fixture_path = FIXTURES_DIR / "swf" / "missing_fields.swf"
    df = parse_swf(fixture_path)
    assert df.height == 3

    # Row 1 has -1 for wait, avg_cpu, used_mem, req_mem
    row_1 = df.filter(pl.col("job_id") == "1")
    assert row_1.select("wait_s").item() == 0
    assert row_1.select("cpu_time_used_s").item() is None
    assert row_1.select("max_rss_mb").item() is None
    assert row_1.select("req_mem_mb").item() is None


def test_swf_empty_trace() -> None:
    """Verify empty SWF traces return empty canonical DataFrame."""
    empty_swf = FIXTURES_DIR / "edge" / "empty_swf.swf"
    df = parse_swf(empty_swf)
    assert df.height == 0


def test_sacct_sidecar_hashes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify parse_sacct reads input_hash and command_hash from sidecar files."""
    monkeypatch.setenv("RCWA_DIR", str(tmp_path))
    sidecar_file = tmp_path / "777.json"
    sidecar_file.write_text('{"input_hash": "side_in_hash", "command_hash": "side_cmd_hash"}')

    raw = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|"
        "State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|"
        "AllocTRES|NodeList|Comment|SubmitLine\n"
        "777|777|eve|acct|part|norm|myjob|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|"
        "2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|8000M|2000M||00:20:00|2400||||node-01||\n"
    )
    df = parse_sacct(raw)
    assert df.height == 1
    assert df.select("input_hash").item() == "side_in_hash"
    assert df.select("command_hash").item() == "side_cmd_hash"


def test_sacct_string_and_bytesio_input() -> None:
    """Verify parse_sacct works with raw multiline strings and BytesIO streams."""
    raw = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|"
        "State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|"
        "AllocTRES|NodeList|Comment|SubmitLine\n"
        "888|888|frank|acct|part|norm|job888|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|"
        "2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|2|2|4000M|||00:10:00|1200||||node-01||sbatch script.sh\n"
    )
    df_str = parse_sacct(raw)
    assert df_str.height == 1

    bytes_stream = io.BytesIO(raw.encode("utf-8"))
    df_bytes = parse_sacct(bytes_stream)  # pyright: ignore[reportArgumentType]
    assert df_bytes.height == 1


def test_sacct_null_bytes_in_string_raises() -> None:
    """Verify parse_sacct detects null bytes in string input."""
    with pytest.raises(ValueError, match="Binary or null bytes detected"):
        parse_sacct("JobID|User\n1\x00|alice")


def test_swf_string_and_bytesio_input() -> None:
    """Verify parse_swf accepts multiline string and BytesIO stream inputs."""
    raw = "; MaxJobs 100\n" "1 0 10 100 4 50 1048576 4 100 1048576 1 10 20 1 2 3 -1 -1\n"
    df_str = parse_swf(raw)
    assert df_str.height == 1

    df_bytes = parse_swf(io.BytesIO(raw.encode("utf-8")))  # pyright: ignore[reportArgumentType]
    assert df_bytes.height == 1


def test_swf_null_bytes_raises() -> None:
    """Verify parse_swf detects null bytes in string input."""
    with pytest.raises(ValueError, match="Binary or null bytes detected"):
        parse_swf("1 0 10\x00 100 4")
