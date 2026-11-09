"""Data normalization and conversion utilities for compute cluster records.

Provides duration, memory, state, TRES, and identifier decomposition logic
to transform raw accounting records into canonical form.
"""

import re
from datetime import UTC, datetime

import polars as pl

from rcwa.model import POLARS_CANONICAL_SCHEMA


def parse_duration_s(val: str | int | float | None) -> float | None:
    """Parse time duration string or numeric value to float seconds.

    Supports formats:
    - 'D-HH:MM:SS' (e.g. '1-02:03:04')
    - 'HH:MM:SS' (e.g. '01:30:15')
    - 'MM:SS.mmm' or 'MM:SS' (e.g. '02:15.500', '00:10')
    - Raw numeric seconds (e.g. '7200', 3600)
    Clamps negative values to 0.0. Returns None for unparseable input.
    """
    if val is None:
        return None

    if isinstance(val, int | float):
        return max(0.0, float(val))

    text = str(val).strip()
    sentinels = ("UNLIMITED", "INVALID", "Partition_Limit", "Unknown", "N/A", "None", "-")
    if not text or text in sentinels:
        return None

    if text.startswith("-"):
        return 0.0

    if "-" in text:
        parts = text.split("-", 1)
        days_str, rest = parts[0], parts[1]
        try:
            days = int(days_str)
        except ValueError:
            return None

        subparts = rest.split(":")
        if len(subparts) == 3:
            try:
                h = int(subparts[0])
                m = int(subparts[1])
                s = float(subparts[2])
                return max(0.0, days * 86400.0 + h * 3600.0 + m * 60.0 + s)
            except ValueError:
                return None
        elif len(subparts) == 2:
            try:
                m = int(subparts[0])
                s = float(subparts[1])
                return max(0.0, days * 86400.0 + m * 60.0 + s)
            except ValueError:
                return None
        else:
            try:
                s = float(rest)
                return max(0.0, days * 86400.0 + s)
            except ValueError:
                return None

    if ":" in text:
        subparts = text.split(":")
        if len(subparts) == 3:
            try:
                h = int(subparts[0])
                m = int(subparts[1])
                s = float(subparts[2])
                return max(0.0, h * 3600.0 + m * 60.0 + s)
            except ValueError:
                return None
        elif len(subparts) == 2:
            try:
                m = int(subparts[0])
                s = float(subparts[1])
                return max(0.0, m * 60.0 + s)
            except ValueError:
                return None
        return None

    try:
        return max(0.0, float(text))
    except ValueError:
        return None


def parse_duration_int(val: str | int | float | None) -> int:
    """Parse time duration string or numeric value to rounded integer seconds."""
    secs = parse_duration_s(val)
    if secs is None:
        return 0
    return int(round(secs + 1e-9))


def parse_slurm_memory_mb(
    val: str | None,
    alloc_cpus: int = 1,
    nodes: int = 1,
) -> int | None:
    """Convert Slurm memory string specification to total job memory in MB.

    Handles suffixes:
    - 'c' (per CPU) -> base * alloc_cpus
    - 'n' (per node) -> base * nodes
    - 'K' (kilobytes) -> base / 1024
    - 'M' (megabytes) -> base
    - 'G' (gigabytes) -> base * 1024
    - 'T' (terabytes) -> base * 1024 * 1024
    - '?' or unknown -> None
    """
    if val is None:
        return None

    text = str(val).strip()
    if not text or text in ("?", "Unknown", "N/A", "None", "-"):
        return None

    per_cpu = False
    per_node = False
    if text.endswith(("c", "C")):
        per_cpu = True
        text = text[:-1]
    elif text.endswith(("n", "N")):
        per_node = True
        text = text[:-1]

    unit = "M"
    if text and text[-1].isalpha():
        unit = text[-1].upper()
        text = text[:-1]

    try:
        num = float(text)
    except ValueError:
        return None

    if num < 0:
        return None

    if unit == "K":
        base_mb = num / 1024.0
    elif unit == "M":
        base_mb = num
    elif unit == "G":
        base_mb = num * 1024.0
    elif unit == "T":
        base_mb = num * 1024.0 * 1024.0
    elif unit == "P":
        base_mb = num * 1024.0 * 1024.0 * 1024.0
    else:
        return None

    if per_cpu:
        total_mb = base_mb * max(1, alloc_cpus)
    elif per_node:
        total_mb = base_mb * max(1, nodes)
    else:
        total_mb = base_mb

    return int(round(total_mb))


def parse_slurm_memory_rss_mb(val: str | None) -> int | None:
    """Parse Slurm MaxRSS or AveRSS memory metric string to megabytes."""
    if val is None:
        return None

    text = str(val).strip()
    if not text or text in ("?", "Unknown", "N/A", "None", "-"):
        return None

    unit = "M"
    if text and text[-1].isalpha():
        unit = text[-1].upper()
        text = text[:-1]

    try:
        num = float(text)
    except ValueError:
        return None

    if num < 0:
        return None

    if unit == "K":
        return int(round(num / 1024.0))
    elif unit == "M":
        return int(round(num))
    elif unit == "G":
        return int(round(num * 1024.0))
    elif unit == "T":
        return int(round(num * 1024.0 * 1024.0))
    elif unit == "P":
        return int(round(num * 1024.0 * 1024.0 * 1024.0))
    return None


def map_slurm_state(raw_state: str | None) -> str:
    """Strip qualifiers and map Slurm state strings to canonical 10-state set."""
    if not raw_state:
        return "OTHER"

    s = raw_state.strip()
    if s.endswith("+"):
        s = s[:-1].strip()

    if s == "COMPLETED":
        return "COMPLETED"
    if s in ("FAILED", "BOOT_FAIL"):
        return "FAILED"
    if s in ("TIMEOUT", "DEADLINE"):
        return "TIMEOUT"
    if s == "OUT_OF_MEMORY":
        return "OUT_OF_MEMORY"
    if s == "NODE_FAIL":
        return "NODE_FAIL"
    if s == "PREEMPTED":
        return "PREEMPTED"
    if s == "RUNNING":
        return "RUNNING"
    if s in ("PENDING", "REQUEUED"):
        return "PENDING"
    if s == "CANCELLED" or s.startswith("CANCELLED ") or s == "REVOKED":
        return "CANCELLED"
    return "OTHER"


def map_swf_status(status_code: int | None) -> str:
    """Map Standard Workload Format numeric status codes to canonical states."""
    if status_code == 1:
        return "COMPLETED"
    if status_code == 0:
        return "FAILED"
    if status_code == 5:
        return "CANCELLED"
    return "OTHER"


def parse_tres(tres_str: str | None) -> dict[str, int]:
    """Parse Slurm TRES allocation strings for GPU, CPU, node, and memory counts."""
    result: dict[str, int] = {"gpus": 0, "cpus": 0, "nodes": 1, "mem_mb": 0}
    if not tres_str:
        return result

    generic_gpu: int | None = None
    typed_gpu_sum = 0
    has_typed_gpu = False
    bare_gpu: int | None = None

    for item in tres_str.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip().lower()
        v = v.strip()

        if k == "cpu":
            try:
                result["cpus"] = int(v)
            except ValueError:
                pass
        elif k == "node":
            try:
                result["nodes"] = max(1, int(v))
            except ValueError:
                pass
        elif k == "mem":
            parsed_mem = parse_slurm_memory_rss_mb(v)
            if parsed_mem is not None:
                result["mem_mb"] = parsed_mem
        elif k == "gres/gpu":
            try:
                generic_gpu = int(v)
            except ValueError:
                pass
        elif k.startswith("gres/gpu:"):
            try:
                typed_gpu_sum += int(v)
                has_typed_gpu = True
            except ValueError:
                pass
        elif k == "gpu":
            try:
                bare_gpu = int(v)
            except ValueError:
                pass

    if generic_gpu is not None:
        result["gpus"] = generic_gpu
    elif has_typed_gpu:
        result["gpus"] = typed_gpu_sum
    elif bare_gpu is not None:
        result["gpus"] = bare_gpu
    else:
        result["gpus"] = 0

    return result


def parse_comment_input_hash(comment: str | None) -> str | None:
    """Extract RCWA_INPUT_HASH hexadecimal digest from Slurm Comment field."""
    if not comment:
        return None
    match = re.search(r"RCWA_INPUT_HASH=([0-9a-fA-F]+)", comment)
    if match:
        return match.group(1).lower()
    return None


def decompose_job_id(raw_id: str) -> tuple[str, str | None, str | None]:
    """Decompose raw JobID into base job id, step name, and parent job id.

    Returns:
        tuple[str, str | None, str | None]: (base_job_id, step_name, parent_job_id)
    """
    raw_id = raw_id.strip()
    step: str | None = None
    if "." in raw_id:
        base_part, step = raw_id.split(".", 1)
    else:
        base_part = raw_id

    parent_job_id: str | None = None
    if "_" in base_part:
        parent_job_id = base_part.split("_", 1)[0]
    elif "+" in base_part:
        parent_job_id = base_part.split("+", 1)[0]

    return base_part, step, parent_job_id


def parse_slurm_timestamp(val: str | None) -> datetime | None:
    """Parse Slurm ISO timestamp string to timezone-aware UTC datetime."""
    if not val:
        return None
    text = val.strip()
    if text in ("Unknown", "N/A", "NONE", "None", ""):
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def parse_slurm_exit_code(val: str | None) -> int | None:
    """Parse Slurm ExitCode string (e.g. '0:0', '1:0', '0:125') to integer status."""
    if not val:
        return None
    text = val.strip()
    if not text or text in ("Unknown", "N/A", "None", "-"):
        return None
    if ":" in text:
        parts = text.split(":", 1)
        try:
            code = int(parts[0])
            sig = int(parts[1])
            return code if code != 0 else (sig if sig != 0 else 0)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_to_canonical(df: pl.DataFrame, source_type: str = "sacct") -> pl.DataFrame:
    """Cast and structure an ingested DataFrame to conform to canonical schema."""
    exprs = []
    for col_name, dtype in POLARS_CANONICAL_SCHEMA.items():
        if col_name in df.columns:
            exprs.append(pl.col(col_name).cast(dtype))
        elif col_name == "source":
            exprs.append(pl.lit(source_type, dtype=dtype).alias("source"))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col_name))
    return df.select(exprs)
