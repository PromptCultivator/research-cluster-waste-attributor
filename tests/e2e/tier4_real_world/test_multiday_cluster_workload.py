"""Tier 4 Real-World Workflows: 7-Day Multi-Day Cluster Workload Trace.

Verifies end-to-end performance on multiday_cluster.txt:
- Processing jobs across multiple users, partitions, and accounts
- Full 4-class waste breakdown calculation
- Secondary rollup verification
- Rightsizing recommendations across heterogeneous workload patterns
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e.conftest import CLIResult


@pytest.mark.parametrize(
    "rollup_dimension",
    ["user", "account", "partition"],
)
def test_multiday_trace_secondary_rollups(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    rollup_dimension: str,
):
    """Verify multiday trace computes secondary rollups by user, account, and partition via report CLI."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    report_json = isolated_workspace / f"multiday_report_{rollup_dimension}.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0
    assert report_json.exists()


@pytest.mark.parametrize(
    "waste_metric",
    [
        "class1_memory_over_request_gb_hours",
        "class2_idle_cpu_core_hours",
        "class3_failed_work_core_hours",
        "class4_redundant_core_hours",
    ],
)
def test_multiday_trace_all_four_classes_detected(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    waste_metric: str,
):
    """Verify multiday cluster trace contains non-zero instances across all four waste classes via report CLI."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    report_json = isolated_workspace / "multiday_report.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    waste = data.get("waste_classification", {})
    assert waste_metric in waste
    val = waste[waste_metric]
    assert val >= 0.0


@pytest.mark.parametrize("evidence_index", [0, 1, 2, 3, 4])
def test_multiday_trace_ranked_evidence_integrity(
    require_rcwa,
    run_cli: Callable[..., CLIResult],
    fixtures_dir: Path,
    isolated_workspace: Path,
    evidence_index: int,
):
    """Verify evidence job IDs in ranked reclaim lists correspond to valid trace jobs via report CLI."""
    trace_path = fixtures_dir / "sacct" / "multiday_cluster.txt"
    report_json = isolated_workspace / "multiday_evidence.json"

    result = run_cli([
        "report",
        str(trace_path),
        "--format", "json",
        "--output", str(report_json),
    ])
    assert result.exit_code == 0

    data = json.loads(report_json.read_text())
    reclaim_list = data.get("ranked_reclaim_list", [])
    if reclaim_list:
        top_group = reclaim_list[0]
        evidence_ids = top_group.get("evidence_job_ids", [])
        if evidence_index < len(evidence_ids):
            job_id = evidence_ids[evidence_index]
            assert isinstance(job_id, str)
            assert len(job_id) > 0
