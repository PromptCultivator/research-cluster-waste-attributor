"""Throughput benchmark test for Slurm sacct export parsing on 100,000 rows."""

import time

from rcwa.adapters.sacct import parse_sacct


def test_sacct_100k_rows_benchmark() -> None:
    """Benchmark parsing throughput on a 100,000-row synthetic sacct trace.

    Measures parsing duration and asserts parsing throughput in jobs/second.
    """
    row_count = 100_000
    headers = (
        "JobIDRaw|JobID|User|Account|Partition|QOS|JobName|Submit|Eligible|Start|End|Elapsed|"
        "State|ExitCode|ReqCPUS|AllocCPUS|ReqMem|MaxRSS|AveRSS|TotalCPU|CPUTimeRAW|ReqTRES|"
        "AllocTRES|NodeList|Comment|SubmitLine"
    )

    rows = [headers]
    for i in range(row_count):
        user_idx = i % 20
        row_str = (
            f"{i}|{i}|user{user_idx}|dept_comp|gpu|normal|model_eval_{i}|"
            "2026-03-01T10:00:00|2026-03-01T10:00:02|2026-03-01T10:00:05|2026-03-01T10:30:05|"
            "00:30:00|COMPLETED|0:0|4|4|8000M|3200M|3000M|01:40:00|7200|"
            "billing=4,cpu=4,mem=8000M,node=1|billing=4,cpu=4,mem=8000M,node=1|"
            "node-01||sbatch run_model.sh"
        )
        rows.append(row_str)

    payload = "\n".join(rows)

    start_time = time.perf_counter()
    df = parse_sacct(payload)
    elapsed_s = time.perf_counter() - start_time

    assert df.height == row_count, f"Expected {row_count} parsed records, got {df.height}"

    throughput_jobs_per_s = row_count / elapsed_s
    # Expect throughput to comfortably exceed 5,000 jobs per second on production hardware
    assert (
        throughput_jobs_per_s >= 5000.0
    ), f"Measured throughput {throughput_jobs_per_s:.1f} jobs/s lower than 5000 jobs/s threshold"
