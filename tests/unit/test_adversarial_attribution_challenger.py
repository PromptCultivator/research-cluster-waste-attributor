"""Adversarial stress and edge case verification suite for attribution, retries, and grouping."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from rcwa.attribute import attribute_trace, export_attributed_records
from rcwa.groups import export_group_metrics, group_jobs
from rcwa.retries import detect_retry_chains


def _create_base_job(
    job_id: str,
    user: str | None = "alice",
    job_name: str | None = "task_a",
    command_hash: str | None = "cmd_hash_1",
    state: str = "FAILED",
    submit_time: datetime | None = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC),
    start_time: datetime | None = datetime(2026, 4, 1, 10, 0, 10, tzinfo=UTC),
    end_time: datetime | None = datetime(2026, 4, 1, 10, 1, 0, tzinfo=UTC),
    run_s: int = 50,
    wait_s: int = 10,
    alloc_cpus: int = 4,
    req_mem_mb: int = 4096,
    cpu_time_used_s: float | None = 20.0,
    max_rss_mb: int | None = 2048,
) -> dict:
    """Construct a dictionary representing a canonical job record."""
    reserved_core_s = alloc_cpus * run_s
    reserved_mem_mb_s = (req_mem_mb * run_s) if req_mem_mb is not None else None
    return {
        "job_id": job_id,
        "parent_job_id": None,
        "source": "sacct",
        "user": user,
        "account": "research",
        "partition": "gpu",
        "job_name": job_name,
        "command_hash": command_hash,
        "input_hash": None,
        "submit_time": submit_time,
        "start_time": start_time,
        "end_time": end_time,
        "wait_s": wait_s,
        "run_s": run_s,
        "state": state,
        "exit_code": 1 if state != "COMPLETED" else 0,
        "req_cpus": alloc_cpus,
        "alloc_cpus": alloc_cpus,
        "cpu_time_used_s": cpu_time_used_s,
        "req_mem_mb": req_mem_mb,
        "max_rss_mb": max_rss_mb,
        "req_gpus": 0,
        "alloc_gpus": 0,
        "nodes": 1,
        "node_list": "node01",
        "reserved_core_s": reserved_core_s,
        "reserved_mem_mb_s": reserved_mem_mb_s,
    }


# ============================================================================
# 1. Temporal window boundaries for retries
# ============================================================================


def test_retry_temporal_window_exact_boundary() -> None:
    """Verify linkage behavior at exact retry_window_s boundaries and offsets."""
    base_t = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
    window_s = 3600  # 1 hour window

    # Parent job fails and ends at base_t + 100s
    parent = _create_base_job(
        "P1",
        submit_time=base_t,
        start_time=base_t,
        end_time=base_t + timedelta(seconds=100),
        run_s=100,
        state="FAILED",
    )
    p_end = base_t + timedelta(seconds=100)

    # Candidate 1: submitted at exact delta = 0 (same second as failure end)
    c_exact_zero = _create_base_job(
        "C0",
        submit_time=p_end,
        start_time=p_end,
        end_time=p_end + timedelta(seconds=50),
        run_s=50,
        state="COMPLETED",
    )
    # Candidate 2: submitted at exact delta = retry_window_s
    c_exact_window = _create_base_job(
        "C_EXACT",
        submit_time=p_end + timedelta(seconds=window_s),
        start_time=p_end + timedelta(seconds=window_s),
        end_time=p_end + timedelta(seconds=window_s + 50),
        run_s=50,
        state="COMPLETED",
    )
    # Candidate 3: submitted at delta = retry_window_s + 1s (outside window)
    c_expired = _create_base_job(
        "C_EXPIRED",
        submit_time=p_end + timedelta(seconds=window_s + 1),
        start_time=p_end + timedelta(seconds=window_s + 1),
        end_time=p_end + timedelta(seconds=window_s + 51),
        run_s=50,
        state="COMPLETED",
    )
    # Candidate 4: submitted at delta = -1s (before failure completes)
    c_pre_completion = _create_base_job(
        "C_CONCURRENT",
        submit_time=p_end - timedelta(seconds=1),
        start_time=p_end - timedelta(seconds=1),
        end_time=p_end + timedelta(seconds=49),
        run_s=50,
        state="COMPLETED",
    )

    # Test exact window match isolated
    df_exact = pl.DataFrame([parent, c_exact_window])
    res_exact = detect_retry_chains(df_exact, retry_window_s=window_s)
    assert res_exact.filter(pl.col("job_id") == "C_EXACT").select("retry_of").item() == "P1"
    assert res_exact.filter(pl.col("job_id") == "P1").select("retry_chain_id").item() == "P1"

    # Test expired window (delta = window_s + 1)
    df_expired = pl.DataFrame([parent, c_expired])
    res_expired = detect_retry_chains(df_expired, retry_window_s=window_s)
    assert res_expired.filter(pl.col("job_id") == "C_EXPIRED").select("retry_of").item() is None
    assert res_expired.filter(pl.col("job_id") == "P1").select("retry_chain_id").item() is None

    # Test exact zero delta (same second)
    df_zero = pl.DataFrame([parent, c_exact_zero])
    res_zero = detect_retry_chains(df_zero, retry_window_s=window_s)
    assert res_zero.filter(pl.col("job_id") == "C0").select("retry_of").item() == "P1"

    # Test negative delta (submitted 1s before failure ends)
    df_pre = pl.DataFrame([parent, c_pre_completion])
    res_pre = detect_retry_chains(df_pre, retry_window_s=window_s)
    assert res_pre.filter(pl.col("job_id") == "C_CONCURRENT").select("retry_of").item() is None


# ============================================================================
# 2. Out-of-order submit times and concurrent submissions
# ============================================================================


def test_retry_out_of_order_submit_times() -> None:
    """Verify chronological resolution when input DataFrame rows are inverted."""
    base_t = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

    p1 = _create_base_job(
        "P1",
        submit_time=base_t,
        start_time=base_t,
        end_time=base_t + timedelta(seconds=100),
        run_s=100,
        state="FAILED",
    )
    c1 = _create_base_job(
        "C1",
        submit_time=base_t + timedelta(seconds=200),
        start_time=base_t + timedelta(seconds=200),
        end_time=base_t + timedelta(seconds=300),
        run_s=100,
        state="COMPLETED",
    )

    # Provide rows in reverse chronological order: [C1, P1]
    df_reversed = pl.DataFrame([c1, p1])
    res = detect_retry_chains(df_reversed, retry_window_s=3600)

    assert res.filter(pl.col("job_id") == "C1").select("retry_of").item() == "P1"
    assert res.filter(pl.col("job_id") == "P1").select("retry_chain_id").item() == "P1"
    assert res.filter(pl.col("job_id") == "C1").select("retry_count").item() == 1


def test_retry_concurrent_submission_before_parent_completion() -> None:
    """Verify a job submitted prior to failure termination is not marked retry_of."""
    base_t = datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC)

    # Long running job fails at base_t + 2000s
    p_long = _create_base_job(
        "P_LONG",
        submit_time=base_t,
        start_time=base_t,
        end_time=base_t + timedelta(seconds=2000),
        run_s=2000,
        state="FAILED",
    )
    # Concurrent job submitted at base_t + 1000s (while P_LONG is still executing)
    c_concurrent = _create_base_job(
        "C_CONC",
        submit_time=base_t + timedelta(seconds=1000),
        start_time=base_t + timedelta(seconds=1000),
        end_time=base_t + timedelta(seconds=2500),
        run_s=1500,
        state="COMPLETED",
    )

    df = pl.DataFrame([p_long, c_concurrent])
    res = detect_retry_chains(df, retry_window_s=86400)

    assert res.filter(pl.col("job_id") == "C_CONC").select("retry_of").item() is None
    assert res.filter(pl.col("job_id") == "P_LONG").select("retry_chain_id").item() is None


def test_retry_null_submit_time_sorting_safety() -> None:
    """Verify DataFrame containing rows with null submit_time does not raise TypeError."""
    base_t = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    j_with_time = _create_base_job("J1", submit_time=base_t, state="FAILED")
    j_null_time = _create_base_job(
        "J2", submit_time=None, start_time=None, end_time=None, state="COMPLETED"
    )

    df = pl.DataFrame([j_with_time, j_null_time])
    res = detect_retry_chains(df)
    assert res.height == 2
    assert res.filter(pl.col("job_id") == "J2").select("retry_of").item() is None


def test_retry_naive_datetime_normalization() -> None:
    """Verify comparison does not fail when datetime instances lack tzinfo."""
    base_naive = datetime(2026, 4, 1, 10, 0, 0)
    p = _create_base_job(
        "P_NAIVE",
        submit_time=base_naive,
        start_time=base_naive,
        end_time=base_naive + timedelta(seconds=100),
        run_s=100,
        state="FAILED",
    )
    c = _create_base_job(
        "C_NAIVE",
        submit_time=base_naive + timedelta(seconds=200),
        start_time=base_naive + timedelta(seconds=200),
        end_time=base_naive + timedelta(seconds=300),
        run_s=100,
        state="COMPLETED",
    )

    df = pl.DataFrame([p, c])
    res = detect_retry_chains(df, retry_window_s=3600)
    assert res.filter(pl.col("job_id") == "C_NAIVE").select("retry_of").item() == "P_NAIVE"


# ============================================================================
# 3. Empty user, null command_hash AND null job_name
# ============================================================================


def test_retry_missing_identifiers_not_linked() -> None:
    """Verify records lacking user or task identifier never enter retry chains."""
    base_t = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Empty string user
    j_empty_user1 = _create_base_job("U1", user="", state="FAILED")
    j_empty_user2 = _create_base_job(
        "U2", user="", submit_time=base_t + timedelta(seconds=100), state="COMPLETED"
    )

    # Null user
    j_null_user1 = _create_base_job("NU1", user=None, state="FAILED")
    j_null_user2 = _create_base_job(
        "NU2", user=None, submit_time=base_t + timedelta(seconds=100), state="COMPLETED"
    )

    # Null command_hash AND null job_name
    j_no_task1 = _create_base_job("T1", job_name=None, command_hash=None, state="FAILED")
    j_no_task2 = _create_base_job(
        "T2",
        job_name=None,
        command_hash=None,
        submit_time=base_t + timedelta(seconds=100),
        state="COMPLETED",
    )

    df = pl.DataFrame(
        [
            j_empty_user1,
            j_empty_user2,
            j_null_user1,
            j_null_user2,
            j_no_task1,
            j_no_task2,
        ]
    )
    res = detect_retry_chains(df)

    for jid in ["U1", "U2", "NU1", "NU2", "T1", "T2"]:
        row = res.filter(pl.col("job_id") == jid)
        assert row.select("retry_of").item() is None
        assert row.select("retry_chain_id").item() is None
        assert row.select("retry_count").item() == 0
        assert row.select("retry_chain_cost_core_s").item() == 0


# ============================================================================
# 4. Multi-hop chain topology: 3-hop and 4-hop chain cost rollups
# ============================================================================


def test_retry_multi_hop_3_hop_and_4_hop_chains() -> None:
    """Verify hop counts and cost aggregations across 3-hop and 4-hop topologies."""
    base_t = datetime(2026, 4, 1, 8, 0, 0, tzinfo=UTC)

    # Build 5 sequential jobs: J0(F) -> J1(F) -> J2(F) -> J3(F) -> J4(C)
    # J0 -> J1: 1 hop
    # J0 -> J2: 2 hops
    # J0 -> J3: 3 hops
    # J0 -> J4: 4 hops
    jobs = []
    expected_core_total = 0
    expected_mem_total = 0

    for idx in range(5):
        t_sub = base_t + timedelta(seconds=idx * 600)
        t_start = t_sub + timedelta(seconds=10)
        t_end = t_start + timedelta(seconds=200)
        is_last = idx == 4
        st = "COMPLETED" if is_last else "FAILED"
        cores = 2 * (idx + 1)
        mem = 1000 * (idx + 1)
        run_s = 200

        core_s = cores * run_s
        mem_mb_s = mem * run_s
        expected_core_total += core_s
        expected_mem_total += mem_mb_s

        job = _create_base_job(
            f"MH_{idx}",
            user="charlie",
            job_name="pipeline",
            command_hash="hash_pipeline",
            state=st,
            submit_time=t_sub,
            start_time=t_start,
            end_time=t_end,
            run_s=run_s,
            alloc_cpus=cores,
            req_mem_mb=mem,
        )
        jobs.append(job)

    # First test 4 jobs (3-hop chain: MH_0 -> MH_1 -> MH_2 -> MH_3)
    df_3hop = pl.DataFrame(jobs[:4])
    res_3hop = detect_retry_chains(df_3hop, retry_window_s=3600)

    assert res_3hop.filter(pl.col("job_id") == "MH_0").select("retry_count").item() == 0
    assert res_3hop.filter(pl.col("job_id") == "MH_1").select("retry_count").item() == 1
    assert res_3hop.filter(pl.col("job_id") == "MH_2").select("retry_count").item() == 2
    assert res_3hop.filter(pl.col("job_id") == "MH_3").select("retry_count").item() == 3

    cost_3hop_core = sum(j["reserved_core_s"] for j in jobs[:4])
    cost_3hop_mem = sum(j["reserved_mem_mb_s"] for j in jobs[:4])
    for jid in ["MH_0", "MH_1", "MH_2", "MH_3"]:
        row = res_3hop.filter(pl.col("job_id") == jid)
        assert row.select("retry_chain_id").item() == "MH_0"
        assert row.select("retry_chain_cost_core_s").item() == cost_3hop_core
        assert row.select("retry_chain_cost_mem_mb_s").item() == cost_3hop_mem

    # Now test full 5 jobs (4-hop chain: MH_0 -> MH_1 -> MH_2 -> MH_3 -> MH_4)
    df_4hop = pl.DataFrame(jobs)
    res_4hop = detect_retry_chains(df_4hop, retry_window_s=3600)

    for idx in range(5):
        jid = f"MH_{idx}"
        row = res_4hop.filter(pl.col("job_id") == jid)
        assert row.select("retry_chain_id").item() == "MH_0"
        assert row.select("retry_count").item() == idx
        assert row.select("retry_chain_cost_core_s").item() == expected_core_total
        assert row.select("retry_chain_cost_mem_mb_s").item() == expected_mem_total

    # Verify parent linkages
    assert res_4hop.filter(pl.col("job_id") == "MH_0").select("retry_of").item() is None
    assert res_4hop.filter(pl.col("job_id") == "MH_1").select("retry_of").item() == "MH_0"
    assert res_4hop.filter(pl.col("job_id") == "MH_2").select("retry_of").item() == "MH_1"
    assert res_4hop.filter(pl.col("job_id") == "MH_3").select("retry_of").item() == "MH_2"
    assert res_4hop.filter(pl.col("job_id") == "MH_4").select("retry_of").item() == "MH_3"


def test_retry_branching_candidate_resolution() -> None:
    """Verify earliest candidate claims failure and subsequent candidates remain unclaimed."""
    base_t = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)

    # Job F fails at base_t + 100s
    p_fail = _create_base_job(
        "F_PARENT",
        submit_time=base_t,
        start_time=base_t,
        end_time=base_t + timedelta(seconds=100),
        run_s=100,
        state="FAILED",
    )
    # Resubmission 1 at base_t + 200s
    c1 = _create_base_job(
        "C1_EARLIER",
        submit_time=base_t + timedelta(seconds=200),
        start_time=base_t + timedelta(seconds=200),
        end_time=base_t + timedelta(seconds=300),
        run_s=100,
        state="COMPLETED",
    )
    # Resubmission 2 at base_t + 250s
    c2 = _create_base_job(
        "C2_LATER",
        submit_time=base_t + timedelta(seconds=250),
        start_time=base_t + timedelta(seconds=250),
        end_time=base_t + timedelta(seconds=350),
        run_s=100,
        state="COMPLETED",
    )

    df = pl.DataFrame([p_fail, c1, c2])
    res = detect_retry_chains(df, retry_window_s=3600)

    # C1_EARLIER claims F_PARENT
    assert res.filter(pl.col("job_id") == "C1_EARLIER").select("retry_of").item() == "F_PARENT"
    assert (
        res.filter(pl.col("job_id") == "C1_EARLIER").select("retry_chain_id").item() == "F_PARENT"
    )

    # C2_LATER does NOT claim F_PARENT (already claimed)
    assert res.filter(pl.col("job_id") == "C2_LATER").select("retry_of").item() is None
    assert res.filter(pl.col("job_id") == "C2_LATER").select("retry_chain_id").item() is None


# ============================================================================
# 5. Grouping: empty, single-job, all-in-one, distinct groups
# ============================================================================


def test_grouping_empty_and_concat_schema() -> None:
    """Verify empty DataFrame grouping and compatibility when concatenated with non-empty results."""
    empty_df = pl.DataFrame()
    grouped_empty = group_jobs(empty_df)
    assert grouped_empty.height == 0
    assert "job_count" in grouped_empty.columns
    assert grouped_empty.schema["job_count"] == pl.Int64

    # Non-empty sample
    job = _create_base_job("G_SINGLE", user="bob", job_name="analysis", state="COMPLETED")
    attr_df = attribute_trace(pl.DataFrame([job]))
    grouped_single = group_jobs(attr_df)
    assert grouped_single.height == 1
    assert grouped_single.schema["job_count"] == pl.Int64

    # Verify concatenation between empty and non-empty result does not fail schema check
    combined = pl.concat([grouped_empty, grouped_single])
    assert combined.height == 1


def test_grouping_single_job_dataframe() -> None:
    """Verify grouping a single job calculates correct shares and sample count flags."""
    job = _create_base_job(
        "G1",
        user="dana",
        job_name="eval",
        state="COMPLETED",
        run_s=100,
        alloc_cpus=2,
        cpu_time_used_s=50.0,
        req_mem_mb=1000,
        max_rss_mb=500,
    )
    attr_df = attribute_trace(pl.DataFrame([job]))
    grouped = group_jobs(attr_df)

    assert grouped.height == 1
    row = grouped.to_dicts()[0]
    assert row["job_count"] == 1
    assert row["sample_count_ok"] is False  # default min_samples = 5
    assert row["cluster_reserved_core_share"] == 1.0
    assert row["cluster_waste_score_share"] == 1.0
    assert row["evidence_job_ids"] == ["G1"]


def test_grouping_all_jobs_in_single_group() -> None:
    """Verify aggregating N jobs belonging to identical group key."""
    jobs = [
        _create_base_job(f"SAME_{i}", user="eve", job_name="worker", state="COMPLETED", run_s=100)
        for i in range(10)
    ]
    attr_df = attribute_trace(pl.DataFrame(jobs))
    grouped = group_jobs(attr_df)

    assert grouped.height == 1
    row = grouped.to_dicts()[0]
    assert row["group"] == "eve/worker"
    assert row["job_count"] == 10
    assert row["sample_count_ok"] is True
    assert row["cluster_reserved_core_share"] == 1.0


def test_grouping_each_job_in_own_group() -> None:
    """Verify aggregating N jobs where each job defines a separate group."""
    n_groups = 6
    jobs = [
        _create_base_job(
            f"DIFF_{i}", user=f"user_{i}", job_name=f"task_{i}", state="COMPLETED", run_s=100
        )
        for i in range(n_groups)
    ]
    attr_df = attribute_trace(pl.DataFrame(jobs))
    grouped = group_jobs(attr_df)

    assert grouped.height == n_groups
    shares = grouped.select("cluster_reserved_core_share").to_series().to_list()
    assert pytest.approx(sum(shares), rel=1e-5) == 1.0


# ============================================================================
# 6. Division by zero and zero cluster waste
# ============================================================================


def test_grouping_zero_cluster_waste_division_by_zero_safety() -> None:
    """Verify zero cluster waste does not trigger division by zero or NaN values."""
    # Completed jobs with 100% CPU usage and RSS matching req_mem -> 0 waste
    jobs = [
        _create_base_job(
            f"PERF_{i}",
            user=f"user_{i}",
            job_name="clean_task",
            state="COMPLETED",
            run_s=100,
            alloc_cpus=2,
            req_mem_mb=1000,
            cpu_time_used_s=200.0,  # 200 CPU seconds / (2 cores * 100s) = 100% utilized
            max_rss_mb=1000,  # 1000 MB utilized out of 1000 MB req
        )
        for i in range(3)
    ]
    attr_df = attribute_trace(pl.DataFrame(jobs))
    grouped = group_jobs(attr_df)

    assert grouped.height == 3
    for row in grouped.iter_rows(named=True):
        assert row["reclaim_score"] == 0.0
        assert row["cluster_waste_score_share"] == 0.0
        assert not pl.Series([row["cluster_waste_score_share"]]).is_nan().item()


def test_grouping_zero_reserved_cores_division_by_zero_safety() -> None:
    """Verify zero reserved cores does not produce NaN or division errors."""
    jobs = [
        _create_base_job(
            "ZERO_CORE",
            user="user_zero",
            job_name="task_zero",
            state="COMPLETED",
            alloc_cpus=0,
            run_s=0,
            cpu_time_used_s=0.0,
            req_mem_mb=0,
            max_rss_mb=0,
        )
    ]
    attr_df = attribute_trace(pl.DataFrame(jobs))
    grouped = group_jobs(attr_df)

    assert grouped.height == 1
    row = grouped.to_dicts()[0]
    assert row["cluster_reserved_core_share"] == 0.0
    assert row["cluster_waste_score_share"] == 0.0


# ============================================================================
# 7. Tie-breaking in top-5 evidence selection
# ============================================================================


def test_grouping_deterministic_evidence_tie_breaking() -> None:
    """Verify deterministic evidence sampling tie-breaking with identical waste scores."""
    # Create 10 jobs with identical waste score and identical group
    # job_ids: J_00, J_01, ..., J_09
    jobs = [
        _create_base_job(
            f"TIE_{i:02d}",
            user="alice",
            job_name="bench",
            state="FAILED",
            run_s=100,
            alloc_cpus=2,
            req_mem_mb=1000,
        )
        for i in range(10)
    ]

    attr_df = attribute_trace(pl.DataFrame(jobs))

    # Run grouping on original order
    grouped1 = group_jobs(attr_df)
    ev_ids1 = grouped1.select("evidence_job_ids").item(0, 0).to_list()

    # Shuffled input order must produce the identical top 5 evidence list
    shuffled_df = attr_df.sample(fraction=1.0, shuffle=True, seed=42)
    grouped2 = group_jobs(shuffled_df)
    ev_ids2 = grouped2.select("evidence_job_ids").item(0, 0).to_list()

    # Lexicographically smallest 5 job_ids must be selected
    expected = ["TIE_00", "TIE_01", "TIE_02", "TIE_03", "TIE_04"]
    assert ev_ids1 == expected
    assert ev_ids2 == expected


# ============================================================================
# 8. Export verification: Parquet and CSV round-trips
# ============================================================================


def test_export_roundtrip_attributed_and_grouped(tmp_path: Path) -> None:
    """Verify writing and re-reading Parquet and CSV for attributed and grouped tables."""
    jobs = [
        _create_base_job("EXP_1", user="u1", job_name="j1", state="FAILED", run_s=60),
        _create_base_job("EXP_2", user="u1", job_name="j1", state="COMPLETED", run_s=120),
        _create_base_job("EXP_3", user="u2", job_name="j2", state="OUT_OF_MEMORY", run_s=180),
    ]
    attr_df = attribute_trace(pl.DataFrame(jobs))
    grouped_df = group_jobs(attr_df)

    # 1. Attributed records exports
    attr_p = tmp_path / "attr.parquet"
    attr_c = tmp_path / "attr.csv"
    export_attributed_records(attr_df, attr_p, format="parquet")
    export_attributed_records(attr_df, attr_c, format="csv")

    assert attr_p.exists()
    assert attr_c.exists()

    read_attr_p = pl.read_parquet(attr_p)
    assert read_attr_p.height == attr_df.height
    assert set(read_attr_p.columns) == set(attr_df.columns)

    read_attr_c = pl.read_csv(attr_c)
    assert read_attr_c.height == attr_df.height

    # 2. Grouped metrics exports
    grp_p = tmp_path / "groups.parquet"
    grp_c = tmp_path / "groups.csv"
    export_group_metrics(grouped_df, grp_p, format="parquet")
    export_group_metrics(grouped_df, grp_c, format="csv")

    assert grp_p.exists()
    assert grp_c.exists()

    read_grp_p = pl.read_parquet(grp_p)
    assert read_grp_p.height == grouped_df.height
    # List dtype check
    assert read_grp_p.schema["evidence_job_ids"] == pl.List(pl.String)

    read_grp_c = pl.read_csv(grp_c)
    assert read_grp_c.height == grouped_df.height
    # Semicolon delimited string verification
    ev_val = read_grp_c.select("evidence_job_ids").item(0, 0)
    assert isinstance(ev_val, str)
