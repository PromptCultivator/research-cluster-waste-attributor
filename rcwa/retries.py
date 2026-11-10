"""Detection and linkage of batch job failure retry chains.

Identifies failed compute jobs and links subsequent resubmissions by the same
user with identical task identifiers within a configurable temporal window.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

FAILED_STATES = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}


def _normalize_dt(dt: datetime | None) -> datetime | None:
    """Ensure datetime carries UTC timezone if naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def detect_retry_chains(
    df: pl.DataFrame,
    retry_window_s: int = 86400,
) -> pl.DataFrame:
    """Identify failed jobs and link subsequent resubmissions into retry chains.

    A later job by the same user with the same task identifier (command_hash or
    job_name) submitted within retry_window_s after a failed job is marked retry_of.
    Each failure is claimed by at most one earliest candidate resubmission.

    Args:
        df: Input canonical Polars DataFrame.
        retry_window_s: Maximum temporal window in seconds for retries (default 86400 = 24h).

    Returns:
        DataFrame augmented with retry_of, retry_chain_id, retry_count,
        retry_chain_cost_core_s, and retry_chain_cost_mem_mb_s columns.
    """
    if df.height == 0:
        return df.with_columns(
            [
                pl.lit(None, dtype=pl.String).alias("retry_of"),
                pl.lit(None, dtype=pl.String).alias("retry_chain_id"),
                pl.lit(0, dtype=pl.Int32).alias("retry_count"),
                pl.lit(0, dtype=pl.Int64).alias("retry_chain_cost_core_s"),
                pl.lit(None, dtype=pl.Int64).alias("retry_chain_cost_mem_mb_s"),
            ]
        )

    # Extract required fields for in-memory graph traversal
    records: list[dict[str, Any]] = df.to_dicts()

    # Precompute effective end times, failure status, and task identifiers
    # Temporal causality: coalesce(end_time, start_time + run_s, submit_time + wait_s + run_s)
    enriched_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(records):
        st = row["state"]
        run_s = row["run_s"] or 0
        wait_s = row["wait_s"] or 0
        sub_time = row["submit_time"]
        start_time = row["start_time"]
        end_time = row["end_time"]

        if end_time is not None:
            eff_end = end_time
        elif start_time is not None:
            eff_end = start_time + timedelta(seconds=run_s)
        elif sub_time is not None:
            eff_end = sub_time + timedelta(seconds=wait_s + run_s)
        else:
            eff_end = None

        is_failed = (
            (st in FAILED_STATES)
            or (st == "CANCELLED" and run_s > 0)
            or (run_s == 0 and st not in {"RUNNING", "PENDING"})
        )

        task_id = row.get("command_hash") or row.get("job_name")

        enriched_rows.append(
            {
                "idx": idx,
                "job_id": str(row["job_id"]),
                "user": row.get("user"),
                "task_id": task_id,
                "submit_time": sub_time,
                "eff_end": eff_end,
                "is_failed": is_failed,
                "reserved_core_s": row.get("reserved_core_s") or 0,
                "reserved_mem_mb_s": row.get("reserved_mem_mb_s"),
            }
        )

    # Group eligible candidates by (user, task_id)
    # Jobs with missing user or task_id cannot establish matching retry links
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row_info in enriched_rows:
        user = row_info["user"]
        task_id = row_info["task_id"]
        if user and task_id:
            groups[(str(user), str(task_id))].append(row_info)

    # Link failures to resubmissions within each group
    # 1-to-1 matching: earliest candidate resubmission claims the failure
    retry_of_map: dict[str, str] = {}  # child_job_id -> parent_job_id
    claimed_children: set[str] = set()

    for _grp_key, grp_items in groups.items():
        # Sort jobs chronologically by submit_time, then job_id
        def _job_sort_key(x: dict[str, Any]) -> tuple[int, datetime, int, str]:
            sub = _normalize_dt(x["submit_time"])
            return (
                0 if sub is not None else 1,
                sub if sub is not None else datetime.min.replace(tzinfo=UTC),
                x["idx"],
                x["job_id"],
            )

        sorted_jobs = sorted(grp_items, key=_job_sort_key)

        # Collect failed jobs in group
        failed_jobs = [j for j in sorted_jobs if j["is_failed"] and j["eff_end"] is not None]

        # Sort failed jobs chronologically by effective end time
        def _failed_sort_key(x: dict[str, Any]) -> tuple[datetime, int, datetime, int, str]:
            eff = _normalize_dt(x["eff_end"]) or datetime.min.replace(tzinfo=UTC)
            sub = _normalize_dt(x["submit_time"])
            return (
                eff,
                0 if sub is not None else 1,
                sub if sub is not None else datetime.min.replace(tzinfo=UTC),
                x["idx"],
                x["job_id"],
            )

        failed_jobs.sort(key=_failed_sort_key)

        for f_job in failed_jobs:
            f_end = _normalize_dt(f_job["eff_end"])
            f_id = f_job["job_id"]
            if f_end is None:
                continue

            # Search for earliest eligible subsequent resubmission
            candidates = []
            for c_job in sorted_jobs:
                c_id = c_job["job_id"]
                if c_id == f_id or c_id in claimed_children:
                    continue
                c_sub = _normalize_dt(c_job["submit_time"])
                if c_sub is None:
                    continue
                # Temporal causality: resubmission must happen at or after failure end
                delta_s = (c_sub - f_end).total_seconds()
                if 0 <= delta_s <= retry_window_s:
                    candidates.append((c_sub, c_id))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                chosen_child_id = candidates[0][1]
                retry_of_map[chosen_child_id] = f_id
                claimed_children.add(chosen_child_id)

    # Multi-hop chain resolution:
    # Trace chains to root failure and determine hop count and total chain cost
    parent_to_children: dict[str, list[str]] = defaultdict(list)
    for child_id, parent_id in retry_of_map.items():
        parent_to_children[parent_id].append(child_id)

    job_info_by_id = {j["job_id"]: j for j in enriched_rows}

    # Find root jobs: jobs that are parents but are not children of any job
    # Also find jobs that are in a chain (either as parent or as child)
    chain_roots: set[str] = set()
    for parent_id in parent_to_children:
        curr = parent_id
        visited = set()
        while curr in retry_of_map and curr not in visited:
            visited.add(curr)
            curr = retry_of_map[curr]
        chain_roots.add(curr)

    # Traverse each root tree to assign root_id, hop distance, and chain totals
    chain_id_map: dict[str, str] = {}
    hop_count_map: dict[str, int] = {}
    chain_members_map: dict[str, list[str]] = {}

    for root_id in chain_roots:
        # Collect all nodes reachable from root_id
        nodes_in_chain: list[str] = []
        stack = [(root_id, 0)]
        visited_nodes: set[str] = set()

        while stack:
            curr_id, depth = stack.pop()
            if curr_id in visited_nodes:
                continue
            visited_nodes.add(curr_id)
            nodes_in_chain.append(curr_id)
            chain_id_map[curr_id] = root_id
            hop_count_map[curr_id] = depth

            for ch_id in parent_to_children.get(curr_id, []):
                if ch_id not in visited_nodes:
                    stack.append((ch_id, depth + 1))

        # Only form a chain if at least 2 jobs participate (root + resubmission)
        if len(nodes_in_chain) >= 2:
            for node_id in nodes_in_chain:
                chain_members_map[node_id] = nodes_in_chain
        else:
            # Standalone job; does not constitute a retry chain
            for node_id in nodes_in_chain:
                chain_id_map.pop(node_id, None)
                hop_count_map.pop(node_id, None)

    # Compute chain costs
    chain_core_cost_by_root: dict[str, int] = {}
    chain_mem_cost_by_root: dict[str, int | None] = {}

    for root_id in chain_roots:
        if root_id not in chain_id_map:
            continue
        members = chain_members_map.get(root_id, [])
        total_core = sum(
            job_info_by_id[m]["reserved_core_s"] for m in members if m in job_info_by_id
        )

        mem_vals = [
            job_info_by_id[m]["reserved_mem_mb_s"]
            for m in members
            if m in job_info_by_id and job_info_by_id[m]["reserved_mem_mb_s"] is not None
        ]
        total_mem = sum(mem_vals) if mem_vals else None

        chain_core_cost_by_root[root_id] = total_core
        chain_mem_cost_by_root[root_id] = total_mem

    # Populate final series arrays matching original row ordering
    retry_of_col: list[str | None] = []
    retry_chain_id_col: list[str | None] = []
    retry_count_col: list[int] = []
    retry_chain_cost_core_col: list[int] = []
    retry_chain_cost_mem_col: list[int | None] = []

    for row_info in enriched_rows:
        jid = row_info["job_id"]
        p_id = retry_of_map.get(jid)
        root_id = chain_id_map.get(jid)
        depth = hop_count_map.get(jid, 0)

        retry_of_col.append(p_id)
        retry_chain_id_col.append(root_id)
        retry_count_col.append(depth)

        if root_id is not None:
            retry_chain_cost_core_col.append(chain_core_cost_by_root.get(root_id, 0))
            retry_chain_cost_mem_col.append(chain_mem_cost_by_root.get(root_id))
        else:
            retry_chain_cost_core_col.append(0)
            retry_chain_cost_mem_col.append(None)

    return df.with_columns(
        [
            pl.Series("retry_of", retry_of_col, dtype=pl.String),
            pl.Series("retry_chain_id", retry_chain_id_col, dtype=pl.String),
            pl.Series("retry_count", retry_count_col, dtype=pl.Int32),
            pl.Series("retry_chain_cost_core_s", retry_chain_cost_core_col, dtype=pl.Int64),
            pl.Series("retry_chain_cost_mem_mb_s", retry_chain_cost_mem_col, dtype=pl.Int64),
        ]
    )
