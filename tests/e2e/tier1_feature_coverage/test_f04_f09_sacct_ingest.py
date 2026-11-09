"""Tier 1 Feature Coverage: F4 through F9 (Slurm sacct parsing and normalization).

Features:
- F4: sacct 26-column parsing, empty fields, unknown columns, reordered headers, trailing delimiters
- F5: Step hierarchy rollup (MaxRSS max over steps, TotalCPU sum excluding .extern)
- F6: Array jobs and heterogeneous pack components
- F7: Time and duration parsing (D-HH:MM:SS, HH:MM:SS, MM:SS.mmm, wait_s calculation)
- F8: Memory suffix parsing (M, Mc, Mn, G, Gc, Gn, K, Kc, Kn, ?)
- F9: State qualifiers and TRES parsing (strip qualifiers, map states, GPU extraction)
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "fixture_name,expected_exit",
    [
        ("sacct_standard_26col.txt", 0),
        ("sacct_empty_optional_fields.txt", 0),
        ("sacct_unknown_columns.txt", 0),
        ("sacct_reordered_headers.txt", 0),
        ("sacct_trailing_delimiters.txt", 0),
        ("multiday_cluster.txt", 0),
        ("sacct_durations_states.txt", 0),
        ("sacct_unattributed_missing.txt", 0),
        ("sacct_memory_suffixes.txt", 0),
        ("sacct_steps_rollup.txt", 0),
        ("sacct_array_heterogeneous.txt", 0),
    ],
)
def test_f04_sacct_format_variations(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
    expected_exit: int,
):
    """F4: Verify sacct parsing across standard, empty, unknown, reordered, and trailing formats."""
    trace_path = fixtures_dir / "sacct" / fixture_name
    out_path = isolated_workspace / f"canonical_{fixture_name}.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == expected_exit, f"Ingest failed: {result.stderr}"
    assert out_path.exists(), f"Output parquet was not created: {out_path}"


def test_f04_unknown_columns_warning(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
):
    """F4: Verify unknown extra columns trigger warning or are safely ignored without schema failure."""
    trace_path = fixtures_dir / "sacct" / "sacct_unknown_columns.txt"
    out_path = isolated_workspace / "canonical_unknown.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()

    df = pl.read_parquet(out_path)
    assert "job_id" in df.columns
    assert "alloc_cpus" in df.columns


@pytest.mark.parametrize(
    "column_name",
    [
        "job_id",
        "parent_job_id",
        "source",
        "user",
        "account",
        "partition",
        "job_name",
        "command_hash",
        "input_hash",
        "submit_time",
        "start_time",
        "end_time",
        "wait_s",
        "run_s",
        "state",
        "exit_code",
        "req_cpus",
        "alloc_cpus",
        "cpu_time_used_s",
        "req_mem_mb",
        "max_rss_mb",
        "nodes",
    ],
)
def test_f04_schema_columns_present(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    column_name: str,
):
    """F4: Verify all mandatory canonical columns exist in ingested sacct output."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    out_path = isolated_workspace / "canonical_schema_check.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    assert column_name in df.columns, f"Expected column {column_name} missing from canonical frame"


@pytest.mark.parametrize(
    "job_id,expected_max_rss,expected_cpu_time_used",
    [
        ("6001", 18000, 19800),  # max(12000, 18000), sum(10800 + 9000, excluding extern 15s)
        ("6002", 8000, 5400),    # max(4000, 8000), sum(1800 + 3600)
    ],
)
def test_f05_step_hierarchy_rollup(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_max_rss: int,
    expected_cpu_time_used: float,
):
    """F5: Verify step rollup assigns maximum RSS and sums TotalCPU excluding .extern."""
    trace_path = fixtures_dir / "sacct" / "sacct_steps_rollup.txt"
    out_path = isolated_workspace / "rolled_up.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    job_row = df.filter(pl.col("job_id") == job_id)
    assert job_row.height == 1, f"Job {job_id} not found in rolled up records"

    actual_rss = job_row.select("max_rss_mb").item()
    actual_cpu = job_row.select("cpu_time_used_s").item()

    assert actual_rss == expected_max_rss, f"RSS mismatch for {job_id}: got {actual_rss}, expected {expected_max_rss}"
    assert actual_cpu == expected_cpu_time_used, f"CPU mismatch for {job_id}: got {actual_cpu}, expected {expected_cpu_time_used}"


@pytest.mark.parametrize(
    "job_id,expected_parent",
    [
        ("7001_0", "7001"),
        ("7001_1", "7001"),
        ("7001_2", "7001"),
        ("7002+0", "7002"),
        ("7002+1", "7002"),
    ],
)
def test_f06_array_and_heterogeneous_jobs(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_parent: str,
):
    """F6: Verify array tasks and heterogeneous pack elements decompose to distinct jobs with parent linkage."""
    trace_path = fixtures_dir / "sacct" / "sacct_array_heterogeneous.txt"
    out_path = isolated_workspace / "array_het.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1, f"Sub-job {job_id} missing from ingested frame"
    parent = row.select("parent_job_id").item()
    assert parent == expected_parent, f"Expected parent {expected_parent} for {job_id}, got {parent}"


@pytest.mark.parametrize(
    "raw_duration,expected_seconds",
    [
        ("00:00:10", 10),
        ("00:01:00", 60),
        ("00:05:00", 300),
        ("00:30:00", 1800),
        ("01:00:00", 3600),
        ("01:30:15", 5415),
        ("05:00:00", 18000),
        ("12:00:00", 43200),
        ("1-00:00:00", 86400),
        ("1-02:03:04", 93784),
        ("2-12:30:00", 217800),
        ("3-00:00:00", 259200),
        ("7-12:00:00", 648000),
        ("00:00.500", 1),
        ("00:10.000", 10),
        ("00:35.450", 35),
        ("01:00.500", 61),
        ("02:15.500", 136),
        ("05:00.000", 300),
        ("00:00.100", 0),
        ("00:00.010", 0),
        ("00:00.001", 0),
    ],
)
def test_f07_duration_parsing(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_duration: str,
    expected_seconds: int,
):
    """F7: Test duration parsing across day-hour-minute-second, sub-minute, and fractional patterns via ingest CLI."""
    trace_file = isolated_workspace / f"dur_{raw_duration.replace(':', '_').replace('.', '_')}.txt"
    out_file = isolated_workspace / f"dur_{raw_duration.replace(':', '_').replace('.', '_')}.parquet"

    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"101|101|alice|res|comp|norm|test_dur|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T11:00:05|{raw_duration}|COMPLETED|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,mem=8000M,node=1|billing=4,cpu=4,mem=8000M,node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_run_s = df.select("run_s").item()
    assert abs(actual_run_s - expected_seconds) <= 1


@pytest.mark.parametrize(
    "job_id,expected_wait_s,expected_run_s",
    [
        ("9001", 5, 93784),
        ("9002", 5, 40),
        ("9003", 5, 136),
        ("9004", 5, 900),
        ("9005", 5, 600),
        ("9006", 5, 480),
    ],
)
def test_f07_wait_and_run_computation(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_wait_s: int,
    expected_run_s: int,
):
    """F7: Verify wait_s and run_s calculation from start, submit, and end timestamps."""
    trace_path = fixtures_dir / "sacct" / "sacct_durations_states.txt"
    out_path = isolated_workspace / "durations_check.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    actual_wait = row.select("wait_s").item()
    actual_run = row.select("run_s").item()

    assert actual_wait == expected_wait_s, f"Wait mismatch for {job_id}: got {actual_wait}"
    assert abs(actual_run - expected_run_s) <= 1, f"Run mismatch for {job_id}: got {actual_run}"


@pytest.mark.parametrize(
    "job_id,expected_mem_mb",
    [
        ("8001", 4000),      # 4000M total
        ("8002", 8000),      # 2000Mc * 4 cpus = 8000 MB
        ("8003", 16000),     # 8000Mn * 2 nodes = 16000 MB
        ("8004", 4096),      # 4G = 4096 MB
        ("8005", 8192),      # 2Gc * 4 cpus = 8192 MB
        ("8006", 32768),     # 16Gn * 2 nodes = 32768 MB
        ("8007", 1024),      # 1048576K = 1024 MB
        ("8008", 2048),      # 524288Kc * 4 cpus = 2048 MB
        ("8009", 4096),      # 2097152Kn * 2 nodes = 4096 MB
        ("8010", None),      # ? unknown memory
    ],
)
def test_f08_memory_suffixes(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_mem_mb: int | None,
):
    """F8: Verify ReqMem conversion across M, Mc, Mn, G, Gc, Gn, K, Kc, Kn, and ? formats."""
    trace_path = fixtures_dir / "sacct" / "sacct_memory_suffixes.txt"
    out_path = isolated_workspace / "mem_suffixes.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(out_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    actual_mem = row.select("req_mem_mb").item()
    assert actual_mem == expected_mem_mb, f"Memory mismatch for {job_id}: got {actual_mem}, expected {expected_mem_mb}"


@pytest.mark.parametrize(
    "raw_req_mem,alloc_cpus,nodes,expected_mb",
    [
        ("1000M", 2, 1, 1000),
        ("500Mc", 2, 1, 1000),
        ("1000Mc", 8, 1, 8000),
        ("2000Mn", 4, 4, 8000),
        ("8G", 4, 1, 8192),
        ("1Gc", 4, 1, 4096),
        ("4Gc", 2, 1, 8192),
        ("32Gn", 16, 2, 65536),
        ("2048K", 1, 1, 2),
        ("4096Kc", 4, 1, 16),
        ("8192Kn", 4, 2, 16),
        ("?", 4, 1, None),
    ],
)
def test_f08_memory_string_conversion_helper(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_req_mem: str,
    alloc_cpus: int,
    nodes: int,
    expected_mb: int | None,
):
    """F8: Test Slurm memory string conversion function across all unit combinations via opaque-box CLI."""
    trace_file = isolated_workspace / f"mem_{raw_req_mem.replace('?', 'unknown')}_{alloc_cpus}_{nodes}.txt"
    out_file = isolated_workspace / f"mem_{raw_req_mem.replace('?', 'unknown')}_{alloc_cpus}_{nodes}.parquet"

    node_list = ",".join(f"node-{i:02d}" for i in range(1, nodes + 1))
    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"201|201|alice|res|comp|norm|mem_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|{alloc_cpus}|{alloc_cpus}|{raw_req_mem}|2000M|1800M|00:10:00|7200|billing={alloc_cpus},cpu={alloc_cpus},node={nodes}|billing={alloc_cpus},cpu={alloc_cpus},node={nodes}|{node_list}||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_mem = df.select("req_mem_mb").item()
    assert actual_mem == expected_mb


@pytest.mark.parametrize(
    "raw_state,expected_canonical_state",
    [
        ("COMPLETED", "COMPLETED"),
        ("COMPLETED+", "COMPLETED"),
        ("FAILED", "FAILED"),
        ("TIMEOUT", "TIMEOUT"),
        ("OUT_OF_MEMORY", "OUT_OF_MEMORY"),
        ("OUT_OF_MEMORY+", "OUT_OF_MEMORY"),
        ("CANCELLED", "CANCELLED"),
        ("CANCELLED by 1005", "CANCELLED"),
        ("CANCELLED by 0", "CANCELLED"),
        ("CANCELLED by 1234", "CANCELLED"),
        ("NODE_FAIL", "NODE_FAIL"),
        ("PREEMPTED", "PREEMPTED"),
        ("BOOT_FAIL", "FAILED"),
        ("DEADLINE", "TIMEOUT"),
        ("RUNNING", "RUNNING"),
        ("PENDING", "PENDING"),
        ("REVOKED", "CANCELLED"),
        ("UNKNOWN_STATUS_XYZ", "OTHER"),
    ],
)
def test_f09_state_mapping(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_state: str,
    expected_canonical_state: str,
):
    """F9: Verify stripping of Slurm state qualifiers and mapping to canonical enum via opaque-box CLI."""
    safe_name = raw_state.replace(" ", "_").replace("+", "plus")
    trace_file = isolated_workspace / f"state_{safe_name}.txt"
    out_file = isolated_workspace / f"state_{safe_name}.parquet"

    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"301|301|alice|res|comp|norm|state_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|{raw_state}|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,mem=8000M,node=1|billing=4,cpu=4,mem=8000M,node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_state = df.select("state").item()
    assert actual_state == expected_canonical_state


@pytest.mark.parametrize(
    "raw_tres,expected_gpus",
    [
        ("billing=8,cpu=8,gres/gpu=1,mem=16000M,node=1", 1),
        ("billing=8,cpu=8,gres/gpu=2,mem=32000M,node=1", 2),
        ("billing=16,cpu=16,gres/gpu=4,mem=64000M,node=2", 4),
        ("billing=4,cpu=4,gres/gpu:a100=2,mem=16000M,node=1", 2),
        ("billing=32,cpu=32,gres/gpu=8,mem=128000M,node=4", 8),
        ("billing=64,cpu=64,gres/gpu=8,mem=256000M,node=8", 8),
        ("billing=2,cpu=2,gres/gpu=1,mem=8000M,node=1", 1),
        ("cpu=128,mem=512000M,node=4,gres/gpu=8", 8),
    ],
)
def test_f09_tres_gpu_parsing(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_tres: str,
    expected_gpus: int,
):
    """F9: Test extraction of GPU counts from Slurm ReqTRES and AllocTRES strings via opaque-box CLI."""
    trace_file = isolated_workspace / f"tres_gpu_{expected_gpus}_{abs(hash(raw_tres))}.txt"
    out_file = isolated_workspace / f"tres_gpu_{expected_gpus}_{abs(hash(raw_tres))}.parquet"

    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"401|401|alice|res|comp|norm|tres_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|8|8|8000M|2000M|1800M|00:10:00|7200|{raw_tres}|{raw_tres}|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_gpus = df.select("alloc_gpus").item()
    assert actual_gpus == expected_gpus
