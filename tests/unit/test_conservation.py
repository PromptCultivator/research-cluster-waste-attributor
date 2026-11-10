"""Guarantee G1 conservation test suite across standard fixtures and a 20,000-job trace.

Verifies that for every job and cluster aggregate, reserved resources equal
utilized resources plus attributed waste classes plus unattributed allocations
with exact integer conservation and zero double counting.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf
from rcwa.attribute import attribute_trace

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _verify_dataframe_g1(df: pl.DataFrame) -> None:
    """Verify Guarantee G1 invariants on every row and in cluster aggregate."""
    assert df.height > 0

    # Non-negativity check
    check_cols = [
        "reserved_core_s",
        "used_core_s",
        "class2_idle_core_s",
        "class3_core_s",
        "class4_core_s",
        "unattributed_core_s",
        "reserved_mem_mb_s",
        "used_mem_mb_s",
        "class1_over_mem_mb_s",
        "class3_mem_mb_s",
        "class4_mem_mb_s",
        "unattributed_mem_mb_s",
    ]
    for c in check_cols:
        min_val = df.select(pl.col(c).min()).item()
        assert (
            min_val is not None and min_val >= 0
        ), f"Column {c} contains negative value: {min_val}"

    # Row-by-row conservation
    core_sum_expr = (
        pl.col("used_core_s")
        + pl.col("class2_idle_core_s")
        + pl.col("class3_core_s")
        + pl.col("class4_core_s")
        + pl.col("unattributed_core_s")
    )
    core_diff = df.select((pl.col("reserved_core_s") - core_sum_expr).abs().max()).item()
    assert core_diff == 0, f"Core conservation violated on rows: max diff = {core_diff}"

    mem_sum_expr = (
        pl.col("used_mem_mb_s")
        + pl.col("class1_over_mem_mb_s")
        + pl.col("class3_mem_mb_s")
        + pl.col("class4_mem_mb_s")
        + pl.col("unattributed_mem_mb_s")
    )
    mem_diff = df.select((pl.col("reserved_mem_mb_s") - mem_sum_expr).abs().max()).item()
    assert mem_diff == 0, f"Memory conservation violated on rows: max diff = {mem_diff}"

    # Aggregate trace-level conservation
    tot_res_core = df.select(pl.col("reserved_core_s").sum()).item()
    tot_used_core = df.select(pl.col("used_core_s").sum()).item()
    tot_c2 = df.select(pl.col("class2_idle_core_s").sum()).item()
    tot_c3_core = df.select(pl.col("class3_core_s").sum()).item()
    tot_c4_core = df.select(pl.col("class4_core_s").sum()).item()
    tot_un_core = df.select(pl.col("unattributed_core_s").sum()).item()

    assert tot_res_core == (tot_used_core + tot_c2 + tot_c3_core + tot_c4_core + tot_un_core)

    tot_res_mem = df.select(pl.col("reserved_mem_mb_s").sum()).item()
    tot_used_mem = df.select(pl.col("used_mem_mb_s").sum()).item()
    tot_c1 = df.select(pl.col("class1_over_mem_mb_s").sum()).item()
    tot_c3_mem = df.select(pl.col("class3_mem_mb_s").sum()).item()
    tot_c4_mem = df.select(pl.col("class4_mem_mb_s").sum()).item()
    tot_un_mem = df.select(pl.col("unattributed_mem_mb_s").sum()).item()

    assert tot_res_mem == (tot_used_mem + tot_c1 + tot_c3_mem + tot_c4_mem + tot_un_mem)


@pytest.mark.parametrize(
    "fixture_rel_path,parser",
    [
        ("sacct/sacct_standard_26col.txt", parse_sacct),
        ("sacct/multiday_cluster.txt", parse_sacct),
        ("sacct/sacct_durations_states.txt", parse_sacct),
        ("sacct/sacct_unattributed_missing.txt", parse_sacct),
        ("swf/standard_with_headers.swf", parse_swf),
        ("swf/sample_workload.swf", parse_swf),
        ("swf/status_variations.swf", parse_swf),
        ("swf/missing_fields.swf", parse_swf),
    ],
)
def test_guarantee_g1_on_fixtures(fixture_rel_path: str, parser) -> None:
    """Verify Guarantee G1 exact conservation across all committed test fixtures."""
    path = FIXTURES_DIR / fixture_rel_path
    canonical_df = parser(path)
    attr_df = attribute_trace(canonical_df)
    _verify_dataframe_g1(attr_df)


def test_guarantee_g1_on_20k_synthetic_trace() -> None:
    """Verify Guarantee G1 holds exactly across a comprehensive 20,000-row synthetic trace."""
    n_jobs = 20000
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    all_states = [
        "COMPLETED",
        "FAILED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "CANCELLED",
        "PREEMPTED",
        "RUNNING",
        "PENDING",
        "OTHER",
    ]

    job_ids = [str(i) for i in range(1, n_jobs + 1)]
    users = [f"user_{i % 50}" for i in range(n_jobs)]
    accounts = [f"acc_{i % 10}" for i in range(n_jobs)]
    partitions = [f"part_{i % 4}" for i in range(n_jobs)]
    job_names = [f"task_{i % 100}" for i in range(n_jobs)]

    # Distribute command and input hashes to generate recomputations
    cmd_hashes = [f"cmd_{i % 200}" if (i % 5 != 0) else None for i in range(n_jobs)]
    inp_hashes = [f"inp_{i % 50}" if (i % 3 != 0) else None for i in range(n_jobs)]

    # Cycle states systematically across all 10 canonical states
    states = [all_states[i % len(all_states)] for i in range(n_jobs)]

    # Generate run_s with mix of 0s, short runs (<=60s), and long runs
    run_s_list = []
    for i in range(n_jobs):
        mod = i % 10
        if mod == 0:
            run_s_list.append(0)
        elif mod == 1:
            run_s_list.append(15)
        elif mod == 2:
            run_s_list.append(45)
        elif mod == 3:
            run_s_list.append(60)
        else:
            run_s_list.append((i % 3600) + 120)

    wait_s_list = [(i % 600) for i in range(n_jobs)]
    alloc_cpus_list = [((i % 8) + 1) for i in range(n_jobs)]
    req_cpus_list = alloc_cpus_list

    # Compute timestamps
    submit_times = [base_time + timedelta(seconds=i * 10) for i in range(n_jobs)]
    start_times = [submit_times[i] + timedelta(seconds=wait_s_list[i]) for i in range(n_jobs)]
    end_times = [start_times[i] + timedelta(seconds=run_s_list[i]) for i in range(n_jobs)]

    # CPU usage: include nulls and various utilization ratios
    cpu_time_used_list: list[float | None] = []
    for i in range(n_jobs):
        if i % 17 == 0:
            cpu_time_used_list.append(None)
        else:
            alloc_c = alloc_cpus_list[i]
            r_s = run_s_list[i]
            util_ratio = ((i % 10) + 1) / 10.0
            cpu_time_used_list.append(float(alloc_c * r_s * util_ratio))

    # Memory: include nulls, over-requests, and peak RSS
    req_mem_mb_list: list[int | None] = []
    max_rss_mb_list: list[int | None] = []
    for i in range(n_jobs):
        if i % 19 == 0:
            req_mem_mb_list.append(None)
            max_rss_mb_list.append(None)
        else:
            req_mb = ((i % 16) + 1) * 1024
            req_mem_mb_list.append(req_mb)
            if i % 23 == 0:
                max_rss_mb_list.append(None)
            else:
                max_rss_mb_list.append(int(req_mb * (((i % 8) + 1) / 10.0)))

    # Compute reservations
    reserved_core_s_list = [alloc_cpus_list[i] * run_s_list[i] for i in range(n_jobs)]
    reserved_mem_mb_s_list = [
        (req_mem_mb_list[i] * run_s_list[i] if req_mem_mb_list[i] is not None else None)
        for i in range(n_jobs)
    ]

    df = pl.DataFrame(
        {
            "job_id": job_ids,
            "parent_job_id": [None if i % 10 != 0 else str(i // 10) for i in range(n_jobs)],
            "source": ["sacct"] * n_jobs,
            "user": users,
            "account": accounts,
            "partition": partitions,
            "job_name": job_names,
            "command_hash": cmd_hashes,
            "input_hash": inp_hashes,
            "submit_time": submit_times,
            "start_time": start_times,
            "end_time": end_times,
            "wait_s": wait_s_list,
            "run_s": run_s_list,
            "state": states,
            "exit_code": [0 if (i % 2 == 0) else 1 for i in range(n_jobs)],
            "req_cpus": req_cpus_list,
            "alloc_cpus": alloc_cpus_list,
            "cpu_time_used_s": cpu_time_used_list,
            "req_mem_mb": req_mem_mb_list,
            "max_rss_mb": max_rss_mb_list,
            "req_gpus": [0] * n_jobs,
            "alloc_gpus": [0] * n_jobs,
            "nodes": [1] * n_jobs,
            "node_list": ["node1"] * n_jobs,
            "reserved_core_s": reserved_core_s_list,
            "reserved_mem_mb_s": reserved_mem_mb_s_list,
        }
    )

    attr_df = attribute_trace(df)

    # RUNNING and PENDING rows must be filtered out (2 out of 10 states)
    # Expected remaining rows: 20000 * 8 / 10 = 16000
    assert attr_df.height == 16000

    # Enforce Guarantee G1 across all 16,000 non-running/non-pending jobs
    _verify_dataframe_g1(attr_df)
