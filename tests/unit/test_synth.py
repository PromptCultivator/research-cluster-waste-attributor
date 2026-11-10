"""Unit tests for synthetic trace generator module."""

from pathlib import Path

import polars as pl
import pytest

from rcwa.adapters.sacct import parse_sacct
from rcwa.attribute import attribute_trace
from rcwa.synth import (
    _format_duration_hms,
    generate_synthetic_trace,
    parse_trace_size,
    write_synthetic_trace,
)


def test_parse_trace_size() -> None:
    """Verify trace size string parsing across diverse descriptors."""
    assert parse_trace_size(50) == 50
    assert parse_trace_size("50") == 50
    assert parse_trace_size("100") == 100
    assert parse_trace_size("20k") == 20000
    assert parse_trace_size("20K") == 20000
    assert parse_trace_size("1M") == 1000000
    assert parse_trace_size("1m") == 1000000
    assert parse_trace_size("1G") == 1000000000
    assert parse_trace_size("") == 20000
    assert parse_trace_size("invalid") == 20000


def test_format_duration_hms() -> None:
    """Verify duration formatting into Slurm duration strings."""
    assert _format_duration_hms(0) == "00:00:00"
    assert _format_duration_hms(45) == "00:00:45"
    assert _format_duration_hms(3665) == "01:01:05"
    assert _format_duration_hms(90000) == "1-01:00:00"


def test_generate_synthetic_trace_structure() -> None:
    """Verify output format and ground truth schema of generated trace."""
    text, truth_df = generate_synthetic_trace(size=30, seed=42)

    lines = text.strip().splitlines()
    assert len(lines) == 31  # Header + 30 jobs
    header = lines[0]
    assert "JobIDRaw|JobID|User|Account|" in header

    assert isinstance(truth_df, pl.DataFrame)
    assert truth_df.height == 30
    assert "job_id" in truth_df.columns
    assert "true_class" in truth_df.columns
    assert "planted_fault_type" in truth_df.columns
    assert "planted_is_recompute" in truth_df.columns


def test_generate_synthetic_trace_determinism() -> None:
    """Verify identical seeds produce byte-identical text and dataframes."""
    text1, truth1 = generate_synthetic_trace(size=40, seed=123)
    text2, truth2 = generate_synthetic_trace(size=40, seed=123)

    assert text1 == text2
    assert truth1.equals(truth2)

    # Different seeds should produce distinct content
    text3, _ = generate_synthetic_trace(size=40, seed=999)
    assert text1 != text3


@pytest.mark.parametrize("faults_profile", ["default", "all_waste", "no_waste"])
def test_generate_synthetic_trace_profiles(faults_profile: str) -> None:
    """Verify trace generation across different fault injection profiles."""
    text, truth_df = generate_synthetic_trace(size=25, seed=7, faults=faults_profile)
    lines = text.strip().splitlines()
    assert len(lines) == 26
    assert truth_df.height == 25


def test_synthetic_trace_parse_and_attribution(tmp_path: Path) -> None:
    """Verify generated synthetic trace parses via sacct adapter and satisfies conservation."""
    trace_path = tmp_path / "test_synth.txt"
    truth_path = tmp_path / "test_synth.truth.parquet"

    text, truth_df = generate_synthetic_trace(size=30, seed=55)
    write_synthetic_trace(trace_path, text, truth_df=truth_df, ground_truth_path=truth_path)

    assert trace_path.exists()
    assert truth_path.exists()

    canonical_df = parse_sacct(trace_path)
    assert canonical_df.height == 30

    attr_df = attribute_trace(canonical_df)
    assert attr_df.height == 30

    # Validate Guarantee G1 conservation
    for row in attr_df.iter_rows(named=True):
        res_core = row["reserved_core_s"]
        used_core = row["used_core_s"]
        c2_core = row["class2_idle_core_s"]
        c3_core = row["class3_core_s"]
        c4_core = row["class4_core_s"]
        un_core = row["unattributed_core_s"]

        assert res_core == used_core + c2_core + c3_core + c4_core + un_core
