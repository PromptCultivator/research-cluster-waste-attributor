"""Unit tests for rcwa-wrap CLI utility, hashing, and normalization."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rcwa.wrap import (
    app,
    compute_input_hash,
    hash_file,
    normalize_command_line,
    record_hash,
)

runner = CliRunner()


def test_normalize_command_line_sorting() -> None:
    """Verify sorting of command options while preserving executable and positionals."""
    cmd = ["python3", "--epochs=10", "--lr=0.01", "train.py", "--batch=32"]
    normalized = normalize_command_line(cmd)
    assert normalized == "python3 --batch=32 --epochs=10 --lr=0.01 train.py"


def test_normalize_command_line_regex_strip() -> None:
    """Verify stripping absolute directory prefixes using configurable regex."""
    cmd = ["/usr/bin/python3", "/home/user/repo/train.py", "--config=/etc/model.yaml"]
    normalized = normalize_command_line(cmd, regex_strip=r"^/usr/bin/|^/home/user/repo/|^/etc/")
    assert normalized == "python3 --config=model.yaml train.py"


def test_normalize_command_line_empty() -> None:
    """Verify empty tokens return empty string."""
    assert normalize_command_line([]) == ""


def test_hash_file_content_and_missing(tmp_path: Path) -> None:
    """Verify content hashing and handling of nonexistent files."""
    f = tmp_path / "sample.txt"
    f.write_text("dataset payload\n", encoding="utf-8")

    digest = hash_file(f, big_file_mode="sha256")
    assert len(digest) == 64

    missing_digest = hash_file(tmp_path / "nonexistent.bin")
    assert missing_digest == "missing"


def test_hash_file_big_file_mode(tmp_path: Path) -> None:
    """Verify size_mtime hashing strategy when file exceeds threshold."""
    f = tmp_path / "large.bin"
    f.write_bytes(b"x" * 200)

    # Threshold set below size
    digest_mtime = hash_file(f, big_file_mode="size_mtime", big_file_threshold=100)
    assert len(digest_mtime) == 64

    # Threshold set above size (content hash)
    digest_sha = hash_file(f, big_file_mode="size_mtime", big_file_threshold=1000)
    assert len(digest_sha) == 64
    assert digest_mtime != digest_sha


def test_compute_input_hash_multi_file(tmp_path: Path) -> None:
    """Verify combined input hashing across multiple files."""
    f1 = tmp_path / "input1.csv"
    f2 = tmp_path / "input2.csv"
    f1.write_text("table 1\n", encoding="utf-8")
    f2.write_text("table 2\n", encoding="utf-8")

    h1 = compute_input_hash([str(f1), str(f2)])
    h2 = compute_input_hash([str(f2), str(f1)])
    assert h1 == h2
    assert len(h1) == 64


def test_record_hash_sidecar_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify recording hash into JSON sidecar."""
    monkeypatch.setenv("RCWA_DIR", str(tmp_path))
    monkeypatch.setenv("SLURM_JOB_ID", "88888")

    record_hash("hash_digest_123", command_hash="cmd_digest_456")

    sidecar = tmp_path / "88888.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["job_id"] == "88888"
    assert data["input_hash"] == "hash_digest_123"
    assert data["command_hash"] == "cmd_digest_456"


def test_wrap_cli_execution_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rcwa-wrap CLI runs commands and records metadata."""
    sidecar_dir = tmp_path / "sidecars"
    monkeypatch.setenv("RCWA_DIR", str(sidecar_dir))
    monkeypatch.setenv("SLURM_JOB_ID", "12345")

    data_file = tmp_path / "data.txt"
    data_file.write_text("sample\n", encoding="utf-8")

    res = runner.invoke(
        app,
        [
            "--inputs",
            str(data_file),
            "--",
            "python3",
            "-c",
            "print('wrapped success')",
        ],
    )
    assert res.exit_code == 0
    assert (sidecar_dir / "12345.json").exists()


def test_wrap_cli_no_command() -> None:
    """Verify rcwa-wrap exits with code 1 when no executable command is supplied."""
    res = runner.invoke(app, [])
    assert res.exit_code == 1
    assert "No command specified" in res.output or "Error" in res.output
