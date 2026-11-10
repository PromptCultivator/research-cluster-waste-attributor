"""Simulator calibration engine.

Calibrates simulator baseline wait times against actual historical wait times.
Calculates Median Absolute Error (MAE) and Spearman rank correlation coefficient.
"""

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace


def compute_calibration_metrics(
    sim_df: pl.DataFrame,
    historical_df: pl.DataFrame,
) -> dict[str, Any]:
    """Calculate calibration divergence metrics between simulated and historical wait times.

    Args:
        sim_df: Simulation output DataFrame containing job_id and sim_wait_s.
        historical_df: Historical trace DataFrame containing job_id and wait_s.

    Returns:
        Dictionary containing median_absolute_error_s, spearman_rank_correlation,
        mean_absolute_error_s, and p95_absolute_error_s.
    """
    joined = sim_df.select(["job_id", "sim_wait_s"]).join(
        historical_df.select(["job_id", "wait_s"]),
        on="job_id",
        how="inner",
    )

    if joined.height == 0:
        return {
            "median_absolute_error_s": 0.0,
            "spearman_rank_correlation": 0.0,
            "mean_absolute_error_s": 0.0,
            "p95_absolute_error_s": 0.0,
            "job_count": 0,
        }

    sim_waits = joined["sim_wait_s"].to_numpy().astype(float)
    real_waits = joined["wait_s"].to_numpy().astype(float)

    abs_errors = np.abs(sim_waits - real_waits)
    mae = float(np.median(abs_errors))
    mean_ae = float(np.mean(abs_errors))
    p95_ae = float(np.percentile(abs_errors, 95))

    # Spearman rank correlation
    if len(sim_waits) < 2:
        spearman_corr = 1.0
    elif np.std(sim_waits) == 0.0 or np.std(real_waits) == 0.0:
        spearman_corr = 1.0 if np.array_equal(sim_waits, real_waits) else 0.0
    else:
        rank_sim = joined.select(pl.col("sim_wait_s").rank()).to_series().to_numpy().astype(float)
        rank_real = joined.select(pl.col("wait_s").rank()).to_series().to_numpy().astype(float)
        corr_matrix = np.corrcoef(rank_sim, rank_real)
        spearman_corr = float(corr_matrix[0, 1])
        if np.isnan(spearman_corr):
            spearman_corr = 0.0

    return {
        "median_absolute_error_s": round(mae, 4),
        "spearman_rank_correlation": round(spearman_corr, 4),
        "mean_absolute_error_s": round(mean_ae, 4),
        "p95_absolute_error_s": round(p95_ae, 4),
        "job_count": joined.height,
    }


def calibrate_trace(
    trace_path: Path | str,
    cluster_path: Path | str | None = None,
) -> dict[str, Any]:
    """Execute baseline simulation on trace and evaluate calibration against historical waits."""
    p = Path(trace_path)
    if not p.is_file():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    from rcwa.adapters.sacct import parse_sacct
    from rcwa.adapters.swf import parse_swf

    name = p.name.lower()
    if name.endswith(".swf") or name.endswith(".swf.gz"):
        hist_df = parse_swf(p)
    elif name.endswith(".parquet"):
        hist_df = pl.read_parquet(p)
    else:
        hist_df = parse_sacct(p)

    if cluster_path is not None:
        cluster = load_cluster_config(cluster_path)
    else:
        cluster = infer_cluster_from_trace(hist_df)

    sim_df, _ = simulate_trace(hist_df, cluster=cluster, scenario="baseline")
    metrics = compute_calibration_metrics(sim_df, hist_df)
    return metrics
