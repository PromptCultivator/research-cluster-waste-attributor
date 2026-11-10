"""Conservation waste attribution engine for cluster batch job traces.

Partitions reserved CPU core-seconds and memory megabyte-seconds across four
mutually exclusive classes or utilized resources according to strict single-pass
precedence rules enforcing Guarantee G1.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from rcwa.retries import FAILED_STATES, detect_retry_chains


def _normalize_dt(dt: datetime | str | int | float | None) -> datetime | None:
    """Ensure datetime carries UTC timezone if naive."""
    if dt is None:
        return None
    if isinstance(dt, int | float):
        return datetime.fromtimestamp(dt, tz=UTC)
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _extract_policy_dict(policy: Any) -> dict[str, Any]:
    """Extract nested dictionary configuration from policy parameter."""
    if policy is None:
        default_path = Path("policies/default.yaml")
        if default_path.is_file():
            import yaml

            try:
                loaded = yaml.safe_load(default_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {}

    if isinstance(policy, str | Path):
        p = Path(policy)
        if p.is_file():
            import yaml

            loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        return {}

    if hasattr(policy, "model_dump"):
        dumped: Any = policy.model_dump()
        if isinstance(dumped, dict):
            return dumped

    if isinstance(policy, dict):
        return policy

    return {}


def attribute_trace(
    canonical_df: pl.DataFrame,
    policy: Any = None,
) -> pl.DataFrame:
    """Attribute reserved resource waste across four conservation classes.

    Precedence order:
    1. Class 3 (Failed/Retried work): entire reservation in both dimensions.
       Sub-labels: early_failure (run_s <= threshold), oom, timeout, node_fail,
       cancelled_after_start, other_failure.
    2. Class 4 (Redundant recomputation): entire reservation when matching declared inputs.
       For SWF traces, reported as 'not_available'. Command-only matches set possible_recompute=True
       without consuming Class 4 totals.
    3. Class 2 (Idle reserved CPU) and Class 1 (Memory over-request):
       Measured against cpu_time_used_s and max_rss_mb respectively.
       Missing metrics map directly to unattributed reservations.

    Args:
        canonical_df: Canonical batch job accounting DataFrame.
        policy: Policy dictionary, configuration object, or path to policy YAML.

    Returns:
        Polars DataFrame augmented with waste classification columns satisfying Guarantee G1.
    """
    # Exclude RUNNING and PENDING jobs from attribution (SPEC section 5.3)
    df = canonical_df.filter(~pl.col("state").is_in(["RUNNING", "PENDING"]))

    # Normalize null memory reservations to 0 to preserve integer conservation without type errors
    df = df.with_columns(pl.col("reserved_mem_mb_s").fill_null(0))

    policy_dict = _extract_policy_dict(policy)
    attr_cfg = policy_dict.get("attribution", {}) if isinstance(policy_dict, dict) else {}

    retry_window_s = int(attr_cfg.get("retry_window_s", 86400))
    recompute_window_s = int(attr_cfg.get("recompute_window_s", 2592000))
    early_failure_threshold_s = int(attr_cfg.get("early_failure_threshold_s", 60))

    if df.height == 0:
        return df.with_columns(
            [
                pl.lit(0, dtype=pl.Int64).alias("used_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("class2_idle_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("idle_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("class3_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("class4_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("unattributed_core_s"),
                pl.lit(0, dtype=pl.Int64).alias("unattributed_cpu_s"),
                pl.lit(0, dtype=pl.Int64).alias("used_mem_mb_s"),
                pl.lit(0, dtype=pl.Int64).alias("class1_over_mem_mb_s"),
                pl.lit(0, dtype=pl.Int64).alias("over_mem_mb_s"),
                pl.lit(0, dtype=pl.Int64).alias("class3_mem_mb_s"),
                pl.lit(0, dtype=pl.Int64).alias("class4_mem_mb_s"),
                pl.lit(0, dtype=pl.Int64).alias("unattributed_mem_mb_s"),
                pl.lit(None, dtype=pl.String).alias("class3_sub_label"),
                pl.lit(False, dtype=pl.Boolean).alias("possible_recompute"),
                pl.lit(None, dtype=pl.String).alias("recompute_confidence"),
                pl.lit(None, dtype=pl.String).alias("retry_of"),
                pl.lit(None, dtype=pl.String).alias("retry_chain_id"),
                pl.lit(0, dtype=pl.Int32).alias("retry_count"),
                pl.lit(0, dtype=pl.Int64).alias("retry_chain_cost_core_s"),
                pl.lit(None, dtype=pl.Int64).alias("retry_chain_cost_mem_mb_s"),
            ]
        )

    # First execute retry chain detection
    df_with_retries = detect_retry_chains(df, retry_window_s=retry_window_s)

    records = df_with_retries.to_dicts()

    # Pre-calculate effective end times for temporal recomputation checks
    eff_end_times = []
    for r in records:
        run_s = r["run_s"] or 0
        wait_s = r["wait_s"] or 0
        sub_time = r["submit_time"]
        st_time = r["start_time"]
        e_time = r["end_time"]

        if e_time is not None:
            eff_end = e_time
        elif st_time is not None:
            eff_end = st_time + timedelta(seconds=run_s)
        elif sub_time is not None:
            eff_end = sub_time + timedelta(seconds=wait_s + run_s)
        else:
            eff_end = None
        eff_end_times.append(eff_end)

    from rcwa.recompute import detect_recomputations

    df_recomp = detect_recomputations(df_with_retries, recompute_window_s=recompute_window_s)
    is_recomp_col = df_recomp["is_recompute"].to_list()
    poss_recomp_col = df_recomp["possible_recompute"].to_list()
    recomp_conf_col = df_recomp["recompute_confidence"].to_list()

    # Perform attribution per row across the precedence order
    used_core_list: list[int] = []
    class2_idle_core_list: list[int] = []
    class3_core_list: list[int] = []
    class4_core_list: list[int] = []
    unattrib_core_list: list[int] = []

    used_mem_list: list[int] = []
    class1_over_mem_list: list[int] = []
    class3_mem_list: list[int] = []
    class4_mem_list: list[int] = []
    unattrib_mem_list: list[int] = []

    sub_labels: list[str | None] = []
    possible_recompute_list: list[bool] = []
    recompute_confidence_list: list[str | None] = []

    for idx, row in enumerate(records):
        st = row["state"]
        run_s = row["run_s"] or 0
        res_core = int(row.get("reserved_core_s") or 0)
        res_mem = int(row.get("reserved_mem_mb_s") or 0)
        req_mem_mb = row.get("req_mem_mb")
        max_rss_mb = row.get("max_rss_mb")
        cpu_used_s = row.get("cpu_time_used_s")

        is_failed = (st in FAILED_STATES) or (st == "CANCELLED" and run_s > 0) or (run_s == 0)

        is_recompute = is_recomp_col[idx]
        poss_recomp = poss_recomp_col[idx]
        recomp_conf = recomp_conf_col[idx]
        possible_recompute_list.append(poss_recomp)
        recompute_confidence_list.append(recomp_conf)

        if is_failed:
            # 1. Class 3 Precedence: Entire reservation attributed to Class 3
            class3_core_list.append(res_core)
            class3_mem_list.append(res_mem)

            used_core_list.append(0)
            class2_idle_core_list.append(0)
            class4_core_list.append(0)
            unattrib_core_list.append(0)

            used_mem_list.append(0)
            class1_over_mem_list.append(0)
            class4_mem_list.append(0)
            unattrib_mem_list.append(0)

            # Assign specific Class 3 sub-label
            if run_s <= early_failure_threshold_s:
                sub_labels.append("early_failure")
            elif st == "OUT_OF_MEMORY":
                sub_labels.append("oom")
            elif st == "TIMEOUT":
                sub_labels.append("timeout")
            elif st == "NODE_FAIL":
                sub_labels.append("node_fail")
            elif st == "CANCELLED":
                sub_labels.append("cancelled_after_start")
            else:
                sub_labels.append("other_failure")

        elif is_recompute:
            # 2. Class 4 Precedence: Entire reservation attributed to Class 4
            sub_labels.append(None)

            class4_core_list.append(res_core)
            class4_mem_list.append(res_mem)

            used_core_list.append(0)
            class2_idle_core_list.append(0)
            class3_core_list.append(0)
            unattrib_core_list.append(0)

            used_mem_list.append(0)
            class1_over_mem_list.append(0)
            class3_mem_list.append(0)
            unattrib_mem_list.append(0)

        else:
            # 3. Class 2 (Core Dimension) and Class 1 (Memory Dimension)
            sub_labels.append(None)
            class3_core_list.append(0)
            class3_mem_list.append(0)
            class4_core_list.append(0)
            class4_mem_list.append(0)

            # Core dimension
            if cpu_used_s is None:
                unattrib_core_list.append(res_core)
                class2_idle_core_list.append(0)
                used_core_list.append(0)
            else:
                rounded_cpu_s = max(0, int(round(cpu_used_s)))
                idle_core = max(0, res_core - rounded_cpu_s)
                used_core = res_core - idle_core
                class2_idle_core_list.append(idle_core)
                used_core_list.append(used_core)
                unattrib_core_list.append(0)

            # Memory dimension
            if req_mem_mb is None or res_mem == 0:
                unattrib_mem_list.append(0)
                class1_over_mem_list.append(0)
                used_mem_list.append(0)
            elif max_rss_mb is None:
                unattrib_mem_list.append(res_mem)
                class1_over_mem_list.append(0)
                used_mem_list.append(0)
            else:
                over_rate = max(0, req_mem_mb - max_rss_mb)
                over_mem = min(res_mem, over_rate * run_s)
                used_mem = res_mem - over_mem
                class1_over_mem_list.append(over_mem)
                used_mem_list.append(used_mem)
                unattrib_mem_list.append(0)

    # Attach attribution columns and expressive aliases
    attributed_df = df_with_retries.with_columns(
        [
            pl.Series("used_core_s", used_core_list, dtype=pl.Int64),
            pl.Series("class2_idle_core_s", class2_idle_core_list, dtype=pl.Int64),
            pl.Series("idle_core_s", class2_idle_core_list, dtype=pl.Int64),
            pl.Series("class3_core_s", class3_core_list, dtype=pl.Int64),
            pl.Series("class4_core_s", class4_core_list, dtype=pl.Int64),
            pl.Series("unattributed_core_s", unattrib_core_list, dtype=pl.Int64),
            pl.Series("unattributed_cpu_s", unattrib_core_list, dtype=pl.Int64),
            pl.Series("used_mem_mb_s", used_mem_list, dtype=pl.Int64),
            pl.Series("class1_over_mem_mb_s", class1_over_mem_list, dtype=pl.Int64),
            pl.Series("over_mem_mb_s", class1_over_mem_list, dtype=pl.Int64),
            pl.Series("class3_mem_mb_s", class3_mem_list, dtype=pl.Int64),
            pl.Series("class4_mem_mb_s", class4_mem_list, dtype=pl.Int64),
            pl.Series("unattributed_mem_mb_s", unattrib_mem_list, dtype=pl.Int64),
            pl.Series("class3_sub_label", sub_labels, dtype=pl.String),
            pl.Series("possible_recompute", possible_recompute_list, dtype=pl.Boolean),
            pl.Series("recompute_confidence", recompute_confidence_list, dtype=pl.String),
        ]
    )

    return attributed_df


def export_attributed_records(
    df: pl.DataFrame,
    path: Path | str,
    format: str = "parquet",
) -> None:
    """Export attributed job table to Parquet or CSV format."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    normalized_fmt = format.lower().strip()
    if normalized_fmt == "csv" or p.suffix.lower() == ".csv":
        df.write_csv(p)
    else:
        df.write_parquet(p)
