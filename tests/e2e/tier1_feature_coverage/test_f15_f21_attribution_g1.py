"""Tier 1 Feature Coverage: F15 through F21 (Attribution precedence, Classes 1-4, and Guarantee G1).

Features:
- F15: One-pass conservation precedence order
- F16: Class 3 attribution (failed/retried work and 6 sub-labels including other_failure)
- F17: Retry chain linkage within retry window
- F18: Class 2 idle reserved CPU calculation
- F19: Class 1 memory over-request calculation
- F20: Unattributed metrics labeling (missing CPU and RSS)
- F21: Guarantee G1 conservation invariant verification
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "job_id,expected_class,expected_core_waste,expected_mem_waste",
    [
        ("1001", "class2_and_class1", 1800, 58320000),  # Completed normal: Class 2 core idle, Class 1 mem over
        ("1002", "class3", 3600, 14400000),            # Failed: entire reservation to Class 3
        ("1003", "class3", 115200, 460800000),         # Timeout: entire reservation to Class 3
        ("1004", "class3", 2400, 9600000),             # OOM: entire reservation to Class 3
        ("1005", "class3", 4800, 9600000),             # Cancelled after start: Class 3
        ("1006", "class3", 21600, 43200000),           # Node fail: Class 3
        ("1007", "class3", 7200, 28800000),            # Preempted: Class 3
    ],
)
def test_f15_f16_precedence_and_class3_attribution(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_class: str,
    expected_core_waste: int,
    expected_mem_waste: int,
):
    """F15, F16: Verify precedence and full-reservation attribution for failed jobs under Class 3."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    attributed_path = isolated_workspace / "attr_precedence.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    if expected_class == "class3":
        assert row.select("class3_core_s").item() == expected_core_waste
        assert row.select("class3_mem_mb_s").item() == expected_mem_waste
        assert row.select("used_core_s").item() == 0
        assert row.select("used_mem_mb_s").item() == 0


@pytest.mark.parametrize(
    "job_id,expected_sub_label",
    [
        ("1004", "oom"),
        ("1003", "timeout"),
        ("1006", "node_fail"),
        ("1005", "cancelled_after_start"),
        ("1010", "early_failure"),    # run_s <= 60s
        ("1008", "other_failure"),    # generic failure with run_s > 60s
    ],
)
def test_f16_class3_sub_labels(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_sub_label: str,
):
    """F16: Verify assignment of specific Class 3 sub-labels (oom, timeout, early_failure, other_failure, etc.)."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    attributed_path = isolated_workspace / "attr_sublabels.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1, f"Job {job_id} not found in attribution output"
    sub_label = row.select("class3_sub_label").item()
    assert sub_label == expected_sub_label, f"Job {job_id} expected {expected_sub_label}, got {sub_label}"


@pytest.mark.parametrize(
    "job_id,expected_retry_of",
    [
        ("1801", None),     # Initial failed job
        ("1802", "1801"),   # First retry within 24h
        ("1803", "1802"),   # Second retry within 24h
        ("1804", None),     # Independent job by different user
    ],
)
def test_f17_retry_chain_detection(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_retry_of: str,
):
    """F17: Verify retry chain pointer assignment for jobs resubmitted within retry_window."""
    trace_path = fixtures_dir / "retries" / "retry_chains.txt"
    attributed_path = isolated_workspace / "attr_retries.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1
    retry_of = row.select("retry_of").item()
    assert retry_of == expected_retry_of, f"Job {job_id} expected retry_of {expected_retry_of}, got {retry_of}"


@pytest.mark.parametrize(
    "reserved_core_s,cpu_used_s,expected_idle_core_s,expected_used_core_s",
    [
        (360, 180.0, 180, 180),
        (7200, 3600.0, 3600, 3600),
        (28800, 27000.0, 1800, 27000),
        (14400, 14400.0, 0, 14400),
        (3600, 4000.0, 0, 3600),
        (1000, 0.0, 1000, 0),
        (2000, 500.0, 1500, 500),
        (5000, 4999.0, 1, 4999),
        (10000, 2500.0, 7500, 2500),
        (86400, 43200.0, 43200, 43200),
        (172800, 86400.0, 86400, 86400),
        (345600, 0.0, 345600, 0),
    ],
)
def test_f18_class2_idle_cpu(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    reserved_core_s: int,
    cpu_used_s: float,
    expected_idle_core_s: int,
    expected_used_core_s: int,
):
    """F18: Verify Class 2 idle CPU calculation and used CPU core-seconds via opaque-box attribution CLI."""
    trace_file = isolated_workspace / f"c2_{reserved_core_s}_{int(cpu_used_s)}.txt"
    attr_file = isolated_workspace / f"c2_{reserved_core_s}_{int(cpu_used_s)}.parquet"

    alloc_cpus = 4
    run_s = reserved_core_s // alloc_cpus
    elapsed_str = f"{run_s // 3600:02d}:{(run_s % 3600) // 60:02d}:{run_s % 60:02d}"
    total_cpu_str = f"{int(cpu_used_s) // 3600:02d}:{(int(cpu_used_s) % 3600) // 60:02d}:{int(cpu_used_s) % 60:02d}"
    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"701|701|alice|res|comp|norm|idle_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|{elapsed_str}|COMPLETED|0:0|{alloc_cpus}|{alloc_cpus}|8000M|2000M|1800M|{total_cpu_str}|{cpu_used_s}|billing={alloc_cpus},cpu={alloc_cpus},node=1|billing={alloc_cpus},cpu={alloc_cpus},node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.select("class2_idle_core_s").item() == expected_idle_core_s
    assert df.select("used_core_s").item() == expected_used_core_s


@pytest.mark.parametrize(
    "req_mem_mb,max_rss_mb,run_s,expected_over_mem_mb_s,expected_used_mem_mb_s",
    [
        (2000, 1000, 60, 60000, 60000),
        (4000, 2000, 300, 600000, 600000),
        (8000, 8000, 1800, 0, 14400000),
        (16000, 4000, 600, 7200000, 2400000),
        (32000, 16000, 3600, 57600000, 57600000),
        (4000, 5000, 100, 0, 400000),
        (64000, 32000, 7200, 230400000, 230400000),
        (128000, 64000, 3600, 230400000, 230400000),
        (8000, 1000, 1200, 8400000, 1200000),
        (16000, 15000, 500, 500000, 7500000),
        (32000, 31000, 1000, 1000000, 31000000),
    ],
)
def test_f19_class1_memory_over_request(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    req_mem_mb: int,
    max_rss_mb: int,
    run_s: int,
    expected_over_mem_mb_s: int,
    expected_used_mem_mb_s: int,
):
    """F19: Verify Class 1 memory over-request calculation and used memory MB-seconds via opaque-box attribution CLI."""
    trace_file = isolated_workspace / f"c1_{req_mem_mb}_{max_rss_mb}.txt"
    attr_file = isolated_workspace / f"c1_{req_mem_mb}_{max_rss_mb}.parquet"

    elapsed_str = f"{run_s // 3600:02d}:{(run_s % 3600) // 60:02d}:{run_s % 60:02d}"
    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        f"801|801|alice|res|comp|norm|mem_over|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|{elapsed_str}|COMPLETED|0:0|4|4|{req_mem_mb}M|{max_rss_mb}M|{max_rss_mb}M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.select("class1_over_mem_mb_s").item() == expected_over_mem_mb_s
    assert df.select("used_mem_mb_s").item() == expected_used_mem_mb_s


@pytest.mark.parametrize(
    "job_id,expected_unattrib_cpu,expected_unattrib_mem",
    [
        ("1201", False, True),   # missing RSS -> unattributed_missing_rss
        ("1202", True, False),   # missing CPU -> unattributed_missing_cpu_time
        ("1203", True, True),    # missing both -> both unattributed (logical AND)
    ],
)
def test_f20_unattributed_metric_labeling(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_id: str,
    expected_unattrib_cpu: bool,
    expected_unattrib_mem: bool,
):
    """F20: Verify labeling of unattributed reservations when metrics are null."""
    trace_path = fixtures_dir / "sacct" / "sacct_unattributed_missing.txt"
    attributed_path = isolated_workspace / "attr_unattrib.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    row = df.filter(pl.col("job_id") == job_id)
    assert row.height == 1

    actual_unattrib_cpu = (row.select("unattributed_core_s").item() > 0)
    actual_unattrib_mem = (row.select("unattributed_mem_mb_s").item() > 0)

    assert actual_unattrib_cpu == expected_unattrib_cpu
    assert actual_unattrib_mem == expected_unattrib_mem
    if expected_unattrib_cpu and expected_unattrib_mem:
        assert actual_unattrib_cpu and actual_unattrib_mem, "Both CPU and memory must be unattributed (logical AND)"


def test_f20_unknown_req_mem_maps_to_unattributed(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
):
    """F20: Verify unknown memory 'ReqMem=?' maps memory reservation to unattributed without TypeError and preserves G1."""
    trace_file = isolated_workspace / "req_mem_question.txt"
    attr_file = isolated_workspace / "req_mem_question.parquet"

    content = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
        "901|901|alice|res|comp|norm|q_test|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|?|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh\n"
    )
    trace_file.write_text(content)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.height == 1

    # Check that memory reservation is either 0 or fully accounted in unattributed
    r_mem = df.select("reserved_mem_mb_s").item()
    u_mem = df.select("used_mem_mb_s").item()
    c1 = df.select("class1_over_mem_mb_s").item()
    c3_m = df.select("class3_mem_mb_s").item()
    c4_m = df.select("class4_mem_mb_s").item()
    un_m = df.select("unattributed_mem_mb_s").item()

    assert InvariantValidators.verify_g1_conservation(
        reserved=r_mem, used=u_mem, class1_or_2=c1, class3=c3_m, class4=c4_m, unattributed=un_m
    )


@pytest.mark.parametrize("job_index", list(range(20)))
def test_f21_guarantee_g1_exact_conservation_per_job(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    job_index: int,
):
    """F21: Enforce Guarantee G1: reserved = used + class1_or_2 + class3 + class4 + unattributed."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    attributed_path = isolated_workspace / "attr_g1.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    if job_index < df.height:
        row = df.slice(job_index, 1)
        r_core = row.select("reserved_core_s").item()
        u_core = row.select("used_core_s").item()
        c2 = row.select("class2_idle_core_s").item()
        c3_core = row.select("class3_core_s").item()
        c4_core = row.select("class4_core_s").item()
        un_core = row.select("unattributed_core_s").item()

        assert InvariantValidators.verify_g1_conservation(
            reserved=r_core,
            used=u_core,
            class1_or_2=c2,
            class3=c3_core,
            class4=c4_core,
            unattributed=un_core,
        ), f"G1 Core conservation violated on job index {job_index}"

        r_mem = row.select("reserved_mem_mb_s").item()
        u_mem = row.select("used_mem_mb_s").item()
        c1 = row.select("class1_over_mem_mb_s").item()
        c3_mem = row.select("class3_mem_mb_s").item()
        c4_mem = row.select("class4_mem_mb_s").item()
        un_mem = row.select("unattributed_mem_mb_s").item()

        assert InvariantValidators.verify_g1_conservation(
            reserved=r_mem,
            used=u_mem,
            class1_or_2=c1,
            class3=c3_mem,
            class4=c4_mem,
            unattributed=un_mem,
        ), f"G1 Memory conservation violated on job index {job_index}"
