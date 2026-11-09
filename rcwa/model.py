"""Canonical job record model and PyArrow/Polars schemas.

Represents batch-scheduler accounting records in the canonical schema
specified in SPEC section 5.3.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import polars as pl


class JobState(str, Enum):
    """Canonical job termination state enum containing exactly 10 states."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    NODE_FAIL = "NODE_FAIL"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"
    RUNNING = "RUNNING"
    PENDING = "PENDING"
    OTHER = "OTHER"


POLARS_CANONICAL_SCHEMA: dict[str, type[pl.DataType] | pl.DataType] = {
    "job_id": pl.String,
    "parent_job_id": pl.String,
    "source": pl.String,
    "user": pl.String,
    "account": pl.String,
    "partition": pl.String,
    "job_name": pl.String,
    "command_hash": pl.String,
    "input_hash": pl.String,
    "submit_time": pl.Datetime("ms", "UTC"),
    "start_time": pl.Datetime("ms", "UTC"),
    "end_time": pl.Datetime("ms", "UTC"),
    "wait_s": pl.Int64,
    "run_s": pl.Int64,
    "state": pl.String,
    "exit_code": pl.Int32,
    "req_cpus": pl.Int32,
    "alloc_cpus": pl.Int32,
    "cpu_time_used_s": pl.Float64,
    "req_mem_mb": pl.Int64,
    "max_rss_mb": pl.Int64,
    "req_gpus": pl.Int32,
    "alloc_gpus": pl.Int32,
    "nodes": pl.Int32,
    "node_list": pl.String,
    "reserved_core_s": pl.Int64,
    "reserved_mem_mb_s": pl.Int64,
}


def empty_canonical_df() -> pl.DataFrame:
    """Return an empty Polars DataFrame conforming to the canonical schema."""
    return pl.DataFrame(schema=POLARS_CANONICAL_SCHEMA)


def _build_canonical_arrow_schema() -> Any:
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("job_id", pa.string(), nullable=False),
            pa.field("parent_job_id", pa.string(), nullable=True),
            pa.field("source", pa.string(), nullable=False),
            pa.field("user", pa.string(), nullable=False),
            pa.field("account", pa.string(), nullable=True),
            pa.field("partition", pa.string(), nullable=True),
            pa.field("job_name", pa.string(), nullable=True),
            pa.field("command_hash", pa.string(), nullable=True),
            pa.field("input_hash", pa.string(), nullable=True),
            pa.field("submit_time", pa.timestamp("s", tz="UTC"), nullable=False),
            pa.field("start_time", pa.timestamp("s", tz="UTC"), nullable=True),
            pa.field("end_time", pa.timestamp("s", tz="UTC"), nullable=True),
            pa.field("wait_s", pa.int64(), nullable=False),
            pa.field("run_s", pa.int64(), nullable=False),
            pa.field("state", pa.string(), nullable=False),
            pa.field("exit_code", pa.int32(), nullable=True),
            pa.field("req_cpus", pa.int32(), nullable=False),
            pa.field("alloc_cpus", pa.int32(), nullable=False),
            pa.field("cpu_time_used_s", pa.float64(), nullable=True),
            pa.field("req_mem_mb", pa.int64(), nullable=True),
            pa.field("max_rss_mb", pa.int64(), nullable=True),
            pa.field("req_gpus", pa.int32(), nullable=False),
            pa.field("alloc_gpus", pa.int32(), nullable=False),
            pa.field("nodes", pa.int32(), nullable=False),
            pa.field("node_list", pa.string(), nullable=True),
            pa.field("reserved_core_s", pa.int64(), nullable=False),
            pa.field("reserved_mem_mb_s", pa.int64(), nullable=True),
        ]
    )


_CANONICAL_ARROW_SCHEMA: Any = None


def get_canonical_arrow_schema() -> Any:
    """Return singleton canonical PyArrow schema instance."""
    global _CANONICAL_ARROW_SCHEMA
    if _CANONICAL_ARROW_SCHEMA is None:
        _CANONICAL_ARROW_SCHEMA = _build_canonical_arrow_schema()
    return _CANONICAL_ARROW_SCHEMA


def to_canonical_arrow(data: Any) -> Any:
    """Convert Polars DataFrame or PyArrow Table to canonical Arrow Table."""
    import pyarrow as pa

    schema = get_canonical_arrow_schema()
    if isinstance(data, pl.DataFrame):
        table = data.to_arrow()
    else:
        table = data

    arrays: list[pa.Array | pa.ChunkedArray] = []
    for field in schema:
        if field.name in table.schema.names:
            col = table.column(field.name)
            if col.type != field.type:
                col = col.cast(field.type)
            arrays.append(col)
        else:
            if not field.nullable:
                raise ValueError(f"Required non-nullable field '{field.name}' is missing")
            null_array = pa.nulls(table.num_rows, type=field.type)
            arrays.append(null_array)

    return pa.Table.from_arrays(arrays, schema=schema)


def from_canonical_arrow(table: Any) -> pl.DataFrame:
    """Convert canonical PyArrow Table to Polars DataFrame with canonical schema."""
    df = pl.from_arrow(table)
    if not isinstance(df, pl.DataFrame):
        df = df.to_frame()

    exprs = []
    for col_name, dtype in POLARS_CANONICAL_SCHEMA.items():
        if col_name in df.columns:
            exprs.append(pl.col(col_name).cast(dtype))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col_name))
    return df.select(exprs)


def _build_canonical_job_record_class() -> type:
    from pydantic import BaseModel, ConfigDict, model_validator

    class _CanonicalJobRecord(BaseModel):
        """Pydantic v2 record for an individual batch compute job."""

        model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

        job_id: str
        parent_job_id: str | None = None
        source: str
        user: str
        account: str | None = None
        partition: str | None = None
        job_name: str | None = None
        command_hash: str | None = None
        input_hash: str | None = None
        submit_time: datetime
        start_time: datetime | None = None
        end_time: datetime | None = None
        wait_s: int
        run_s: int
        state: JobState
        exit_code: int | None = None
        req_cpus: int
        alloc_cpus: int
        cpu_time_used_s: float | None = None
        req_mem_mb: int | None = None
        max_rss_mb: int | None = None
        req_gpus: int = 0
        alloc_gpus: int = 0
        nodes: int = 1
        node_list: str | None = None
        reserved_core_s: int | None = None
        reserved_mem_mb_s: int | None = None

        @model_validator(mode="after")
        def compute_reserved_resources(self) -> "_CanonicalJobRecord":
            """Compute reserved core-seconds and memory-megabyte-seconds if not provided."""
            if self.reserved_core_s is None:
                self.reserved_core_s = max(0, self.alloc_cpus * self.run_s)
            if self.reserved_mem_mb_s is None:
                if self.req_mem_mb is not None:
                    self.reserved_mem_mb_s = max(0, self.req_mem_mb * self.run_s)
                else:
                    self.reserved_mem_mb_s = None
            return self

    _CanonicalJobRecord.__name__ = "CanonicalJobRecord"
    _CanonicalJobRecord.__qualname__ = "CanonicalJobRecord"
    return _CanonicalJobRecord


_CanonicalJobRecordClass: type | None = None


if TYPE_CHECKING:
    import pyarrow as pa
    from pydantic import BaseModel

    CANONICAL_ARROW_SCHEMA: pa.Schema

    class CanonicalJobRecord(BaseModel):
        job_id: str
        parent_job_id: str | None = None
        source: str
        user: str
        account: str | None = None
        partition: str | None = None
        job_name: str | None = None
        command_hash: str | None = None
        input_hash: str | None = None
        submit_time: datetime
        start_time: datetime | None = None
        end_time: datetime | None = None
        wait_s: int
        run_s: int
        state: JobState
        exit_code: int | None = None
        req_cpus: int
        alloc_cpus: int
        cpu_time_used_s: float | None = None
        req_mem_mb: int | None = None
        max_rss_mb: int | None = None
        req_gpus: int = 0
        alloc_gpus: int = 0
        nodes: int = 1
        node_list: str | None = None
        reserved_core_s: int | None = None
        reserved_mem_mb_s: int | None = None


def __getattr__(name: str) -> Any:
    global _CanonicalJobRecordClass
    if name == "CANONICAL_ARROW_SCHEMA":
        return get_canonical_arrow_schema()
    if name == "CanonicalJobRecord":
        if _CanonicalJobRecordClass is None:
            _CanonicalJobRecordClass = _build_canonical_job_record_class()
        return _CanonicalJobRecordClass
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
