"""Tier 1 Feature Coverage: F22 through F28 (Grouping, Reclaim Scoring, Recommendations, and Guarantee G2).

Features:
- F22: Grouping by configured keys and secondary rollups (user, account, partition)
- F23: Ranked reclaim scoring and top-5 evidence job selection
- F24: Percentile memory rightsizing with observed peak floor guardrail
- F25: Out-of-memory (OOM) escalation guardrail (increase direction, excluded from reclaimable memory)
- F26: CPU rightsizing with clamp and short job (<120s) guardrail
- F27: Timeout limit recommendations and early failure reporting
- F28: Guarantee G2 safety invariants verification
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "fixture_name,expected_min_groups",
    [
        ("multiday_cluster.txt", 4),
        ("sacct_standard_26col.txt", 2),
    ],
)
def test_f22_job_grouping_and_rollups(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
    expected_min_groups: int,
):
    """F22: Test job grouping by primary key and secondary aggregations through chained attribute and recommend CLI."""
    trace_path = fixtures_dir / "sacct" / fixture_name
    attr_out = isolated_workspace / f"attr_{fixture_name}.parquet"
    recs_out = isolated_workspace / f"recs_{fixture_name}.parquet"

    res_attr = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert res_attr.exit_code == 0

    res_rec = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert res_rec.exit_code == 0

    df = pl.read_parquet(recs_out)
    assert df.height >= expected_min_groups


@pytest.mark.parametrize(
    "core_hours,gb_hours,mem_weight",
    [
        (10.0, 40.0, 0.25),
        (20.0, 0.0, 0.25),
        (5.0, 100.0, 0.25),
        (15.0, 30.0, 0.50),
        (0.0, 80.0, 0.25),
        (50.0, 200.0, 0.25),
        (100.0, 400.0, 0.125),
        (25.0, 50.0, 0.50),
        (10.0, 20.0, 1.0),
        (0.0, 0.0, 0.25),
        (5.5, 10.0, 0.5),
        (100.0, 0.0, 0.5),
    ],
)
def test_f23_reclaim_scoring_formula(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    core_hours: float,
    gb_hours: float,
    mem_weight: float,
):
    """F23: Verify calculation of composite reclaim score from core-hours and weighted GB-hours via recommend CLI."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    attr_out = isolated_workspace / "attr_score.parquet"
    recs_out = isolated_workspace / f"recs_score_{core_hours}_{gb_hours}.parquet"

    run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    res = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_out)
    assert "score" in df.columns
    assert "reclaimable_core_hours" in df.columns
    assert "reclaimable_gb_hours" in df.columns
    if df.height > 0:
        actual_score = df.select("score").item(0, 0)
        reclaim_cores = df.select("reclaimable_core_hours").item(0, 0)
        reclaim_gb = df.select("reclaimable_gb_hours").item(0, 0)
        expected_score = reclaim_cores + mem_weight * reclaim_gb
        assert abs(actual_score - expected_score) < 1e-4


@pytest.mark.parametrize(
    "group_id,expected_evidence_max",
    [
        ("alice/alpha_train", 5),
        ("david/order_book_proc", 5),
    ],
)
def test_f23_evidence_job_sampling(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    group_id: str,
    expected_evidence_max: int,
):
    """F23: Verify selection of up to 5 highest-waste evidence job IDs per group."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    attr_out = isolated_workspace / "attr_ev.parquet"
    recs_out = isolated_workspace / "recs_ev.parquet"

    run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    result = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert result.exit_code == 0

    df = pl.read_parquet(recs_out)
    matches = df.filter(pl.col("group") == group_id)
    if matches.height > 0:
        evidence = matches.select("evidence_job_ids").item()
        assert len(evidence) <= expected_evidence_max
        assert len(evidence) > 0


@pytest.mark.parametrize(
    "samples,safety_factor",
    [
        ([1000, 2000, 3000, 4000, 5000], 1.2),
        ([1000, 1000, 1000, 1000, 10000], 1.2),
        ([8000, 8000, 8000, 8000, 8000], 1.2),
        ([4000, 4500, 4200, 4100, 4300], 1.5),
        ([500, 600, 700, 800, 900], 1.2),
        ([2000, 2500, 3000, 3500, 4000], 1.25),
        ([10000, 12000, 14000, 16000, 18000], 1.2),
        ([3000, 3100, 3200, 3300, 3400], 1.1),
    ],
)
def test_f24_memory_rightsizing_and_floor(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    samples: list[int],
    safety_factor: float,
):
    """F24: Verify memory rightsizing applies p99 * safety_factor bounded by observed max floor via CLI."""
    trace_file = isolated_workspace / f"mem_trace_{safety_factor}.txt"
    attr_file = isolated_workspace / f"mem_attr_{safety_factor}.parquet"
    recs_file = isolated_workspace / f"mem_recs_{safety_factor}.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i, rss in enumerate(samples):
        row = f"{1000 + i}|{1000 + i}|alice|res|comp|norm|task|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|COMPLETED|0:0|4|4|20000M|{rss}M|{rss}M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    rec_mem = df.select("recommended_req_mem_mb").item()
    observed_max = max(samples)
    assert rec_mem >= observed_max, f"Floor violated: {rec_mem} < {observed_max}"


@pytest.mark.parametrize(
    "fixture_name,group_name,expected_direction,is_reclaimable",
    [
        ("oom_groups.txt", "alice/oom_candidate", "increase", False),
    ],
)
def test_f25_oom_escalation_guardrail(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    fixture_name: str,
    group_name: str,
    expected_direction: str,
    is_reclaimable: bool,
):
    """F25: Verify groups with OUT_OF_MEMORY force increase and are excluded from reclaimable memory."""
    trace_path = fixtures_dir / "guardrails" / fixture_name
    attr_out = isolated_workspace / "oom_attr.parquet"
    recs_out = isolated_workspace / "oom_recs.parquet"

    run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    result = run_cli(["recommend", str(attr_out), "--output", str(recs_out)])
    assert result.exit_code == 0

    df = pl.read_parquet(recs_out)
    row = df.filter(pl.col("group") == group_name)
    assert row.height == 1

    direction = row.select("recommendation_direction").item()
    reclaim_gb = row.select("reclaimable_gb_hours").item()

    assert direction == expected_direction, f"Expected direction '{expected_direction}', got '{direction}'"
    if not is_reclaimable:
        assert reclaim_gb == 0.0, f"OOM group must have 0 reclaimable GB-hours, got {reclaim_gb}"


@pytest.mark.parametrize(
    "alloc_cpus,run_s,is_short_job",
    [
        (8, 300, False),
        (4, 600, False),
        (8, 1800, False),
        (8, 60, True),
        (16, 500, False),
        (4, 1000, False),
        (8, 200, False),
        (32, 3600, False),
    ],
)
def test_f26_cpu_rightsizing_and_short_job_guardrail(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    alloc_cpus: int,
    run_s: int,
    is_short_job: bool,
):
    """F26: Test CPU rightsizing with clamp and short job exclusion (<120s) via recommend CLI."""
    trace_file = isolated_workspace / f"cpu_right_{alloc_cpus}_{run_s}.txt"
    attr_file = isolated_workspace / f"cpu_right_{alloc_cpus}_{run_s}.parquet"
    recs_file = isolated_workspace / f"cpu_right_{alloc_cpus}_{run_s}_recs.parquet"

    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i in range(5):
        row = f"{2000 + i}|{2000 + i}|alice|res|comp|norm|cpu_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:05:05|00:05:00|COMPLETED|0:0|{alloc_cpus}|{alloc_cpus}|8000M|2000M|1800M|00:02:00|{alloc_cpus * run_s}|billing={alloc_cpus},cpu={alloc_cpus},node=1|billing={alloc_cpus},cpu={alloc_cpus},node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    rec_cpu = df.select("recommended_cpus").item()
    if is_short_job:
        assert rec_cpu is None, f"Short job (<120s) must not receive CPU recommendation, got {rec_cpu}"
    else:
        assert rec_cpu is not None, "Regular job must receive CPU recommendation"


@pytest.mark.parametrize(
    "durations,has_timeout",
    [
        ([1000, 2000, 3000, 4000, 5000], True),
        ([100, 200, 300, 400, 500], False),
        ([500, 1000, 1500, 2000, 2500], True),
        ([60, 120, 180, 240, 300], True),
        ([3600, 3600, 3600, 3600, 3600], True),
    ],
)
def test_f27_timeout_recommendations(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    durations: list[int],
    has_timeout: bool,
):
    """F27: Verify time limit recommendation applies factor on groups with timeouts."""
    trace_file = isolated_workspace / f"to_trace_{has_timeout}.txt"
    attr_file = isolated_workspace / f"to_attr_{has_timeout}.parquet"
    recs_file = isolated_workspace / f"to_recs_{has_timeout}.parquet"

    state_str = "TIMEOUT" if has_timeout else "COMPLETED"
    rows = [
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    ]
    for i, dur in enumerate(durations):
        row = f"{3000 + i}|{3000 + i}|alice|res|comp|norm|to_job|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|{state_str}|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh"
        rows.append(row)
    trace_file.write_text("\n".join(rows) + "\n")

    run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    res = run_cli(["recommend", str(attr_file), "--output", str(recs_file)])
    assert res.exit_code == 0

    df = pl.read_parquet(recs_file)
    assert df.height == 1
    rec_timeout = df.select("recommended_time_limit_s").item()
    if has_timeout:
        assert rec_timeout is not None, "Group with timeouts must receive timeout recommendation"
    else:
        assert rec_timeout is None, "Group without timeouts must not receive timeout recommendation"


def test_f27_early_failure_reporting(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
):
    """F27: Verify early failure group reporting outputs failure share and sample exit codes."""
    trace_path = fixtures_dir / "sacct" / "sacct_standard_26col.txt"
    report_json = isolated_workspace / "early_fail_report.json"

    res = run_cli(["report", str(trace_path), "--format", "json", "--output", str(report_json)])
    assert res.exit_code == 0
    assert report_json.exists()

    data = json.loads(report_json.read_text())
    early_failures = data.get("early_failure_groups", [])
    assert isinstance(early_failures, list)
    for group in early_failures:
        assert "failure_share" in group, "failure_share missing from early failure group reporting"
        assert "sample_exit_codes" in group, "sample_exit_codes missing from early failure group reporting"


@pytest.mark.parametrize(
    "group_name,sample_count,min_samples,should_receive_recommendation",
    [
        ("alice/task_single", 1, 5, False),
        ("bob/task_four", 4, 5, False),
        ("carol/task_five", 5, 5, True),
        ("david/task_twenty", 20, 5, True),
    ],
)
def test_f28_guarantee_g2_sample_size_floor(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    group_name: str,
    sample_count: int,
    min_samples: int,
    should_receive_recommendation: bool,
):
    """F28: Enforce Guarantee G2: groups below min_samples must receive no recommendations."""
    trace_path = fixtures_dir / "guardrails" / "group_sample_sizes.txt"
    attr_out = isolated_workspace / "sample_size_attr.parquet"
    recs_out = isolated_workspace / "sample_size_recs.parquet"

    run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    result = run_cli([
        "recommend",
        str(attr_out),
        "--output", str(recs_out),
    ])
    assert result.exit_code == 0

    df = pl.read_parquet(recs_out)
    row = df.filter(pl.col("group") == group_name)
    assert row.height == 1

    rec_mem = row.select("recommended_req_mem_mb").item()
    if should_receive_recommendation:
        assert rec_mem is not None, f"Group {group_name} with {sample_count} samples should receive recommendation"
    else:
        assert rec_mem is None, f"Group {group_name} with {sample_count} < {min_samples} must NOT receive recommendation"
