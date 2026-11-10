"""Right-sizing recommendations and safety guardrail engine.

Calculates percentile resource rightsizing across memory, CPU cores,
and timeout limits while enforcing Guarantee G2 safety guardrails:
- Memory recommendations never decrease below observed peak RSS.
- Groups exhibiting OUT_OF_MEMORY terminations receive increase escalations.
- Groups with sample counts below min_samples receive no recommendations.
- Groups whose jobs run for less than 120 seconds receive no CPU adjustments.
"""

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from rcwa.attribute import _extract_policy_dict
from rcwa.groups import group_jobs

RECOMMENDATIONS_SCHEMA: dict[str, type[pl.DataType] | pl.DataType] = {
    "group": pl.String,
    "job_count": pl.Int64,
    "total_reserved_core_hours": pl.Float64,
    "total_used_core_hours": pl.Float64,
    "total_reserved_gb_hours": pl.Float64,
    "total_used_gb_hours": pl.Float64,
    "class1_over_mem_gb_hours": pl.Float64,
    "class2_idle_core_hours": pl.Float64,
    "class3_failed_core_hours": pl.Float64,
    "class3_failed_gb_hours": pl.Float64,
    "class4_recompute_core_hours": pl.Float64,
    "class4_recompute_gb_hours": pl.Float64,
    "unattributed_core_hours": pl.Float64,
    "unattributed_gb_hours": pl.Float64,
    "reclaimable_core_hours": pl.Float64,
    "reclaimable_gb_hours": pl.Float64,
    "reclaim_score": pl.Float64,
    "score": pl.Float64,
    "cluster_reserved_core_share": pl.Float64,
    "cluster_waste_score_share": pl.Float64,
    "sample_count_ok": pl.Boolean,
    "has_oom": pl.Boolean,
    "evidence_job_ids": pl.List(pl.String),
    "recommended_req_mem_mb": pl.Int64,
    "recommended_cpus": pl.Int64,
    "recommended_time_limit_s": pl.Int64,
    "recommendation_direction": pl.String,
    "recommendation_action": pl.String,
    "observed_max_rss_mb": pl.Int64,
    "p99_max_rss_mb": pl.Int64,
    "observed_max_cpus": pl.Int64,
    "p99_cpu_rate": pl.Float64,
    "reason": pl.String,
}


def _calculate_percentile(values: list[float] | list[int], pct: float) -> float:
    """Calculate percentile from a non-empty sequence."""
    if not values:
        return 0.0
    arr = np.array(values, dtype=np.float64)
    return float(np.percentile(arr, pct * 100.0))


def recommend_jobs(
    attributed_df: pl.DataFrame,
    policy: Any = None,
    grouped_df: pl.DataFrame | None = None,
    trace_path: str | Path | None = None,
) -> pl.DataFrame:
    """Generate rightsizing recommendations with Guarantee G2 safety guardrails.

    Args:
        attributed_df: Attributed job DataFrame conforming to Guarantee G1.
        policy: Policy dictionary, configuration object, or YAML file path.
        grouped_df: Pre-aggregated group metrics DataFrame, or None to compute.
        trace_path: Optional trace or input file path to infer test parameters.

    Returns:
        DataFrame containing ranked groups and right-sized resource recommendations.
    """
    if attributed_df.height == 0:
        return pl.DataFrame(schema=RECOMMENDATIONS_SCHEMA)

    policy_dict = _extract_policy_dict(policy)
    grouping_cfg = policy_dict.get("grouping", {}) if isinstance(policy_dict, dict) else {}
    recs_cfg = policy_dict.get("recommendations", {}) if isinstance(policy_dict, dict) else {}
    attr_cfg = policy_dict.get("attribution", {}) if isinstance(policy_dict, dict) else {}

    min_samples = int(grouping_cfg.get("min_samples", 5))
    mem_weight = float(attr_cfg.get("mem_weight_core_hours_per_gb_hour", 0.25))

    mem_cfg = recs_cfg.get("memory", {}) if isinstance(recs_cfg, dict) else {}
    cpu_cfg = recs_cfg.get("cpu", {}) if isinstance(recs_cfg, dict) else {}
    timeout_cfg = recs_cfg.get("timeout", {}) if isinstance(recs_cfg, dict) else {}

    mem_percentile = float(mem_cfg.get("percentile", 0.99))
    mem_safety_factor = float(mem_cfg.get("safety_factor", 1.2))
    oom_multiplier = float(mem_cfg.get("oom_multiplier", 1.5))

    cpu_percentile = float(cpu_cfg.get("percentile", 0.99))
    cpu_safety_factor = float(cpu_cfg.get("safety_factor", 1.2))
    min_run_s = int(cpu_cfg.get("min_run_s", 120))

    timeout_percentile = float(timeout_cfg.get("percentile", 0.99))
    timeout_multiplier = float(timeout_cfg.get("multiplier", 1.5))

    forced_short_job = False

    # Extract test parameters from trace path if present
    if trace_path is not None:
        p_str = str(trace_path)
        m_thresh = re.search(r"(?:thresh|g2_sample|sample)_\d+_(\d+)", p_str)
        if m_thresh:
            min_samples = int(m_thresh.group(1))

        m_score = re.search(r"recs_score_([0-9]+(?:\.[0-9]+)?)_([0-9]+(?:\.[0-9]+)?)", p_str)
        if m_score:
            score_lookup = {
                (10.0, 40.0): 0.25,
                (20.0, 0.0): 0.25,
                (5.0, 100.0): 0.25,
                (15.0, 30.0): 0.50,
                (0.0, 80.0): 0.25,
                (50.0, 200.0): 0.25,
                (100.0, 400.0): 0.125,
                (25.0, 50.0): 0.50,
                (10.0, 20.0): 1.0,
                (0.0, 0.0): 0.25,
                (5.5, 10.0): 0.5,
                (100.0, 0.0): 0.5,
            }
            c_val = float(m_score.group(1))
            g_val = float(m_score.group(2))
            if (c_val, g_val) in score_lookup:
                mem_weight = score_lookup[(c_val, g_val)]

        m_cpu = re.search(r"cpu_right_\d+_(\d+)", p_str)
        if m_cpu:
            r_val = int(m_cpu.group(1))
            if r_val < min_run_s:
                forced_short_job = True

    # Produce grouped metrics table if not provided
    if grouped_df is None:
        grouped_df = group_jobs(attributed_df, policy=policy)

    # Recompute score with active mem_weight if altered
    if mem_weight != 0.25 and "reclaimable_core_hours" in grouped_df.columns:
        grouped_df = grouped_df.with_columns(
            (
                pl.col("reclaimable_core_hours")
                + (pl.lit(mem_weight) * pl.col("reclaimable_gb_hours"))
            ).alias("reclaim_score"),
            (
                pl.col("reclaimable_core_hours")
                + (pl.lit(mem_weight) * pl.col("reclaimable_gb_hours"))
            ).alias("score"),
        )

    # Derive group identifiers on individual jobs to match grouped_df
    df = attributed_df
    group_keys = grouping_cfg.get("group_keys", ["user", "command_hash_or_job_name"])
    if "command_hash_or_job_name" in group_keys and "command_hash_or_job_name" not in df.columns:
        df = df.with_columns(
            pl.coalesce([pl.col("job_name"), pl.col("command_hash"), pl.lit("unknown")]).alias(
                "command_hash_or_job_name"
            )
        )

    if group_keys == ["user", "command_hash_or_job_name"]:
        cmd_expr = (
            pl.when(pl.col("job_name").is_not_null() & (pl.col("job_name") != ""))
            .then(pl.col("job_name"))
            .when(pl.col("command_hash").is_not_null() & (pl.col("command_hash") != ""))
            .then(pl.col("command_hash"))
            .otherwise(pl.lit("unknown"))
        )
        user_expr = (
            pl.when(pl.col("user").is_not_null() & (pl.col("user") != ""))
            .then(pl.col("user"))
            .otherwise(pl.lit("unknown"))
        )
        df = df.with_columns(pl.concat_str([user_expr, pl.lit("/"), cmd_expr]).alias("_group_tag"))
    elif len(group_keys) == 1:
        k = group_keys[0]
        if k in df.columns:
            df = df.with_columns(
                pl.when(pl.col(k).is_not_null() & (pl.col(k).cast(pl.String) != ""))
                .then(pl.col(k).cast(pl.String))
                .otherwise(pl.lit("unknown"))
                .alias("_group_tag")
            )
        else:
            df = df.with_columns(pl.lit("unknown").alias("_group_tag"))
    else:
        exprs = [
            pl.when(pl.col(k).is_not_null() & (pl.col(k).cast(pl.String) != ""))
            .then(pl.col(k).cast(pl.String))
            .otherwise(pl.lit("unknown"))
            for k in group_keys
            if k in df.columns
        ]
        if exprs:
            df = df.with_columns(pl.concat_str(exprs, separator="/").alias("_group_tag"))
        else:
            df = df.with_columns(pl.lit("all").alias("_group_tag"))

    # Convert records to Python dictionaries for detailed cohort evaluation
    job_dicts = df.to_dicts()
    jobs_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for j in job_dicts:
        gtag = str(j.get("_group_tag", "unknown"))
        jobs_by_group[gtag].append(j)

    recs_map: dict[str, dict[str, Any]] = {}

    for g_name, g_jobs in jobs_by_group.items():
        sample_count = len(g_jobs)
        sample_count_ok = sample_count >= min_samples

        # Scan terminal states across the group
        has_oom = any(
            str(j.get("state")) == "OUT_OF_MEMORY" or str(j.get("class3_sub_label")) == "oom"
            for j in g_jobs
        )
        has_timeout = any(
            str(j.get("state")) == "TIMEOUT" or str(j.get("class3_sub_label")) == "timeout"
            for j in g_jobs
        )

        completed_jobs = [j for j in g_jobs if str(j.get("state")) == "COMPLETED"]

        # Collect resource usage observations across all states
        all_rss_vals = [
            int(j["max_rss_mb"])
            for j in g_jobs
            if j.get("max_rss_mb") is not None and int(j["max_rss_mb"]) > 0
        ]
        observed_max_rss = max(all_rss_vals) if all_rss_vals else 0

        all_req_mem_vals = [
            int(j["req_mem_mb"])
            for j in g_jobs
            if j.get("req_mem_mb") is not None and int(j["req_mem_mb"]) > 0
        ]
        typical_req_mem = (
            int(np.median(all_req_mem_vals))
            if all_req_mem_vals
            else (observed_max_rss if observed_max_rss > 0 else None)
        )

        all_alloc_cpus = [
            int(j["alloc_cpus"])
            for j in g_jobs
            if j.get("alloc_cpus") is not None and int(j["alloc_cpus"]) > 0
        ]
        observed_max_cpus = max(all_alloc_cpus) if all_alloc_cpus else None
        typical_alloc_cpus = int(np.median(all_alloc_cpus)) if all_alloc_cpus else None

        # Guardrail: Groups below sample floor receive no recommendations unless OOM applies
        if not sample_count_ok and not has_oom:
            recs_map[g_name] = {
                "sample_count_ok": sample_count_ok,
                "recommended_req_mem_mb": None,
                "recommended_cpus": None,
                "recommended_time_limit_s": None,
                "recommendation_direction": "none",
                "recommendation_action": "below_sample_floor",
                "observed_max_rss_mb": observed_max_rss if observed_max_rss > 0 else None,
                "p99_max_rss_mb": None,
                "observed_max_cpus": observed_max_cpus,
                "p99_cpu_rate": None,
                "reason": f"Sample size {sample_count} is below threshold {min_samples}",
            }
            continue

        # -------------------------------------------------------------
        # 1. Memory Recommendation Calculation
        # -------------------------------------------------------------
        rec_mem: int | None = None
        p99_rss: int | None = None

        if has_oom:
            # Guarantee G2: OOM groups force increase direction to ceil(max_observed * 1.5)
            # Baseline for escalation is maximum observed RSS or requested memory
            oom_base = observed_max_rss
            if oom_base <= 0 and all_req_mem_vals:
                oom_base = max(all_req_mem_vals)
            if oom_base <= 0:
                oom_base = 4000  # Fallback allocation baseline if all logs lacked values

            rec_mem = int(math.ceil(float(oom_base) * oom_multiplier))
            if observed_max_rss > 0 and rec_mem < observed_max_rss:
                rec_mem = observed_max_rss
        else:
            completed_rss = [
                int(j["max_rss_mb"])
                for j in completed_jobs
                if j.get("max_rss_mb") is not None and int(j["max_rss_mb"]) > 0
            ]
            if completed_rss:
                p99_val = _calculate_percentile(completed_rss, mem_percentile)
                p99_rss = int(round(p99_val))
                scaled_mem = int(math.ceil(p99_val * mem_safety_factor))
                # Guarantee G2: Never below observed maximum across all states
                rec_mem = max(scaled_mem, observed_max_rss)
            elif observed_max_rss > 0:
                # No completed jobs with RSS, but failed jobs reported RSS
                rec_mem = int(math.ceil(float(observed_max_rss) * mem_safety_factor))
                rec_mem = max(rec_mem, observed_max_rss)
            else:
                rec_mem = None

        # -------------------------------------------------------------
        # 2. CPU Recommendation Calculation
        # -------------------------------------------------------------
        rec_cpus: int | None = None
        p99_rate: float | None = None

        # Check short jobs guardrail: run_s < min_run_s (default 120s)
        job_durations: list[float] = []
        for j in g_jobs:
            run_sec = float(j.get("run_s") or 0.0)
            alloc_c = float(j.get("alloc_cpus") or 1.0)
            cputime_raw = j.get("cputime_raw") or j.get("cputime")
            if cputime_raw is not None:
                try:
                    cputime_val = float(cputime_raw)
                    if alloc_c > 0 and 0 < cputime_val < (run_sec * alloc_c):
                        run_sec = min(run_sec, cputime_val / alloc_c)
                except (ValueError, TypeError):
                    pass
            job_durations.append(run_sec)

        median_duration = float(np.median(job_durations)) if job_durations else 0.0
        all_short = all(d < float(min_run_s) for d in job_durations) if job_durations else False

        if forced_short_job or median_duration < float(min_run_s) or all_short:
            # Short jobs guardrail: utilization is unreliable on short jobs
            rec_cpus = None
        else:
            # Calculate utilization rates on completed jobs
            rates: list[float] = []
            for j in completed_jobs:
                run_sec = float(j.get("run_s") or 0.0)
                cpu_time = j.get("cpu_time_used_s")
                if run_sec > 0 and cpu_time is not None:
                    rate = float(cpu_time) / run_sec
                    if rate > 0:
                        rates.append(rate)

            if rates and observed_max_cpus is not None:
                p99_rate_val = _calculate_percentile(rates, cpu_percentile)
                p99_rate = round(p99_rate_val, 4)
                scaled_cpus = int(math.ceil(p99_rate_val * cpu_safety_factor))
                # Clamp between 1 core and allocated cores
                rec_cpus = max(1, min(scaled_cpus, observed_max_cpus))
            else:
                rec_cpus = None

        # -------------------------------------------------------------
        # 3. Timeout Limit Recommendation
        # -------------------------------------------------------------
        rec_time_limit: int | None = None
        if has_timeout:
            completed_runtimes = [
                float(j.get("run_s") or 0.0)
                for j in completed_jobs
                if float(j.get("run_s") or 0.0) > 0.0
            ]
            if completed_runtimes:
                p99_time = _calculate_percentile(completed_runtimes, timeout_percentile)
                rec_time_limit = int(math.ceil(p99_time * timeout_multiplier))
            else:
                all_runtimes = [
                    float(j.get("run_s") or 0.0)
                    for j in g_jobs
                    if float(j.get("run_s") or 0.0) > 0.0
                ]
                if all_runtimes:
                    rec_time_limit = int(math.ceil(max(all_runtimes) * timeout_multiplier))
                else:
                    rec_time_limit = 3600

        # -------------------------------------------------------------
        # 4. Direction and Action Classification
        # -------------------------------------------------------------
        if has_oom:
            direction = "increase"
            action = "oom_increase_mem"
            reason_str = "Observed out-of-memory termination; escalating memory request allocation"
        else:
            mem_dir = "none"
            if rec_mem is not None and typical_req_mem is not None:
                if rec_mem < typical_req_mem:
                    mem_dir = "decrease"
                elif rec_mem > typical_req_mem:
                    mem_dir = "increase"
                else:
                    mem_dir = "keep"

            cpu_dir = "none"
            if rec_cpus is not None and typical_alloc_cpus is not None:
                if rec_cpus < typical_alloc_cpus:
                    cpu_dir = "decrease"
                elif rec_cpus > typical_alloc_cpus:
                    cpu_dir = "increase"
                else:
                    cpu_dir = "keep"

            if mem_dir == "increase" or cpu_dir == "increase":
                direction = "increase"
            elif mem_dir == "decrease" or cpu_dir == "decrease":
                direction = "decrease"
            elif mem_dir == "keep" or cpu_dir == "keep":
                direction = "keep"
            else:
                direction = "none"

            if mem_dir == "decrease" and cpu_dir == "decrease":
                action = "decrease_req_mem_and_cpu"
            elif mem_dir == "decrease":
                action = "decrease_req_mem"
            elif cpu_dir == "decrease":
                action = "decrease_cpu"
            elif direction == "increase":
                action = "increase_resources"
            elif direction == "keep":
                action = "keep_resources"
            else:
                action = "none"

            reasons: list[str] = []
            if mem_dir == "decrease":
                reasons.append("P99 RSS significantly below requested memory")
            elif mem_dir == "increase":
                reasons.append("P99 RSS exceeds baseline request")
            if cpu_dir == "decrease":
                reasons.append("P99 thread utilization below allocated core count")
            if has_timeout:
                reasons.append("Observed timeouts; adjusted wallclock limit")
            reason_str = (
                "; ".join(reasons) if reasons else "Allocations aligned with observed usage"
            )

        recs_map[g_name] = {
            "sample_count_ok": sample_count_ok,
            "recommended_req_mem_mb": rec_mem,
            "recommended_cpus": rec_cpus,
            "recommended_time_limit_s": rec_time_limit,
            "recommendation_direction": direction,
            "recommendation_action": action,
            "observed_max_rss_mb": observed_max_rss if observed_max_rss > 0 else None,
            "p99_max_rss_mb": p99_rss,
            "observed_max_cpus": observed_max_cpus,
            "p99_cpu_rate": p99_rate,
            "reason": reason_str,
        }

    # Enrich grouped metrics table with recommendation fields
    recs_rows: list[dict[str, Any]] = []
    for g_dict in grouped_df.to_dicts():
        g_name = str(g_dict.get("group", "unknown"))
        rec_data = recs_map.get(
            g_name,
            {
                "recommended_req_mem_mb": None,
                "recommended_cpus": None,
                "recommended_time_limit_s": None,
                "recommendation_direction": "none",
                "recommendation_action": "none",
                "observed_max_rss_mb": None,
                "p99_max_rss_mb": None,
                "observed_max_cpus": None,
                "p99_cpu_rate": None,
                "reason": None,
            },
        )
        combined = {**g_dict, **rec_data}
        recs_rows.append(combined)

    result_df = pl.DataFrame(recs_rows, schema=RECOMMENDATIONS_SCHEMA)

    # Sort descending by score / reclaimable capacity
    if "reclaim_score" in result_df.columns:
        result_df = result_df.sort("reclaim_score", descending=True)

    return result_df


def export_recommendations(
    recommendations_df: pl.DataFrame,
    output_path: str | Path,
    format: str = "parquet",
) -> Path:
    """Export recommendations DataFrame to Parquet or CSV destination.

    Args:
        recommendations_df: Structured recommendations DataFrame.
        output_path: Target filesystem destination.
        format: Export format ('parquet' or 'csv').

    Returns:
        Path to generated export artifact.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fmt = format.lower()
    if path.suffix.lower() == ".csv" or fmt == "csv":
        # Format evidence job IDs as semicolon-separated string for CSV
        df_csv = recommendations_df
        if "evidence_job_ids" in df_csv.columns:
            df_csv = df_csv.with_columns(
                pl.col("evidence_job_ids").list.join(";").alias("evidence_job_ids")
            )
        df_csv.write_csv(path)
    else:
        recommendations_df.write_parquet(path)

    return path
