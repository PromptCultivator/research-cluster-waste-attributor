"""Tier 2 Boundary and Corner Cases: Corrupted and Extreme Values.

Verifies system handling of:
- Inverted and unparseable timestamps (clamping run_s >= 0 without negative core-s or mem-s)
- Multi-year extreme runtimes without integer overflow
- Sub-millisecond runtimes without zero-division
- Binary corruption inputs
- Unrecognized scheduler states
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "corrupted_trace",
    [
        "corrupted_timestamps.txt",
        "extreme_durations.txt",
    ],
)
def test_boundary_corrupted_timestamps_and_extremes(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    corrupted_trace: str,
):
    """Verify corrupted timestamps and extreme durations clamp run_s >= 0 and never yield negative reservations."""
    trace_path = fixtures_dir / "edge" / corrupted_trace
    out_path = isolated_workspace / f"edge_{corrupted_trace}.parquet"
    attr_path = isolated_workspace / f"edge_attr_{corrupted_trace}.parquet"

    result = run_cli(["ingest", str(trace_path), "--output", str(out_path)])
    assert result.exit_code == 0
    assert out_path.exists()

    df = pl.read_parquet(out_path)
    assert df.height > 0
    assert (df["run_s"] >= 0).all(), "Inverted timestamps must clamp run_s to >= 0"

    res_attr = run_cli(["attribute", str(trace_path), "--output", str(attr_path)])
    assert res_attr.exit_code == 0
    df_attr = pl.read_parquet(attr_path)
    assert (df_attr["reserved_core_s"] >= 0).all(), "Must never produce negative reserved core-s"
    assert (df_attr["reserved_mem_mb_s"] >= 0).all(), "Must never produce negative reserved mem-s"


@pytest.mark.parametrize("binary_file", ["corrupted_binary.bin"])
def test_boundary_binary_corruption_rejected(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    binary_file: str,
):
    """Verify binary non-text files are rejected with a clear exit code and message."""
    bin_path = fixtures_dir / "edge" / binary_file
    out_path = isolated_workspace / "bin_out.parquet"

    result = run_cli(["ingest", str(bin_path), "--output", str(out_path)])
    assert result.exit_code != 0
    assert "error" in result.stderr.lower() or "decode" in result.stderr.lower() or "invalid" in result.stderr.lower()


@pytest.mark.parametrize(
    "extreme_elapsed_str,expected_seconds_floor",
    [
        ("1826-00:00:00", 150000000),   # ~5 years
        ("3650-12:00:00", 300000000),   # ~10 years
        ("00:00.001", 0),               # sub-millisecond
        ("00:00:00", 0),                # zero runtime
    ],
)
def test_boundary_extreme_duration_parsing(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    extreme_elapsed_str: str,
    expected_seconds_floor: int,
):
    """Verify duration parser handles multi-year durations and fractional seconds via opaque-box CLI."""
    trace_file = isolated_workspace / f"ext_dur_{extreme_elapsed_str.replace(':', '_').replace('-', '_')}.txt"
    out_file = isolated_workspace / f"ext_dur_{extreme_elapsed_str.replace(':', '_').replace('-', '_')}.parquet"

    header = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
    row = f"1001|1001|alice|res|comp|norm|ext|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T11:00:05|{extreme_elapsed_str}|COMPLETED|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh\n"
    trace_file.write_text(header + row)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    val = df.select("run_s").item()
    assert val >= expected_seconds_floor


@pytest.mark.parametrize(
    "unknown_state_str",
    [
        "FAILED_BY_ADMIN",
        "REVOKED_SPECIAL_STATUS",
        "SYSTEM_HALTED_42",
        "CUSTOM_PROPRIETARY_STATE",
        "RESV_DEL_HOLD",
    ],
)
def test_boundary_unknown_states_mapped_to_other(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    isolated_workspace: Path,
    unknown_state_str: str,
):
    """Verify arbitrary unknown scheduler state strings map to canonical OTHER via opaque-box CLI."""
    trace_file = isolated_workspace / f"unk_{unknown_state_str}.txt"
    out_file = isolated_workspace / f"unk_{unknown_state_str}.parquet"

    header = "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine\n"
    row = f"1002|1002|alice|res|comp|norm|unk|2026-03-01T10:00:00|2026-03-01T10:00:01|2026-03-01T10:00:05|2026-03-01T10:30:05|00:30:00|{unknown_state_str}|0:0|4|4|8000M|2000M|1800M|00:10:00|7200|billing=4,cpu=4,node=1|billing=4,cpu=4,node=1|node-01||sbatch run.sh\n"
    trace_file.write_text(header + row)

    res = run_cli(["ingest", str(trace_file), "--output", str(out_file)])
    assert res.exit_code == 0
    df = pl.read_parquet(out_file)
    canonical = df.select("state").item()
    assert canonical == "OTHER"
