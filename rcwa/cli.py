"""Command-line interface for research-cluster-waste-attributor."""

from pathlib import Path
from typing import Annotated

import typer

from rcwa import __version__

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
    faults: Annotated[str, typer.Option("--faults", help="Fault generation profile.")] = "default",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination file for generated trace."),
    ] = None,
) -> None:
    """Generate a synthetic trace with planted waste categories."""
    destination = str(output) if output else "stdout"
    typer.echo(
        f"Synthesizing trace: size={size}, seed={seed}, faults={faults}, output={destination}"
    )


@app.command()
def ingest(
    trace: Annotated[Path, typer.Argument(help="Path to sacct or SWF accounting trace.")],
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


@app.command()
def attribute(
    trace: Annotated[Path, typer.Argument(help="Canonical trace path.")],
    policy: Annotated[
        Path,
        typer.Option("--policy", "-p", help="Attribution policy file path."),
    ] = Path("policies/default.yaml"),
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Attributed records destination path."),
    ] = None,
) -> None:
    """Attribute reserved resource waste across the four conservation classes."""
    typer.echo(f"Attributing waste for {trace} using policy {policy} (output={output})")


@app.command()
def recommend(
    attributed: Annotated[Path, typer.Argument(help="Attributed records Parquet file.")],
    policy: Annotated[
        Path,
        typer.Option("--policy", "-p", help="Rightsizing policy file path."),
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
    trace: Annotated[Path, typer.Argument(help="Canonical trace path.")],
    cluster: Annotated[
        Path,
        typer.Option("--cluster", "-c", help="Cluster configuration YAML."),
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
        typer.Argument(help="Trace file path for calibration against recorded wait times."),
    ] = None,
    cluster: Annotated[
        Path,
        typer.Option("--cluster", "-c", help="Cluster configuration YAML."),
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
        typer.Argument(help="Path to attributed or simulated trace results."),
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


@app.command()
def run(
    trace: Annotated[
        Path | None,
        typer.Argument(help="Trace path to process end-to-end."),
    ] = None,
    cluster: Annotated[
        Path,
        typer.Option("--cluster", "-c", help="Cluster configuration YAML."),
    ] = Path("clusters/example.yaml"),
    policy: Annotated[
        Path,
        typer.Option("--policy", "-p", help="Policy configuration YAML."),
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
