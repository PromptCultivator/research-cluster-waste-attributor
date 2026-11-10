"""Standard Workload Format (SWF) trace adapter.

Parses 18-field whitespace-separated SWF logs, extracts header pragmas,
converts per-processor memory and CPU metrics to cluster totals,
and produces canonical DataFrames.
"""

import gzip
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal, overload

import polars as pl

from rcwa.model import POLARS_CANONICAL_SCHEMA, empty_canonical_df
from rcwa.normalize import map_swf_status


def _get_line_iterator(source: Path | IO[str] | str) -> tuple[Iterator[str], bool]:
    """Obtain line iterator from path, stream, or text string.

    Returns:
        tuple[Iterator[str], bool]: line iterator and empty status flag.
    """
    if isinstance(source, Path) or (
        isinstance(source, str) and "\n" not in source and os.path.exists(source)
    ):
        file_path = Path(source)
        if not file_path.is_file():
            return iter([]), True

        raw_bytes = file_path.read_bytes()[:8192]
        if raw_bytes[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(file_path.read_bytes()).decode("utf-8", errors="replace")
                lines = content.splitlines()
                return iter(lines), len(lines) == 0
            except Exception as exc:
                raise ValueError(f"Failed to decompress gzip file: {file_path}") from exc

        if b"\x00" in raw_bytes:
            raise ValueError(f"Binary or non-UTF-8 trace file cannot be decoded: {file_path}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Decoding failed for file: {file_path}") from exc

        lines = content.splitlines()
        return iter(lines), len(lines) == 0

    if isinstance(source, str):
        if "\x00" in source:
            raise ValueError("Binary or null bytes detected in string input")
        lines = source.splitlines()
        return iter(lines), len(lines) == 0

    raw: Any = getattr(source, "read")()
    if isinstance(raw, bytes):
        if raw[:2] == b"\x1f\x8b":
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
        elif 0 in raw:
            raise ValueError("Binary content detected in file stream")
        else:
            text = raw.decode("utf-8")
    else:
        text = str(raw)

    lines = text.splitlines()
    return iter(lines), len(lines) == 0


def parse_swf_pragmas(lines: list[str]) -> dict[str, str]:
    """Extract pragma header comments starting with semicolon."""
    pragmas: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if not s.startswith(";"):
            continue
        comment_body = s[1:].strip()
        if ":" in comment_body:
            key, val = comment_body.split(":", 1)
            pragmas[key.strip()] = val.strip()
        else:
            parts = comment_body.split(None, 1)
            if parts:
                pragmas[parts[0]] = parts[1] if len(parts) > 1 else ""
    return pragmas


def parse_swf_with_pragmas(
    source: Path | IO[str] | str,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Parse SWF trace and return both canonical DataFrame and header pragmas."""
    line_iter, is_empty = _get_line_iterator(source)
    if is_empty:
        return empty_canonical_df(), {}

    all_lines = list(line_iter)
    pragmas = parse_swf_pragmas(all_lines)

    base_epoch = 0
    if "UnixStartTime" in pragmas:
        try:
            base_epoch = int(pragmas["UnixStartTime"])
        except ValueError:
            base_epoch = 0

    records: list[dict[str, Any]] = []

    for line in all_lines:
        s = line.strip()
        if not s or s.startswith(";"):
            continue

        parts = s.split()
        if len(parts) < 11:
            # Skip truncated lines without required field count
            continue

        # 1. Job Number
        job_id = str(int(float(parts[0])))

        # 2. Submit Time
        submit_offset = int(float(parts[1]))
        submit_time = datetime.fromtimestamp(base_epoch + max(0, submit_offset), tz=UTC)

        # 3. Wait Time (-1 for missing)
        wait_val = int(float(parts[2]))
        wait_s = max(0, wait_val)

        # 4. Run Time (-1 for missing)
        run_val = int(float(parts[3]))
        run_s = max(0, run_val)

        # 5. Allocated Processors
        alloc_cpus_val = int(float(parts[4]))
        alloc_cpus = max(1, alloc_cpus_val)

        # 6. Average CPU Time Used (seconds per proc; -1 for missing)
        avg_cpu = float(parts[5])
        if avg_cpu >= 0:
            cpu_time_used_s: float | None = avg_cpu * alloc_cpus
        else:
            cpu_time_used_s = None

        # 7. Used Memory (KB per proc; -1 for missing) -> total MB
        used_mem_kb_proc = float(parts[6])
        if used_mem_kb_proc >= 0:
            max_rss_mb: int | None = int(round(used_mem_kb_proc * alloc_cpus / 1024.0))
        else:
            max_rss_mb = None

        # 8. Requested Processors (-1 for missing)
        req_cpus_val = int(float(parts[7]))
        req_cpus = req_cpus_val if req_cpus_val > 0 else alloc_cpus

        # 10. Requested Memory (KB per proc; -1 for missing) -> total MB
        req_mem_kb_proc = float(parts[9])
        if req_mem_kb_proc >= 0:
            req_mem_mb: int | None = int(round(req_mem_kb_proc * alloc_cpus / 1024.0))
        else:
            req_mem_mb = None

        # 11. Status Code
        status_code = int(float(parts[10]))
        state = map_swf_status(status_code)

        # 12. User ID
        user = str(int(float(parts[11]))) if len(parts) > 11 else "unknown"

        # 13. Group ID (-1 for missing)
        group_id_val = int(float(parts[12])) if len(parts) > 12 else -1
        account = str(group_id_val) if group_id_val != -1 else None

        # 14. Executable Number (-1 for missing) -> command_hash
        exec_val = int(float(parts[13])) if len(parts) > 13 else -1
        command_hash = str(exec_val) if exec_val != -1 else None

        # 15. Queue Number / 16. Partition Number
        queue_val = int(float(parts[14])) if len(parts) > 14 else -1
        part_val = int(float(parts[15])) if len(parts) > 15 else -1
        if queue_val != -1:
            partition = str(queue_val)
        elif part_val != -1:
            partition = str(part_val)
        else:
            partition = None

        # Timestamps
        start_time = (
            datetime.fromtimestamp(base_epoch + submit_offset + wait_s, tz=UTC)
            if wait_val >= 0
            else None
        )
        end_time = (
            datetime.fromtimestamp(base_epoch + submit_offset + wait_s + run_s, tz=UTC)
            if (wait_val >= 0 and run_val >= 0)
            else None
        )

        reserved_core_s = max(0, alloc_cpus * run_s)
        reserved_mem_mb_s = max(0, req_mem_mb * run_s) if req_mem_mb is not None else None

        records.append(
            {
                "job_id": job_id,
                "parent_job_id": None,
                "source": "swf",
                "user": user,
                "account": account,
                "partition": partition,
                "job_name": None,
                "command_hash": command_hash,
                "input_hash": None,
                "submit_time": submit_time,
                "start_time": start_time,
                "end_time": end_time,
                "wait_s": wait_s,
                "run_s": run_s,
                "state": state,
                "exit_code": None,
                "req_cpus": req_cpus,
                "alloc_cpus": alloc_cpus,
                "cpu_time_used_s": cpu_time_used_s,
                "req_mem_mb": req_mem_mb,
                "max_rss_mb": max_rss_mb,
                "req_gpus": 0,
                "alloc_gpus": 0,
                "nodes": 1,
                "node_list": None,
                "reserved_core_s": reserved_core_s,
                "reserved_mem_mb_s": reserved_mem_mb_s,
            }
        )

    if not records:
        return empty_canonical_df(), pragmas

    df = pl.DataFrame(records, schema=POLARS_CANONICAL_SCHEMA)
    return df, pragmas


@overload
def parse_swf(
    source: Path | IO[str] | str,
    return_pragmas: Literal[False] = False,
) -> pl.DataFrame: ...


@overload
def parse_swf(
    source: Path | IO[str] | str,
    return_pragmas: Literal[True],
) -> tuple[pl.DataFrame, dict[str, Any]]: ...


def parse_swf(
    source: Path | IO[str] | str,
    return_pragmas: bool = False,
) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
    """Parse SWF accounting trace returning a canonical Polars DataFrame."""
    df, pragmas = parse_swf_with_pragmas(source)
    if return_pragmas:
        return df, pragmas
    return df
