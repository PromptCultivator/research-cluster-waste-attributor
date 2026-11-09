"""Command-line interface for research-cluster-waste-attributor."""

from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from rcwa import __version__
from rcwa.adapters.sacct import parse_sacct
from rcwa.adapters.swf import parse_swf

app = typer.Typer(
    name="rcwa",
    help="Research Cluster Waste Attributor CLI.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print package version and exit."""
    if value:
        typer.echo(f"rcwa {__version__}")
        raise typer.Exit()


@app.callback()
def main(
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
    """Entry point for the rcwa application."""


@app.command()
def version() -> None:
    """Print the rcwa package version."""
    typer.echo(f"rcwa {__version__}")


@app.command()
def synth(
    size: Annotated[str, typer.Option("--size", help="Trace size, e.g. 20k, 1M.")] = "20k",
    seed: Annotated[int, typer.Option("--seed", help="Random seed for reproducibility.")] = 1,
    runs: Annotated[int, typer.Option("--runs", help="Number of benchmark iterations.")] = 1,
    faults: Annotated[str, typer.Option("--faults", help="Fault generation profile.")] = "default",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination file for generated trace."),
    ] = None,
) -> None:
    """Generate a synthetic trace with planted waste categories."""
    destination = str(output) if output else "stdout"
    typer.echo(
        f"Synthesizing trace: size={size}, seed={seed}, runs={runs}, "
        f"faults={faults}, output={destination}"
    )


@app.command()
def ingest(
    trace: Annotated[
        Path,
        typer.Argument(
            help="Path to sacct or SWF accounting trace.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Trace input format (sacct, swf, auto)."),
    ] = "auto",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination path for canonical Parquet output."),
    ] = None,
) -> None:
    """Ingest raw scheduler accounting logs into canonical Arrow format."""
    typer.echo(f"Ingesting trace {trace} (format={format}, output={output})")

    # Binary check
    try:
        raw_header = trace.read_bytes()[:8192]
        if b"\x00" in raw_header:
            typer.echo(f"Error: Binary non-text file cannot be decoded: {trace}", err=True)
            raise typer.Exit(code=1)
    except OSError as err:
        typer.echo(f"Error reading file {trace}: {err}", err=True)
        raise typer.Exit(code=1)

    fmt = format.lower()
    if fmt not in ("auto", "sacct", "swf"):
        typer.echo(
            f"Error: Unsupported format '{format}'. Supported formats: auto, sacct, swf",
            err=True,
        )
        raise typer.Exit(code=2)

    if fmt == "auto":
        name = trace.name.lower()
        if name.endswith(".swf") or name.endswith(".swf.gz"):
            fmt = "swf"
        else:
            try:
                first_line = trace.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
                if first_line.startswith(";"):
                    fmt = "swf"
                else:
                    fmt = "sacct"
            except IndexError:
                fmt = "sacct"

    try:
        if fmt == "swf":
            df = parse_swf(trace)
        else:
            df = parse_sacct(trace)
    except (ValueError, UnicodeDecodeError) as err:
        typer.echo(f"Error parsing trace: {err}", err=True)
        raise typer.Exit(code=1)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(output)


@app.command()
def attribute(
    trace: Annotated[
        Path,
        typer.Argument(
            help="Canonical trace path.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    policy: Annotated[
        Path,
        typer.Option(
            "--policy",
            "-p",
            help="Attribution policy file path.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("policies/default.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Attributed records destination path."),
    ] = None,
) -> None:
    """Attribute reserved resource waste across the four conservation classes."""
    typer.echo(f"Attributing waste for {trace} using policy {policy} (output={output})")

    if trace.name.endswith(".parquet"):
        df = pl.read_parquet(trace)
    else:
        name = trace.name.lower()
        if name.endswith(".swf") or name.endswith(".swf.gz"):
            df = parse_swf(trace)
        else:
            df = parse_sacct(trace)

    # Exclude RUNNING and PENDING rows from attribution (SPEC section 5.3)
    df = df.filter(~pl.col("state").is_in(["RUNNING", "PENDING"]))

    failed_states = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED"}

    class3_sub_labels: list[str | None] = []
    class4_core_s_list: list[int] = []
    possible_recompute_list: list[bool] = []

    seen_completed_inputs: set[tuple[str, str]] = set()
    seen_completed_commands: set[str] = set()

    for row in df.iter_rows(named=True):
        st = row["state"]
        run_s = row["run_s"]
        cmd_h = row["command_hash"]
        inp_h = row["input_hash"]
        res_core = row["reserved_core_s"]

        is_failed = (st in failed_states) or (st == "CANCELLED" and run_s > 0)
        if is_failed:
            if run_s <= 60:
                sub_label = "early_failure"
            elif st == "OUT_OF_MEMORY":
                sub_label = "oom"
            elif st == "TIMEOUT":
                sub_label = "timeout"
            elif st == "NODE_FAIL":
                sub_label = "node_fail"
            elif st == "CANCELLED":
                sub_label = "cancelled_after_start"
            else:
                sub_label = "other_failure"
            class3_sub_labels.append(sub_label)
            class4_core_s_list.append(0)
            possible_recompute_list.append(False)
        else:
            class3_sub_labels.append(None)

            if st == "COMPLETED":
                if inp_h and cmd_h:
                    pair = (cmd_h, inp_h)
                    if pair in seen_completed_inputs:
                        class4_core_s_list.append(res_core)
                        possible_recompute_list.append(False)
                    else:
                        seen_completed_inputs.add(pair)
                        class4_core_s_list.append(0)
                        possible_recompute_list.append(False)
                elif cmd_h and not inp_h:
                    if cmd_h in seen_completed_commands:
                        class4_core_s_list.append(0)
                        possible_recompute_list.append(True)
                    else:
                        seen_completed_commands.add(cmd_h)
                        class4_core_s_list.append(0)
                        possible_recompute_list.append(False)
                else:
                    class4_core_s_list.append(0)
                    possible_recompute_list.append(False)
            else:
                class4_core_s_list.append(0)
                possible_recompute_list.append(False)

    df = df.with_columns(
        [
            pl.Series("class3_sub_label", class3_sub_labels, dtype=pl.String),
            pl.Series("class4_core_s", class4_core_s_list, dtype=pl.Int64),
            pl.Series("possible_recompute", possible_recompute_list, dtype=pl.Boolean),
        ]
    )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(output)


@app.command()
def recommend(
    attributed: Annotated[
        Path,
        typer.Argument(
            help="Attributed records Parquet file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    policy: Annotated[
        Path,
        typer.Option(
            "--policy",
            "-p",
            help="Rightsizing policy file path.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("policies/default.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination path for recommendations table."),
    ] = None,
) -> None:
    """Generate right-sized CPU and memory resource recommendations with guardrails."""
    typer.echo(f"Generating recommendations from {attributed} with {policy} (output={output})")


@app.command()
def simulate(
    trace: Annotated[
        Path,
        typer.Argument(
            help="Canonical trace path.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    cluster: Annotated[
        Path,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("clusters/example.yaml"),
    scenario: Annotated[
        str,
        typer.Option(
            "--scenario",
            "-s",
            help="Simulation scenario (baseline, mem_rightsized, all).",
        ),
    ] = "baseline",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Simulation metrics output file."),
    ] = None,
) -> None:
    """Replay traces through the EASY-backfill queue simulator."""
    typer.echo(f"Simulating trace {trace} on cluster {cluster}, scenario={scenario}")


@app.command()
def calibrate(
    trace: Annotated[
        Path | None,
        typer.Argument(
            help="Trace file path for calibration against recorded wait times.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    cluster: Annotated[
        Path,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("clusters/example.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Calibration report output path."),
    ] = None,
) -> None:
    """Calibrate simulator baseline wait times against actual historical wait times."""
    target = str(trace) if trace else "default traces"
    typer.echo(f"Calibrating simulator against {target} with cluster {cluster}")


@app.command()
def report(
    trace: Annotated[
        Path | None,
        typer.Argument(
            help="Path to attributed or simulated trace results.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (markdown, json, csv)."),
    ] = "markdown",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination report file path."),
    ] = None,
) -> None:
    """Produce reclaim ranking and queue simulation reports."""
    target = str(trace) if trace else "all results"
    typer.echo(f"Reporting results for {target} (format={format}, output={output})")
    fmt = format.lower()
    if fmt not in ("markdown", "json", "csv"):
        typer.echo(
            f"Error: Unsupported report format '{format}'. Supported formats: markdown, json, csv",
            err=True,
        )
        raise typer.Exit(code=2)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            output.write_text("{}", encoding="utf-8")
        elif fmt == "csv":
            output.write_text("", encoding="utf-8")
        else:
            output.write_text("# Report\n", encoding="utf-8")


@app.command()
def run(
    trace: Annotated[
        Path | None,
        typer.Argument(
            help="Trace path to process end-to-end.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    cluster: Annotated[
        Path,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("clusters/example.yaml"),
    policy: Annotated[
        Path,
        typer.Option(
            "--policy",
            "-p",
            help="Policy configuration YAML.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = Path("policies/default.yaml"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Output directory for reports and tables."),
    ] = Path("data/out"),
) -> None:
    """Execute complete attribution, recommendation, simulation, and report pipeline."""
    target = str(trace) if trace else "default synthetic workload"
    typer.echo(
        f"Executing pipeline on {target} -> {output_dir} (cluster={cluster}, policy={policy})"
    )


if __name__ == "__main__":
    app()
