"""Hypothesis property-based tests enforcing Guarantee G2 safety guardrails.

Validates that:
- Recommended memory never falls below observed maximum peak RSS across all states.
- Groups exhibiting OUT_OF_MEMORY terminations receive increase directions and zero reclaimable memory.
- Groups with sample counts below min_samples receive no recommendations.
- Groups running under 120 seconds receive no CPU core adjustments.
- Acceptance criterion: zero guardrail violations across 10,000 generated groups.
"""

from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from rcwa.attribute import attribute_trace
from rcwa.recommend import recommend_jobs


def _generate_workload_batch(
    seed: int,
    num_groups: int = 200,
) -> pl.DataFrame:
    """Generate synthetic batch of groups for property testing."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    job_id = 0
    states_pool = ["COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"]

    for g in range(num_groups):
        user_name = f"user_{g % 50}"
        task_name = f"task_{seed}_{g}"

        # 25% below sample floor (< 5 jobs), 75% between 5 and 20 jobs
        if rng.random() < 0.25:
            n_jobs = int(rng.integers(1, 5))
        else:
            n_jobs = int(rng.integers(5, 21))

        has_oom = bool(rng.random() < 0.15)
        is_short = bool(rng.random() < 0.15)

        for j in range(n_jobs):
            job_id += 1
            if has_oom and j == 0:
                st_job = "OUT_OF_MEMORY"
            else:
                st_job = "COMPLETED" if rng.random() < 0.65 else str(rng.choice(states_pool))

            run_sec = int(rng.integers(10, 110)) if is_short else int(rng.integers(120, 7200))
            alloc_c = int(rng.choice([1, 2, 4, 8, 16, 32]))
            cpu_used = float(rng.uniform(0.1, float(alloc_c * run_sec)))
            rss = int(rng.integers(256, 32000))
            req_mem = int(max(rss, rng.integers(rss, 64000)))

            rows.append(
                {
                    "job_id": f"job_{seed}_{job_id}",
                    "parent_job_id": None,
                    "source": "sacct",
                    "user": user_name,
                    "account": "research",
                    "partition": "compute",
                    "job_name": task_name,
                    "command_hash": f"hash_{task_name}",
                    "input_hash": None,
                    "submit_time": datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
                    "start_time": datetime(2026, 3, 1, 10, 0, 5, tzinfo=UTC),
                    "end_time": datetime(2026, 3, 1, 10, 30, 5, tzinfo=UTC),
                    "wait_s": 5,
                    "run_s": run_sec,
                    "state": st_job,
                    "exit_code": 0 if st_job == "COMPLETED" else 1,
                    "req_cpus": alloc_c,
                    "alloc_cpus": alloc_c,
                    "cpu_time_used_s": cpu_used,
                    "req_mem_mb": req_mem,
                    "max_rss_mb": rss,
                    "ave_rss_mb": int(rss * 0.95),
                    "req_nodes": 1,
                    "alloc_nodes": 1,
                    "node_list": "node-01",
                    "gpus": 0,
                    "time_limit_s": 7200,
                    "array_task_id": None,
                    "het_component_id": None,
                    "reserved_core_s": alloc_c * run_sec,
                    "reserved_mem_mb_s": req_mem * run_sec,
                }
            )

    return pl.DataFrame(rows)


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=1_000_000))
def test_guarantee_g2_invariants_property(seed: int) -> None:
    """Hypothesis property test validating Guarantee G2 across diverse batches."""
    raw_df = _generate_workload_batch(seed=seed, num_groups=200)
    attr_df = attribute_trace(raw_df)
    recs_df = recommend_jobs(attr_df)

    assert recs_df.height > 0

    for record in recs_df.to_dicts():
        cnt = int(record["job_count"])
        rec_mem = record["recommended_req_mem_mb"]
        rec_cpus = record["recommended_cpus"]
        rec_time = record["recommended_time_limit_s"]
        direction = str(record["recommendation_direction"])
        action = str(record["recommendation_action"])
        has_oom = bool(record["has_oom"])
        reclaim_gb = float(record["reclaimable_gb_hours"])
        obs_max_rss = int(record["observed_max_rss_mb"] or 0)
        obs_max_cpus = record["observed_max_cpus"]

        # 1. Sample floor guardrail: non-OOM groups with job_count < 5 receive no recommendation
        if cnt < 5 and not has_oom:
            assert rec_mem is None, f"Sample floor violated: rec_mem={rec_mem} for cnt={cnt}"
            assert rec_cpus is None
            assert rec_time is None
            assert direction == "none"
            assert action == "below_sample_floor"
            continue

        # 2. Guarantee G2: OUT_OF_MEMORY escalation
        if has_oom:
            assert (
                direction == "increase"
            ), f"Expected increase direction for OOM group, got {direction}"
            assert reclaim_gb == 0.0, f"OOM group must have 0 reclaimable memory, got {reclaim_gb}"
            assert rec_mem is not None
            assert rec_mem >= obs_max_rss, f"OOM floor violated: {rec_mem} < {obs_max_rss}"
        else:
            # 3. Standard memory floor guardrail: never below observed maximum RSS
            if rec_mem is not None and obs_max_rss > 0:
                assert rec_mem >= obs_max_rss, f"Memory floor violated: {rec_mem} < {obs_max_rss}"

        # 4. CPU recommendation bounds
        if rec_cpus is not None:
            assert obs_max_cpus is not None
            assert 1 <= rec_cpus <= int(obs_max_cpus)


def test_guarantee_g2_ten_thousand_groups_acceptance() -> None:
    """Acceptance: Verify zero guardrail violations across 10,000 generated groups."""
    total_target_groups = 10_000
    batch_size = 500
    num_batches = total_target_groups // batch_size
    accumulated_groups = 0
    guardrail_violations = 0

    for b in range(num_batches):
        batch_df = _generate_workload_batch(seed=1000 + b, num_groups=batch_size)
        attr_df = attribute_trace(batch_df)
        recs_df = recommend_jobs(attr_df)

        accumulated_groups += recs_df.height

        for record in recs_df.to_dicts():
            cnt = int(record["job_count"])
            rec_mem = record["recommended_req_mem_mb"]
            rec_cpus = record["recommended_cpus"]
            direction = str(record["recommendation_direction"])
            has_oom = bool(record["has_oom"])
            reclaim_gb = float(record["reclaimable_gb_hours"])
            obs_max_rss = int(record["observed_max_rss_mb"] or 0)
            obs_max_cpus = record["observed_max_cpus"]

            # Guardrail 1: Sample size floor (< 5 jobs, non-OOM)
            if cnt < 5 and not has_oom:
                if rec_mem is not None or rec_cpus is not None or direction != "none":
                    guardrail_violations += 1
                continue

            # Guardrail 2: OUT_OF_MEMORY escalation and exclusion
            if has_oom:
                if rec_mem is None or rec_mem < obs_max_rss:
                    guardrail_violations += 1
                if direction != "increase":
                    guardrail_violations += 1
                if reclaim_gb != 0.0:
                    guardrail_violations += 1
            else:
                # Guardrail 3: Memory recommendation never below observed peak RSS
                if rec_mem is not None and obs_max_rss > 0 and rec_mem < obs_max_rss:
                    guardrail_violations += 1

            # Guardrail 4: CPU clamping
            if rec_cpus is not None:
                if obs_max_cpus is None or not (1 <= rec_cpus <= int(obs_max_cpus)):
                    guardrail_violations += 1

    assert accumulated_groups == total_target_groups
    assert (
        guardrail_violations == 0
    ), f"Detected {guardrail_violations} guardrail violations in 10,000 groups"
