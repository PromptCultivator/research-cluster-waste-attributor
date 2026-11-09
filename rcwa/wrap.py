"""rcwa-wrap: Wrapper utility recording declared input hashes for jobs."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from rcwa import __version__

app = typer.Typer(
    name="rcwa-wrap",
    help="Record input hashes and execute job commands.",
    no_args_is_help=True,
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print wrapper version and exit."""
    if value:
        typer.echo(f"rcwa-wrap {__version__}")
        raise typer.Exit()


def normalize_command_line(cmd: list[str], regex_strip: str = "") -> str:
    """Normalize command-line tokens by stripping paths and sorting options."""
    if not cmd:
        return ""

    tokens = list(cmd)
    if regex_strip:
        pattern = re.compile(regex_strip)
        tokens = [pattern.sub("", t) for t in tokens]

    executable = tokens[0]
    args = tokens[1:]

    # Separate options (--key=value or --flag) from positional arguments
    options: list[str] = []
    positionals: list[str] = []

    for arg in args:
        if arg.startswith("-"):
            options.append(arg)
        else:
            positionals.append(arg)

    options.sort()
    normalized_parts = [executable] + options + positionals
    return " ".join(normalized_parts)


def hash_file(
    file_path: Path,
    big_file_mode: str = "size_mtime",
    big_file_threshold: int = 104857600,
) -> str:
    """Calculate file content hash or size/mtime representation."""
    if not file_path.exists():
        return "missing"

    try:
        stat_info = file_path.stat()
        file_size = stat_info.st_size
        mtime = int(stat_info.st_mtime)

        if big_file_mode == "size_mtime" and file_size > big_file_threshold:
            payload = f"{file_path.name}:{file_size}:{mtime}".encode()
            return hashlib.sha256(payload).hexdigest()

        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                hasher.update(block)
        return hasher.hexdigest()
    except OSError:
        return "missing"


def compute_input_hash(
    inputs: list[str],
    cmd: list[str],
    big_file_mode: str = "size_mtime",
    big_file_threshold: int = 104857600,
    regex_strip: str = "",
) -> str:
    """Produce deterministic composite hash for declared inputs and command line."""
    combined_hasher = hashlib.sha256()

    for item in sorted(inputs):
        path = Path(item)
        file_digest = hash_file(
            path,
            big_file_mode=big_file_mode,
            big_file_threshold=big_file_threshold,
        )
        combined_hasher.update(f"{item}={file_digest}\n".encode())

    normalized_cmd = normalize_command_line(cmd, regex_strip=regex_strip)
    combined_hasher.update(f"cmd={normalized_cmd}\n".encode())

    return combined_hasher.hexdigest()


def record_hash(input_hash: str) -> None:
    """Record input hash into Slurm comment and sidecar file when applicable."""
    slurm_job_id = os.environ.get("SLURM_JOB_ID")

    # 1. Update Slurm comment if job id is present
    if slurm_job_id:
        try:
            update_cmd = [
                "scontrol",
                "update",
                f"JobId={slurm_job_id}",
                f"Comment=RCWA_INPUT_HASH={input_hash}",
            ]
            subprocess.run(update_cmd, check=False, capture_output=True)
        except FileNotFoundError:
            pass

    # 2. Write sidecar json file if RCWA_DIR is specified
    rcwa_dir_env = os.environ.get("RCWA_DIR")
    if rcwa_dir_env:
        try:
            sidecar_dir = Path(rcwa_dir_env)
            sidecar_dir.mkdir(parents=True, exist_ok=True)
            job_key = slurm_job_id if slurm_job_id else "unknown"
            sidecar_file = sidecar_dir / f"{job_key}.json"
            sidecar_payload = {
                "job_id": job_key,
                "input_hash": input_hash,
            }
            sidecar_file.write_text(json.dumps(sidecar_payload, indent=2), encoding="utf-8")
        except OSError:
            pass


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_wrap(
    ctx: typer.Context,
    inputs: Annotated[
        str | None,
        typer.Option(
            "--inputs",
            help="Comma-separated declared input paths to hash.",
        ),
    ] = None,
    big_file_mode: Annotated[
        str,
        typer.Option(
            "--big-file-mode",
            help="Hashing strategy for large files: size_mtime or sha256.",
        ),
    ] = "size_mtime",
    big_file_threshold: Annotated[
        int,
        typer.Option(
            "--big-file-threshold",
            help="Threshold size in bytes to trigger big-file mode.",
        ),
    ] = 104857600,
    regex_strip: Annotated[
        str,
        typer.Option(
            "--regex-strip",
            help="Regex pattern to strip from command tokens during normalization.",
        ),
    ] = "",
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Wrap command execution and record input checksums."""
    command_tokens = ctx.args
    if not command_tokens:
        typer.echo("Error: No command specified to execute.", err=True)
        raise typer.Exit(code=1)

    input_list = [p.strip() for p in inputs.split(",") if p.strip()] if inputs else []
    digest = compute_input_hash(
        inputs=input_list,
        cmd=command_tokens,
        big_file_mode=big_file_mode,
        big_file_threshold=big_file_threshold,
        regex_strip=regex_strip,
    )

    record_hash(digest)

    result = subprocess.run(command_tokens)
    raise typer.Exit(code=result.returncode)


def main() -> None:
    """Console script entrypoint."""
    app()


if __name__ == "__main__":
    main()
