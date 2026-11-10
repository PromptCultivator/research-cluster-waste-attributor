"""Synthetic trace generator with planted waste categories and ground-truth emission.

Generates realistic Slurm sacct accounting records containing planted instances of:
- Class 1: Memory over-request (generous reservation relative to peak resident size)
- Class 2: Idle reserved CPU (multi-core allocation with single-threaded execution)
- Class 3: Failed and retried work (job failures, timeouts, out-of-memory kills, retry chains)
- Class 4: Redundant recomputation (identical inputs and commands producing duplicate outputs)
- Normal execution (balanced utilization and successful completion)
- Data quality edge cases (unattributed missing metrics, active running/pending jobs)
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl


def parse_trace_size(size_val: int | str) -> int:
    """Parse trace size descriptor string or integer to job count.

    Examples:
        >>> parse_trace_size("20k")
        20000
        >>> parse_trace_size("1M")
        1000000
        >>> parse_trace_size(50)
        50
    """
    if isinstance(size_val, int):
        return max(1, size_val)

    s = str(size_val).strip()
    if not s:
        return 20000

    s_upper = s.upper()
    if s_upper.endswith("K"):
        multiplier = 1000
        numeric_str = s_upper[:-1]
    elif s_upper.endswith("M"):
        multiplier = 1000000
        numeric_str = s_upper[:-1]
    elif s_upper.endswith("G"):
        multiplier = 1000000000
        numeric_str = s_upper[:-1]
    else:
        multiplier = 1
        numeric_str = s_upper

    try:
        val = float(numeric_str)
        return max(1, int(val * multiplier))
    except ValueError:
        return 20000


def _format_duration_hms(seconds: int) -> str:
    """Format duration in seconds to Slurm D-HH:MM:SS or HH:MM:SS string."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    if days > 0:
        return f"{days}-{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def generate_synthetic_trace(
    size: int | str = "20k",
    seed: int = 1,
    faults: str = "default",
) -> tuple[str, pl.DataFrame]:
    """Generate synthetic sacct accounting export text and paired ground-truth table.

    Args:
        size: Target number of job records (e.g. 50, '20k', '1M').
        seed: Random seed for deterministic generation.
        faults: Fault injection profile ('default', 'all_waste', 'no_waste').

    Returns:
        Tuple of (sacct_pipe_delimited_text, ground_truth_dataframe).
    """
    n_jobs = parse_trace_size(size)
    rng = random.Random(seed)

    users = [
        ("alice", "quant_research", "alpha_train", "compute", "alpha.sh"),
        ("bob", "execution_eng", "feed_handler", "compute", "feed.sh"),
        ("carol", "strat_test", "sim_portfolio", "compute", "sim.sh"),
        ("david", "data_eng", "order_book_proc", "fatmem", "book.sh"),
        ("eve", "strat_test", "nn_forward", "gpu", "nn.sh"),
        ("frank", "quant_research", "mc_risk", "compute", "risk.sh"),
        ("grace", "strat_test", "quick_check", "compute", "check.sh"),
        ("heidi", "data_eng", "feature_matrix", "fatmem", "features.sh"),
    ]

    base_time = datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC)

    # Header line conforming to SPEC.md §5.1
    header = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|"
        "Elapsed|State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|"
        "CPUTimeRAW|ReqTRES|AllocTRES|NodeList|Comment|SubmitLine"
    )

    sacct_lines = [header]
    truth_rows: list[dict[str, Any]] = []

    # Store earlier jobs for duplicate recomputation (Class 4) and retry chains (Class 3)
    completed_cache: list[dict[str, Any]] = []
    failed_for_retry: list[dict[str, Any]] = []

    for i in range(1, n_jobs + 1):
        job_id = str(10000 + i)
        u_info = users[(i - 1) % len(users)]
        user, acct, job_name, partition, script_name = u_info

        job_subgroup = (i // 50) % 4
        job_name = f"{job_name}_{job_subgroup}"
        script_name = f"{job_name}.sh"

        # Stagger submit time monotonically across trace lifetime
        submit_offset = (i - 1) * 35
        submit_dt = base_time + timedelta(seconds=submit_offset)
        wait_s = rng.randint(2, 60)
        start_dt = submit_dt + timedelta(seconds=wait_s)

        # Determine fault type based on profile and deterministic cycling
        fault_selector = rng.random()

        if faults == "no_waste":
            fault_type = "normal"
        elif faults == "all_waste":
            options = ["class1", "class2", "class3_fail", "class4_dup"]
            fault_type = options[(i - 1) % len(options)]
        else:
            # Default realistic distribution
            if failed_for_retry and rng.random() < 0.15:
                fault_type = "retry_success"
            elif completed_cache and rng.random() < 0.12:
                fault_type = "class4_dup"
            elif fault_selector < 0.25:
                fault_type = "class1_mem"
            elif fault_selector < 0.45:
                fault_type = "class2_cpu"
            elif fault_selector < 0.55:
                fail_kinds = ["fail", "timeout", "oom", "early"]
                fault_type = f"class3_{rng.choice(fail_kinds)}"
            elif fault_selector < 0.60:
                fault_type = "unattributed"
            elif fault_selector < 0.63 and i > n_jobs - 5:
                fault_type = "active_running"
            else:
                fault_type = "normal"

        # Defaults for job characteristics
        cpus = rng.choice([2, 4, 8, 16])
        req_mem_mb = cpus * rng.choice([1024, 2048, 4096])
        run_s = rng.randint(60, 1800)
        state = "COMPLETED"
        exit_code = "0:0"
        comment = ""
        input_hash = None
        command_hash = hashlib.sha256(f"{job_name}:{script_name}".encode()).hexdigest()[:16]

        true_class = 0
        is_recompute = False
        is_retry = False

        if fault_type == "normal":
            # Balanced utilization
            max_rss_mb = int(req_mem_mb * rng.uniform(0.75, 0.95))
            ave_rss_mb = int(max_rss_mb * 0.90)
            cpu_util = rng.uniform(0.85, 0.98)
            cpu_used_s = run_s * cpus * cpu_util
            true_class = 0

            # Store in completed cache for potential future Class 4 duplication
            input_hash = hashlib.sha256(f"dataset_{i % 20}".encode()).hexdigest()
            comment = f"RCWA_INPUT_HASH={input_hash}"
            completed_cache.append(
                {
                    "user": user,
                    "account": acct,
                    "partition": partition,
                    "job_name": job_name,
                    "command_hash": command_hash,
                    "input_hash": input_hash,
                    "cpus": cpus,
                    "req_mem_mb": req_mem_mb,
                    "run_s": run_s,
                }
            )

        elif fault_type == "class1_mem":
            # Memory over-request: low RSS relative to requested memory
            true_class = 1
            max_rss_mb = int(req_mem_mb * rng.uniform(0.10, 0.25))
            ave_rss_mb = int(max_rss_mb * 0.85)
            cpu_util = rng.uniform(0.85, 0.95)
            cpu_used_s = run_s * cpus * cpu_util

        elif fault_type == "class2_cpu":
            # Idle reserved CPU: multi-core request executed single-threaded
            true_class = 2
            cpus = max(4, cpus)
            max_rss_mb = int(req_mem_mb * rng.uniform(0.70, 0.90))
            ave_rss_mb = int(max_rss_mb * 0.85)
            # CPU usage corresponds to ~1 core active
            cpu_used_s = float(run_s * 0.95)

        elif fault_type == "class3_fail":
            true_class = 3
            state = "FAILED"
            exit_code = "1:0"
            max_rss_mb = int(req_mem_mb * 0.5)
            ave_rss_mb = int(max_rss_mb * 0.8)
            cpu_used_s = float(run_s * cpus * 0.5)
            failed_for_retry.append(
                {
                    "user": user,
                    "account": acct,
                    "partition": partition,
                    "job_name": job_name,
                    "command_hash": command_hash,
                    "fail_submit": submit_dt,
                }
            )

        elif fault_type == "class3_timeout":
            true_class = 3
            state = "TIMEOUT"
            exit_code = "0:0"
            run_s = 7200
            max_rss_mb = int(req_mem_mb * 0.7)
            ave_rss_mb = int(max_rss_mb * 0.9)
            cpu_used_s = float(run_s * cpus * 0.9)

        elif fault_type == "class3_oom":
            true_class = 3
            state = "OUT_OF_MEMORY"
            exit_code = "0:125"
            max_rss_mb = req_mem_mb
            ave_rss_mb = int(max_rss_mb * 0.95)
            cpu_used_s = float(run_s * cpus * 0.6)

        elif fault_type == "class3_early":
            true_class = 3
            state = "FAILED"
            exit_code = "2:0"
            run_s = 15
            max_rss_mb = int(req_mem_mb * 0.1)
            ave_rss_mb = max_rss_mb
            cpu_used_s = float(run_s * cpus * 0.2)

        elif fault_type == "retry_success":
            # Successful retry of a prior failure
            prior_fail = failed_for_retry.pop(0)
            user = prior_fail["user"]
            acct = prior_fail["account"]
            partition = prior_fail["partition"]
            job_name = prior_fail["job_name"]
            command_hash = prior_fail["command_hash"]
            # Ensure submit time is strictly after prior failure
            submit_dt = prior_fail["fail_submit"] + timedelta(seconds=rng.randint(60, 600))
            start_dt = submit_dt + timedelta(seconds=rng.randint(5, 30))
            true_class = 0
            is_retry = True
            state = "COMPLETED"
            exit_code = "0:0"
            max_rss_mb = int(req_mem_mb * 0.8)
            ave_rss_mb = int(max_rss_mb * 0.9)
            cpu_used_s = float(run_s * cpus * 0.9)

        elif fault_type == "class4_dup":
            if completed_cache:
                # Redundant recomputation: duplicate input hash and command
                prior_job = rng.choice(completed_cache)
                user = prior_job["user"]
                acct = prior_job["account"]
                partition = prior_job["partition"]
                job_name = prior_job["job_name"]
                command_hash = prior_job["command_hash"]
                input_hash = prior_job["input_hash"]
                cpus = prior_job["cpus"]
                req_mem_mb = prior_job["req_mem_mb"]
                run_s = prior_job["run_s"]
                comment = f"RCWA_INPUT_HASH={input_hash}"

                true_class = 4
                is_recompute = True
                state = "COMPLETED"
                exit_code = "0:0"
                max_rss_mb = int(req_mem_mb * 0.8)
                ave_rss_mb = int(max_rss_mb * 0.9)
                cpu_used_s = float(run_s * cpus * 0.9)
            else:
                # Populate cache with initial completed job for subsequent duplicates
                true_class = 0
                max_rss_mb = int(req_mem_mb * 0.8)
                ave_rss_mb = int(max_rss_mb * 0.9)
                cpu_used_s = float(run_s * cpus * 0.9)
                input_hash = hashlib.sha256(f"seed_dataset_{i}".encode()).hexdigest()
                comment = f"RCWA_INPUT_HASH={input_hash}"
                completed_cache.append(
                    {
                        "user": user,
                        "account": acct,
                        "partition": partition,
                        "job_name": job_name,
                        "command_hash": command_hash,
                        "input_hash": input_hash,
                        "cpus": cpus,
                        "req_mem_mb": req_mem_mb,
                        "run_s": run_s,
                    }
                )

        elif fault_type == "unattributed":
            # Incomplete metrics resulting in unattributed waste
            true_class = -1
            state = "COMPLETED"
            exit_code = "0:0"
            max_rss_mb = None
            ave_rss_mb = None
            cpu_used_s = None

        elif fault_type == "active_running":
            # Active job excluded from attribution
            true_class = -2
            state = "RUNNING"
            exit_code = "0:0"
            run_s = 120
            max_rss_mb = int(req_mem_mb * 0.5)
            ave_rss_mb = int(max_rss_mb * 0.8)
            cpu_used_s = float(run_s * cpus * 0.5)

        else:
            max_rss_mb = int(req_mem_mb * 0.8)
            ave_rss_mb = int(max_rss_mb * 0.9)
            cpu_used_s = float(run_s * cpus * 0.9)

        # Temporal boundaries
        if state in ("RUNNING", "PENDING"):
            end_dt_str = "Unknown"
        else:
            end_dt = start_dt + timedelta(seconds=run_s)
            end_dt_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

        submit_dt_str = submit_dt.strftime("%Y-%m-%dT%H:%M:%S")
        eligible_dt_str = (submit_dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")
        start_dt_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        elapsed_str = _format_duration_hms(run_s)
        total_cpu_str = _format_duration_hms(int(cpu_used_s)) if cpu_used_s is not None else ""
        cputime_raw = str(int(run_s * cpus))

        req_mem_str = f"{req_mem_mb}M"
        max_rss_str = f"{max_rss_mb}M" if max_rss_mb is not None else ""
        ave_rss_str = f"{ave_rss_mb}M" if ave_rss_mb is not None else ""

        gpu_tres = ",gres/gpu=1" if partition == "gpu" else ""
        req_tres = f"billing={cpus},cpu={cpus}{gpu_tres},mem={req_mem_mb}M,node=1"
        alloc_tres = req_tres
        node_id = f"node-{(i % 32) + 1:02d}"
        submit_line = f"sbatch {script_name}"

        row_fields = [
            job_id,  # JobIDRaw
            job_id,  # JobID
            user,  # User
            acct,  # Account
            partition,  # Partition
            "normal",  # QOS
            job_name,  # JobName
            submit_dt_str,  # Submit
            eligible_dt_str,  # Eligible
            start_dt_str,  # Start
            end_dt_str,  # End
            elapsed_str,  # Elapsed
            state,  # State
            exit_code,  # ExitCode
            str(cpus),  # ReqCPUS
            str(cpus),  # AllocCPUS
            req_mem_str,  # ReqMem
            max_rss_str,  # MaxRSS
            ave_rss_str,  # AveRSS
            total_cpu_str,  # TotalCPU
            cputime_raw,  # CPUTimeRAW
            req_tres,  # ReqTRES
            alloc_tres,  # AllocTRES
            node_id,  # NodeList
            comment,  # Comment
            submit_line,  # SubmitLine
        ]

        sacct_lines.append("|".join(row_fields))

        # Ground truth tracking record
        truth_rows.append(
            {
                "job_id": job_id,
                "true_class": true_class,
                "planted_fault_type": fault_type,
                "planted_is_recompute": is_recompute,
                "planted_is_retry": is_retry,
                "is_recompute": is_recompute,
                "is_retry": is_retry,
                "user": user,
                "job_name": job_name,
                "command_hash": command_hash,
                "input_hash": input_hash,
                "req_cpus": cpus,
                "alloc_cpus": cpus,
                "req_mem_mb": req_mem_mb,
                "max_rss_mb": max_rss_mb,
                "run_s": run_s,
                "state": state,
            }
        )

    sacct_text = "\n".join(sacct_lines) + "\n"
    truth_df = pl.DataFrame(truth_rows)
    return sacct_text, truth_df


def write_synthetic_trace(
    output_path: Path | str,
    sacct_text: str,
    truth_df: pl.DataFrame | None = None,
    ground_truth_path: Path | str | None = None,
) -> None:
    """Write synthetic sacct trace and paired ground truth table to disk."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sacct_text, encoding="utf-8")

    if truth_df is not None:
        if ground_truth_path is not None:
            gt_p = Path(ground_truth_path)
        else:
            # Suffix alongside output file
            gt_p = out.with_suffix(".truth.parquet")
        gt_p.parent.mkdir(parents=True, exist_ok=True)
        truth_df.write_parquet(gt_p)
