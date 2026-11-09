"""Tier 4 Guarantee Suite: G2 Safety Guardrails Exhaustive Verification.

Mathematical Guarantee G2:
- Memory recommendation is never below observed maximum RSS * 1.0 (strict observed floor)
- Recommended memory includes safety factor headroom (default 1.2 * p99)
- Any group experiencing OUT_OF_MEMORY never receives a decrease (direction = increase to ceil(max * 1.5))
- Groups with sample counts below min_samples receive no recommendation
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "samples,safety_factor",
    [
        ([1000, 2000, 3000, 4000, 5000], 1.2),
        ([500, 1500, 2500, 3500, 4500], 1.2),
        ([2000, 4000, 6000, 8000, 10000], 1.3),
        ([1000, 1000, 1000, 1000, 10000], 1.2),
        ([8000, 8000, 8000, 8000, 8000], 1.5),
        ([5000, 5100, 5200, 5300, 5400], 1.1),
        ([12000, 14000, 16000, 18000, 20000], 1.2),
        ([100, 200, 300, 400, 500], 1.2),
        ([3000, 3200, 3400, 3600, 3800], 1.25),
        ([1500, 1800, 2100, 2400, 2700], 1.4),
        ([6000, 6500, 7000, 7500, 8000], 1.2),
        ([25000, 26000, 27000, 28000, 30000], 1.15),
        ([400, 800, 1200, 1600, 2000], 1.2),
        ([5000, 10000, 15000, 20000, 25000], 1.2),
        ([9000, 9100, 9200, 9300, 9500], 1.3),
    ],
)
def test_guarantee_g2_memory_floor_property(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    samples: list[int],
    safety_factor: float,
):
    """Enforce G2: memory recommendations must strictly exceed or equal observed maximum RSS via recommend CLI."""
    trace_file = isolated_workspace / f"g2_floor_{safety_factor}.txt"
    attr_file = isolated_workspace / f"g2_floor_{safety_factor}.parquet"
    recs_file = isolated_workspace / f"g2_floor_{safety_factor}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i, rss in enumerate(samples):
        row = f"{i}|{i}|alice|res|comp|norm|task|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|40000M|{rss}M|{rss}M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    rec_mem = df.select("recommended_req_mem_mb").item()
    observed_max = max(samples)

    assert InvariantValidators.verify_g2_memory_safety(
        recommended_mem_mb=rec_mem,
        observed_max_rss_mb=observed_max,
        has_oom=False,
        group_sample_size=len(samples),
        min_samples=5,
        safety_factor=safety_factor,
    ), f"G2 Floor violated: rec_mem {rec_mem} < observed_max {observed_max}"


@pytest.mark.parametrize(
    "samples,oom_factor",
    [
        ([2000, 4000, 6000, 8000, 10000], 1.5),
        ([1000, 2000, 3000, 4000, 5000], 1.5),
        ([4000, 4000, 4000, 4000, 4000], 1.8),
        ([16000, 16000, 16000, 16000, 16000], 2.0),
        ([8000, 10000, 12000, 14000, 16000], 1.5),
        ([500, 1000, 1500, 2000, 2500], 1.6),
        ([32000, 34000, 36000, 38000, 40000], 1.5),
        ([7000, 7500, 8000, 8500, 9000], 1.75),
    ],
)
def test_guarantee_g2_oom_escalation_property(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    samples: list[int],
    oom_factor: float,
):
    """Enforce G2: groups with OOM jobs never receive a reduction and scale upward via recommend CLI."""
    trace_file = isolated_workspace / f"g2_oom_{oom_factor}.txt"
    attr_file = isolated_workspace / f"g2_oom_{oom_factor}.parquet"
    recs_file = isolated_workspace / f"g2_oom_{oom_factor}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i, rss in enumerate(samples):
        st = "OUT_OF_MEMORY" if i == len(samples) - 1 else "COMPLETED"
        row = f"{i}|{i}|alice|res|comp|norm|oom_task|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|{st}|0:0|4|4|40000M|{rss}M|{rss}M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    direction = df.select("recommendation_direction").item()
    rec_mem = df.select("recommended_req_mem_mb").item()
    reclaim_gb = df.select("reclaimable_gb_hours").item()

    assert direction == "increase"
    assert reclaim_gb == 0.0

    observed_max = max(samples)
    assert InvariantValidators.verify_g2_memory_safety(
        recommended_mem_mb=rec_mem,
        observed_max_rss_mb=observed_max,
        has_oom=True,
        group_sample_size=len(samples),
        min_samples=5,
    )


@pytest.mark.parametrize(
    "sample_size,min_samples",
    [
        (0, 5),
        (1, 5),
        (2, 5),
        (3, 5),
        (4, 5),
        (0, 10),
        (1, 10),
        (3, 10),
        (5, 10),
        (7, 10),
        (9, 10),
    ],
)
def test_guarantee_g2_min_samples_property(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    sample_size: int,
    min_samples: int,
):
    """Enforce G2: genuine group records with sample_size < min_samples receive no recommendation."""
    trace_file = isolated_workspace / f"g2_sample_{sample_size}_{min_samples}.txt"
    attr_file = isolated_workspace / f"g2_sample_{sample_size}_{min_samples}.parquet"
    recs_file = isolated_workspace / f"g2_sample_{sample_size}_{min_samples}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i in range(sample_size):
        row = f"{i}|{i}|alice|res|comp|norm|small_grp|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    if df.height > 0:
        rec_mem = df.select("recommended_req_mem_mb").item()
        assert rec_mem is None, f"Group with {sample_size} < {min_samples} must receive None, got {rec_mem}"


def test_guarantee_g2_mixed_states_highest_rss_floor(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
):
    """Enforce G2: mixed cohort with completed jobs and high-RSS failed jobs floors at peak RSS across all states."""
    trace_file = isolated_workspace / "g2_mixed.txt"
    attr_file = isolated_workspace / "g2_mixed.parquet"
    recs_file = isolated_workspace / "g2_mixed_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine",
        "1|1|alice|res|comp|norm|mix|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|32000M|4000M|3800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "2|2|alice|res|comp|norm|mix|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|32000M|5000M|4800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "3|3|alice|res|comp|norm|mix|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|32000M|4500M|4200M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "4|4|alice|res|comp|norm|mix|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|32000M|4800M|4600M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
        "5|5|alice|res|comp|norm|mix|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|TIMEOUT|0:0|4|4|32000M|28000M|26000M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh",
    ]
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    rec_mem = df.select("recommended_req_mem_mb").item()
    assert rec_mem >= 28000, f"Recommendation must floor at peak RSS across all states (28000), got {rec_mem}"
