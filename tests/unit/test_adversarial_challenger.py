"""Adversarial stress and edge case verification suite for Slurm sacct adapter and normalization."""

from datetime import UTC, datetime

import polars as pl
import pytest

from rcwa.adapters.sacct import parse_sacct
from rcwa.normalize import (
    decompose_job_id,
    map_slurm_state,
    parse_duration_int,
    parse_duration_s,
    parse_slurm_memory_mb,
    parse_slurm_timestamp,
)

# ============================================================================
# 1. Malformed dates/timestamps and missing start/end times
# ============================================================================


@pytest.mark.parametrize(
    "raw_ts,expected",
    [
        ("2026-03-01T12:00:00", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
        ("2026-03-01 12:00:00", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
        ("2026-03-01T12:00:00Z", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
        ("2026-03-01T14:00:00+02:00", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
        ("2026-99-99", None),
        ("invalid-timestamp", None),
        ("2026-02-30T10:00:00", None),
        ("Unknown", None),
        ("N/A", None),
        ("NONE", None),
        ("None", None),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_adversarial_parse_slurm_timestamp(raw_ts: str | None, expected: datetime | None) -> None:
    """Verify timestamp parsing rejects malformed dates without uncaught exceptions."""
    assert parse_slurm_timestamp(raw_ts) == expected


def test_adversarial_missing_and_inverted_timestamps() -> None:
    """Verify trace handling when timestamps are missing, inverted, or skewed."""
    trace = (
        "JobIDRaw|Submit|Start|End|Elapsed|State|AllocCPUS|ReqMem\n"
        # Job 101: missing start and end, has elapsed
        "101|2026-03-01T10:00:00|||00:10:00|COMPLETED|2|4000M\n"
        # Job 102: missing submit, has start and end
        "102||2026-03-01T10:00:00|2026-03-01T10:10:00|00:10:00|COMPLETED|2|4000M\n"
        # Job 103: missing all timestamps, has elapsed
        "103||||00:10:00|COMPLETED|2|4000M\n"
        # Job 104: missing all timestamps and elapsed
        "104|||||COMPLETED|2|4000M\n"
        # Job 105: inverted start and end (end before start), missing elapsed
        "105|2026-03-01T10:00:00|2026-03-01T10:10:00|2026-03-01T10:05:00||FAILED|2|4000M\n"
        # Job 106: clock skew (start before submit)
        "106|2026-03-01T10:10:00|2026-03-01T10:05:00|2026-03-01T10:15:00|00:10:00|COMPLETED|2|4000M\n"
    )
    df = parse_sacct(trace)
    assert df.height == 6

    # Job 101
    r101 = df.filter(pl.col("job_id") == "101")
    assert r101.select("start_time").item() is None
    assert r101.select("end_time").item() is None
    assert r101.select("wait_s").item() == 0
    assert r101.select("run_s").item() == 600

    # Job 102: submit_time constructed from start_time
    r102 = df.filter(pl.col("job_id") == "102")
    assert r102.select("submit_time").item() == datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    assert r102.select("wait_s").item() == 0
    assert r102.select("run_s").item() == 600

    # Job 103: submit_time falls back to epoch
    r103 = df.filter(pl.col("job_id") == "103")
    assert r103.select("submit_time").item() == datetime(1970, 1, 1, tzinfo=UTC)
    assert r103.select("run_s").item() == 600

    # Job 104: all missing -> run_s 0
    r104 = df.filter(pl.col("job_id") == "104")
    assert r104.select("run_s").item() == 0
    assert r104.select("wait_s").item() == 0

    # Job 105: inverted times clamped to run_s 0
    r105 = df.filter(pl.col("job_id") == "105")
    assert r105.select("run_s").item() == 0

    # Job 106: start < submit clamped to wait_s 0
    r106 = df.filter(pl.col("job_id") == "106")
    assert r106.select("wait_s").item() == 0
    assert r106.select("run_s").item() == 600


# ============================================================================
# 2. Step rows with no parent row in the trace (orphaned steps)
# ============================================================================


def test_adversarial_orphaned_steps_only() -> None:
    """Verify trace containing only child steps without parent row produces empty canonical frame."""
    trace = (
        "JobIDRaw|User|Account|State|Elapsed|TotalCPU|MaxRSS|ReqMem|AllocCPUS\n"
        "201.0|alice|lab|COMPLETED|00:01:00|00:00:30|500M|1000M|2\n"
        "201.batch|alice|lab|COMPLETED|00:01:00|00:00:10|600M|1000M|2\n"
        "201.extern|alice|lab|COMPLETED|00:01:00|00:00:05|50M|1000M|2\n"
    )
    df = parse_sacct(trace)
    assert df.height == 0
    assert "job_id" in df.columns


def test_adversarial_orphaned_steps_mixed_with_valid_jobs() -> None:
    """Verify orphaned steps do not contaminate or drop valid peer jobs."""
    trace = (
        "JobIDRaw|User|Account|State|Elapsed|TotalCPU|MaxRSS|ReqMem|AllocCPUS\n"
        "201.0|alice|lab|COMPLETED|00:01:00|00:00:30|500M|1000M|2\n"
        "202|bob|lab|COMPLETED|00:02:00|00:01:00|700M|2000M|4\n"
        "203.batch|charlie|lab|COMPLETED|00:01:00|00:00:10|600M|1000M|2\n"
    )
    df = parse_sacct(trace)
    assert df.height == 1
    assert df.select("job_id").item() == "202"
    assert df.select("user").item() == "bob"


def test_adversarial_steps_appearing_before_parent() -> None:
    """Verify child steps appearing in trace before parent row roll up correctly."""
    trace = (
        "JobIDRaw|User|Account|State|Elapsed|TotalCPU|MaxRSS|ReqMem|AllocCPUS\n"
        "301.0|alice|lab|COMPLETED|00:01:00|00:00:30|500M|1000M|2\n"
        "301.batch|alice|lab|COMPLETED|00:01:00|00:00:10|600M|1000M|2\n"
        "301.extern|alice|lab|COMPLETED|00:01:00|00:00:05|100M|1000M|2\n"
        "301|alice|lab|COMPLETED|00:02:00|00:00:00||1000M|2\n"
    )
    df = parse_sacct(trace)
    assert df.height == 1
    row = df.filter(pl.col("job_id") == "301")
    assert row.select("max_rss_mb").item() == 600
    assert row.select("cpu_time_used_s").item() == 40.0


# ============================================================================
# 3. Multiple steps with the same step index
# ============================================================================


def test_adversarial_multiple_steps_same_index() -> None:
    """Verify multiple step rows with identical step indices roll up without failure."""
    trace = (
        "JobIDRaw|User|Account|State|Elapsed|TotalCPU|MaxRSS|ReqMem|AllocCPUS\n"
        "401|alice|lab|COMPLETED|00:05:00|00:00:00||2000M|4\n"
        "401.0|alice|lab|COMPLETED|00:02:00|00:01:00|500M|2000M|4\n"
        "401.0|alice|lab|COMPLETED|00:02:00|00:01:30|800M|2000M|4\n"
        "401.batch|alice|lab|COMPLETED|00:01:00|00:00:30|600M|2000M|4\n"
        "401.batch|alice|lab|COMPLETED|00:01:00|00:00:45|950M|2000M|4\n"
    )
    df = parse_sacct(trace)
    assert df.height == 1
    row = df.filter(pl.col("job_id") == "401")
    # Max of (500, 800, 600, 950) = 950
    assert row.select("max_rss_mb").item() == 950
    # Sum of (60, 90, 30, 45) = 225.0
    assert row.select("cpu_time_used_s").item() == 225.0


# ============================================================================
# 4. Memory suffixes, unknown strings, and negative values
# ============================================================================


@pytest.mark.parametrize(
    "raw_val,alloc_cpus,nodes,expected_mb",
    [
        ("4000M", 2, 2, 4000),
        ("4000Mc", 2, 2, 8000),
        ("4000Mn", 2, 3, 12000),
        ("4G", 2, 2, 4096),
        ("4Gc", 2, 2, 8192),
        ("4Gn", 2, 3, 12288),
        ("1048576K", 2, 2, 1024),
        ("524288Kc", 2, 2, 1024),
        ("2097152Kn", 2, 2, 4096),
        ("?", 2, 2, None),
        ("unknown_str", 2, 2, None),
        ("corrupted_123", 2, 2, None),
        ("4000X", 2, 2, None),
        ("0", 2, 2, 0),
        ("0M", 2, 2, 0),
        ("0Mc", 2, 2, 0),
        ("0Mn", 2, 2, 0),
        ("-100M", 2, 2, None),
        ("-1", 2, 2, None),
    ],
)
def test_adversarial_memory_suffixes_and_variations(
    raw_val: str,
    alloc_cpus: int,
    nodes: int,
    expected_mb: int | None,
) -> None:
    """Verify parsing of all required memory suffix combinations."""
    assert parse_slurm_memory_mb(raw_val, alloc_cpus=alloc_cpus, nodes=nodes) == expected_mb


def test_adversarial_trace_memory_suffixes_ingest() -> None:
    """Verify end-to-end ingestion of traces containing all memory suffix permutations."""
    trace = (
        "JobIDRaw|User|State|Elapsed|ReqMem|AllocCPUS|AllocTRES\n"
        "5001|alice|COMPLETED|00:01:00|4000M|2|node=1\n"
        "5002|alice|COMPLETED|00:01:00|4000Mc|2|node=1\n"
        "5003|alice|COMPLETED|00:01:00|4000Mn|2|node=2\n"
        "5004|alice|COMPLETED|00:01:00|4G|2|node=1\n"
        "5005|alice|COMPLETED|00:01:00|4Gc|2|node=1\n"
        "5006|alice|COMPLETED|00:01:00|4Gn|2|node=2\n"
        "5007|alice|COMPLETED|00:01:00|1048576K|2|node=1\n"
        "5008|alice|COMPLETED|00:01:00|524288Kc|2|node=1\n"
        "5009|alice|COMPLETED|00:01:00|2097152Kn|2|node=2\n"
        "5010|alice|COMPLETED|00:01:00|?|2|node=1\n"
        "5011|alice|COMPLETED|00:01:00|unknown|2|node=1\n"
        "5012|alice|COMPLETED|00:01:00|-100M|2|node=1\n"
    )
    df = parse_sacct(trace)
    assert df.height == 12

    # Check 5001: 4000M
    assert df.filter(pl.col("job_id") == "5001").select("req_mem_mb").item() == 4000
    # Check 5002: 4000Mc * 2 = 8000
    assert df.filter(pl.col("job_id") == "5002").select("req_mem_mb").item() == 8000
    # Check 5003: 4000Mn * 2 = 8000
    assert df.filter(pl.col("job_id") == "5003").select("req_mem_mb").item() == 8000
    # Check 5004: 4G = 4096
    assert df.filter(pl.col("job_id") == "5004").select("req_mem_mb").item() == 4096
    # Check 5005: 4Gc * 2 = 8192
    assert df.filter(pl.col("job_id") == "5005").select("req_mem_mb").item() == 8192
    # Check 5006: 4Gn * 2 = 8192
    assert df.filter(pl.col("job_id") == "5006").select("req_mem_mb").item() == 8192
    # Check 5007: 1048576K = 1024
    assert df.filter(pl.col("job_id") == "5007").select("req_mem_mb").item() == 1024
    # Check 5008: 524288Kc * 2 = 1024
    assert df.filter(pl.col("job_id") == "5008").select("req_mem_mb").item() == 1024
    # Check 5009: 2097152Kn * 2 = 4096
    assert df.filter(pl.col("job_id") == "5009").select("req_mem_mb").item() == 4096
    # Check 5010: ? -> None
    assert df.filter(pl.col("job_id") == "5010").select("req_mem_mb").item() is None
    assert df.filter(pl.col("job_id") == "5010").select("reserved_mem_mb_s").item() is None
    # Check 5011: unknown -> None
    assert df.filter(pl.col("job_id") == "5011").select("req_mem_mb").item() is None
    # Check 5012: negative memory maps to None (unknown/unattributed)
    assert df.filter(pl.col("job_id") == "5012").select("req_mem_mb").item() is None
    assert df.filter(pl.col("job_id") == "5012").select("reserved_mem_mb_s").item() is None


# ============================================================================
# 5. State qualifiers
# ============================================================================


@pytest.mark.parametrize(
    "raw_state,expected",
    [
        ("CANCELLED by 1234", "CANCELLED"),
        ("CANCELLED by 0", "CANCELLED"),
        ("CANCELLED by root", "CANCELLED"),
        ("CANCELLED", "CANCELLED"),
        ("CANCELLED+", "CANCELLED"),
        ("OUT_OF_MEMORY+", "OUT_OF_MEMORY"),
        ("OUT_OF_MEMORY", "OUT_OF_MEMORY"),
        ("BOOT_FAIL", "FAILED"),
        ("BOOT_FAIL+", "FAILED"),
        ("NODE_FAIL", "NODE_FAIL"),
        ("NODE_FAIL+", "NODE_FAIL"),
        ("COMPLETED+", "COMPLETED"),
        ("COMPLETED", "COMPLETED"),
        ("TIMEOUT+", "TIMEOUT"),
        ("TIMEOUT", "TIMEOUT"),
        ("DEADLINE", "TIMEOUT"),
        ("DEADLINE+", "TIMEOUT"),
        ("PREEMPTED+", "PREEMPTED"),
        ("PREEMPTED", "PREEMPTED"),
        ("RUNNING+", "RUNNING"),
        ("RUNNING", "RUNNING"),
        ("PENDING+", "PENDING"),
        ("PENDING", "PENDING"),
        ("REQUEUED", "PENDING"),
        ("REVOKED", "CANCELLED"),
        ("FAILED", "FAILED"),
        ("FAILED+", "FAILED"),
        ("FAILED_SPECIAL_CAUSE", "OTHER"),
        ("UNKNOWN_STATUS", "OTHER"),
        ("", "OTHER"),
        (None, "OTHER"),
    ],
)
def test_adversarial_state_mapping(raw_state: str | None, expected: str) -> None:
    """Verify stripping qualifiers and mapping Slurm states to canonical 10-state set."""
    assert map_slurm_state(raw_state) == expected


# ============================================================================
# 6. Zero runtimes (run_s = 0) preserved as early failures
# ============================================================================


def test_adversarial_zero_runtimes_preserved() -> None:
    """Verify zero runtimes are preserved as early failures in canonical DataFrame."""
    trace = (
        "JobIDRaw|User|State|Elapsed|Submit|Start|End|AllocCPUS|ReqMem\n"
        "601|alice|FAILED|00:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|2|4000M\n"
        "602|bob|OUT_OF_MEMORY|0|2026-03-01T10:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|4|8000M\n"
        "603|charlie|BOOT_FAIL|00:00.000|2026-03-01T10:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|1|2000M\n"
        "604|david|NODE_FAIL|00:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|8|16000M\n"
        "605|eve|COMPLETED|00:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|2026-03-01T10:00:00|1|1000M\n"
    )
    df = parse_sacct(trace)
    assert df.height == 5

    # Check that each job has run_s = 0 and is present
    for jid, expected_state in [
        ("601", "FAILED"),
        ("602", "OUT_OF_MEMORY"),
        ("603", "FAILED"),
        ("604", "NODE_FAIL"),
        ("605", "COMPLETED"),
    ]:
        row = df.filter(pl.col("job_id") == jid)
        assert row.height == 1
        assert row.select("run_s").item() == 0
        assert row.select("state").item() == expected_state
        assert row.select("reserved_core_s").item() == 0
        assert row.select("reserved_mem_mb_s").item() == 0


# ============================================================================
# 7. Array jobs with brackets vs concrete tasks
# ============================================================================


@pytest.mark.parametrize(
    "raw_id,expected_base,expected_step,expected_parent",
    [
        ("12345_[0-99]", "12345_[0-99]", None, "12345"),
        ("12345_[0-99].batch", "12345_[0-99]", "batch", "12345"),
        ("12345_[1-50%2]", "12345_[1-50%2]", None, "12345"),
        ("12345_1", "12345_1", None, "12345"),
        ("12345_1.batch", "12345_1", "batch", "12345"),
        ("12345_0.0", "12345_0", "0", "12345"),
        ("7002+0", "7002+0", None, "7002"),
        ("7002+1.0", "7002+1", "0", "7002"),
        ("99999", "99999", None, None),
    ],
)
def test_adversarial_job_id_decomposition(
    raw_id: str,
    expected_base: str,
    expected_step: str | None,
    expected_parent: str | None,
) -> None:
    """Verify decomposition of bracketed array masters and concrete task instances."""
    base, step, parent = decompose_job_id(raw_id)
    assert base == expected_base
    assert step == expected_step
    assert parent == expected_parent


def test_adversarial_array_trace_with_master_and_concrete_tasks() -> None:
    """Verify trace containing bracketed array master and concrete tasks parses correctly."""
    trace = (
        "JobIDRaw|User|State|Elapsed|AllocCPUS|ReqMem\n"
        "12345_[0-99]|alice|PENDING|00:00:00|1|1000M\n"
        "12345_0|alice|COMPLETED|00:10:00|1|1000M\n"
        "12345_1|alice|COMPLETED|00:10:00|1|1000M\n"
        "12345_1.0|alice|COMPLETED|00:05:00|1|1000M\n"
    )
    df = parse_sacct(trace)
    assert df.height == 3

    # Check bracketed array master
    master = df.filter(pl.col("job_id") == "12345_[0-99]")
    assert master.height == 1
    assert master.select("parent_job_id").item() == "12345"
    assert master.select("state").item() == "PENDING"

    # Check concrete task 0
    t0 = df.filter(pl.col("job_id") == "12345_0")
    assert t0.height == 1
    assert t0.select("parent_job_id").item() == "12345"
    assert t0.select("state").item() == "COMPLETED"

    # Check concrete task 1
    t1 = df.filter(pl.col("job_id") == "12345_1")
    assert t1.height == 1
    assert t1.select("parent_job_id").item() == "12345"


# ============================================================================
# 8. Extreme duration values
# ============================================================================


@pytest.mark.parametrize(
    "raw_dur,expected_float,expected_int",
    [
        ("0", 0.0, 0),
        ("00:00:00", 0.0, 0),
        ("00:00.000", 0.0, 0),
        ("00:00.000001", 1e-06, 0),
        ("00:00.0005", 0.0005, 0),
        ("00:00.499", 0.499, 0),
        ("00:00.500", 0.5, 1),
        ("00:00.999", 0.999, 1),
        ("00:01:00", 60.0, 60),
        ("365-00:00:00", 31536000.0, 31536000),
        ("3650-00:00:00", 315360000.0, 315360000),
        ("99999-23:59:59", 8639999999.0, 8639999999),
        ("-00:10:00", 0.0, 0),
        ("-1", 0.0, 0),
        ("INVALID", None, 0),
        ("UNLIMITED", None, 0),
        ("Partition_Limit", None, 0),
        ("Unknown", None, 0),
        ("N/A", None, 0),
        ("None", None, 0),
        ("-", None, 0),
        ("", None, 0),
        (None, None, 0),
    ],
)
def test_adversarial_extreme_durations(
    raw_dur: str | None,
    expected_float: float | None,
    expected_int: int,
) -> None:
    """Verify duration parsing with microsecond, multi-year, negative, and sentinel values."""
    actual_float = parse_duration_s(raw_dur)
    if expected_float is None:
        assert actual_float is None
    else:
        assert actual_float is not None
        assert abs(actual_float - expected_float) < 1e-6

    assert parse_duration_int(raw_dur) == expected_int
