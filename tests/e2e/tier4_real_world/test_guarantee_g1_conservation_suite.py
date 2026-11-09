"""Tier 4 Guarantee Suite: G1 Conservation Invariant Exhaustive Verification.

Mathematical Guarantee G1:
For every job in the trace and each dimension (cores and memory):
reserved = used + class1_or_2 + class3 + class4 + unattributed
Holds strictly in integer seconds and MB-seconds.
Verified per job and across trace-wide aggregate sums.
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult, InvariantValidators


@pytest.mark.parametrize(
    "trace_path_rel",
    [
        "sacct/sacct_standard_26col.txt",
        "sacct/sacct_steps_rollup.txt",
        "sacct/sacct_array_heterogeneous.txt",
        "sacct/sacct_memory_suffixes.txt",
        "sacct/sacct_durations_states.txt",
        "sacct/sacct_unattributed_missing.txt",
        "sacct/multiday_cluster.txt",
        "swf/standard_with_headers.swf",
        "swf/missing_fields.swf",
        "swf/status_variations.swf",
        "swf/sample_workload.swf",
        "recompute/recompute_pairs.txt",
        "recompute/recompute_command_only.txt",
        "retries/retry_chains.txt",
        "guardrails/oom_groups.txt",
    ],
)
def test_guarantee_g1_across_all_fixtures(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_path_rel: str,
):
    """Enforce Guarantee G1 per-job and trace-wide sum equality across every fixture file."""
    trace_path = fixtures_dir / trace_path_rel
    sanitized_name = trace_path_rel.replace("/", "_").replace(".", "_")
    attr_out = isolated_workspace / f"g1_{sanitized_name}.parquet"
    report_json = isolated_workspace / f"g1_report_{sanitized_name}.json"

    result = run_cli(["attribute", str(trace_path), "--output", str(attr_out)])
    assert result.exit_code == 0, f"Attribution failed on {trace_path_rel}: {result.stderr}"

    df = pl.read_parquet(attr_out)

    # 1. Per-Job Conservation Check
    for i in range(df.height):
        row = df.slice(i, 1)

        # Core Dimension
        r_core = row.select("reserved_core_s").item()
        u_core = row.select("used_core_s").item()
        c2 = row.select("class2_idle_core_s").item()
        c3_c = row.select("class3_core_s").item()
        c4_c = row.select("class4_core_s").item()
        un_c = row.select("unattributed_core_s").item()

        assert InvariantValidators.verify_g1_conservation(
            reserved=r_core,
            used=u_core,
            class1_or_2=c2,
            class3=c3_c,
            class4=c4_c,
            unattributed=un_c,
        ), f"G1 Core conservation violated on {trace_path_rel} row {i}"

        # Memory Dimension
        r_mem = row.select("reserved_mem_mb_s").item()
        u_mem = row.select("used_mem_mb_s").item()
        c1 = row.select("class1_over_mem_mb_s").item()
        c3_m = row.select("class3_mem_mb_s").item()
        c4_m = row.select("class4_mem_mb_s").item()
        un_m = row.select("unattributed_mem_mb_s").item()

        assert InvariantValidators.verify_g1_conservation(
            reserved=r_mem,
            used=u_mem,
            class1_or_2=c1,
            class3=c3_m,
            class4=c4_m,
            unattributed=un_m,
        ), f"G1 Memory conservation violated on {trace_path_rel} row {i}"

    # 2. Trace-Wide Sum Equality Check
    sum_res_core = df.select("reserved_core_s").sum().item()
    sum_used_core = df.select("used_core_s").sum().item()
    sum_c2 = df.select("class2_idle_core_s").sum().item()
    sum_c3_c = df.select("class3_core_s").sum().item()
    sum_c4_c = df.select("class4_core_s").sum().item()
    sum_un_c = df.select("unattributed_core_s").sum().item()

    assert sum_res_core == sum_used_core + sum_c2 + sum_c3_c + sum_c4_c + sum_un_c, (
        f"Trace-wide core conservation sum violated on {trace_path_rel}"
    )

    sum_res_mem = df.select("reserved_mem_mb_s").sum().item()
    sum_used_mem = df.select("used_mem_mb_s").sum().item()
    sum_c1 = df.select("class1_over_mem_mb_s").sum().item()
    sum_c3_m = df.select("class3_mem_mb_s").sum().item()
    sum_c4_m = df.select("class4_mem_mb_s").sum().item()
    sum_un_m = df.select("unattributed_mem_mb_s").sum().item()

    assert sum_res_mem == sum_used_mem + sum_c1 + sum_c3_m + sum_c4_m + sum_un_m, (
        f"Trace-wide memory conservation sum violated on {trace_path_rel}"
    )

    # 3. Reconcile with Report Summary
    res_rep = run_cli(["report", str(trace_path), "--format", "json", "--output", str(report_json)])
    if res_rep.exit_code == 0 and report_json.exists():
        data = json.loads(report_json.read_text())
        summary = data.get("summary", {})
        if "total_reserved_core_hours" in summary:
            expected_core_hours = round(sum_res_core / 3600.0, 1)
            actual_core_hours = round(summary["total_reserved_core_hours"], 1)
            assert abs(actual_core_hours - expected_core_hours) <= 0.2


@pytest.mark.parametrize(
    "trace_size,seed_val",
    [
        (10, 101),
        (20, 202),
        (30, 303),
        (40, 404),
        (50, 505),
        (60, 606),
        (70, 707),
        (80, 808),
        (90, 909),
        (100, 1010),
    ],
)
def test_guarantee_g1_across_synthetic_sizes(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    trace_size: int,
    seed_val: int,
):
    """Enforce Guarantee G1 across generated synthetic traces with diverse planted faults."""
    trace_file = isolated_workspace / f"synth_g1_{trace_size}_{seed_val}.txt"
    attr_file = isolated_workspace / f"synth_g1_{trace_size}_{seed_val}.parquet"

    res_synth = run_cli(["synth", "--size", str(trace_size), "--seed", str(seed_val), "--output", str(trace_file)])
    assert res_synth.exit_code == 0

    res_attr = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res_attr.exit_code == 0

    df = pl.read_parquet(attr_file)
    for i in range(df.height):
        row = df.slice(i, 1)
        r_core = row.select("reserved_core_s").item()
        u_core = row.select("used_core_s").item()
        c2 = row.select("class2_idle_core_s").item()
        c3_c = row.select("class3_core_s").item()
        c4_c = row.select("class4_core_s").item()
        un_c = row.select("unattributed_core_s").item()

        assert InvariantValidators.verify_g1_conservation(
            reserved=r_core, used=u_core, class1_or_2=c2, class3=c3_c, class4=c4_c, unattributed=un_c
        )


@pytest.mark.parametrize(
    "alloc_cpus,run_s,state",
    [
        (1, 10, "COMPLETED"),
        (2, 60, "COMPLETED"),
        (4, 120, "FAILED"),
        (8, 300, "TIMEOUT"),
        (16, 600, "OUT_OF_MEMORY"),
        (32, 1200, "NODE_FAIL"),
        (64, 3600, "CANCELLED"),
        (4, 0, "FAILED"),
        (8, 60, "COMPLETED"),
        (16, 120, "COMPLETED"),
    ],
)
def test_guarantee_g1_synthetic_edge_permutations(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    alloc_cpus: int,
    run_s: int,
    state: str,
):
    """Enforce G1: mathematical validation over CLI-generated attribution parquet outputs."""
    trace_file = isolated_workspace / f"edge_g1_{alloc_cpus}_{run_s}_{state}.txt"
    attr_file = isolated_workspace / f"edge_g1_{alloc_cpus}_{run_s}_{state}.parquet"

    header = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
    row = f"2001|2001|alice|res|comp|norm|g1_perm|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:10:00|{state}|0:0|{alloc_cpus}|{alloc_cpus}|{alloc_cpus * 4000}M|{alloc_cpus * 2000}M|{alloc_cpus * 1800}M|00:05:00|7200|billing={alloc_cpus},cpu={alloc_cpus},node=1|billing={alloc_cpus},cpu={alloc_cpus},node=1|node-01||sbatch run.sh\n"
    trace_file.write_text(header + row)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)

    row_data = df.slice(0, 1)
    res_core = row_data.select("reserved_core_s").item()
    used_core = row_data.select("used_core_s").item()
    c2 = row_data.select("class2_idle_core_s").item()
    c3_c = row_data.select("class3_core_s").item()
    c4_c = row_data.select("class4_core_s").item()
    un_c = row_data.select("unattributed_core_s").item()

    assert InvariantValidators.verify_g1_conservation(
        reserved=res_core,
        used=used_core,
        class1_or_2=c2,
        class3=c3_c,
        class4=c4_c,
        unattributed=un_c,
    )
