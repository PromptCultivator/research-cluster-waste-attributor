"""Hardware and environment telemetry profiling for benchmark runs."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def get_hardware_info() -> dict[str, str]:
    """Capture host CPU model, core count, memory, operating system, and git commit."""
    cpu_model = platform.processor() or "Unknown CPU"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass

    cores = str(os.cpu_count() or 1)

    ram_str = "Unknown"
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "MemTotal" in line:
                    kb_str = line.split(":", 1)[1].strip().split()[0]
                    gb_val = round(int(kb_str) / (1024 * 1024), 2)
                    ram_str = f"{gb_val} GB"
                    break
        except (OSError, ValueError):
            pass

    os_info = f"{platform.system()} {platform.release()}"

    lib_versions: list[str] = []
    for mod_name in ["polars", "pyarrow", "numpy", "pydantic"]:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "unknown")
            lib_versions.append(f"{mod_name}={ver}")
        except ImportError:
            pass

    libs_str = f" ({', '.join(lib_versions)})" if lib_versions else ""
    python_ver = f"{sys.version.split()[0]}{libs_str}"

    commit_hash = "unknown"
    try:
        commit_hash = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=5
            )
            .decode("utf-8")
            .strip()
        )
    except (subprocess.SubprocessError, OSError):
        pass

    return {
        "cpu_model": cpu_model,
        "cores": cores,
        "ram": ram_str,
        "os": os_info,
        "python": python_ver,
        "commit": commit_hash,
    }


def format_hardware_block() -> str:
    """Format hardware profile block matching SPEC.md §9 requirements."""
    info = get_hardware_info()
    return (
        f"CPU Model: {info['cpu_model']}\n"
        f"Physical Cores: {info['cores']}\n"
        f"RAM: {info['ram']}\n"
        f"Operating System: {info['os']}\n"
        f"Python Version: {info['python']}\n"
        f"Commit Hash: {info['commit']}"
    )


if __name__ == "__main__":
    print(format_hardware_block())
