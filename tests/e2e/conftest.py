"""Shared test configuration, fixtures, and invariant validators for E2E testing."""

import importlib.util
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


def is_rcwa_functional() -> bool:
    """Check whether rcwa feature modules (e.g. adapters.sacct) have been implemented."""
    try:
        return importlib.util.find_spec("rcwa.adapters.sacct") is not None
    except (ModuleNotFoundError, ValueError):
        return False


@dataclass
class CLIResult:
    """Result container for CLI command invocations."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def output(self) -> str:
        """Combined stdout and stderr text."""
        return f"{self.stdout}\n{self.stderr}".strip()


@pytest.fixture
def run_cli() -> Callable[..., CLIResult]:
    """Execute rcwa CLI commands via subprocess or module invocation."""

    def _invoke(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float = 60.0,
    ) -> CLIResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        # Ensure current working directory is on pythonpath
        repo_root = str(Path(__file__).resolve().parent.parent.parent)
        pythonpath = merged_env.get("PYTHONPATH", "")
        if repo_root not in pythonpath.split(os.pathsep):
            merged_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{pythonpath}".strip(os.pathsep)

        start_time = time.monotonic()
        # Form invocation using the current python executable
        cmd = [sys.executable, "-m", "rcwa.cli"] + args

        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        duration_s = time.monotonic() - start_time

        return CLIResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=duration_s,
        )

    return _invoke


@pytest.fixture
def run_wrap_cli() -> Callable[..., CLIResult]:
    """Execute rcwa-wrap CLI commands via subprocess or module invocation."""

    def _invoke(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float = 60.0,
    ) -> CLIResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        repo_root = str(Path(__file__).resolve().parent.parent.parent)
        pythonpath = merged_env.get("PYTHONPATH", "")
        if repo_root not in pythonpath.split(os.pathsep):
            merged_env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{pythonpath}".strip(os.pathsep)

        start_time = time.monotonic()
        cmd = [sys.executable, "-m", "rcwa.wrap"] + args

        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        duration_s = time.monotonic() - start_time

        return CLIResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=duration_s,
        )

    return _invoke


@pytest.fixture
def isolated_workspace(tmp_path: Path) -> Path:
    """Provide an isolated temporary workspace directory for test execution."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to tests/fixtures directory."""
    return Path(__file__).resolve().parent.parent / "fixtures"


class InvariantValidators:
    """Independent mathematical and logical verification methods for G1-G4."""

    @staticmethod
    def verify_g1_conservation(
        reserved: int,
        used: int,
        class1_or_2: int,
        class3: int,
        class4: int,
        unattributed: int,
    ) -> bool:
        """Verify Guarantee G1: reserved = used + waste + unattributed in exact integer arithmetic."""
        total_attributed = used + class1_or_2 + class3 + class4 + unattributed
        return int(reserved) == int(total_attributed)

    @staticmethod
    def verify_g2_memory_safety(
        recommended_mem_mb: int,
        observed_max_rss_mb: int,
        has_oom: bool,
        group_sample_size: int,
        min_samples: int = 5,
        safety_factor: float = 1.2,
    ) -> bool:
        """Verify Guarantee G2: recommendation respects floor, OOM escalation, and sample floor."""
        if group_sample_size < min_samples:
            return recommended_mem_mb is None

        if has_oom:
            # Memory must increase and be at least 1.5x observed max
            expected_lower_bound = int(observed_max_rss_mb * 1.5)
            return recommended_mem_mb >= expected_lower_bound

        # Standard guardrail: never below observed max
        expected_floor = int(observed_max_rss_mb)
        return recommended_mem_mb >= expected_floor

    @staticmethod
    def verify_g3_determinism(content_a: bytes, content_b: bytes) -> bool:
        """Verify Guarantee G3: byte-identical outputs across independent runs."""
        return content_a == content_b

    @staticmethod
    def verify_g4_schedule_validity(
        scheduled_jobs: list[dict[str, Any]],
        total_nodes: int,
        cores_per_node: int,
        mem_mb_per_node: int,
    ) -> bool:
        """Verify Guarantee G4: schedule completeness, temporal causality, and concurrency limits."""
        seen_job_ids = set()
        max_cluster_cores = total_nodes * cores_per_node
        max_cluster_mem = total_nodes * mem_mb_per_node

        critical_events: set[int] = set()

        for job in scheduled_jobs:
            job_id = job["job_id"]
            if job_id in seen_job_ids:
                return False
            seen_job_ids.add(job_id)

            sim_start = int(job["sim_start"])
            submit_time = int(job["submit_time"])
            run_s = int(job.get("run_s", 0))
            sim_end = int(job.get("sim_end", sim_start + run_s))

            if sim_start < submit_time:
                return False
            if sim_end < sim_start:
                return False

            critical_events.add(sim_start)
            critical_events.add(sim_end)

        # Evaluate active resource allocations across all event timestamps
        for t in sorted(critical_events):
            concurrent_cores = sum(
                int(job.get("alloc_cpus", 0))
                for job in scheduled_jobs
                if int(job["sim_start"]) <= t < int(job.get("sim_end", int(job["sim_start"]) + int(job.get("run_s", 0))))
            )
            concurrent_mem = sum(
                int(job.get("req_mem_mb", 0))
                for job in scheduled_jobs
                if int(job["sim_start"]) <= t < int(job.get("sim_end", int(job["sim_start"]) + int(job.get("run_s", 0))))
            )

            if concurrent_cores > max_cluster_cores:
                return False
            if concurrent_mem > max_cluster_mem:
                return False

        return True


@pytest.fixture
def validators() -> InvariantValidators:
    """Return invariant verification helper instance."""
    return InvariantValidators()


@pytest.fixture
def require_rcwa():
    """Skip test gracefully if rcwa functional pipeline is pending implementation."""
    if not is_rcwa_functional():
        pytest.skip("rcwa functional pipeline is pending implementation in Phase 1+")
