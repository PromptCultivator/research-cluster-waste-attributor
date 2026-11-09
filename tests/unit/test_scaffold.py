"""Scaffold and baseline functionality tests for rcwa package."""

import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import rcwa
from rcwa import cli, wrap

runner = CliRunner()


def test_package_version() -> None:
    """Verify package version string."""
    assert rcwa.__version__ == "0.1.0"


def test_cli_version_flag() -> None:
    """Verify cli --version flag returns version and exits cleanly."""
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "rcwa 0.1.0" in result.stdout


def test_cli_version_subcommand() -> None:
    """Verify cli version subcommand returns version."""
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "rcwa 0.1.0" in result.stdout


def test_cli_version_callback_noop() -> None:
    """Verify version callback does nothing when flag is false."""
    assert cli.version_callback(False) is None


def test_cli_subcommands_execution(tmp_path: Path) -> None:
    """Verify execution of all CLI subcommands with valid arguments."""
    dummy_file = tmp_path / "dummy_trace.txt"
    dummy_file.write_text("sample trace payload", encoding="utf-8")

    # synth
    res = runner.invoke(cli.app, ["synth", "--size", "10k", "--seed", "42", "--runs", "1"])
    assert res.exit_code == 0
    assert "Synthesizing trace" in res.stdout

    # ingest
    res = runner.invoke(cli.app, ["ingest", str(dummy_file), "--format", "sacct"])
    assert res.exit_code == 0
    assert "Ingesting trace" in res.stdout

    # attribute
    res = runner.invoke(cli.app, ["attribute", str(dummy_file)])
    assert res.exit_code == 0
    assert "Attributing waste" in res.stdout

    # recommend
    res = runner.invoke(cli.app, ["recommend", str(dummy_file)])
    assert res.exit_code == 0
    assert "Generating recommendations" in res.stdout

    # simulate
    res = runner.invoke(cli.app, ["simulate", str(dummy_file), "--scenario", "baseline"])
    assert res.exit_code == 0
    assert "Simulating trace" in res.stdout

    # calibrate
    res = runner.invoke(cli.app, ["calibrate"])
    assert res.exit_code == 0
    assert "Calibrating simulator" in res.stdout

    # report
    res = runner.invoke(cli.app, ["report", "--format", "json"])
    assert res.exit_code == 0
    assert "Reporting results" in res.stdout

    # run
    res = runner.invoke(cli.app, ["run", str(dummy_file)])
    assert res.exit_code == 0
    assert "Executing pipeline" in res.stdout


def test_cli_subcommands_help() -> None:
    """Verify --help succeeds on all subcommands including those with positional arguments."""
    for cmd in [
        "ingest",
        "attribute",
        "recommend",
        "simulate",
        "calibrate",
        "report",
        "run",
        "synth",
    ]:
        res = runner.invoke(cli.app, [cmd, "--help"])
        assert res.exit_code == 0
        assert f"Usage: rcwa {cmd}" in res.output


def test_cli_subcommands_missing_required_arguments() -> None:
    """Verify missing required positional arguments fail with exit status 2."""
    for cmd in ["ingest", "attribute", "recommend", "simulate"]:
        res = runner.invoke(cli.app, [cmd])
        assert res.exit_code == 2
        assert "Missing argument" in res.output


def test_cli_subcommands_nonexistent_paths() -> None:
    """Verify passing non-existent file paths fails validation with exit code 2."""
    res = runner.invoke(cli.app, ["ingest", "definitely_nonexistent_path_xyz.sacct"])
    assert res.exit_code == 2
    assert "Invalid value for 'TRACE'" in res.output
    assert "not exist" in res.output


def test_wrap_version() -> None:
    """Verify rcwa-wrap version options and callback."""
    result = runner.invoke(wrap.app, ["--version"])
    assert result.exit_code == 0
    assert "rcwa-wrap 0.1.0" in result.stdout

    assert wrap.version_callback(False) is None


def test_wrap_command_normalization() -> None:
    """Verify argument sorting and prefix stripping."""
    tokens = ["/usr/bin/python3", "--batch-size=32", "--lr=0.01", "train.py"]
    normalized = wrap.normalize_command_line(tokens, regex_strip=r"/usr/bin/")
    assert normalized == "python3 --batch-size=32 --lr=0.01 train.py"

    assert wrap.normalize_command_line([]) == ""


def test_wrap_hash_file() -> None:
    """Verify file hashing and large-file size/mtime mode."""
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write("sample payload data")
        tmp_path = Path(tmp.name)

    try:
        digest_content = wrap.hash_file(tmp_path, big_file_mode="sha256")
        assert len(digest_content) == 64

        digest_mtime = wrap.hash_file(
            tmp_path,
            big_file_mode="size_mtime",
            big_file_threshold=5,
        )
        assert len(digest_mtime) == 64
        assert digest_content != digest_mtime

        missing_digest = wrap.hash_file(Path("/nonexistent/file/path"))
        assert missing_digest == "missing"
    finally:
        tmp_path.unlink(missing_ok=True)


def test_wrap_compute_input_hash() -> None:
    """Verify composite hash generation across inputs and command line."""
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write("input payload")
        tmp_path = Path(tmp.name)

    try:
        digest = wrap.compute_input_hash(
            inputs=[str(tmp_path)],
            cmd=["python3", "script.py", "--epochs=5"],
        )
        assert len(digest) == 64
    finally:
        tmp_path.unlink(missing_ok=True)


def test_wrap_record_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify hash recording in sidecar file."""
    monkeypatch.setenv("RCWA_DIR", str(tmp_path))
    monkeypatch.setenv("SLURM_JOB_ID", "99999")

    test_hash = "abcdef1234567890"
    wrap.record_hash(test_hash)

    sidecar = tmp_path / "99999.json"
    assert sidecar.exists()
    assert test_hash in sidecar.read_text(encoding="utf-8")


def test_wrap_execution_missing_command() -> None:
    """Verify wrapper raises error when no target command is supplied."""
    result = runner.invoke(wrap.app, [])
    assert result.exit_code != 0
    assert "Error: No command specified" in result.output


def test_wrap_execution_command_run() -> None:
    """Verify wrapper executes command and exits with command status code."""
    result = runner.invoke(wrap.app, ["--", "python3", "-c", "import sys; sys.exit(0)"])
    assert result.exit_code == 0


def test_wrap_command_not_found() -> None:
    """Verify rcwa-wrap reports informative message and exits with 127 when binary is missing."""
    res = runner.invoke(wrap.app, ["--", "nonexistent_binary_xyz_12345"])
    assert res.exit_code == 127
    assert "rcwa-wrap: command not found" in res.output


def test_wrap_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify rcwa-wrap handles PermissionError with exit status 126."""

    def mock_run(*args: object, **kwargs: object) -> None:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(subprocess, "run", mock_run)
    res = runner.invoke(wrap.app, ["--", "non_executable_script"])
    assert res.exit_code == 126
    assert "rcwa-wrap: permission denied" in res.output


def test_policy_yaml_load() -> None:
    """Verify policies/default.yaml contains valid configuration keys."""
    policy_path = Path("policies/default.yaml")
    assert policy_path.exists()

    content = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    assert "grouping" in content
    assert "attribution" in content
    assert "recommendations" in content
    assert content["grouping"]["min_samples"] == 5
    assert content["attribution"]["retry_window_s"] == 86400
    assert content["recommendations"]["memory"]["safety_factor"] == 1.2


def test_cluster_yaml_load() -> None:
    """Verify clusters/example.yaml contains expected cluster topology."""
    cluster_path = Path("clusters/example.yaml")
    assert cluster_path.exists()

    content = yaml.safe_load(cluster_path.read_text(encoding="utf-8"))
    assert content["cluster_name"] == "example"
    assert content["node_count"] == 64
    assert content["cores_per_node"] == 32
    assert content["mem_mb_per_node"] == 131072


def test_click_compat_make_metavar() -> None:
    """Verify Click make_metavar compatibility bridge handles missing context."""
    import click

    opt = click.Option(["--test-option"], help="Test option")
    metavar = opt.make_metavar()  # pyright: ignore[reportCallIssue]
    assert isinstance(metavar, str)


def test_wrap_main_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify wrap main invokes app."""
    monkeypatch.setattr(wrap, "app", lambda: None)
    wrap.main()


def test_wrap_record_hash_slurm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify hash recording with SLURM_JOB_ID without sidecar directory."""
    monkeypatch.delenv("RCWA_DIR", raising=False)
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    wrap.record_hash("dummy_hash")


def test_wrap_execution_with_inputs_and_flags(tmp_path: Path) -> None:
    """Verify wrapper runs with explicit input hashing and regex strip."""
    input_file = tmp_path / "data.csv"
    input_file.write_text("sample payload", encoding="utf-8")

    result = runner.invoke(
        wrap.app,
        [
            f"--inputs={input_file}",
            "--big-file-mode=size_mtime",
            "--regex-strip=/usr/bin/",
            "--",
            "python3",
            "-c",
            "print('wrapped')",
        ],
    )
    assert result.exit_code == 0


def test_data_gitignore_patterns() -> None:
    """Verify data/.gitignore ignores expected trace and artifact extensions."""
    data_gitignore = Path("data/.gitignore")
    assert data_gitignore.exists()
    content = data_gitignore.read_text(encoding="utf-8")
    assert "*.swf.gz" in content
    assert "*.gz" in content
    assert "*.tar.gz" in content
    assert "sacct_export.txt" in content
    assert "*.parquet" in content
    assert "*.arrow" in content
