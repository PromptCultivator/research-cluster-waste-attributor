"""Unit tests for duration, memory, state, TRES, and identifier normalization."""

from datetime import UTC, datetime

import polars as pl
import pytest

from rcwa.normalize import (
    decompose_job_id,
    map_slurm_state,
    map_swf_status,
    normalize_to_canonical,
    parse_comment_input_hash,
    parse_duration_int,
    parse_duration_s,
    parse_slurm_exit_code,
    parse_slurm_memory_mb,
    parse_slurm_memory_rss_mb,
    parse_slurm_timestamp,
    parse_tres,
)


@pytest.mark.parametrize(
    "raw_input,expected_seconds",
    [
        ("00:00:10", 10.0),
        ("01:30:00", 5400.0),
        ("1-02:03:04", 93784.0),
        ("02:15.500", 135.5),
        ("00:10", 10.0),
        ("7200", 7200.0),
        (3600, 3600.0),
        (12.5, 12.5),
        ("-00:10:00", 0.0),  # clamped
        (None, None),
        ("UNLIMITED", None),
        ("INVALID", None),
        ("Partition_Limit", None),
        ("Unknown", None),
    ],
)
def test_parse_duration_s(
    raw_input: str | int | float | None, expected_seconds: float | None
) -> None:
    """Verify parse_duration_s converts diverse string and numeric representations."""
    actual = parse_duration_s(raw_input)
    if expected_seconds is None:
        assert actual is None
    else:
        assert actual is not None
        assert abs(actual - expected_seconds) < 1e-3


def test_parse_duration_int() -> None:
    """Verify parse_duration_int rounds accurately and defaults None to zero."""
    assert parse_duration_int("00:00.500") == 1
    assert parse_duration_int("00:00.100") == 0
    assert parse_duration_int("01:00.500") == 61
    assert parse_duration_int(None) == 0
    assert parse_duration_int("INVALID") == 0


@pytest.mark.parametrize(
    "raw_mem,alloc_cpus,nodes,expected_mb",
    [
        ("4000M", 2, 1, 4000),
        ("2000Mc", 4, 1, 8000),
        ("8000Mn", 4, 2, 16000),
        ("4G", 1, 1, 4096),
        ("2Gc", 4, 1, 8192),
        ("16Gn", 8, 2, 32768),
        ("1048576K", 1, 1, 1024),
        ("524288Kc", 4, 1, 2048),
        ("2097152Kn", 4, 2, 4096),
        ("1T", 1, 1, 1048576),
        ("?", 4, 1, None),
        ("Unknown", 4, 1, None),
        (None, 4, 1, None),
    ],
)
def test_parse_slurm_memory_mb(
    raw_mem: str | None,
    alloc_cpus: int,
    nodes: int,
    expected_mb: int | None,
) -> None:
    """Verify parse_slurm_memory_mb scales correctly with CPU and node multipliers."""
    actual = parse_slurm_memory_mb(raw_mem, alloc_cpus=alloc_cpus, nodes=nodes)
    assert actual == expected_mb


def test_parse_slurm_memory_rss_mb() -> None:
    """Verify RSS parsing from Slurm formats to integer megabytes."""
    assert parse_slurm_memory_rss_mb("15800M") == 15800
    assert parse_slurm_memory_rss_mb("1048576K") == 1024
    assert parse_slurm_memory_rss_mb("4G") == 4096
    assert parse_slurm_memory_rss_mb("?") is None
    assert parse_slurm_memory_rss_mb(None) is None


@pytest.mark.parametrize(
    "raw_state,expected_state",
    [
        ("COMPLETED", "COMPLETED"),
        ("COMPLETED+", "COMPLETED"),
        ("FAILED", "FAILED"),
        ("BOOT_FAIL", "FAILED"),
        ("TIMEOUT", "TIMEOUT"),
        ("DEADLINE", "TIMEOUT"),
        ("OUT_OF_MEMORY", "OUT_OF_MEMORY"),
        ("OUT_OF_MEMORY+", "OUT_OF_MEMORY"),
        ("NODE_FAIL", "NODE_FAIL"),
        ("PREEMPTED", "PREEMPTED"),
        ("RUNNING", "RUNNING"),
        ("PENDING", "PENDING"),
        ("REQUEUED", "PENDING"),
        ("CANCELLED", "CANCELLED"),
        ("CANCELLED by 1005", "CANCELLED"),
        ("REVOKED", "CANCELLED"),
        ("FAILED_BY_ADMIN", "OTHER"),
        ("REVOKED_SPECIAL_STATUS", "OTHER"),
        ("UNKNOWN_XYZ", "OTHER"),
        (None, "OTHER"),
    ],
)
def test_map_slurm_state(raw_state: str | None, expected_state: str) -> None:
    """Verify Slurm state mapping and qualifier stripping."""
    assert map_slurm_state(raw_state) == expected_state


@pytest.mark.parametrize(
    "status_code,expected_state",
    [
        (1, "COMPLETED"),
        (0, "FAILED"),
        (5, "CANCELLED"),
        (2, "OTHER"),
        (99, "OTHER"),
        (None, "OTHER"),
    ],
)
def test_map_swf_status(status_code: int | None, expected_state: str) -> None:
    """Verify SWF numeric status codes map to canonical state strings."""
    assert map_swf_status(status_code) == expected_state


def test_parse_tres_variations() -> None:
    """Verify TRES parsing extracts CPU, node, and GPU resources."""
    tres1 = "billing=8,cpu=8,gres/gpu=2,mem=32000M,node=1"
    parsed1 = parse_tres(tres1)
    assert parsed1["cpus"] == 8
    assert parsed1["nodes"] == 1
    assert parsed1["gpus"] == 2
    assert parsed1["mem_mb"] == 32000

    tres_model = "billing=4,cpu=4,gres/gpu:a100=2,mem=16000M,node=1"
    parsed_model = parse_tres(tres_model)
    assert parsed_model["gpus"] == 2

    tres_bare = "cpu=64,mem=256000M,node=2,gpu=4"
    parsed_bare = parse_tres(tres_bare)
    assert parsed_bare["gpus"] == 4

    assert parse_tres(None) == {"gpus": 0, "cpus": 0, "nodes": 1, "mem_mb": 0}


def test_parse_comment_input_hash() -> None:
    """Verify extraction of RCWA_INPUT_HASH digest from comments."""
    comment = "preamble RCWA_INPUT_HASH=deadbeef12345678 extra"
    assert parse_comment_input_hash(comment) == "deadbeef12345678"
    assert parse_comment_input_hash("unrelated comment") is None
    assert parse_comment_input_hash(None) is None


@pytest.mark.parametrize(
    "raw_id,expected_base,expected_step,expected_parent",
    [
        ("12345", "12345", None, None),
        ("12345.batch", "12345", "batch", None),
        ("12345.0", "12345", "0", None),
        ("12345.extern", "12345", "extern", None),
        ("7001_0", "7001_0", None, "7001"),
        ("7001_0.batch", "7001_0", "batch", "7001"),
        ("7002+0", "7002+0", None, "7002"),
        ("7002+1.0", "7002+1", "0", "7002"),
    ],
)
def test_decompose_job_id(
    raw_id: str,
    expected_base: str,
    expected_step: str | None,
    expected_parent: str | None,
) -> None:
    """Verify decomposition of job identifiers across steps, arrays, and pack components."""
    base, step, parent = decompose_job_id(raw_id)
    assert base == expected_base
    assert step == expected_step
    assert parent == expected_parent


def test_parse_slurm_timestamp() -> None:
    """Verify parsing ISO timestamps to timezone-aware UTC datetime."""
    parsed = parse_slurm_timestamp("2026-03-01T10:00:00")
    assert parsed == datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    assert parse_slurm_timestamp("Unknown") is None
    assert parse_slurm_timestamp(None) is None
    assert parse_slurm_timestamp("not-a-timestamp") is None


def test_parse_slurm_exit_code() -> None:
    """Verify parsing exit code and signal numbers."""
    assert parse_slurm_exit_code("0:0") == 0
    assert parse_slurm_exit_code("1:0") == 1
    assert parse_slurm_exit_code("0:125") == 125
    assert parse_slurm_exit_code("137") == 137
    assert parse_slurm_exit_code(None) is None
    assert parse_slurm_exit_code("Unknown") is None


def test_normalize_to_canonical() -> None:
    """Verify normalization constructs DataFrame conforming to canonical columns."""
    df = pl.DataFrame({"job_id": ["101"], "user": ["alice"]})
    canonical_df = normalize_to_canonical(df, source_type="test_src")
    assert "job_id" in canonical_df.columns
    assert "source" in canonical_df.columns
    assert canonical_df.select("source").item() == "test_src"
    assert len(canonical_df.columns) == 27


def test_normalize_duration_edge_cases() -> None:
    """Verify duration parsing failure and alternative split format branches."""
    assert parse_duration_s("1-02:30") == 86400.0 + 120.0 + 30.0
    assert parse_duration_s("1-bad") is None
    assert parse_duration_s("1-02:30:bad") is None
    assert parse_duration_s("1-bad:30") is None
    assert parse_duration_s("bad:30") is None
    assert parse_duration_s("01:bad:30") is None
    assert parse_duration_s("01:02:03:04") is None
    assert parse_duration_s("not_a_duration") is None


def test_normalize_memory_and_tres_edge_cases() -> None:
    """Verify petabyte scaling, invalid strings, and malformed TRES tokens."""
    assert parse_slurm_memory_mb("2P", alloc_cpus=1, nodes=1) == 2 * 1024 * 1024 * 1024
    assert parse_slurm_memory_mb("invalid") is None
    assert parse_slurm_memory_rss_mb("invalid") is None
    assert parse_slurm_memory_rss_mb("1T") == 1024 * 1024

    tres_bad = "cpu=bad,node=bad,gres/gpu=bad,gres/gpu:a100=bad,gpu=bad,unparsed_token"
    res = parse_tres(tres_bad)
    assert res["gpus"] == 0

    assert parse_slurm_exit_code("bad:bad") is None
    assert parse_slurm_exit_code("not_number") is None
