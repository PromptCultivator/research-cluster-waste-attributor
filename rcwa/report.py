"""Reporting generator for cluster resource waste attribution.

Produces structured JSON, Markdown, and CSV summaries of resource utilization,
waste classification, ranked reclaim targets, data quality accounting, and
result cache recommendations.
"""

from typing import Any

import polars as pl

from rcwa.groups import group_jobs
from rcwa.recommend import recommend_jobs
from rcwa.recompute import simulate_result_cache


def build_report_data(
    canonical_df: pl.DataFrame,
    attributed_df: pl.DataFrame,
    policy: Any = None,
    cluster: Any = None,
    simulation_scenarios: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    include_simulation: bool = True,
) -> dict[str, Any]:
    """Compile comprehensive attribution and recommendation report structure.

    Args:
        canonical_df: Canonical jobs table prior to attribution exclusions.
        attributed_df: Attributed jobs table satisfying Guarantee G1.
        policy: Policy settings or configuration dictionary.

    Returns:
        Structured report data dictionary.
    """
    total_jobs = canonical_df.height
    evaluated_jobs = attributed_df.height
    excluded_jobs = max(0, total_jobs - evaluated_jobs)

    # Ensure required grouping columns exist
    if "job_name" not in attributed_df.columns:
        attributed_df = attributed_df.with_columns(pl.lit(None, dtype=pl.String).alias("job_name"))
    if "command_hash" not in attributed_df.columns:
        attributed_df = attributed_df.with_columns(
            pl.lit(None, dtype=pl.String).alias("command_hash")
        )
    if "exit_code" not in attributed_df.columns:
        attributed_df = attributed_df.with_columns(pl.lit(None, dtype=pl.Int32).alias("exit_code"))

    # Core hour conversion factor
    sec_to_hours = 3600.0
    mb_sec_to_gb_hours = 1024.0 * 3600.0

    res_core_s = float(attributed_df["reserved_core_s"].sum()) if evaluated_jobs > 0 else 0.0
    used_core_s = float(attributed_df["used_core_s"].sum()) if evaluated_jobs > 0 else 0.0
    res_mem_mb_s = float(attributed_df["reserved_mem_mb_s"].sum()) if evaluated_jobs > 0 else 0.0
    used_mem_mb_s = float(attributed_df["used_mem_mb_s"].sum()) if evaluated_jobs > 0 else 0.0

    c1_mem_s = (
        float(attributed_df["class1_over_mem_mb_s"].sum())
        if "class1_over_mem_mb_s" in attributed_df.columns
        else 0.0
    )
    c2_core_s = (
        float(attributed_df["class2_idle_core_s"].sum())
        if "class2_idle_core_s" in attributed_df.columns
        else 0.0
    )
    c3_core_s = (
        float(attributed_df["class3_core_s"].sum())
        if "class3_core_s" in attributed_df.columns
        else 0.0
    )
    c3_mem_s = (
        float(attributed_df["class3_mem_mb_s"].sum())
        if "class3_mem_mb_s" in attributed_df.columns
        else 0.0
    )
    c4_core_s = (
        float(attributed_df["class4_core_s"].sum())
        if "class4_core_s" in attributed_df.columns
        else 0.0
    )
    c4_mem_s = (
        float(attributed_df["class4_mem_mb_s"].sum())
        if "class4_mem_mb_s" in attributed_df.columns
        else 0.0
    )
    unattrib_core_s = (
        float(attributed_df["unattributed_core_s"].sum())
        if "unattributed_core_s" in attributed_df.columns
        else 0.0
    )
    unattrib_mem_s = (
        float(attributed_df["unattributed_mem_mb_s"].sum())
        if "unattributed_mem_mb_s" in attributed_df.columns
        else 0.0
    )

    summary = {
        "total_jobs": total_jobs,
        "evaluated_jobs": evaluated_jobs,
        "excluded_jobs": excluded_jobs,
        "total_reserved_core_hours": round(res_core_s / sec_to_hours, 2),
        "total_used_core_hours": round(used_core_s / sec_to_hours, 2),
        "total_reserved_gb_hours": round(res_mem_mb_s / mb_sec_to_gb_hours, 2),
        "total_used_gb_hours": round(used_mem_mb_s / mb_sec_to_gb_hours, 2),
    }

    # Detect if trace source is exclusively SWF
    is_swf = False
    if "source" in canonical_df.columns and canonical_df.height > 0:
        sources = canonical_df["source"].drop_nulls().unique().to_list()
        if sources and all(str(s).lower() == "swf" for s in sources):
            is_swf = True

    waste_classification: dict[str, Any] = {
        "class1_memory_over_request_gb_hours": round(c1_mem_s / mb_sec_to_gb_hours, 2),
        "class2_idle_cpu_core_hours": round(c2_core_s / sec_to_hours, 2),
        "class3_failed_work_core_hours": round(c3_core_s / sec_to_hours, 2),
        "class3_failed_work_gb_hours": round(c3_mem_s / mb_sec_to_gb_hours, 2),
        "class4_redundant_core_hours": 0.0 if is_swf else round(c4_core_s / sec_to_hours, 2),
        "class4_redundant_gb_hours": 0.0 if is_swf else round(c4_mem_s / mb_sec_to_gb_hours, 2),
        "unattributed_cpu_core_hours": round(unattrib_core_s / sec_to_hours, 2),
        "unattributed_memory_gb_hours": round(unattrib_mem_s / mb_sec_to_gb_hours, 2),
    }
    if is_swf:
        waste_classification["class4_status"] = "not available"

    # Data quality calculations
    unattrib_cpu_pct = round(100.0 * unattrib_core_s / max(1.0, res_core_s), 2)
    unattrib_mem_pct = round(100.0 * unattrib_mem_s / max(1.0, res_mem_mb_s), 2)
    valid_hash_expr = pl.col("input_hash").is_not_null() & (pl.col("input_hash") != "")
    declared_input_count = (
        canonical_df.filter(valid_hash_expr).height if "input_hash" in canonical_df.columns else 0
    )
    coverage_pct = round(100.0 * declared_input_count / max(1, total_jobs), 2)

    data_quality = {
        "excluded_active_count": excluded_jobs,
        "unattributed_cpu_share_pct": unattrib_cpu_pct,
        "unattributed_memory_share_pct": unattrib_mem_pct,
        "declared_input_coverage_pct": coverage_pct,
    }

    # Generate recommendations table
    recs_df = recommend_jobs(attributed_df, policy=policy)
    recs_dicts = recs_df.to_dicts() if recs_df.height > 0 else []

    ranked_reclaim_list: list[dict[str, Any]] = []
    for idx, r in enumerate(recs_dicts, start=1):
        grp_name = str(r.get("group_key") or r.get("group") or "")
        ev_ids_raw = r.get("evidence_job_ids") or []
        if isinstance(ev_ids_raw, str):
            ev_ids = [item.strip() for item in ev_ids_raw.split(";") if item.strip()]
        elif isinstance(ev_ids_raw, list):
            ev_ids = [str(x) for x in ev_ids_raw]
        else:
            ev_ids = []

        rec_core = round(
            float(r.get("reclaimable_core_hours") or r.get("reclaim_core_hours") or 0.0), 2
        )
        rec_gb = round(float(r.get("reclaimable_gb_hours") or r.get("reclaim_gb_hours") or 0.0), 2)
        score = round(float(r.get("reclaim_score") or r.get("score") or 0.0), 2)
        rec_action = str(
            r.get("recommendation_action") or r.get("recommendation_direction") or "none"
        )

        rec_entry: dict[str, Any] = {
            "rank": idx,
            "group": grp_name,
            "count": int(r.get("job_count") or r.get("count") or 0),
            "reclaim_core_hours": rec_core,
            "reclaim_gb_hours": rec_gb,
            "score": score,
            "recommendation": {
                "req_mem_mb": r.get("recommended_req_mem_mb"),
                "cpus": r.get("recommended_cpus"),
                "direction": r.get("recommendation_direction"),
            },
            "recommendation_action": rec_action,
            "evidence_job_ids": ev_ids,
        }
        ranked_reclaim_list.append(rec_entry)

    # Calculate early failure groups
    early_failure_groups: list[dict[str, Any]] = []
    if evaluated_jobs > 0 and "class3_sub_label" in attributed_df.columns:
        # Group by group_key or user/job_name
        grp_col = pl.col("group_key") if "group_key" in attributed_df.columns else pl.col("user")
        grouped_early = (
            attributed_df.group_by(grp_col)
            .agg(
                [
                    pl.len().alias("total_jobs"),
                    (pl.col("class3_sub_label") == "early_failure").sum().alias("early_fail_count"),
                    pl.col("exit_code").drop_nulls().unique().alias("exit_codes"),
                ]
            )
            .filter(pl.col("early_fail_count") > 0)
        )
        for ef in grouped_early.to_dicts():
            tot = ef.get("total_jobs") or 1
            fails = ef.get("early_fail_count") or 0
            codes = ef.get("exit_codes") or []
            if not isinstance(codes, list):
                codes = [codes]
            early_failure_groups.append(
                {
                    "group": str(ef.get("group_key") or ef.get("user") or ""),
                    "failure_count": int(fails),
                    "total_jobs": int(tot),
                    "failure_share": round(float(fails) / float(tot), 4),
                    "sample_exit_codes": [int(c) for c in codes[:5]],
                }
            )

    # Result cache simulation
    cache_sim = simulate_result_cache(attributed_df)

    # Secondary rollups
    secondary_rollups: dict[str, list[dict[str, Any]]] = {}
    for dim in ["user", "account", "partition"]:
        if dim in attributed_df.columns:
            dim_grouped = group_jobs(attributed_df, group_keys=[dim], policy=policy)
            secondary_rollups[dim] = dim_grouped.to_dicts()

    # Dynamic simulation scenarios
    if simulation_scenarios is not None:
        scenarios_data = simulation_scenarios
    elif include_simulation and evaluated_jobs > 0:
        from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace

        if cluster is not None:
            cluster_cfg = load_cluster_config(cluster)
        else:
            cluster_cfg = infer_cluster_from_trace(canonical_df)

        scenarios_data = {}
        for sc in [
            "baseline",
            "mem_rightsized",
            "cpu_rightsized_none",
            "cpu_rightsized_proportional",
            "cache_dedup",
            "all",
        ]:
            try:
                _, s_metrics = simulate_trace(
                    canonical_df, cluster=cluster_cfg, scenario=sc, policy=policy
                )
                scenarios_data[sc] = {
                    "median_wait_s": float(s_metrics.get("median_wait_s", 0.0)),
                    "p95_wait_s": float(s_metrics.get("p95_wait_s", 0.0)),
                    "makespan_s": int(s_metrics.get("makespan_s", 0)),
                    "core_utilization_pct": round(
                        float(s_metrics.get("core_utilization", 0.0)) * 100.0, 1
                    ),
                    "memory_utilization_pct": round(
                        float(s_metrics.get("mem_utilization", 0.0)) * 100.0, 1
                    ),
                    "jobs_per_day": float(s_metrics.get("jobs_completed_per_day", 0.0)),
                }
            except Exception:
                pass
    else:
        scenarios_data = {}

    # Dynamic calibration metrics
    if calibration is not None:
        calib_data = calibration
    elif include_simulation and evaluated_jobs > 0 and "wait_s" in canonical_df.columns:
        from rcwa.calibrate import compute_calibration_metrics
        from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace

        if cluster is not None:
            cluster_cfg = load_cluster_config(cluster)
        else:
            cluster_cfg = infer_cluster_from_trace(canonical_df)
        try:
            sim_df, _ = simulate_trace(
                canonical_df, cluster=cluster_cfg, scenario="baseline", policy=policy
            )
            calib_res = compute_calibration_metrics(sim_df, canonical_df)
            calib_data = {
                "median_absolute_error_s": float(calib_res.get("median_absolute_error_s", 0.0)),
                "spearman_rank_correlation": float(calib_res.get("spearman_rank_correlation", 0.0)),
            }
        except Exception:
            calib_data = {}
    else:
        calib_data = {}

    report: dict[str, Any] = {
        "summary": summary,
        "waste_classification": waste_classification,
        "ranked_reclaim_list": ranked_reclaim_list,
        "data_quality": data_quality,
        "early_failure_groups": early_failure_groups,
        "result_cache": cache_sim,
        "secondary_rollups": secondary_rollups,
        "simulation_scenarios": scenarios_data,
        "calibration": calib_data,
    }

    return _round_floats(report, digits=6)


def _round_floats(val: Any, digits: int = 6) -> Any:
    """Recursively round floating-point metrics for Guarantee G3 determinism."""
    if isinstance(val, float):
        return round(val, digits)
    if isinstance(val, dict):
        return {k: _round_floats(v, digits) for k, v in sorted(val.items())}
    if isinstance(val, list):
        return [_round_floats(item, digits) for item in val]
    return val


def render_markdown_report(report_data: dict[str, Any]) -> str:
    """Format structured report data as GitHub-compatible Markdown.

    Args:
        report_data: Dictionary compiled by build_report_data.

    Returns:
        Formatted Markdown text document.
    """
    sum_data = report_data.get("summary", {})
    waste = report_data.get("waste_classification", {})
    ranked = report_data.get("ranked_reclaim_list", [])
    quality = report_data.get("data_quality", {})

    lines: list[str] = [
        "# Research Cluster Waste Attribution Report",
        "",
        "## Summary",
        f"- Total Jobs: {sum_data.get('total_jobs', 0)}",
        f"- Evaluated Jobs: {sum_data.get('evaluated_jobs', 0)}",
        f"- Excluded Jobs (RUNNING/PENDING): {sum_data.get('excluded_jobs', 0)}",
        f"- Total Reserved Core-Hours: {sum_data.get('total_reserved_core_hours', 0.0):.2f}",
        f"- Total Used Core-Hours: {sum_data.get('total_used_core_hours', 0.0):.2f}",
        f"- Total Reserved GB-Hours: {sum_data.get('total_reserved_gb_hours', 0.0):.2f}",
        f"- Total Used GB-Hours: {sum_data.get('total_used_gb_hours', 0.0):.2f}",
        "",
        "## Waste Classification",
        "| Waste Class | Core-Hours | Share % | GB-Hours | Share % |",
        "|---|---|---|---|---|",
    ]

    total_core = max(0.01, float(sum_data.get("total_reserved_core_hours") or 1.0))
    total_gb = max(0.01, float(sum_data.get("total_reserved_gb_hours") or 1.0))

    c1_gb = float(waste.get("class1_memory_over_request_gb_hours", 0.0))
    c2_core = float(waste.get("class2_idle_cpu_core_hours", 0.0))
    c3_core = float(waste.get("class3_failed_work_core_hours", 0.0))
    c3_gb = float(waste.get("class3_failed_work_gb_hours", 0.0))
    c4_core = float(waste.get("class4_redundant_core_hours", 0.0))
    c4_gb = float(waste.get("class4_redundant_gb_hours", 0.0))
    used_core = float(sum_data.get("total_used_core_hours", 0.0))
    used_gb = float(sum_data.get("total_used_gb_hours", 0.0))
    unatt_core = float(waste.get("unattributed_cpu_core_hours", 0.0))
    unatt_gb = float(waste.get("unattributed_memory_gb_hours", 0.0))

    c1_pct = 100 * c1_gb / total_gb
    lines.append(f"| Class 1: Memory Over-Request | - | - | {c1_gb:.2f} | {c1_pct:.2f}% |")

    c2_pct = 100 * c2_core / total_core
    lines.append(f"| Class 2: Idle Reserved CPU | {c2_core:.2f} | {c2_pct:.2f}% | - | - |")

    c3_c_pct = 100 * c3_core / total_core
    c3_g_pct = 100 * c3_gb / total_gb
    lines.append(
        f"| Class 3: Failed & Retried Work | {c3_core:.2f} | {c3_c_pct:.2f}% | "
        f"{c3_gb:.2f} | {c3_g_pct:.2f}% |"
    )

    c4_c_pct = 100 * c4_core / total_core
    c4_g_pct = 100 * c4_gb / total_gb
    if waste.get("class4_status") == "not available":
        lines.append("| Class 4: Redundant Recomputation | not available | - | not available | - |")
    else:
        lines.append(
            f"| Class 4: Redundant Recomputation | {c4_core:.2f} | {c4_c_pct:.2f}% | "
            f"{c4_gb:.2f} | {c4_g_pct:.2f}% |"
        )

    used_c_pct = 100 * used_core / total_core
    used_g_pct = 100 * used_gb / total_gb
    lines.append(
        f"| Used | {used_core:.2f} | {used_c_pct:.2f}% | " f"{used_gb:.2f} | {used_g_pct:.2f}% |"
    )

    unatt_c_pct = 100 * unatt_core / total_core
    unatt_g_pct = 100 * unatt_gb / total_gb
    lines.append(
        f"| Unattributed Missing | {unatt_core:.2f} | {unatt_c_pct:.2f}% | "
        f"{unatt_gb:.2f} | {unatt_g_pct:.2f}% |"
    )
    lines.append("")
    lines.append("## Ranked Reclaim List")
    lines.append(
        "| Rank | Group | Count | Reclaim Core-Hours | Reclaim GB-Hours | "
        "Score | Recommendation | Evidence Job IDs |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")

    for r in ranked:
        rank = r.get("rank", 1)
        grp = r.get("group", "")
        cnt = r.get("count", 0)
        rec_core = float(r.get("reclaim_core_hours", 0.0))
        rec_gb = float(r.get("reclaim_gb_hours", 0.0))
        score = float(r.get("score", 0.0))
        rec = r.get("recommendation") or {}
        action = str(r.get("recommendation_action") or rec.get("direction") or "none")
        mem = rec.get("req_mem_mb")
        cpus = rec.get("cpus")
        if action == "below_sample_floor" or rec.get("direction") == "below_sample_floor":
            rec_str = "None (< min_samples)"
        elif action in ("oom_increase_mem", "oom_escalation") or (
            rec.get("direction") == "increase" and mem is not None and cpus is None
        ):
            rec_str = f"req_mem_mb={mem}M (OOM escalation)"
        elif mem is not None or cpus is not None:
            parts = []
            if mem is not None:
                parts.append(f"req_mem_mb={mem}M")
            if cpus is not None:
                parts.append(f"cpus={cpus}")
            rec_str = ", ".join(parts)
        else:
            rec_str = "None"
        ev_raw = r.get("evidence_job_ids", [])
        if isinstance(ev_raw, list):
            ev_str = ", ".join(str(x) for x in ev_raw)
        else:
            ev_str = str(ev_raw)
        lines.append(
            f"| {rank} | {grp} | {cnt} | {rec_core:.2f} | {rec_gb:.2f} | "
            f"{score:.2f} | {rec_str} | {ev_str} |"
        )

    lines.append("")
    lines.append("## Data Quality Accounting")
    lines.append(f"- Active Jobs Excluded: {quality.get('excluded_active_count', 0)}")
    cpu_share = quality.get("unattributed_cpu_share_pct", 0.0)
    lines.append(f"- Unattributed CPU Share: {cpu_share:.2f}%")
    mem_share = quality.get("unattributed_memory_share_pct", 0.0)
    lines.append(f"- Unattributed Memory Share: {mem_share:.2f}%")
    input_cov = quality.get("declared_input_coverage_pct", 0.0)
    lines.append(f"- Declared Input Coverage: {input_cov:.2f}%")
    lines.append("")

    early_failures = report_data.get("early_failure_groups", [])
    if early_failures:
        lines.append("## Early Failure Groups")
        lines.append("| Group | Failures | Total | Share % | Sample Exit Codes |")
        lines.append("|---|---|---|---|---|")
        for ef in early_failures:
            grp = ef.get("group", "")
            fc = ef.get("failure_count", 0)
            tot = ef.get("total_jobs", 0)
            pct = 100.0 * float(ef.get("failure_share", 0.0))
            codes = ", ".join(str(c) for c in ef.get("sample_exit_codes", []))
            lines.append(f"| {grp} | {fc} | {tot} | {pct:.2f}% | {codes} |")
        lines.append("")

    cache_res = report_data.get("result_cache", [])
    if isinstance(cache_res, list) and any(r.get("recommended") for r in cache_res):
        recommended_caches = [r for r in cache_res if r.get("recommended")]
        lines.append("## Result Cache Recommendations")
        lines.append(
            "| Group | Completed Jobs | Cache Hits | Hit Rate % | "
            "Reclaim Core-Hours | Reclaim GB-Hours |"
        )
        lines.append("|---|---|---|---|---|---|")
        for c in recommended_caches:
            grp = c.get("group", "")
            tc = c.get("total_completed_jobs", 0)
            hits = c.get("cache_hits", 0)
            hr = float(c.get("hit_rate", 0.0)) * 100.0
            r_c = float(c.get("reclaimable_core_hours", 0.0))
            r_g = float(c.get("reclaimable_gb_hours", 0.0))
            lines.append(f"| {grp} | {tc} | {hits} | {hr:.1f}% | {r_c:.2f} | {r_g:.2f} |")
        lines.append("")
    elif isinstance(cache_res, dict) and cache_res.get("recomputation_groups_count", 0) > 0:
        lines.append("## Result Cache Recommendations")
        lines.append(
            f"- Recomputation Groups Detected: {cache_res.get('recomputation_groups_count', 0)}"
        )
        hr = float(cache_res.get("cache_hit_rate_pct", 0.0))
        lines.append(f"- Simulated Cache Hit Rate: {hr:.2f}%")
        rc_c = float(cache_res.get("reclaimable_core_hours", 0.0))
        lines.append(f"- Reclaimable Redundant Core-Hours: {rc_c:.2f}")
        rc_g = float(cache_res.get("reclaimable_gb_hours", 0.0))
        lines.append(f"- Reclaimable Redundant GB-Hours: {rc_g:.2f}")
        lines.append("")

    scenarios = report_data.get("simulation_scenarios", {})
    if scenarios:
        lines.append("## Simulation Scenarios")
        lines.append(
            "| Scenario | Median Wait (s) | P95 Wait (s) | Makespan (s) | "
            "Core Utilization % | Memory Utilization % | Jobs/Day |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for sc_name in [
            "baseline",
            "mem_rightsized",
            "cpu_rightsized_none",
            "cpu_rightsized_proportional",
            "cache_dedup",
            "all",
        ]:
            if sc_name in scenarios:
                sc = scenarios[sc_name]
                med = float(sc.get("median_wait_s", 0.0))
                p95 = float(sc.get("p95_wait_s", 0.0))
                ms = int(sc.get("makespan_s", 0))
                cu = float(sc.get("core_utilization_pct", 0.0))
                mu = float(sc.get("memory_utilization_pct", 0.0))
                jpd = float(sc.get("jobs_per_day", 0.0))
                lines.append(
                    f"| {sc_name} | {med:.1f} | {p95:.1f} | {ms} | "
                    f"{cu:.1f}% | {mu:.1f}% | {jpd:.2f} |"
                )
        lines.append("")

    calib = report_data.get("calibration", {})
    if calib:
        lines.append("## Calibration Metrics")
        lines.append("- Historical Baseline Calibration Error:")
        mae = float(calib.get("median_absolute_error_s", 0.0))
        lines.append(f"  - Median Absolute Error: {mae:.2f} s")
        rho = float(calib.get("spearman_rank_correlation", 0.0))
        lines.append(f"  - Spearman Rank Correlation: {rho:.3f}")
        lines.append("")

    return "\n".join(lines)


def render_csv_report(report_data: dict[str, Any]) -> str:
    """Format ranked reclaim list as CSV table.

    Args:
        report_data: Dictionary compiled by build_report_data.

    Returns:
        CSV string content.
    """
    ranked = report_data.get("ranked_reclaim_list", [])
    headers = [
        "rank",
        "group",
        "count",
        "reclaim_core_hours",
        "reclaim_gb_hours",
        "score",
        "recommendation_action",
        "evidence_job_ids",
    ]
    rows: list[str] = [",".join(headers)]

    for r in ranked:
        rank = str(r.get("rank", 1))
        grp = str(r.get("group", ""))
        cnt = str(r.get("count", 0))
        rec_core = f"{float(r.get('reclaim_core_hours', 0.0)):.2f}"
        rec_gb = f"{float(r.get('reclaim_gb_hours', 0.0)):.2f}"
        score = f"{float(r.get('score', 0.0)):.2f}"
        rec = r.get("recommendation") or {}
        action = str(r.get("recommendation_action") or rec.get("direction") or "none")
        ev_raw = r.get("evidence_job_ids", [])
        if isinstance(ev_raw, list):
            ev_ids = ";".join(str(x) for x in ev_raw)
        else:
            ev_ids = str(ev_raw)
        rows.append(f'{rank},{grp},{cnt},{rec_core},{rec_gb},{score},{action},"{ev_ids}"')

    return "\n".join(rows) + "\n"
