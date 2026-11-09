"""Unit tests for canonical model, PyArrow/Polars schemas, and Pydantic validation."""

from datetime import UTC, datetime

import polars as pl
import pyarrow as pa
import pytest
from pydantic import ValidationError

from rcwa.model import (
    CANONICAL_ARROW_SCHEMA,
    POLARS_CANONICAL_SCHEMA,
    CanonicalJobRecord,
    JobState,
    empty_canonical_df,
    from_canonical_arrow,
    get_canonical_arrow_schema,
    to_canonical_arrow,
)


def test_job_state_enum_cardinality_and_members() -> None:
    """Verify JobState enum has exactly the 10 defined canonical states."""
    expected_states = {
        "COMPLETED",
        "FAILED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "CANCELLED",
        "PREEMPTED",
        "RUNNING",
        "PENDING",
        "OTHER",
    }
    actual_states = {s.value for s in JobState}
    assert actual_states == expected_states
    assert len(JobState) == 10

    for state_name in expected_states:
        state_item = JobState(state_name)
        assert state_item == state_name


def test_canonical_arrow_schema_fields() -> None:
    """Verify PyArrow schema defines required fields with correct types and nullability."""
    schema = get_canonical_arrow_schema()
    assert len(schema) == 27

    field_map = {f.name: f for f in schema}

    # Non-nullable required fields
    non_nullable_fields = [
        "job_id",
        "source",
        "user",
        "submit_time",
        "wait_s",
        "run_s",
        "state",
        "req_cpus",
        "alloc_cpus",
        "req_gpus",
        "alloc_gpus",
        "nodes",
        "reserved_core_s",
    ]
    for field_name in non_nullable_fields:
        assert field_name in field_map, f"Missing field {field_name}"
        assert not field_map[field_name].nullable, f"Field {field_name} must not be nullable"

    # Nullable fields
    nullable_fields = [
        "parent_job_id",
        "account",
        "partition",
        "job_name",
        "command_hash",
        "input_hash",
        "start_time",
        "end_time",
        "exit_code",
        "cpu_time_used_s",
        "req_mem_mb",
        "max_rss_mb",
        "node_list",
        "reserved_mem_mb_s",
    ]
    for field_name in nullable_fields:
        assert field_name in field_map, f"Missing field {field_name}"
        assert field_map[field_name].nullable, f"Field {field_name} must be nullable"

    # Verify types
    assert field_map["submit_time"].type == pa.timestamp("s", tz="UTC")
    assert field_map["wait_s"].type == pa.int64()
    assert field_map["run_s"].type == pa.int64()
    assert field_map["alloc_cpus"].type == pa.int32()
    assert field_map["cpu_time_used_s"].type == pa.float64()
    assert field_map["reserved_core_s"].type == pa.int64()


def test_empty_canonical_df() -> None:
    """Verify empty canonical DataFrame has correct columns and zero rows."""
    df = empty_canonical_df()
    assert df.height == 0
    assert len(df.columns) == 27
    for col_name, expected_dtype in POLARS_CANONICAL_SCHEMA.items():
        assert col_name in df.columns
        assert df.schema[col_name] == expected_dtype


def test_to_and_from_canonical_arrow_roundtrip() -> None:
    """Verify bidirectional roundtrip between Polars DataFrame and Arrow Table."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    records = [
        {
            "job_id": "1001",
            "parent_job_id": None,
            "source": "sacct",
            "user": "alice",
            "account": "research",
            "partition": "compute",
            "job_name": "test_job",
            "command_hash": "abc123hash",
            "input_hash": "inp456hash",
            "submit_time": now,
            "start_time": now,
            "end_time": now,
            "wait_s": 0,
            "run_s": 3600,
            "state": "COMPLETED",
            "exit_code": 0,
            "req_cpus": 4,
            "alloc_cpus": 4,
            "cpu_time_used_s": 14400.0,
            "req_mem_mb": 16000,
            "max_rss_mb": 8000,
            "req_gpus": 1,
            "alloc_gpus": 1,
            "nodes": 1,
            "node_list": "node-01",
            "reserved_core_s": 14400,
            "reserved_mem_mb_s": 57600000,
        }
    ]
    df = pl.DataFrame(records, schema=POLARS_CANONICAL_SCHEMA)
    arrow_tbl = to_canonical_arrow(df)

    assert arrow_tbl.num_rows == 1
    assert arrow_tbl.schema == CANONICAL_ARROW_SCHEMA

    restored_df = from_canonical_arrow(arrow_tbl)
    assert restored_df.height == 1
    assert restored_df.select("job_id").item() == "1001"
    assert restored_df.select("alloc_cpus").item() == 4
    assert restored_df.select("reserved_core_s").item() == 14400


def test_to_canonical_arrow_missing_non_nullable_raises() -> None:
    """Verify to_canonical_arrow raises ValueError when non-nullable column is absent."""
    partial_table = pa.table({"user": ["alice"]})
    with pytest.raises(ValueError, match="Required non-nullable field 'job_id' is missing"):
        to_canonical_arrow(partial_table)


def test_canonical_job_record_validation_and_calculations() -> None:
    """Verify CanonicalJobRecord computes reserved resources automatically."""
    submit = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    rec = CanonicalJobRecord(
        job_id="2001",
        source="sacct",
        user="bob",
        submit_time=submit,
        wait_s=10,
        run_s=100,
        state=JobState.COMPLETED,
        req_cpus=8,
        alloc_cpus=8,
        req_mem_mb=4000,
    )

    assert rec.reserved_core_s == 800
    assert rec.reserved_mem_mb_s == 400000
    assert rec.req_gpus == 0
    assert rec.alloc_gpus == 0
    assert rec.nodes == 1


def test_canonical_job_record_null_memory_calculation() -> None:
    """Verify reserved_mem_mb_s is None when req_mem_mb is None."""
    submit = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    rec = CanonicalJobRecord(
        job_id="2002",
        source="swf",
        user="carol",
        submit_time=submit,
        wait_s=0,
        run_s=50,
        state=JobState.FAILED,
        req_cpus=2,
        alloc_cpus=2,
        req_mem_mb=None,
    )

    assert rec.reserved_core_s == 100
    assert rec.reserved_mem_mb_s is None


def test_canonical_job_record_serialization() -> None:
    """Verify CanonicalJobRecord serializes to dict and json."""
    submit = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    rec = CanonicalJobRecord(
        job_id="3001",
        source="sacct",
        user="david",
        submit_time=submit,
        wait_s=5,
        run_s=60,
        state=JobState.TIMEOUT,
        req_cpus=1,
        alloc_cpus=1,
    )

    dumped = rec.model_dump()
    assert dumped["job_id"] == "3001"
    assert dumped["state"] == JobState.TIMEOUT

    json_str = rec.model_dump_json()
    assert '"job_id":"3001"' in json_str
    assert '"TIMEOUT"' in json_str


def test_canonical_job_record_validation_error() -> None:
    """Verify validation errors on missing required fields."""
    with pytest.raises(ValidationError):
        CanonicalJobRecord.model_validate({"job_id": "999"})
