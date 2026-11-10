"""Redundant recomputation detection and result cache simulation.

Identifies duplicate job executions from declared input checksums and
normalized command lines within configured time horizons.
"""

import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl


def _normalize_dt(dt: datetime | str | None) -> datetime | None:
    """Normalize naive, aware datetime, or ISO string to UTC."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return _normalize_dt(parsed)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def load_sidecar(sidecar_path: Path | str) -> dict[str, Any]:
    """Load and parse sidecar metadata from a JSON file.

    Args:
        sidecar_path: Path to sidecar JSON file.

    Returns:
        Dictionary containing sidecar attributes or empty dictionary on failure.
    """
    p = Path(sidecar_path)
    if not p.is_file():
        return {}

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_sidecars_from_dir(sidecar_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Scan directory and index sidecar files by job identifier.

    Args:
        sidecar_dir: Directory containing sidecar JSON files.

    Returns:
        Mapping of job identifier to parsed sidecar dictionary.
    """
    directory = Path(sidecar_dir)
    if not directory.is_dir():
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for entry in directory.glob("*.json"):
        payload = load_sidecar(entry)
        job_key = payload.get("job_id") or entry.stem
        indexed[str(job_key)] = payload

    return indexed


def merge_sidecars(
    df: pl.DataFrame,
    sidecar_dir: Path | str | None = None,
) -> pl.DataFrame:
    """Merge input and command hashes from sidecar files into canonical table.

    Args:
        df: Canonical jobs DataFrame.
        sidecar_dir: Optional path to directory containing sidecars. Falls back
            to RCWA_DIR environment variable if not provided.

    Returns:
        DataFrame with input_hash and command_hash updated from sidecars.
    """
    target_dir = sidecar_dir or os.environ.get("RCWA_DIR")
    if not target_dir:
        return df

    sidecars = load_sidecars_from_dir(target_dir)
    if not sidecars:
        return df

    records = df.to_dicts()
    updated = False
    for r in records:
        jid = str(r.get("job_id") or "")
        base_id = jid.split(".")[0].split("_")[0]
        sidecar_data = sidecars.get(jid) or sidecars.get(base_id)
        if sidecar_data:
            sidecar_input_hash = sidecar_data.get("input_hash")
            sidecar_cmd_hash = sidecar_data.get("command_hash")
            if sidecar_input_hash and not r.get("input_hash"):
                r["input_hash"] = sidecar_input_hash
                updated = True
            if sidecar_cmd_hash and not r.get("command_hash"):
                r["command_hash"] = sidecar_cmd_hash
                updated = True

    if updated:
        return pl.DataFrame(records, schema=df.schema)
    return df


def detect_recomputations(
    df: pl.DataFrame,
    recompute_window_s: int = 2592000,
) -> pl.DataFrame:
    """Identify duplicate executions and command-only matches.

    Applies deterministic matching:
    1. A COMPLETED job matching an earlier COMPLETED job on both command_hash
       and input_hash within recompute_window_s is flagged as is_recompute=True
       with confidence 'declared_inputs'.
    2. A COMPLETED job with missing input_hash matching an earlier COMPLETED job
       on command_hash within recompute_window_s is flagged as
       possible_recompute=True with confidence 'command_only'.
    3. SWF traces do not carry declared inputs; confidence is 'not_available'.

    Args:
        df: Canonical or attributed jobs DataFrame.
        recompute_window_s: Time horizon in seconds for duplicate recognition.

    Returns:
        DataFrame augmented with is_recompute, possible_recompute,
        recompute_confidence, and recomputed_from_job_id columns.
    """
    if df.height == 0:
        return df.with_columns(
            [
                pl.lit(False, dtype=pl.Boolean).alias("is_recompute"),
                pl.lit(False, dtype=pl.Boolean).alias("possible_recompute"),
                pl.lit(None, dtype=pl.String).alias("recompute_confidence"),
                pl.lit(None, dtype=pl.String).alias("recomputed_from_job_id"),
            ]
        )

    records = df.to_dicts()

    # Determine effective end times for temporal sequence evaluation
    eff_end_times: list[datetime | None] = []
    for r in records:
        run_s = r.get("run_s") or 0
        wait_s = r.get("wait_s") or 0
        sub_time = r.get("submit_time")
        st_time = r.get("start_time")
        e_time = r.get("end_time")

        if e_time is not None:
            eff_end = e_time
        elif st_time is not None:
            eff_end = st_time + timedelta(seconds=run_s)
        elif sub_time is not None:
            eff_end = sub_time + timedelta(seconds=wait_s + run_s)
        else:
            eff_end = None
        eff_end_times.append(_normalize_dt(eff_end))

    # Index completed runs: (cmd_hash, inp_hash) -> list of (end_time, job_id)
    completed_pairs: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    # cmd_hash -> list of (end_time, job_id)
    completed_commands: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    # Sort index deterministically by submission timestamp, start, and job_id
    def _sort_key(i: int) -> tuple[int, datetime, int, str]:
        sub = _normalize_dt(records[i].get("submit_time"))
        eff = eff_end_times[i]
        t = sub if sub is not None else eff
        return (
            0 if t is not None else 1,
            t if t is not None else datetime.min.replace(tzinfo=UTC),
            i,
            str(records[i].get("job_id") or ""),
        )

    indexed_order = sorted(range(len(records)), key=_sort_key)

    is_recomp_map: dict[int, bool] = {}
    poss_recomp_map: dict[int, bool] = {}
    conf_map: dict[int, str | None] = {}
    parent_map: dict[int, str | None] = {}

    for idx in indexed_order:
        row = records[idx]
        jid = str(row.get("job_id") or "")
        st = row.get("state")
        source = str(row.get("source") or "").lower()
        cmd_h = row.get("command_hash")
        inp_h = row.get("input_hash")
        sub_time = _normalize_dt(row.get("submit_time"))
        eff_end = eff_end_times[idx]

        if source == "swf":
            is_recomp_map[idx] = False
            poss_recomp_map[idx] = False
            conf_map[idx] = "not_available"
            parent_map[idx] = None
            continue

        if st != "COMPLETED":
            is_recomp_map[idx] = False
            poss_recomp_map[idx] = False
            conf_map[idx] = None
            parent_map[idx] = None
            continue

        matched_recompute = False
        matched_possible = False
        matched_conf: str | None = None
        matched_parent: str | None = None

        if cmd_h and inp_h:
            pair = (cmd_h, inp_h)
            if pair in completed_pairs and sub_time is not None:
                for prev_end, prev_jid in completed_pairs[pair]:
                    delta = (sub_time - prev_end).total_seconds()
                    if 0 <= delta <= recompute_window_s:
                        matched_recompute = True
                        matched_conf = "declared_inputs"
                        matched_parent = prev_jid
                        break

            if not matched_recompute and cmd_h in completed_commands and sub_time is not None:
                for prev_end, prev_jid in completed_commands[cmd_h]:
                    delta = (sub_time - prev_end).total_seconds()
                    if 0 <= delta <= recompute_window_s:
                        matched_possible = True
                        matched_conf = "command_only"
                        matched_parent = prev_jid
                        break

            if eff_end is not None:
                completed_pairs[pair].append((eff_end, jid))
                completed_commands[cmd_h].append((eff_end, jid))

        elif cmd_h and not inp_h:
            if cmd_h in completed_commands and sub_time is not None:
                for prev_end, prev_jid in completed_commands[cmd_h]:
                    delta = (sub_time - prev_end).total_seconds()
                    if 0 <= delta <= recompute_window_s:
                        matched_possible = True
                        matched_conf = "command_only"
                        matched_parent = prev_jid
                        break

            if eff_end is not None:
                completed_commands[cmd_h].append((eff_end, jid))

        is_recomp_map[idx] = matched_recompute
        poss_recomp_map[idx] = matched_possible
        conf_map[idx] = matched_conf
        parent_map[idx] = matched_parent

    is_recompute_col = [is_recomp_map.get(i, False) for i in range(len(records))]
    possible_recompute_col = [poss_recomp_map.get(i, False) for i in range(len(records))]
    confidence_col = [conf_map.get(i) for i in range(len(records))]
    parent_col = [parent_map.get(i) for i in range(len(records))]

    return df.with_columns(
        [
            pl.Series("is_recompute", is_recompute_col, dtype=pl.Boolean),
            pl.Series("possible_recompute", possible_recompute_col, dtype=pl.Boolean),
            pl.Series("recompute_confidence", confidence_col, dtype=pl.String),
            pl.Series("recomputed_from_job_id", parent_col, dtype=pl.String),
        ]
    )


def simulate_result_cache(
    df: pl.DataFrame,
    cache_threshold_waste_share: float = 0.05,
) -> list[dict[str, Any]]:
    """Simulate result cache potential and hit rates for workload groups.

    For each group whose Class 4 redundant reservation exceeds the configured
    waste share threshold, computes simulated cache hits, misses, and hit rates.

    Args:
        df: Attributed jobs DataFrame containing class4 columns.
        cache_threshold_waste_share: Threshold share of waste to trigger
            caching recommendations.

    Returns:
        List of result cache recommendation dictionaries.
    """
    if df.height == 0:
        return []

    # Check for presence of group identifier or fallback
    has_group = "group_key" in df.columns
    if not has_group:
        user_expr = (
            pl.col("user").fill_null("unknown") if "user" in df.columns else pl.lit("unknown")
        )
        if "command_hash" in df.columns and "job_name" in df.columns:
            cmd_expr = pl.col("command_hash").fill_null(pl.col("job_name").fill_null("default"))
        elif "command_hash" in df.columns:
            cmd_expr = pl.col("command_hash").fill_null("default")
        elif "job_name" in df.columns:
            cmd_expr = pl.col("job_name").fill_null("default")
        else:
            cmd_expr = pl.lit("default")
        eval_df = df.with_columns((user_expr + "/" + cmd_expr).alias("group_key"))
    else:
        eval_df = df

    total_trace_c4_core = (
        float(eval_df.select(pl.col("class4_core_s").sum()).item()) / 3600.0
        if "class4_core_s" in eval_df.columns
        else 0.0
    )
    total_trace_core = (
        float(eval_df.select(pl.col("reserved_core_s").sum()).item()) / 3600.0
        if "reserved_core_s" in eval_df.columns
        else 1.0
    )
    trace_waste_share = total_trace_c4_core / max(1.0, total_trace_core)

    recommendations: list[dict[str, Any]] = []

    unique_groups = eval_df.select("group_key").unique().to_series().to_list()
    for grp in sorted(unique_groups):
        grp_rows = eval_df.filter(pl.col("group_key") == grp)
        completed_rows = grp_rows.filter(pl.col("state") == "COMPLETED")
        total_eval = completed_rows.height
        if total_eval == 0:
            continue

        c4_core_s = (
            float(grp_rows.select(pl.col("class4_core_s").sum()).item())
            if "class4_core_s" in grp_rows.columns
            else 0.0
        )
        c4_mem_s = (
            float(grp_rows.select(pl.col("class4_mem_mb_s").sum()).item())
            if "class4_mem_mb_s" in grp_rows.columns
            else 0.0
        )
        res_core_s = (
            float(grp_rows.select(pl.col("reserved_core_s").sum()).item())
            if "reserved_core_s" in grp_rows.columns
            else 1.0
        )

        group_waste_share = c4_core_s / max(1.0, res_core_s)
        reclaim_core_h = round(c4_core_s / 3600.0, 4)
        reclaim_gb_h = round(c4_mem_s / (1024.0 * 3600.0), 4)

        # Count runs that hit cache (is_recompute or class4_core_s > 0)
        if "is_recompute" in grp_rows.columns:
            hits = int(grp_rows.filter(pl.col("is_recompute")).height)
        elif "class4_core_s" in grp_rows.columns:
            hits = int(grp_rows.filter(pl.col("class4_core_s") > 0).height)
        else:
            hits = 0

        hit_rate = round(hits / total_eval, 4) if total_eval > 0 else 0.0

        is_recommended = (
            group_waste_share >= cache_threshold_waste_share
            or trace_waste_share >= cache_threshold_waste_share
            or hits > 0
        )

        recommendations.append(
            {
                "group": grp,
                "total_completed_jobs": total_eval,
                "cache_hits": hits,
                "hit_rate": hit_rate,
                "reclaimable_core_hours": reclaim_core_h,
                "reclaimable_gb_hours": reclaim_gb_h,
                "group_class4_share": round(group_waste_share, 4),
                "recommended": is_recommended,
            }
        )

    return recommendations


def evaluate_recomputation_accuracy(
    detected_df: pl.DataFrame,
    ground_truth_df: pl.DataFrame,
    join_col: str = "job_id",
) -> dict[str, float]:
    """Calculate recall and precision against planted duplicate ground truth.

    Args:
        detected_df: DataFrame with detected recomputations (is_recompute or class4_core_s).
        ground_truth_df: DataFrame with known planted recomputation labels
            (planted_is_recompute or true_class4).
        join_col: Identifier column to join tables.

    Returns:
        Dictionary reporting precision, recall, f1_score, and counts.
    """
    joined = detected_df.join(ground_truth_df, on=join_col, how="inner")

    # Determine detected positive series
    if "is_recompute" in joined.columns:
        det_series = joined["is_recompute"]
    elif "class4_core_s" in joined.columns:
        det_series = joined["class4_core_s"] > 0
    else:
        det_series = pl.Series([False] * joined.height)

    # Determine ground truth positive series
    if "is_recompute_right" in joined.columns:
        truth_series = joined["is_recompute_right"]
    elif "planted_is_recompute" in joined.columns:
        truth_series = joined["planted_is_recompute"]
    elif "true_class" in joined.columns:
        truth_series = joined["true_class"] == 4
    elif "is_recompute" in joined.columns:
        truth_series = joined["is_recompute"]
    else:
        truth_series = pl.Series([False] * joined.height)

    tp = 0
    fp = 0
    fn = 0
    tn = 0

    for d, t in zip(det_series.to_list(), truth_series.to_list(), strict=False):
        d_bool = bool(d)
        t_bool = bool(t)
        if d_bool and t_bool:
            tp += 1
        elif d_bool and not t_bool:
            fp += 1
        elif not d_bool and t_bool:
            fn += 1
        else:
            tn += 1

    precision = round(tp / (tp + fp), 6) if (tp + fp) > 0 else 1.0
    recall = round(tp / (tp + fn), 6) if (tp + fn) > 0 else 1.0
    denom = precision + recall
    f1 = round(2 * (precision * recall) / denom, 6) if denom > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "true_positives": float(tp),
        "false_positives": float(fp),
        "false_negatives": float(fn),
        "true_negatives": float(tn),
    }
