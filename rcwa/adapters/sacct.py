"""Slurm sacct accounting export adapter.

Parses pipe-delimited sacct traces, performs step hierarchy rollups,
extracts GPU and memory metrics, and outputs canonical DataFrames.
"""

import hashlib
import json
import os
import warnings
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import polars as pl

from rcwa.model import POLARS_CANONICAL_SCHEMA, empty_canonical_df
from rcwa.normalize import (
    decompose_job_id,
    map_slurm_state,
    parse_comment_input_hash,
    parse_duration_int,
    parse_duration_s,
    parse_slurm_exit_code,
    parse_slurm_memory_mb,
    parse_slurm_memory_rss_mb,
    parse_slurm_timestamp,
    parse_tres,
)

KNOWN_SACCT_COLUMNS = {
    "jobidraw",
    "jobid",
    "user",
    "account",
    "partition",
    "qos",
    "jobname",
    "submit",
    "eligible",
    "start",
    "end",
    "elapsed",
    "state",
    "exitcode",
    "reqcpus",
    "alloccpus",
    "reqmem",
    "maxrss",
    "averss",
    "totalcpu",
    "cputimeraw",
    "reqtres",
    "alloctres",
    "nodelist",
    "comment",
    "submitline",
}


def _read_sidecar_hashes(job_id: str) -> tuple[str | None, str | None]:
    """Read input_hash and command_hash from sidecar JSON file if present."""
    rcwa_dir = os.environ.get("RCWA_DIR")
    if not rcwa_dir:
        return None, None

    sidecar_path = Path(rcwa_dir) / f"{job_id}.json"
    if not sidecar_path.is_file():
        return None, None

    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        input_hash = data.get("input_hash")
        command_hash = data.get("command_hash")
        return input_hash, command_hash
    except (OSError, json.JSONDecodeError):
        return None, None


def _get_line_iterator(source: Path | IO[str] | str) -> tuple[Iterator[str], bool]:
    """Obtain line iterator from path, file stream, or string payload.

    Returns:
        tuple[Iterator[str], bool]: line iterator and a flag indicating if content was empty.
    """
    if isinstance(source, Path) or (
        isinstance(source, str) and "\n" not in source and os.path.exists(source)
    ):
        file_path = Path(source)
        if not file_path.is_file():
            return iter([]), True

        # Binary corruption check
        raw_header = file_path.read_bytes()[:8192]
        if b"\x00" in raw_header:
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

    # Assume IO stream
    raw: Any = getattr(source, "read")()
    if isinstance(raw, bytes):
        if 0 in raw:
            raise ValueError("Binary content detected in file stream")
        text = raw.decode("utf-8")
    else:
        text = str(raw)

    lines = text.splitlines()
    return iter(lines), len(lines) == 0


def parse_sacct(source: Path | IO[str] | str) -> pl.DataFrame:
    """Parse Slurm sacct pipe-delimited accounting trace into canonical DataFrame.

    Implements:
    - Pipe-delimited parsing with empty field conversion to null
    - Warning on unknown extra columns
    - Step hierarchy rollup (MaxRSS maximum, TotalCPU sum excluding .extern)
    - Array task and pack component decomposition with parent linkage
    - Units and duration normalization
    """
    line_iter, is_empty = _get_line_iterator(source)
    if is_empty:
        return empty_canonical_df()

    # Find the header line
    header_line: str | None = None
    for line in line_iter:
        s = line.strip()
        if s:
            header_line = s
            break

    if header_line is None:
        return empty_canonical_df()

    # Detect trailing delimiter
    has_trailing_delim = header_line.endswith("|")
    raw_header_tokens = [tok.strip() for tok in header_line.split("|")]
    if has_trailing_delim and raw_header_tokens and raw_header_tokens[-1] == "":
        raw_header_tokens = raw_header_tokens[:-1]

    header_cols = [c.lower() for c in raw_header_tokens]
    if not header_cols:
        return empty_canonical_df()

    # Identify unknown extra columns and issue UserWarning
    unknown_cols = [c for c in header_cols if c and c not in KNOWN_SACCT_COLUMNS]
    if unknown_cols:
        warnings.warn(
            f"Unknown column(s) in sacct trace: {unknown_cols}",
            UserWarning,
            stacklevel=2,
        )

    col_index: dict[str, int] = {name: idx for idx, name in enumerate(header_cols)}

    # If neither jobid nor jobidraw is found, file format is unrecognized
    if "jobid" not in col_index and "jobidraw" not in col_index:
        warnings.warn(
            f"Unrecognized sacct header in trace: {header_line}",
            UserWarning,
            stacklevel=2,
        )
        return empty_canonical_df()

    parent_rows: dict[str, dict[str, str]] = {}
    parent_order: list[str] = []
    step_records: dict[str, list[tuple[str, int | None, float | None]]] = defaultdict(list)

    for line in line_iter:
        line_clean = line.rstrip("\r\n")
        if not line_clean.strip():
            continue

        raw_tokens = [tok.strip() for tok in line_clean.split("|")]
        if has_trailing_delim and raw_tokens and raw_tokens[-1] == "":
            raw_tokens = raw_tokens[:-1]

        # Tolerate truncated rows gracefully
        if len(raw_tokens) < 2:
            continue

        def get_val(col_name: str) -> str:
            idx = col_index.get(col_name)
            if idx is not None and idx < len(raw_tokens):
                return raw_tokens[idx]
            return ""

        raw_id = get_val("jobidraw") or get_val("jobid")
        if not raw_id:
            continue

        base_id, step, parent_id = decompose_job_id(raw_id)

        if step is not None:
            # Child step row: collect resource metrics
            max_rss_raw = get_val("maxrss")
            total_cpu_raw = get_val("totalcpu")
            max_rss_mb = parse_slurm_memory_rss_mb(max_rss_raw)
            cpu_s = parse_duration_s(total_cpu_raw)
            step_records[base_id].append((step, max_rss_mb, cpu_s))
        else:
            # Parent job row
            if base_id not in parent_rows:
                parent_order.append(base_id)
            row_dict = {
                "base_id": base_id,
                "parent_job_id": parent_id or "",
                "user": get_val("user"),
                "account": get_val("account"),
                "partition": get_val("partition"),
                "job_name": get_val("jobname"),
                "submit": get_val("submit"),
                "start": get_val("start"),
                "end": get_val("end"),
                "elapsed": get_val("elapsed"),
                "state": get_val("state"),
                "exit_code": get_val("exitcode"),
                "req_cpus": get_val("reqcpus"),
                "alloc_cpus": get_val("alloccpus"),
                "req_mem": get_val("reqmem"),
                "max_rss": get_val("maxrss"),
                "ave_rss": get_val("averss"),
                "total_cpu": get_val("totalcpu"),
                "req_tres": get_val("reqtres"),
                "alloc_tres": get_val("alloctres"),
                "node_list": get_val("nodelist"),
                "comment": get_val("comment"),
                "submit_line": get_val("submitline"),
            }
            parent_rows[base_id] = row_dict

    # Build canonical records
    records: list[dict[str, Any]] = []

    for base_id in parent_order:
        data = parent_rows[base_id]

        # TRES parsing
        alloc_tres_dict = parse_tres(data.get("alloc_tres"))
        req_tres_dict = parse_tres(data.get("req_tres"))

        alloc_cpus_val = data.get("alloc_cpus")
        try:
            alloc_cpus = int(alloc_cpus_val) if alloc_cpus_val else alloc_tres_dict["cpus"]
        except ValueError:
            alloc_cpus = alloc_tres_dict["cpus"]
        if alloc_cpus <= 0:
            alloc_cpus = 1

        req_cpus_val = data.get("req_cpus")
        try:
            req_cpus = int(req_cpus_val) if req_cpus_val else req_tres_dict["cpus"]
        except ValueError:
            req_cpus = req_tres_dict["cpus"]
        if req_cpus <= 0:
            req_cpus = alloc_cpus

        nodes_val = alloc_tres_dict["nodes"] or req_tres_dict["nodes"] or 1
        alloc_gpus = alloc_tres_dict["gpus"]
        req_gpus = req_tres_dict["gpus"] or alloc_gpus

        req_mem_mb = parse_slurm_memory_mb(
            data.get("req_mem"),
            alloc_cpus=alloc_cpus,
            nodes=nodes_val,
        )

        # Roll up steps
        steps = step_records.get(base_id, [])
        if steps:
            rss_candidates = [rss for (_, rss, _) in steps if rss is not None]
            if rss_candidates:
                max_rss_mb: int | None = max(rss_candidates)
            else:
                max_rss_mb = parse_slurm_memory_rss_mb(data.get("max_rss"))

            cpu_candidates = [
                cpu
                for (s_name, _, cpu) in steps
                if cpu is not None and s_name != "extern" and not s_name.startswith("extern")
            ]
            if cpu_candidates:
                cpu_time_used_s: float | None = sum(cpu_candidates)
            else:
                cpu_time_used_s = parse_duration_s(data.get("total_cpu"))
        else:
            max_rss_mb = parse_slurm_memory_rss_mb(data.get("max_rss"))
            cpu_time_used_s = parse_duration_s(data.get("total_cpu"))

        # Timestamps and durations
        submit_time = parse_slurm_timestamp(data.get("submit"))
        start_time = parse_slurm_timestamp(data.get("start"))
        end_time = parse_slurm_timestamp(data.get("end"))

        run_s_parsed = parse_duration_s(data.get("elapsed"))
        if run_s_parsed is not None:
            run_s = parse_duration_int(run_s_parsed)
        elif start_time and end_time:
            diff_s = int((end_time - start_time).total_seconds())
            run_s = max(0, diff_s)
        else:
            run_s = 0

        if start_time and submit_time:
            wait_s = max(0, int((start_time - submit_time).total_seconds()))
        else:
            wait_s = 0

        # When submit_time is missing, construct fallback from start or end
        if submit_time is None:
            submit_time = start_time or end_time or datetime(1970, 1, 1, tzinfo=UTC)

        # Check comment and sidecars for input_hash and command_hash
        sidecar_input_hash, sidecar_command_hash = _read_sidecar_hashes(base_id)
        input_hash = parse_comment_input_hash(data.get("comment")) or sidecar_input_hash

        command_hash = sidecar_command_hash
        if not command_hash:
            submit_line = data.get("submit_line", "").strip()
            if submit_line:
                command_hash = hashlib.sha256(submit_line.encode("utf-8")).hexdigest()
            else:
                job_name = data.get("job_name", "").strip()
                if job_name:
                    command_hash = hashlib.sha256(job_name.encode("utf-8")).hexdigest()

        # Reservations
        reserved_core_s = max(0, alloc_cpus * run_s)
        reserved_mem_mb_s = max(0, req_mem_mb * run_s) if req_mem_mb is not None else None

        records.append(
            {
                "job_id": base_id,
                "parent_job_id": data.get("parent_job_id") or None,
                "source": "sacct",
                "user": data.get("user") or "unknown",
                "account": data.get("account") or None,
                "partition": data.get("partition") or None,
                "job_name": data.get("job_name") or None,
                "command_hash": command_hash,
                "input_hash": input_hash,
                "submit_time": submit_time,
                "start_time": start_time,
                "end_time": end_time,
                "wait_s": wait_s,
                "run_s": run_s,
                "state": map_slurm_state(data.get("state")),
                "exit_code": parse_slurm_exit_code(data.get("exit_code")),
                "req_cpus": req_cpus,
                "alloc_cpus": alloc_cpus,
                "cpu_time_used_s": cpu_time_used_s,
                "req_mem_mb": req_mem_mb,
                "max_rss_mb": max_rss_mb,
                "req_gpus": req_gpus,
                "alloc_gpus": alloc_gpus,
                "nodes": nodes_val,
                "node_list": data.get("node_list") or None,
                "reserved_core_s": reserved_core_s,
                "reserved_mem_mb_s": reserved_mem_mb_s,
            }
        )

    if not records:
        return empty_canonical_df()

    df = pl.DataFrame(records, schema=POLARS_CANONICAL_SCHEMA)
    return df
