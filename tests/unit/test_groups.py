"""Unit tests for workload grouping, scoring, secondary rollups, and evidence sampling."""

from pathlib import Path

import polars as pl

from rcwa.adapters.sacct import parse_sacct
from rcwa.attribute import attribute_trace
from rcwa.groups import export_group_metrics, generate_secondary_rollups, group_jobs

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_group_jobs_empty() -> None:
    """Verify grouping handles empty DataFrame safely."""
    empty_df = pl.DataFrame()
    res = group_jobs(empty_df)
    assert res.height == 0
    assert "group" in res.columns
    assert "reclaim_score" in res.columns
    assert "evidence_job_ids" in res.columns


def test_group_jobs_multiday_fixture() -> None:
    """Verify grouping on multiday cluster fixture produces expected groups and metrics."""
    trace_file = FIXTURES_DIR / "sacct" / "multiday_cluster.txt"
    raw_df = parse_sacct(trace_file)
    attr_df = attribute_trace(raw_df)

    grouped = group_jobs(attr_df)
    assert grouped.height >= 4

    # Check required schema columns
    expected_cols = [
        "group",
        "job_count",
        "total_reserved_core_hours",
        "total_used_core_hours",
        "total_reserved_gb_hours",
        "total_used_gb_hours",
        "class1_over_mem_gb_hours",
        "class2_idle_core_hours",
        "class3_failed_core_hours",
        "class3_failed_gb_hours",
        "class4_recompute_core_hours",
        "class4_recompute_gb_hours",
        "unattributed_core_hours",
        "unattributed_gb_hours",
        "reclaimable_core_hours",
        "reclaimable_gb_hours",
        "reclaim_score",
        "score",
        "cluster_reserved_core_share",
        "cluster_waste_score_share",
        "sample_count_ok",
        "has_oom",
        "evidence_job_ids",
    ]
    for col in expected_cols:
        assert col in grouped.columns

    # Verify score ranking: rows must be sorted descending by reclaim_score
    scores = grouped.select("reclaim_score").to_series().to_list()
    assert scores == sorted(scores, reverse=True)


def test_group_jobs_oom_guardrail() -> None:
    """Verify groups containing OUT_OF_MEMORY jobs receive 0 reclaimable GB hours."""
    trace_file = FIXTURES_DIR / "sacct" / "multiday_cluster.txt"
    raw_df = parse_sacct(trace_file)
    attr_df = attribute_trace(raw_df)

    grouped = group_jobs(attr_df)
    # david/order_book_proc has an OOM job
    oom_grp = grouped.filter(pl.col("group") == "david/order_book_proc")
    assert oom_grp.height == 1
    assert oom_grp.select("has_oom").item() is True
    assert oom_grp.select("reclaimable_gb_hours").item() == 0.0


def test_group_jobs_evidence_sampling_and_limits() -> None:
    """Verify evidence job ID sampling returns up to 5 IDs per group."""
    trace_file = FIXTURES_DIR / "sacct" / "multiday_cluster.txt"
    raw_df = parse_sacct(trace_file)
    attr_df = attribute_trace(raw_df)

    grouped = group_jobs(attr_df)
    for row in grouped.iter_rows(named=True):
        ev_ids = row["evidence_job_ids"]
        assert isinstance(ev_ids, list)
        assert len(ev_ids) <= 5
        assert len(ev_ids) <= row["job_count"]


def test_secondary_rollups() -> None:
    """Verify secondary rollups aggregate by account, partition, and user."""
    trace_file = FIXTURES_DIR / "sacct" / "multiday_cluster.txt"
    raw_df = parse_sacct(trace_file)
    attr_df = attribute_trace(raw_df)

    rollups = generate_secondary_rollups(attr_df)
    assert set(rollups.keys()) == {"account", "partition", "user"}

    for dim, df_dim in rollups.items():
        assert df_dim.height > 0
        assert "group" in df_dim.columns
        assert "reclaim_score" in df_dim.columns


def test_export_group_metrics_csv_and_parquet(tmp_path: Path) -> None:
    """Verify group metrics export with semicolon serialization for CSV."""
    trace_file = FIXTURES_DIR / "sacct" / "multiday_cluster.txt"
    raw_df = parse_sacct(trace_file)
    attr_df = attribute_trace(raw_df)
    grouped = group_jobs(attr_df)

    p_out = tmp_path / "groups.parquet"
    c_out = tmp_path / "groups.csv"

    export_group_metrics(grouped, p_out, format="parquet")
    export_group_metrics(grouped, c_out, format="csv")

    assert p_out.exists()
    assert c_out.exists()

    df_p = pl.read_parquet(p_out)
    assert df_p.height == grouped.height

    df_c = pl.read_csv(c_out)
    assert df_c.height == grouped.height
    # Check that evidence_job_ids in CSV is a string
    ev_val = df_c.select("evidence_job_ids").item(0, 0)
    assert isinstance(ev_val, str)
