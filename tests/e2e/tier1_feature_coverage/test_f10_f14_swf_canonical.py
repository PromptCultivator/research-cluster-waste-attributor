"""Tier 1 Feature Coverage: F10 through F14 (SWF parsing, conversions, canonical model, exclusions, throughput).

Features:
- F10: SWF format parsing (18 whitespace-separated fields, header pragmas)
- F11: SWF metric conversions (KB/proc to MB total, proc CPU to total seconds, -1 to null)
- F12: Canonical job record model (Arrow schema, calculated reserved resources)
- F13: Exclusion of active jobs (RUNNING/PENDING) and retention of zero-runtime jobs
- F14: Ingest throughput verification on synthetic batches
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "fixture_name,expected_min_jobs",
    [
        ("standard_with_headers.swf", 5),
        ("missing_fields.swf", 3),
        ("status_variations.swf", 4),
        ("sample_workload.swf", 10),
        ("calibration_reference.swf", 8),
    ],
)
def test_f10_swf_parsing(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
    expected_min_jobs: int,
):
    """F10: Verify SWF traces parse across variations and extract all job records."""
    trace_path = fixtures_dir / "swf" / fixture_name
    out_path = isolated_workspace / f"swf_{fixture_name}.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0, f"SWF ingest failed: {result.stderr}"

    df = pl.read_parquet(out_path)
    assert df.height >= expected_min_jobs, f"Expected at least {expected_min_jobs} jobs, found {df.height}"


@pytest.mark.parametrize(
    "pragma_header,pragma_value",
    [
        ("; UnixStartTime: 1704067200", "1704067200"),
        ("; MaxProcs: 256", "256"),
        ("; MaxNodes: 64", "64"),
        ("; MaxJobs: 10000", "10000"),
        ("; MaxMemory: 1048576", "1048576"),
        ("; Time: 86400", "86400"),
        ("; Note: Standard SWF reference trace fixture", "Standard SWF reference trace fixture"),
    ],
)
def test_f10_swf_header_pragmas(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    pragma_header: str,
    pragma_value: str,
):
    """F10: Verify SWF header pragmas are parsed and do not corrupt job table ingestion."""
    swf_file = isolated_workspace / "pragma_test.swf"
    out_file = isolated_workspace / "pragma_test.parquet"

    content = (
        f"{pragma_header}\n"
        "1 0 10 100 4 100 4096 4 100 1 1 1 1 1 -1 -1 -1 -1\n"
    )
    swf_file.write_text(content)

    res = run_cli(["ingest", str(swf_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    assert df.height == 1
    assert df.select("job_id").item() == "1"


@pytest.mark.parametrize(
    "raw_kb_per_proc,alloc_cpus,expected_mb",
    [
        (1048576, 1, 1024),
        (524288, 2, 1024),
        (1048576, 2, 2048),
        (1048576, 4, 4096),
        (2097152, 4, 8192),
        (2097152, 8, 16384),
        (4194304, 8, 32768),
        (2097152, 16, 32768),
        (4194304, 16, 65536),
        (4194304, 32, 131072),
        (-1, 4, None),
        (-1, 8, None),
    ],
)
def test_f11_swf_memory_conversion(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    raw_kb_per_proc: int,
    alloc_cpus: int,
    expected_mb: int | None,
):
    """F11: Verify conversion of SWF memory (KB per allocated processor) to job-level MB via ingest CLI."""
    swf_file = isolated_workspace / f"swf_mem_{raw_kb_per_proc}_{alloc_cpus}.swf"
    out_file = isolated_workspace / f"swf_mem_{raw_kb_per_proc}_{alloc_cpus}.parquet"

    # Field 1: Job Number, 2: Submit, 3: Wait, 4: Run, 5: AllocCPUS, 6: AvgCPU, 7: UsedMem, 8: ReqCPUS, 9: ReqTime, 10: ReqMem
    content = f"1 0 10 100 {alloc_cpus} 100 {raw_kb_per_proc} {alloc_cpus} 100 {raw_kb_per_proc} 1 1 1 1 -1 -1 -1 -1\n"
    swf_file.write_text(content)

    res = run_cli(["ingest", str(swf_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_mem = df.select("req_mem_mb").item()
    assert actual_mem == expected_mb


@pytest.mark.parametrize(
    "avg_cpu_time,alloc_cpus,expected_total_cpu_s",
    [
        (100, 1, 100.0),
        (500, 2, 1000.0),
        (600, 4, 2400.0),
        (1200, 4, 4800.0),
        (1500, 8, 12000.0),
        (3000, 8, 24000.0),
        (600, 16, 9600.0),
        (1800, 16, 28800.0),
        (3600, 32, 115200.0),
        (-1, 4, None),
        (-1, 8, None),
    ],
)
def test_f11_swf_cpu_conversion(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    avg_cpu_time: int,
    alloc_cpus: int,
    expected_total_cpu_s: float | None,
):
    """F11: Verify SWF average CPU time per processor scales to total job CPU seconds via ingest CLI."""
    swf_file = isolated_workspace / f"swf_cpu_{avg_cpu_time}_{alloc_cpus}.swf"
    out_file = isolated_workspace / f"swf_cpu_{avg_cpu_time}_{alloc_cpus}.parquet"

    # Field 6 is Average CPU Time Used
    content = f"1 0 10 100 {alloc_cpus} {avg_cpu_time} 1048576 {alloc_cpus} 100 1048576 1 1 1 1 -1 -1 -1 -1\n"
    swf_file.write_text(content)

    res = run_cli(["ingest", str(swf_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_cpu = df.select("cpu_time_used_s").item()
    assert actual_cpu == expected_total_cpu_s


@pytest.mark.parametrize(
    "status_code,expected_canonical_state",
    [
        (1, "COMPLETED"),
        (0, "FAILED"),
        (5, "CANCELLED"),
        (2, "OTHER"),
        (3, "OTHER"),
        (4, "OTHER"),
        (99, "OTHER"),
    ],
)
def test_f11_swf_status_mapping(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    status_code: int,
    expected_canonical_state: str,
):
    """F11: Verify mapping of SWF numeric status codes to canonical state enum via ingest CLI."""
    swf_file = isolated_workspace / f"swf_status_{status_code}.swf"
    out_file = isolated_workspace / f"swf_status_{status_code}.parquet"

    # Field 11 is Status Code
    content = f"1 0 10 100 4 100 1048576 4 100 1048576 {status_code} 1 1 1 -1 -1 -1 -1\n"
    swf_file.write_text(content)

    res = run_cli(["ingest", str(swf_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    actual_state = df.select("state").item()
    assert actual_state == expected_canonical_state


@pytest.mark.parametrize(
    "alloc_cpus,req_mem_mb,run_s,expected_core_s,expected_mem_mb_s",
    [
        (1, 1024, 10, 10, 10240),
        (1, 2048, 60, 60, 122880),
        (2, 4000, 300, 600, 1200000),
        (2, 8000, 900, 1800, 7200000),
        (4, 16000, 1800, 7200, 28800000),
        (8, 32000, 3600, 28800, 115200000),
        (16, 64000, 7200, 115200, 460800000),
        (32, 128000, 100, 3200, 12800000),
        (64, 256000, 3600, 230400, 921600000),
        (8, 64000, 1800, 14400, 115200000),
        (4, 32000, 900, 3600, 28800000),
    ],
)
def test_f12_canonical_reservation_arithmetic(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    alloc_cpus: int,
    req_mem_mb: int,
    run_s: int,
    expected_core_s: int,
    expected_mem_mb_s: int,
):
    """F12: Verify reserved_core_s and reserved_mem_mb_s calculations on canonical records via attribute CLI."""
    trace_file = isolated_workspace / f"res_{alloc_cpus}_{req_mem_mb}_{run_s}.txt"
    attr_file = isolated_workspace / f"res_{alloc_cpus}_{req_mem_mb}_{run_s}.parquet"

    elapsed_str = f"{run_s // 3600:02d}:{(run_s % 3600) // 60:02d}:{run_s % 60:02d}"
    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"501|501|alice|res|comp|norm|res_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T11:00:05|{elapsed_str}|COMPLETED|0:0|{alloc_cpus}|{alloc_cpus}|{req_mem_mb}M|2000M|1800M|00:05:00|7200|billing={alloc_cpus},cpu={alloc_cpus},node=1|billing={alloc_cpus},cpu={alloc_cpus},node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.select("reserved_core_s").item() == expected_core_s
    assert df.select("reserved_mem_mb_s").item() == expected_mem_mb_s


@pytest.mark.parametrize(
    "job_id,expected_retained,expected_reserved_core_s",
    [
        ("1101", False, 0),     # RUNNING excluded from attribution
        ("1102", False, 0),     # PENDING excluded from attribution
        ("1103", True, 7200),   # COMPLETED retained
    ],
)
def test_f13_active_job_exclusions(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_retained: bool,
    expected_reserved_core_s: int,
):
    """F13: Verify RUNNING and PENDING rows are excluded from attribution records."""
    trace_path = fixtures_dir / "sacct" / "sacct_running_pending.txt"
    attributed_path = isolated_workspace / "attributed_exclusions.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    matches = df.filter(pl.col("job_id") == job_id)
    if expected_retained:
        assert matches.height == 1
        assert matches.select("reserved_core_s").item() == expected_reserved_core_s
    else:
        assert matches.height == 0, f"Active job {job_id} was improperly included in attribution"


@pytest.mark.parametrize("run_s_val", [0, 10, 60])
def test_f13_zero_runtime_early_failures(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    run_s_val: int,
):
    """F13: Verify zero and short runtime jobs (<=60s) are kept as early failures via attribute CLI."""
    trace_file = isolated_workspace / f"zero_run_{run_s_val}.txt"
    attr_file = isolated_workspace / f"zero_run_{run_s_val}.parquet"

    elapsed_str = f"00:00:{run_s_val:02d}"
    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"601|601|alice|res|comp|norm|zero_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:00:05|{elapsed_str}|FAILED|1:0|4|4|8000M|||00:00:00|0|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.height == 1
    assert df.select("reserved_core_s").item() == 4 * run_s_val
    assert df.select("class3_sub_label").item() == "early_failure"


@pytest.mark.parametrize(
    "batch_size,min_jobs_per_sec",
    [
        (100, 300),
        (200, 400),
        (500, 500),
        (1000, 500),
    ],
)
def test_f14_ingest_throughput_verification(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    batch_size: int,
    min_jobs_per_sec: float,
):
    """F14: Measure parsing throughput on synthetic sacct rows via CLI to confirm ingestion efficiency."""
    import time

    headers = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    rows = [headers]
    for i in range(batch_size):
        row = f"{i}|{i}|user{i % 10}|acct|part|normal|job{i}|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|8000M|3000M|2800M|01:30:00|7200|billing=4,cpu=4,mem=8000M,node=1|billing=4,cpu=4,mem=8000M,node=1|node-01||sbatch run.sh"
        rows.append(row)
    data = "\n".join(rows)

    trace_file = isolated_workspace / f"bench_{batch_size}.txt"
    out_file = isolated_workspace / f"bench_{batch_size}.parquet"
    trace_file.write_text(data)

    start = time.perf_counter()
    result = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    duration = time.perf_counter() - start

    assert result.exit_code == 0
    df = pl.read_parquet(out_file)
    assert df.height == batch_size

    jobs_per_sec = batch_size / duration
    assert jobs_per_sec >= min_jobs_per_sec, f"Throughput {jobs_per_sec:.1f} jobs/s lower than required {min_jobs_per_sec}"
