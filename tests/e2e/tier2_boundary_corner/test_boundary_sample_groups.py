"""Tier 2 Boundary and Corner Cases: Boundary Sample Groups.

Verifies rightsizing behavior at exact sample size thresholds:
- Sample threshold step behavior across diverse min_samples settings
- Groups where all jobs failed or suffered OUT_OF_MEMORY
- Mixed cohorts with completed and failed jobs
- Groups with uniform identical usage
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "sample_count,min_samples,should_emit",
    [
        (0, 3, False),
        (1, 3, False),
        (2, 3, False),
        (3, 3, True),
        (4, 3, True),
        (0, 5, False),
        (1, 5, False),
        (2, 5, False),
        (3, 5, False),
        (4, 5, False),
        (5, 5, True),
        (6, 5, True),
        (7, 5, True),
        (8, 5, True),
        (0, 8, False),
        (4, 8, False),
        (7, 8, False),
        (8, 8, True),
        (9, 8, True),
        (0, 10, False),
        (5, 10, False),
        (9, 10, False),
        (10, 10, True),
        (15, 10, True),
        (20, 10, True),
    ],
)
def test_boundary_exact_min_sample_threshold(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    sample_count: int,
    min_samples: int,
    should_emit: bool,
):
    """Verify recommendation generation strictly toggles at the min_samples boundary via recommend CLI."""
    trace_file = isolated_workspace / f"thresh_{sample_count}_{min_samples}.txt"
    attr_file = isolated_workspace / f"thresh_{sample_count}_{min_samples}.parquet"
    recs_file = isolated_workspace / f"thresh_{sample_count}_{min_samples}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i in range(sample_count):
        row = f"{i}|{i}|alice|res|comp|norm|task|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    if df.height > 0:
        rec_mem = df.select("recommended_req_mem_mb").item()
        assert (rec_mem is not None) == should_emit
    else:
        assert not should_emit


@pytest.mark.parametrize("identical_val", [1000, 2000, 4000, 8000, 16000, 32000])
def test_boundary_uniform_usage_rightsizing(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    identical_val: int,
):
    """Verify rightsizing calculation on groups where all jobs report identical RSS via recommend CLI."""
    trace_file = isolated_workspace / f"unif_{identical_val}.txt"
    attr_file = isolated_workspace / f"unif_{identical_val}.parquet"
    recs_file = isolated_workspace / f"unif_{identical_val}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i in range(6):
        row = f"{i}|{i}|alice|res|comp|norm|task|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|40000M|{identical_val}M|{identical_val}M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    rec_mem = df.select("recommended_req_mem_mb").item()
    assert rec_mem >= identical_val


@pytest.mark.parametrize("failed_state", ["FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED"])
def test_boundary_all_failed_group_no_completed_samples(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    failed_state: str,
):
    """Verify group containing exclusively failed jobs handles rightsizing gracefully via recommend CLI."""
    trace_file = isolated_workspace / f"failed_{failed_state}.txt"
    attr_file = isolated_workspace / f"failed_{failed_state}.parquet"
    recs_file = isolated_workspace / f"failed_{failed_state}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i in range(6):
        row = f"{i}|{i}|alice|res|comp|norm|fail_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|{failed_state}|1:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    if failed_state == "OUT_OF_MEMORY":
        row = df.filter(pl.col("group") == "alice/fail_job")
        assert row.select("recommendation_direction").item() == "increase"
        assert row.select("reclaimable_gb_hours").item() == 0.0


def test_boundary_mixed_cohort_floor_preservation(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
):
    """Verify mixed cohort (COMPLETED jobs with moderate RSS + TIMEOUT job with high RSS) floors at observed maximum."""
    trace_file = isolated_workspace / "mixed_cohort.txt"
    attr_file = isolated_workspace / "mixed_cohort.parquet"
    recs_file = isolated_workspace / "mixed_cohort_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine",
        "1|1|alice|res|comp|norm|mixed_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|16000M|4000M|3800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "2|2|alice|res|comp|norm|mixed_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|16000M|4200M|4000M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "3|3|alice|res|comp|norm|mixed_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|16000M|3900M|3700M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "4|4|alice|res|comp|norm|mixed_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|16000M|4100M|3900M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "5|5|alice|res|comp|norm|mixed_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|TIMEOUT|0:0|4|4|16000M|12000M|11000M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
    ]
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    row = df.filter(pl.col("group") == "alice/mixed_job")
    rec_mem = row.select("recommended_req_mem_mb").item()
    assert rec_mem >= 12000, f"Recommendation must floor at observed maximum across states (12000), got {rec_mem}"
