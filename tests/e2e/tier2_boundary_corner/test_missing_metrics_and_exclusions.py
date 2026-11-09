"""Tier 2 Boundary and Corner Cases: Missing Metrics and Exclusions.

Verifies handling of:
- Missing MaxRSS and TotalCPU fields (asserting unattributed_core_s > 0 AND unattributed_mem_mb_s > 0)
- Workloads containing only RUNNING and PENDING states
- Negative numeric values in SWF sentinels resolving to null
- Zero-core and zero-memory reservations
"""

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "trace_name",
    [
        "sacct_unattributed_missing.txt",
    ],
)
def test_boundary_missing_metrics_attribution_coverage(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """Verify jobs with missing MaxRSS or TotalCPU are tracked under unattributed coverage with logical AND."""
    trace_path = fixtures_dir / "sacct" / trace_name
    attributed_path = isolated_workspace / f"attr_{trace_name}.parquet"

    result = run_cli(["attribute", str(trace_path), "--output", str(attributed_path)])
    assert result.exit_code == 0

    df = pl.read_parquet(attributed_path)
    unattrib_core_total = df.select("unattributed_core_s").sum().item()
    unattrib_mem_total = df.select("unattributed_mem_mb_s").sum().item()

    assert unattrib_core_total > 0 and unattrib_mem_total > 0, "Both core and memory unattributed metrics must be > 0"


@pytest.mark.parametrize("trace_name", ["sacct_running_pending.txt"])
def test_boundary_all_active_trace_reporting(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    trace_name: str,
):
    """Verify trace with active jobs (RUNNING/PENDING) reports them in data quality section via report CLI."""
    trace_path = fixtures_dir / "sacct" / trace_name
    report_json = isolated_workspace / "active_report.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    quality = data.get("data_quality", {})
    assert quality.get("excluded_active_count", 0) >= 2


@pytest.mark.parametrize(
    "field_idx,field_name",
    [
        (6, "cpu_time_used_s"),
        (7, "max_rss_mb"),
        (10, "req_mem_mb"),
    ],
)
def test_boundary_swf_negative_sentinels(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    field_idx: int,
    field_name: str,
):
    """Verify SWF negative sentinel values (-1) resolve strictly to null in canonical Parquet via ingest CLI."""
    swf_file = isolated_workspace / f"sentinel_{field_name}.swf"
    out_file = isolated_workspace / f"sentinel_{field_name}.parquet"

    # Job Number, Submit, Wait, Run, AllocCPUS, AvgCPU, UsedMem, ReqCPUS, ReqTime, ReqMem, Status ...
    fields = ["1", "0", "10", "100", "4", "100", "4096", "4", "100", "4096", "1", "1", "1", "1", "-1", "-1", "-1", "-1"]
    fields[field_idx - 1] = "-1"
    swf_file.write_text(" ".join(fields) + "\n")

    res = run_cli(["ingest", str(swf_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    val = df.select(field_name).item()
    assert val is None, f"Expected null for sentinel in {field_name}, got {val}"


@pytest.mark.parametrize("alloc_cpus,req_mem_mb,run_s", [(0, 0, 100), (4, 0, 0), (0, 8000, 50)])
def test_boundary_zero_resource_reservations(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    alloc_cpus: int,
    req_mem_mb: int,
    run_s: int,
):
    """Verify zero resource or zero runtime requests compute zero reservation without exceptions via attribute CLI."""
    trace_file = isolated_workspace / f"zero_res_{alloc_cpus}_{req_mem_mb}_{run_s}.txt"
    attr_file = isolated_workspace / f"zero_res_{alloc_cpus}_{req_mem_mb}_{run_s}.parquet"

    header = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
    row = f"1003|1003|alice|res|comp|norm|zr|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:00:05|00:00:00|COMPLETED|0:0|{alloc_cpus}|{alloc_cpus}|{req_mem_mb}M|0M|0M|00:00:00|0|billing=0,cpu=0,node=1|billing=0,cpu=0,node=1|node-01||sbatch run.sh\n"
    trace_file.write_text(header + row)

    res = run_cli(["attribute", str(trace_file), "--output", str(attr_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(attr_file)
    assert df.height == 1
    assert df.select("reserved_core_s").item() == alloc_cpus * run_s
