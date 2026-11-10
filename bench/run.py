"""Benchmark harness measuring throughput, attribution accuracy, and simulation metrics."""

from __future__ import annotations

import argparse
import csv
import io
import resource
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from bench.hardware import format_hardware_block
from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf
from rcwa.attribute import attribute_trace
from rcwa.calibrate import compute_calibration_metrics
from rcwa.recommend import recommend_jobs
from rcwa.simulate import infer_cluster_from_trace, simulate_trace
from rcwa.synth import generate_synthetic_trace, parse_trace_size


def compute_binary_metrics(pred: np.ndarray, truth: np.ndarray) -> tuple[float, float, float]:
    """Calculate recall, precision, and F1 score for boolean vectors."""
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    fn = int(np.sum(~pred & truth))

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return recall, precision, f1


def run_benchmark_iteration(
    size_str: str,
    seed: int,
    data_dir: Path,
) -> dict[str, Any]:
    """Execute single benchmark iteration over synthetic and real traces."""
    n_jobs = parse_trace_size(size_str)

    # 1. Synthetic Trace Generation
    t0 = time.perf_counter()
    sacct_text, truth_df = generate_synthetic_trace(size=size_str, seed=seed)

    # 2. Ingestion Throughput (sacct)
    t0 = time.perf_counter()
    canonical_df = parse_sacct(io.StringIO(sacct_text))
    sacct_ingest_s = max(0.0001, time.perf_counter() - t0)
    sacct_ingest_throughput = len(canonical_df) / sacct_ingest_s

    # Ingestion Throughput (SWF)
    swf_sample = Path("tests/fixtures/swf/sample_workload.swf")
    swf_candidate = data_dir / "raw" / "SDSC-SP2-1998-4.2-cln.swf.gz"
    swf_target = (
        swf_candidate if swf_candidate.exists() and swf_candidate.stat().st_size > 0 else swf_sample
    )
    t0 = time.perf_counter()
    swf_df = parse_swf(swf_target)
    swf_ingest_s = max(0.0001, time.perf_counter() - t0)
    swf_ingest_throughput = len(swf_df) / swf_ingest_s

    # 3. Attribution and Guarantee G1 Conservation Check
    attr_df = attribute_trace(canonical_df)

    g1_exact = True
    for row in attr_df.iter_rows(named=True):
        res_c = row["reserved_core_s"]
        used_c = row["used_core_s"]
        c2 = row["class2_idle_core_s"]
        c3_c = row["class3_core_s"]
        c4_c = row["class4_core_s"]
        un_c = row["unattributed_core_s"]
        if res_c != (used_c + c2 + c3_c + c4_c + un_c):
            g1_exact = False
            break

        res_m = row["reserved_mem_mb_s"]
        used_m = row["used_mem_mb_s"]
        c1 = row.get("class1_over_mem_mb_s") or row.get("over_mem_mb_s") or 0
        c3_m = row["class3_mem_mb_s"]
        c4_m = row["class4_mem_mb_s"]
        un_m = row["unattributed_mem_mb_s"]
        if res_m != (used_m + c1 + c3_m + c4_m + un_m):
            g1_exact = False
            break

    # Attribution Coverage
    total_res_c = float(attr_df["reserved_core_s"].sum())
    total_unatt_c = float(attr_df["unattributed_core_s"].sum())
    total_res_m = float(attr_df["reserved_mem_mb_s"].sum())
    total_unatt_m = float(attr_df["unattributed_mem_mb_s"].sum())
    cov_c = (
        100.0 * (total_res_c - total_unatt_c) / max(1.0, total_res_c) if total_res_c > 0 else 100.0
    )
    cov_m = (
        100.0 * (total_res_m - total_unatt_m) / max(1.0, total_res_m) if total_res_m > 0 else 100.0
    )
    attribution_coverage_pct = round((cov_c + cov_m) / 2.0, 2)

    # Reclaimable shares
    tot_c2 = float(attr_df["class2_idle_core_s"].sum())
    tot_c3_c = float(attr_df["class3_core_s"].sum())
    tot_c4_c = float(attr_df["class4_core_s"].sum())
    reclaim_c_share = round(100.0 * (tot_c2 + tot_c3_c + tot_c4_c) / max(1.0, total_res_c), 2)

    c1_col = (
        "class1_over_mem_mb_s" if "class1_over_mem_mb_s" in attr_df.columns else "over_mem_mb_s"
    )
    tot_c1 = float(attr_df[c1_col].sum())
    tot_c3_m = float(attr_df["class3_mem_mb_s"].sum())
    tot_c4_m = float(attr_df["class4_mem_mb_s"].sum())
    reclaim_m_share = round(100.0 * (tot_c1 + tot_c3_m + tot_c4_m) / max(1.0, total_res_m), 2)

    # 4. Per-Class Precision and Recall against Ground Truth
    joined = attr_df.join(truth_df, on="job_id", how="inner")
    true_class = joined["true_class"].to_numpy()

    # Class 1: memory over-request
    c1_join_col = (
        "class1_over_mem_mb_s" if "class1_over_mem_mb_s" in joined.columns else "over_mem_mb_s"
    )
    c1_pred = (joined[c1_join_col] > 0).to_numpy()
    c1_rec, c1_prec, _ = compute_binary_metrics(c1_pred, true_class == 1)

    # Class 2: idle CPU
    c2_pred = (joined["class2_idle_core_s"] > 0).to_numpy()
    c2_rec, c2_prec, _ = compute_binary_metrics(c2_pred, true_class == 2)

    # Class 3: failed work
    c3_pred = (joined["class3_core_s"] > 0).to_numpy()
    c3_rec, c3_prec, _ = compute_binary_metrics(c3_pred, true_class == 3)

    # Class 4: recomputation
    c4_pred = (joined["class4_core_s"] > 0).to_numpy()
    c4_rec, c4_prec, _ = compute_binary_metrics(c4_pred, true_class == 4)

    # 5. Recommendations and Guarantee G2 Guardrail Verification
    recs_df = recommend_jobs(attr_df)
    guardrail_violations = 0
    for rec in recs_df.iter_rows(named=True):
        act = rec.get("recommendation_action")
        oom_c = rec.get("oom_count") or 0
        sample_c = rec.get("job_count") or 0
        rec_m = rec.get("recommended_req_mem_mb")
        max_m = rec.get("max_observed_rss_mb") or 0

        # Safety: OOM group never receives decrease
        if oom_c > 0 and act == "decrease_mem":
            guardrail_violations += 1

        # Safety: Below sample floor receives no recommendation
        if sample_c < 5 and act in ("decrease_mem", "decrease_cpu"):
            guardrail_violations += 1

        # Safety: Recommendation not below observed maximum
        if rec_m is not None and rec_m < max_m:
            guardrail_violations += 1

    # 6. Discrete-Event Simulation
    cluster_cfg = infer_cluster_from_trace(canonical_df)

    t0 = time.perf_counter()
    _, baseline_res = simulate_trace(canonical_df, cluster=cluster_cfg, scenario="baseline")
    sim_duration_s = max(0.0001, time.perf_counter() - t0)
    sim_throughput = len(canonical_df) / sim_duration_s

    # Counterfactual scenarios
    scenarios_wait: dict[str, tuple[float, float]] = {}
    scenarios_wait["baseline"] = (
        float(baseline_res.get("median_wait_s", 0.0)),
        float(baseline_res.get("p95_wait_s", 0.0)),
    )
    for sc in [
        "mem_rightsized",
        "cpu_rightsized_none",
        "cpu_rightsized_proportional",
        "cache_dedup",
        "all",
    ]:
        _, sc_res = simulate_trace(attr_df, cluster=cluster_cfg, scenario=sc)
        scenarios_wait[sc] = (
            float(sc_res.get("median_wait_s", 0.0)),
            float(sc_res.get("p95_wait_s", 0.0)),
        )

    base_med, base_p95 = scenarios_wait["baseline"]
    all_med, all_p95 = scenarios_wait["all"]
    med_wait_change = round(all_med - base_med, 2)
    p95_wait_change = round(all_p95 - base_p95, 2)

    # 7. Calibration on SWF trace
    calib_sample = (
        swf_df if len(swf_df) > 0 else parse_swf(Path("tests/fixtures/swf/sample_workload.swf"))
    )
    calib_cluster = infer_cluster_from_trace(calib_sample)
    # Replay on first 1000 jobs for quick benchmark evaluation
    calib_slice = calib_sample.head(min(1000, len(calib_sample)))
    sim_calib_df, _ = simulate_trace(calib_slice, cluster=calib_cluster, scenario="baseline")
    calib_metrics = compute_calibration_metrics(sim_calib_df, calib_slice)
    calib_mae = round(float(calib_metrics.get("median_absolute_error_s", 0.0)), 2)
    calib_rho = round(float(calib_metrics.get("spearman_rank_correlation", 0.0)), 3)

    # 8. Peak Process Memory RSS
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # ru_maxrss is in kilobytes on Linux
    peak_rss_mb = round(usage.ru_maxrss / 1024.0, 2)

    return {
        "n_jobs": n_jobs,
        "seed": seed,
        "g1_exact": g1_exact,
        "guardrail_violations": guardrail_violations,
        "attribution_coverage_pct": attribution_coverage_pct,
        "reclaim_core_share_pct": reclaim_c_share,
        "reclaim_mem_share_pct": reclaim_m_share,
        "class1_recall": round(c1_rec, 4),
        "class1_precision": round(c1_prec, 4),
        "class2_recall": round(c2_rec, 4),
        "class2_precision": round(c2_prec, 4),
        "class3_recall": round(c3_rec, 4),
        "class3_precision": round(c3_prec, 4),
        "class4_recall": round(c4_rec, 4),
        "class4_precision": round(c4_prec, 4),
        "sacct_ingest_throughput": round(sacct_ingest_throughput, 1),
        "swf_ingest_throughput": round(swf_ingest_throughput, 1),
        "sim_throughput": round(sim_throughput, 1),
        "median_wait_change_s": med_wait_change,
        "p95_wait_change_s": p95_wait_change,
        "calibration_mae_s": calib_mae,
        "calibration_rho": calib_rho,
        "peak_rss_mb": peak_rss_mb,
    }


def run_benchmark(
    size_str: str = "20k",
    runs: int = 1,
    seed: int = 1,
    output_dir: Path | str = "bench/results",
    smoke_mode: bool = False,
) -> dict[str, Any]:
    """Execute multi-iteration benchmark suite, write results, and verify invariants."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path("data")

    print(
        f"Starting benchmark suite: size={size_str}, runs={runs}, seed={seed}, smoke={smoke_mode}"
    )

    results: list[dict[str, Any]] = []
    for r in range(runs):
        current_seed = seed + r
        print(f"Executing run {r + 1}/{runs} with seed={current_seed}...")
        res = run_benchmark_iteration(size_str, current_seed, data_dir)
        results.append(res)

    # Smoke assertions
    if smoke_mode:
        for idx, res in enumerate(results):
            assert res["g1_exact"], f"Guarantee G1 conservation failed on smoke run {idx + 1}"
            assert (
                res["guardrail_violations"] == 0
            ), f"Guarantee G2 guardrail violations: {res['guardrail_violations']}"
        print("Smoke verification passed: Guarantee G1 exact and zero guardrail violations.")

    # Compute summary aggregates across runs
    summary_row: dict[str, Any] = {}
    for key in results[0]:
        vals = [r[key] for r in results]
        if isinstance(vals[0], bool):
            summary_row[key] = all(vals)
        elif isinstance(vals[0], int | float):
            summary_row[key] = round(float(np.median(vals)), 2)
            summary_row[f"{key}_min"] = round(float(np.min(vals)), 2)
            summary_row[f"{key}_max"] = round(float(np.max(vals)), 2)
        else:
            summary_row[key] = vals[0]

    # Write CSV artifact
    csv_file = out_dir / "bench.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"Wrote benchmark results to {csv_file}")

    # Write Markdown artifact
    md_file = out_dir / "bench.md"
    hw_block = format_hardware_block()

    c1_rec_val = summary_row.get("class1_recall", 0.0)
    c1_prec_val = summary_row.get("class1_precision", 0.0)
    c2_rec_val = summary_row.get("class2_recall", 0.0)
    c2_prec_val = summary_row.get("class2_precision", 0.0)
    c3_rec_val = summary_row.get("class3_recall", 0.0)
    c3_prec_val = summary_row.get("class3_precision", 0.0)
    c4_rec_val = summary_row.get("class4_recall", 0.0)
    c4_prec_val = summary_row.get("class4_precision", 0.0)

    md_lines = [
        "# Research Cluster Waste Attributor — Benchmark Results",
        "",
        "## Hardware and Environment",
        "```",
        hw_block,
        "```",
        "",
        "## Summary Metrics",
        f"- Trace Scale: {size_str} jobs ({summary_row.get('n_jobs', 0)} records)",
        f"- Benchmark Runs: {runs}",
        f"- Guarantee G1 Conservation: {'EXACT' if summary_row.get('g1_exact') else 'VIOLATED'}",
        f"- Guarantee G2 Guardrail Violations: {summary_row.get('guardrail_violations', 0)}",
        f"- Attribution Coverage: {summary_row.get('attribution_coverage_pct', 0.0)}%",
        f"- Reclaimable Core-Hours Share: {summary_row.get('reclaim_core_share_pct', 0.0)}%",
        f"- Reclaimable GB-Hours Share: {summary_row.get('reclaim_mem_share_pct', 0.0)}%",
        f"- SACCT Ingestion Throughput: {summary_row.get('sacct_ingest_throughput', 0.0)} jobs/s",
        f"- SWF Ingestion Throughput: {summary_row.get('swf_ingest_throughput', 0.0)} jobs/s",
        f"- Simulation Baseline Throughput: {summary_row.get('sim_throughput', 0.0)} jobs/s",
        f"- Peak Resident Memory: {summary_row.get('peak_rss_mb', 0.0)} MB",
        "",
        "## Recall and Precision against Planted Ground Truth",
        "| Waste Class | Recall | Precision |",
        "|---|---|---|",
        f"| Class 1: Memory Over-Request | {c1_rec_val:.4f} | {c1_prec_val:.4f} |",
        f"| Class 2: Idle Reserved CPU | {c2_rec_val:.4f} | {c2_prec_val:.4f} |",
        f"| Class 3: Failed & Retried Work | {c3_rec_val:.4f} | {c3_prec_val:.4f} |",
        f"| Class 4: Redundant Recomputation | {c4_rec_val:.4f} | {c4_prec_val:.4f} |",
        "",
        "## Simulation and Calibration",
        (
            f"- Median Wait Change (Scenario 'all' vs Baseline): "
            f"{summary_row.get('median_wait_change_s', 0.0)} s"
        ),
        (
            f"- P95 Wait Change (Scenario 'all' vs Baseline): "
            f"{summary_row.get('p95_wait_change_s', 0.0)} s"
        ),
        (
            f"- Historical Trace Calibration Error (MAE): "
            f"{summary_row.get('calibration_mae_s', 0.0)} s"
        ),
        (
            f"- Historical Trace Rank Correlation (Spearman rho): "
            f"{summary_row.get('calibration_rho', 0.0)}"
        ),
        "",
    ]
    md_file.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote benchmark summary to {md_file}")

    return summary_row


def main() -> None:
    """CLI entrypoint for bench.run."""
    parser = argparse.ArgumentParser(
        description="Run benchmark suite measuring throughput and accuracy."
    )
    parser.add_argument("--size", default="20k", help="Synthetic trace size (e.g. 20k, 1M).")
    parser.add_argument("--runs", type=int, default=1, help="Number of benchmark iterations.")
    parser.add_argument("--seed", type=int, default=1, help="Starting random seed value.")
    parser.add_argument(
        "--output-dir", default="bench/results", help="Directory for output artifacts."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Execute in smoke verification mode asserting invariants.",
    )

    args = parser.parse_args()
    try:
        run_benchmark(
            size_str=args.size,
            runs=args.runs,
            seed=args.seed,
            output_dir=args.output_dir,
            smoke_mode=args.smoke,
        )
    except AssertionError as exc:
        print(f"Benchmark assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
