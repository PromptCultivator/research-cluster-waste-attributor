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


def test_guarantee_g1_null_metrics() -> None:
    """Verify Guarantee G1 when cpu_time_used_s, max_rss_mb, or req_mem_mb are null."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    # Job 1: Null cpu_time_used_s -> 100% unattributed core reservation without drift
    # Job 2: Null max_rss_mb -> 100% unattributed memory reservation without drift
    # Job 3: Null req_mem_mb -> normalized to 0 reservation, 0 consumption
    df = pl.DataFrame(
        {
            "job_id": ["null_cpu", "null_rss", "null_req_mem"],
            "parent_job_id": [None, None, None],
            "source": ["sacct", "sacct", "sacct"],
            "user": ["user_a", "user_b", "user_c"],
            "account": ["acc", "acc", "acc"],
            "partition": ["part", "part", "part"],
            "job_name": ["job_a", "job_b", "job_c"],
            "command_hash": ["cmd_a", "cmd_b", "cmd_c"],
            "input_hash": ["inp_a", "inp_b", "inp_c"],
            "submit_time": [base_time, base_time, base_time],
            "start_time": [base_time, base_time, base_time],
            "end_time": [
                base_time + timedelta(seconds=100),
                base_time + timedelta(seconds=100),
                base_time + timedelta(seconds=100),
            ],
            "wait_s": [0, 0, 0],
            "run_s": [100, 100, 100],
            "state": ["COMPLETED", "COMPLETED", "COMPLETED"],
            "exit_code": [0, 0, 0],
            "req_cpus": [4, 4, 4],
            "alloc_cpus": [4, 4, 4],
            "cpu_time_used_s": [None, 300.0, 200.0],
            "req_mem_mb": [4000, 4000, None],
            "max_rss_mb": [2000, None, None],
            "req_gpus": [0, 0, 0],
            "alloc_gpus": [0, 0, 0],
            "nodes": [1, 1, 1],
            "node_list": ["node1", "node1", "node1"],
            "reserved_core_s": [400, 400, 400],
            "reserved_mem_mb_s": [400000, 400000, None],
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)

    # Job null_cpu assertions
    row_cpu = attr_df.filter(pl.col("job_id") == "null_cpu")
    assert row_cpu.select("unattributed_core_s").item() == 400
    assert row_cpu.select("used_core_s").item() == 0
    assert row_cpu.select("class2_idle_core_s").item() == 0

    # Job null_rss assertions
    row_rss = attr_df.filter(pl.col("job_id") == "null_rss")
    assert row_rss.select("unattributed_mem_mb_s").item() == 400000
    assert row_rss.select("used_mem_mb_s").item() == 0
    assert row_rss.select("class1_over_mem_mb_s").item() == 0

    # Job null_req_mem assertions: 0 == 0 + 0 + 0 + 0 + 0
    row_mem = attr_df.filter(pl.col("job_id") == "null_req_mem")
    assert row_mem.select("reserved_mem_mb_s").item() == 0
    assert row_mem.select("used_mem_mb_s").item() == 0
    assert row_mem.select("class1_over_mem_mb_s").item() == 0
    assert row_mem.select("unattributed_mem_mb_s").item() == 0


def test_guarantee_g1_zero_run_s() -> None:
    """Verify jobs with run_s = 0 are attributed to Class 3 early failure with zero consumption."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    df = pl.DataFrame(
        {
            "job_id": ["z_fail", "z_comp", "z_canc"],
            "parent_job_id": [None, None, None],
            "source": ["sacct", "sacct", "sacct"],
            "user": ["u1", "u1", "u1"],
            "account": ["acc", "acc", "acc"],
            "partition": ["part", "part", "part"],
            "job_name": ["j1", "j2", "j3"],
            "command_hash": ["cmd1", "cmd2", "cmd3"],
            "input_hash": ["inp1", "inp2", "inp3"],
            "submit_time": [base_time, base_time, base_time],
            "start_time": [base_time, base_time, base_time],
            "end_time": [base_time, base_time, base_time],
            "wait_s": [0, 0, 0],
            "run_s": [0, 0, 0],
            "state": ["FAILED", "COMPLETED", "CANCELLED"],
            "exit_code": [1, 0, 0],
            "req_cpus": [8, 8, 8],
            "alloc_cpus": [8, 8, 8],
            "cpu_time_used_s": [0.0, 0.0, 0.0],
            "req_mem_mb": [16000, 16000, 16000],
            "max_rss_mb": [0, 0, 0],
            "req_gpus": [0, 0, 0],
            "alloc_gpus": [0, 0, 0],
            "nodes": [1, 1, 1],
            "node_list": ["node1", "node1", "node1"],
            "reserved_core_s": [0, 0, 0],
            "reserved_mem_mb_s": [0, 0, 0],
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)

    for row in attr_df.to_dicts():
        assert row["class3_sub_label"] == "early_failure"
        assert row["class3_core_s"] == 0
        assert row["class3_mem_mb_s"] == 0
        assert row["used_core_s"] == 0
        assert row["used_mem_mb_s"] == 0
        assert row["reserved_core_s"] == 0
        assert row["reserved_mem_mb_s"] == 0


def test_guarantee_g1_float_rounding() -> None:
    """Verify float rounding in cpu_time_used_s preserves exact conservation and non-negativity."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    float_values = [0.49, 0.50, 0.51, 99.49, 99.50, 99.51, 99.999, 0.001, 100.49, 100.51]

    df = pl.DataFrame(
        {
            "job_id": [f"flt_{i}" for i in range(len(float_values))],
            "parent_job_id": [None] * len(float_values),
            "source": ["sacct"] * len(float_values),
            "user": ["u1"] * len(float_values),
            "account": ["acc"] * len(float_values),
            "partition": ["part"] * len(float_values),
            "job_name": ["job"] * len(float_values),
            "command_hash": [f"c_{i}" for i in range(len(float_values))],
            "input_hash": [f"i_{i}" for i in range(len(float_values))],
            "submit_time": [base_time] * len(float_values),
            "start_time": [base_time] * len(float_values),
            "end_time": [base_time + timedelta(seconds=100)] * len(float_values),
            "wait_s": [0] * len(float_values),
            "run_s": [100] * len(float_values),
            "state": ["COMPLETED"] * len(float_values),
            "exit_code": [0] * len(float_values),
            "req_cpus": [1] * len(float_values),
            "alloc_cpus": [1] * len(float_values),
            "cpu_time_used_s": float_values,
            "req_mem_mb": [1000] * len(float_values),
            "max_rss_mb": [500] * len(float_values),
            "req_gpus": [0] * len(float_values),
            "alloc_gpus": [0] * len(float_values),
            "nodes": [1] * len(float_values),
            "node_list": ["node1"] * len(float_values),
            "reserved_core_s": [100] * len(float_values),
            "reserved_mem_mb_s": [100000] * len(float_values),
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)


def test_guarantee_g1_multithreading_and_memory_burst() -> None:
    """Verify used resources clamp to reservation and idle/over stay non-negative during burst spikes."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    df = pl.DataFrame(
        {
            "job_id": ["cpu_burst", "mem_burst", "both_burst"],
            "parent_job_id": [None, None, None],
            "source": ["sacct", "sacct", "sacct"],
            "user": ["u1", "u1", "u1"],
            "account": ["acc", "acc", "acc"],
            "partition": ["part", "part", "part"],
            "job_name": ["j1", "j2", "j3"],
            "command_hash": ["cmd1", "cmd2", "cmd3"],
            "input_hash": ["inp1", "inp2", "inp3"],
            "submit_time": [base_time, base_time, base_time],
            "start_time": [base_time, base_time, base_time],
            "end_time": [
                base_time + timedelta(seconds=10),
                base_time + timedelta(seconds=10),
                base_time + timedelta(seconds=10),
            ],
            "wait_s": [0, 0, 0],
            "run_s": [10, 10, 10],
            "state": ["COMPLETED", "COMPLETED", "COMPLETED"],
            "exit_code": [0, 0, 0],
            "req_cpus": [2, 2, 2],
            "alloc_cpus": [2, 2, 2],
            "cpu_time_used_s": [50.0, 10.0, 100.0],  # 50 > 20 reserved, 100 > 20 reserved
            "req_mem_mb": [1000, 1000, 1000],
            "max_rss_mb": [500, 2500, 5000],  # 2500 > 1000 requested, 5000 > 1000 requested
            "req_gpus": [0, 0, 0],
            "alloc_gpus": [0, 0, 0],
            "nodes": [1, 1, 1],
            "node_list": ["node1", "node1", "node1"],
            "reserved_core_s": [20, 20, 20],
            "reserved_mem_mb_s": [10000, 10000, 10000],
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)

    for row in attr_df.to_dicts():
        assert row["used_core_s"] <= row["reserved_core_s"]
        assert row["class2_idle_core_s"] >= 0
        assert row["used_core_s"] + row["class2_idle_core_s"] == row["reserved_core_s"]
        assert row["used_mem_mb_s"] <= row["reserved_mem_mb_s"]
        assert row["class1_over_mem_mb_s"] >= 0
        assert row["used_mem_mb_s"] + row["class1_over_mem_mb_s"] == row["reserved_mem_mb_s"]


def test_guarantee_g1_early_failure_threshold_boundary() -> None:
    """Verify sub-label classification across the 60s vs 61s early failure boundary."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    df = pl.DataFrame(
        {
            "job_id": [
                "fail_60",
                "fail_61",
                "oom_60",
                "oom_61",
                "timeout_60",
                "timeout_61",
                "canc_60",
                "canc_61",
            ],
            "parent_job_id": [None] * 8,
            "source": ["sacct"] * 8,
            "user": ["u1"] * 8,
            "account": ["acc"] * 8,
            "partition": ["part"] * 8,
            "job_name": ["job"] * 8,
            "command_hash": [f"c_{i}" for i in range(8)],
            "input_hash": [f"i_{i}" for i in range(8)],
            "submit_time": [base_time] * 8,
            "start_time": [base_time] * 8,
            "end_time": [base_time + timedelta(seconds=60 if i % 2 == 0 else 61) for i in range(8)],
            "wait_s": [0] * 8,
            "run_s": [60, 61, 60, 61, 60, 61, 60, 61],
            "state": [
                "FAILED",
                "FAILED",
                "OUT_OF_MEMORY",
                "OUT_OF_MEMORY",
                "TIMEOUT",
                "TIMEOUT",
                "CANCELLED",
                "CANCELLED",
            ],
            "exit_code": [1, 1, 125, 125, 0, 0, 0, 0],
            "req_cpus": [2] * 8,
            "alloc_cpus": [2] * 8,
            "cpu_time_used_s": [10.0] * 8,
            "req_mem_mb": [1000] * 8,
            "max_rss_mb": [500] * 8,
            "req_gpus": [0] * 8,
            "alloc_gpus": [0] * 8,
            "nodes": [1] * 8,
            "node_list": ["node1"] * 8,
            "reserved_core_s": [120, 122, 120, 122, 120, 122, 120, 122],
            "reserved_mem_mb_s": [60000, 61000, 60000, 61000, 60000, 61000, 60000, 61000],
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)

    expected_labels = {
        "fail_60": "early_failure",
        "fail_61": "other_failure",
        "oom_60": "early_failure",
        "oom_61": "oom",
        "timeout_60": "early_failure",
        "timeout_61": "timeout",
        "canc_60": "early_failure",
        "canc_61": "cancelled_after_start",
    }
    for jid, label in expected_labels.items():
        assert attr_df.filter(pl.col("job_id") == jid).select("class3_sub_label").item() == label


def test_guarantee_g1_cancelled_boundary() -> None:
    """Verify CANCELLED jobs across run_s = 0, short duration, and long duration."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    df = pl.DataFrame(
        {
            "job_id": ["canc_zero", "canc_short", "canc_long"],
            "parent_job_id": [None, None, None],
            "source": ["sacct", "sacct", "sacct"],
            "user": ["u1", "u1", "u1"],
            "account": ["acc", "acc", "acc"],
            "partition": ["part", "part", "part"],
            "job_name": ["job", "job", "job"],
            "command_hash": ["c1", "c2", "c3"],
            "input_hash": ["i1", "i2", "i3"],
            "submit_time": [base_time, base_time, base_time],
            "start_time": [base_time, base_time, base_time],
            "end_time": [
                base_time,
                base_time + timedelta(seconds=15),
                base_time + timedelta(seconds=300),
            ],
            "wait_s": [0, 0, 0],
            "run_s": [0, 15, 300],
            "state": ["CANCELLED", "CANCELLED", "CANCELLED"],
            "exit_code": [0, 0, 0],
            "req_cpus": [4, 4, 4],
            "alloc_cpus": [4, 4, 4],
            "cpu_time_used_s": [0.0, 10.0, 100.0],
            "req_mem_mb": [2000, 2000, 2000],
            "max_rss_mb": [0, 500, 1000],
            "req_gpus": [0, 0, 0],
            "alloc_gpus": [0, 0, 0],
            "nodes": [1, 1, 1],
            "node_list": ["node1", "node1", "node1"],
            "reserved_core_s": [0, 60, 1200],
            "reserved_mem_mb_s": [0, 30000, 600000],
        }
    )

    attr_df = attribute_trace(df)
    _verify_dataframe_g1(attr_df)

    row_zero = attr_df.filter(pl.col("job_id") == "canc_zero")
    assert row_zero.select("class3_sub_label").item() == "early_failure"
    assert row_zero.select("class3_core_s").item() == 0
    assert row_zero.select("reserved_core_s").item() == 0

    row_short = attr_df.filter(pl.col("job_id") == "canc_short")
    assert row_short.select("class3_sub_label").item() == "early_failure"
    assert row_short.select("class3_core_s").item() == 60

    row_long = attr_df.filter(pl.col("job_id") == "canc_long")
    assert row_long.select("class3_sub_label").item() == "cancelled_after_start"
    assert row_long.select("class3_core_s").item() == 1200
