"""Workload aggregation and hierarchical job grouping engine.

Aggregates attributed compute records across primary keys and secondary
dimensions (account, partition, user), scoring reclaimable capacity and
sampling evidence records.
"""

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import polars as pl

from rcwa.attribute import _extract_policy_dict

GROUP_METRICS_SCHEMA: dict[str, type[pl.DataType] | pl.DataType] = {
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
}


def group_jobs(
    attributed_df: pl.DataFrame,
    policy: Any = None,
    group_keys: list[str] | None = None,
) -> pl.DataFrame:
    """Group attributed jobs and compute waste metrics, reclaim scores, and evidence IDs.

    Args:
        attributed_df: Attributed job DataFrame satisfying Guarantee G1.
        policy: Policy dictionary or path to policy YAML configuration.
        group_keys: Optional explicit grouping keys (defaults to policy or user/task).

    Returns:
        Aggregated metrics DataFrame sorted by reclaim_score descending.
    """
    policy_dict = _extract_policy_dict(policy)
    grouping_cfg = policy_dict.get("grouping", {}) if isinstance(policy_dict, dict) else {}
    attr_cfg = policy_dict.get("attribution", {}) if isinstance(policy_dict, dict) else {}

    min_samples = int(grouping_cfg.get("min_samples", 5))
    mem_weight = float(attr_cfg.get("mem_weight_core_hours_per_gb_hour", 0.25))

    if group_keys is None:
        configured_keys = grouping_cfg.get("group_keys")
        if configured_keys and isinstance(configured_keys, list):
            group_keys = [str(k) for k in configured_keys]
        else:
            group_keys = ["user", "command_hash_or_job_name"]

    if attributed_df.height == 0:
        return pl.DataFrame(schema=GROUP_METRICS_SCHEMA)

    # Prepare DataFrame with derived identifiers if required
    df = attributed_df
    if "command_hash_or_job_name" in group_keys and "command_hash_or_job_name" not in df.columns:
        df = df.with_columns(
            pl.coalesce([pl.col("job_name"), pl.col("command_hash"), pl.lit("unknown")]).alias(
                "command_hash_or_job_name"
            )
        )

    # Determine group label expression
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
        df = df.with_columns(pl.concat_str([user_expr, pl.lit("/"), cmd_expr]).alias("group"))
    elif len(group_keys) == 1:
        k = group_keys[0]
        if k in df.columns:
            col_expr = (
                pl.when(pl.col(k).is_not_null() & (pl.col(k).cast(pl.String) != ""))
                .then(pl.col(k).cast(pl.String))
                .otherwise(pl.lit("unknown"))
            )
            df = df.with_columns(col_expr.alias("group"))
        else:
            df = df.with_columns(pl.lit("unknown").alias("group"))
    else:
        exprs = [
            pl.when(pl.col(k).is_not_null() & (pl.col(k).cast(pl.String) != ""))
            .then(pl.col(k).cast(pl.String))
            .otherwise(pl.lit("unknown"))
            for k in group_keys
            if k in df.columns
        ]
        if exprs:
            df = df.with_columns(pl.concat_str(exprs, separator="/").alias("group"))
        else:
            df = df.with_columns(pl.lit("all").alias("group"))

    # Compute individual job waste score for evidence job sampling
    # waste_score = waste_core_hours + mem_weight * waste_gb_hours
    core_waste_s = pl.col("class2_idle_core_s") + pl.col("class3_core_s") + pl.col("class4_core_s")
    mem_waste_s = (
        pl.col("class1_over_mem_mb_s") + pl.col("class3_mem_mb_s") + pl.col("class4_mem_mb_s")
    )
    job_waste_score_expr = (core_waste_s / 3600.0) + (
        mem_weight * (mem_waste_s / (1024.0 * 3600.0))
    )
    df = df.with_columns(job_waste_score_expr.alias("_job_waste_score"))

    # Aggregate metric quantities per group
    # 1 GB-hour = 1024 * 3600 MB-seconds
    mb_to_gb_hours = 1024.0 * 3600.0
    agg_df = df.group_by("group").agg(
        [
            pl.len().cast(pl.Int64).alias("job_count"),
            (pl.col("reserved_core_s").sum() / 3600.0).alias("total_reserved_core_hours"),
            (pl.col("used_core_s").sum() / 3600.0).alias("total_used_core_hours"),
            (pl.col("reserved_mem_mb_s").sum() / mb_to_gb_hours).alias("total_reserved_gb_hours"),
            (pl.col("used_mem_mb_s").sum() / mb_to_gb_hours).alias("total_used_gb_hours"),
            (pl.col("class1_over_mem_mb_s").sum() / mb_to_gb_hours).alias(
                "class1_over_mem_gb_hours"
            ),
            (pl.col("class2_idle_core_s").sum() / 3600.0).alias("class2_idle_core_hours"),
            (pl.col("class3_core_s").sum() / 3600.0).alias("class3_failed_core_hours"),
            (pl.col("class3_mem_mb_s").sum() / mb_to_gb_hours).alias("class3_failed_gb_hours"),
            (pl.col("class4_core_s").sum() / 3600.0).alias("class4_recompute_core_hours"),
            (pl.col("class4_mem_mb_s").sum() / mb_to_gb_hours).alias("class4_recompute_gb_hours"),
            (pl.col("unattributed_core_s").sum() / 3600.0).alias("unattributed_core_hours"),
            (pl.col("unattributed_mem_mb_s").sum() / mb_to_gb_hours).alias("unattributed_gb_hours"),
            ((pl.col("state") == "OUT_OF_MEMORY") | (pl.col("class3_sub_label") == "oom"))
            .any()
            .alias("has_oom"),
        ]
    )

    # Compute reclaimable core and memory hours
    # Core reclaimable: Class 2 idle CPU + Class 4 redundant recomputation
    # Memory reclaimable: Class 1 memory over-request + Class 4 redundant recomputation
    # Guardrail: Groups with observed OUT_OF_MEMORY are excluded from reclaimable memory
    reclaim_core_expr = pl.col("class2_idle_core_hours") + pl.col("class4_recompute_core_hours")
    reclaim_gb_expr = (
        pl.when(pl.col("has_oom"))
        .then(pl.lit(0.0))
        .otherwise(pl.col("class1_over_mem_gb_hours") + pl.col("class4_recompute_gb_hours"))
    )

    agg_df = agg_df.with_columns(
        [
            reclaim_core_expr.alias("reclaimable_core_hours"),
            reclaim_gb_expr.alias("reclaimable_gb_hours"),
        ]
    )

    # Compute combined reclaim score
    # reclaim_score = reclaimable_core_hours + mem_weight * reclaimable_gb_hours
    reclaim_score_expr = pl.col("reclaimable_core_hours") + (
        pl.lit(mem_weight) * pl.col("reclaimable_gb_hours")
    )
    agg_df = agg_df.with_columns(
        [
            reclaim_score_expr.alias("reclaim_score"),
            reclaim_score_expr.alias("score"),
            (pl.col("job_count") >= min_samples).alias("sample_count_ok"),
        ]
    )

    # Compute cluster total shares
    total_cluster_reserved_cores = agg_df.select(pl.col("total_reserved_core_hours").sum()).item()
    total_cluster_waste_score = agg_df.select(pl.col("reclaim_score").sum()).item()
    total_reserved = float(total_cluster_reserved_cores or 0.0)
    total_waste = float(total_cluster_waste_score or 0.0)

    agg_df = agg_df.with_columns(
        [
            pl.when(pl.lit(total_reserved > 0.0))
            .then(pl.col("total_reserved_core_hours") / pl.lit(total_reserved))
            .otherwise(pl.lit(0.0))
            .alias("cluster_reserved_core_share"),
            pl.when(pl.lit(total_waste > 0.0))
            .then(pl.col("reclaim_score") / pl.lit(total_waste))
            .otherwise(pl.lit(0.0))
            .alias("cluster_waste_score_share"),
        ]
    )

    # Evidence job sampling: top 5 job IDs per group by waste score
    evidence_map: dict[str, list[str]] = defaultdict(list)
    raw_evidence_rows = df.select(["group", "job_id", "_job_waste_score"]).to_dicts()

    group_jobs_dict: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for r in raw_evidence_rows:
        grp = str(r["group"])
        jid = str(r["job_id"])
        score_raw = r["_job_waste_score"]
        score_val = float(score_raw) if score_raw is not None else 0.0
        if math.isnan(score_val):
            score_val = 0.0
        group_jobs_dict[grp].append((score_val, jid))

    for grp, job_tuples in group_jobs_dict.items():
        # Sort descending by waste score, break ties ascending by job_id
        sorted_tuples = sorted(job_tuples, key=lambda x: (-x[0], x[1]))
        top_5_ids = [t[1] for t in sorted_tuples[:5]]
        evidence_map[grp] = top_5_ids

    # Attach evidence_job_ids list column
    group_list = agg_df.select("group").to_series().to_list()
    evidence_col = [evidence_map.get(str(g), []) for g in group_list]

    agg_df = agg_df.with_columns(
        pl.Series("evidence_job_ids", evidence_col, dtype=pl.List(pl.String))
    )

    # Select canonical schema columns and sort by reclaim_score descending,
    # breaking ties by group ascending
    return agg_df.select(list(GROUP_METRICS_SCHEMA.keys())).sort(
        ["reclaim_score", "group"], descending=[True, False]
    )


def generate_secondary_rollups(
    attributed_df: pl.DataFrame,
    policy: Any = None,
) -> dict[str, pl.DataFrame]:
    """Generate secondary aggregate rollups by account, partition, and user dimensions.

    Args:
        attributed_df: Attributed job records DataFrame.
        policy: Policy configuration.

    Returns:
        Dictionary mapping rollup dimension names to their aggregated DataFrames.
    """
    rollups: dict[str, pl.DataFrame] = {}
    for rollup_key in ("account", "partition", "user"):
        rollups[rollup_key] = group_jobs(
            attributed_df,
            policy=policy,
            group_keys=[rollup_key],
        )
    return rollups


def export_group_metrics(
    df: pl.DataFrame,
    path: Path | str,
    format: str = "parquet",
) -> None:
    """Export group metrics table to Parquet or CSV format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    normalized_fmt = format.lower().strip()
    if normalized_fmt == "csv" or p.suffix.lower() == ".csv":
        # Format evidence_job_ids list as semicolon-delimited string for CSV
        if "evidence_job_ids" in df.columns:
            df_csv = df.with_columns(
                pl.col("evidence_job_ids").list.join(";").alias("evidence_job_ids")
            )
        else:
            df_csv = df
        df_csv.write_csv(p)
    else:
        df.write_parquet(p)
