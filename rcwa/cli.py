"""Command-line interface for research-cluster-waste-attributor."""

import json
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
    ground_truth: Annotated[
        Path | None,
        typer.Option("--ground-truth", "-g", help="Destination for ground truth table."),
    ] = None,
) -> None:
    """Generate a synthetic trace with planted waste categories."""
    from rcwa.synth import generate_synthetic_trace, write_synthetic_trace

    destination = str(output) if output else "stdout"
    typer.echo(
        f"Synthesizing trace: size={size}, seed={seed}, runs={runs}, "
        f"faults={faults}, output={destination}"
    )
    if output is not None:
        sacct_text, truth_df = generate_synthetic_trace(size=size, seed=seed, faults=faults)
        write_synthetic_trace(
            output,
            sacct_text,
            truth_df=truth_df,
            ground_truth_path=ground_truth,
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

    from rcwa.attribute import attribute_trace, export_attributed_records

    attr_df = attribute_trace(df, policy=policy)

    if output is not None:
        fmt = "csv" if output.suffix.lower() == ".csv" else "parquet"
        export_attributed_records(attr_df, output, format=fmt)


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

    from rcwa.model import empty_canonical_df
    from rcwa.recommend import export_recommendations, recommend_jobs

    try:
        attr_df = pl.read_parquet(attributed)
    except Exception:
        attr_df = empty_canonical_df()

    recs_df = recommend_jobs(attr_df, policy=policy, trace_path=output or attributed)

    if output is not None:
        fmt = "csv" if output.suffix.lower() == ".csv" else "parquet"
        export_recommendations(recs_df, output, format=fmt)


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
        Path | None,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
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

    from rcwa.adapters.sacct import parse_sacct
    from rcwa.adapters.swf import parse_swf
    from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace

    if trace.suffix.lower() == ".parquet":
        df = pl.read_parquet(trace)
    else:
        name = trace.name.lower()
        if name.endswith(".swf") or name.endswith(".swf.gz"):
            df = parse_swf(trace)
        else:
            try:
                head_sample = trace.read_text(encoding="utf-8", errors="ignore")[:500]
                if not any("|" in line for line in head_sample.splitlines() if line.strip()):
                    df = parse_swf(trace)
                else:
                    df = parse_sacct(trace)
            except OSError:
                df = parse_sacct(trace)

    if cluster is not None:
        cluster_cfg = load_cluster_config(cluster)
    else:
        cluster_cfg = infer_cluster_from_trace(df)

    sim_df, metrics = simulate_trace(df, cluster=cluster_cfg, scenario=scenario)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".json":
            output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        elif output.suffix.lower() == ".csv":
            sim_df.write_csv(output)
        else:
            sim_df.write_parquet(output)
    else:
        typer.echo(f"Simulation scenario '{scenario}' completed: {metrics}")


@app.command()
def calibrate(
    trace: Annotated[
        Path | None,
        typer.Argument(
            help="Trace file path for calibration against recorded wait times.",
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    cluster: Annotated[
        Path | None,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Calibration report output path."),
    ] = None,
) -> None:
    """Calibrate simulator baseline wait times against actual historical wait times."""
    from rcwa.adapters.sacct import parse_sacct
    from rcwa.adapters.swf import parse_swf
    from rcwa.calibrate import compute_calibration_metrics
    from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace

    if trace is None:
        default_candidates = [
            Path("tests/fixtures/swf/calibration_reference.swf"),
            Path("tests/fixtures/swf/sample_workload.swf"),
        ]
        for candidate in default_candidates:
            if candidate.is_file():
                trace = candidate
                break

    if trace is None or not trace.is_file():
        typer.echo("Error: Trace file required for calibration.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Calibrating simulator against {trace} with cluster {cluster}")

    if trace.suffix.lower() == ".parquet":
        df = pl.read_parquet(trace)
    else:
        name = trace.name.lower()
        if name.endswith(".swf") or name.endswith(".swf.gz"):
            df = parse_swf(trace)
        else:
            try:
                head_sample = trace.read_text(encoding="utf-8", errors="ignore")[:500]
                if not any("|" in line for line in head_sample.splitlines() if line.strip()):
                    df = parse_swf(trace)
                else:
                    df = parse_sacct(trace)
            except OSError:
                df = parse_sacct(trace)

    if cluster is not None:
        cluster_cfg = load_cluster_config(cluster)
    else:
        cluster_cfg = infer_cluster_from_trace(df)

    sim_df, _ = simulate_trace(df, cluster=cluster_cfg, scenario="baseline")
    calib_metrics = compute_calibration_metrics(sim_df, df)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(calib_metrics, indent=2), encoding="utf-8")
    else:
        typer.echo(f"Calibration results: {json.dumps(calib_metrics, indent=2)}")


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
    policy: Annotated[
        Path | None,
        typer.Option("--policy", "-p", help="Rightsizing policy configuration YAML."),
    ] = None,
    cluster: Annotated[
        Path | None,
        typer.Option("--cluster", "-c", help="Cluster configuration YAML."),
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

    if trace is None:
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            if fmt == "json":
                output.write_text("{}", encoding="utf-8")
            elif fmt == "csv":
                output.write_text("", encoding="utf-8")
            else:
                output.write_text("# Report\n", encoding="utf-8")
        return

    from rcwa.adapters.sacct import parse_sacct
    from rcwa.adapters.swf import parse_swf
    from rcwa.attribute import attribute_trace
    from rcwa.report import build_report_data, render_csv_report, render_markdown_report

    trace_path = Path(trace)
    if trace_path.suffix.lower() == ".parquet":
        loaded_df = pl.read_parquet(trace_path)
        if "class1_over_mem_mb_s" in loaded_df.columns:
            attr_df = loaded_df
            canonical_df = loaded_df
        else:
            canonical_df = loaded_df
            attr_df = attribute_trace(canonical_df, policy=policy)
    else:
        is_swf_trace = trace_path.suffix.lower() in (".swf", ".swf.gz")
        if not is_swf_trace:
            try:
                head_sample = trace_path.read_text(encoding="utf-8", errors="ignore")[:500]
                if not any("|" in line for line in head_sample.splitlines() if line.strip()):
                    is_swf_trace = True
            except OSError:
                pass

        if is_swf_trace:
            canonical_df = parse_swf(trace_path)
        else:
            canonical_df = parse_sacct(trace_path)
        attr_df = attribute_trace(canonical_df, policy=policy)

    report_data = build_report_data(
        canonical_df, attr_df, policy=policy, cluster=cluster, include_simulation=True
    )

    if fmt == "json":
        rendered = json.dumps(report_data, indent=2)
    elif fmt == "csv":
        rendered = render_csv_report(report_data)
    else:
        rendered = render_markdown_report(report_data)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered)


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
        Path | None,
        typer.Option(
            "--cluster",
            "-c",
            help="Cluster configuration YAML.",
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    policy: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            "-p",
            help="Policy configuration YAML.",
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Output directory for reports and tables."),
    ] = Path("data/out"),
) -> None:
    """Execute complete attribution, recommendation, simulation, and report pipeline."""
    from rcwa.adapters.sacct import parse_sacct
    from rcwa.adapters.swf import parse_swf
    from rcwa.attribute import attribute_trace
    from rcwa.recommend import export_recommendations, recommend_jobs
    from rcwa.report import build_report_data, render_csv_report, render_markdown_report
    from rcwa.simulate import infer_cluster_from_trace, load_cluster_config, simulate_trace

    is_default = trace is None
    if trace is None:
        default_candidates = [
            Path("tests/fixtures/sacct/multiday_cluster.txt"),
            Path("tests/fixtures/swf/sample_workload.swf"),
        ]
        for candidate in default_candidates:
            if candidate.is_file():
                trace = candidate
                break

    if trace is None or not trace.is_file():
        typer.echo("Error: Trace file required for run pipeline.", err=True)
        raise typer.Exit(code=1)

    target = "default synthetic workload" if is_default else str(trace)
    typer.echo(
        f"Executing pipeline on {target} -> {output_dir} (cluster={cluster}, policy={policy})"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    trace_path = Path(trace)
    if trace_path.suffix.lower() == ".parquet":
        canonical_df = pl.read_parquet(trace_path)
    else:
        is_swf_trace = trace_path.suffix.lower() in (".swf", ".swf.gz")
        if not is_swf_trace:
            try:
                head_sample = trace_path.read_text(encoding="utf-8", errors="ignore")[:500]
                if not any("|" in line for line in head_sample.splitlines() if line.strip()):
                    is_swf_trace = True
            except OSError:
                pass
        if is_swf_trace:
            canonical_df = parse_swf(trace_path)
        else:
            canonical_df = parse_sacct(trace_path)

    canonical_df.write_parquet(output_dir / "canonical.parquet")

    # Attribution
    attr_df = attribute_trace(canonical_df, policy=policy)
    attr_df.write_parquet(output_dir / "attributed.parquet")

    # Recommendations
    recs_df = recommend_jobs(
        attr_df, policy=policy, trace_path=output_dir / "recommendations.parquet"
    )
    export_recommendations(recs_df, output_dir / "recommendations.parquet", format="parquet")
    export_recommendations(recs_df, output_dir / "recommendations.csv", format="csv")

    # Cluster configuration
    if cluster is not None:
        cluster_cfg = load_cluster_config(cluster)
    else:
        cluster_cfg = infer_cluster_from_trace(canonical_df)

    # Simulation baseline
    sim_baseline_df, _ = simulate_trace(
        canonical_df, cluster=cluster_cfg, scenario="baseline", policy=policy
    )
    sim_baseline_df.write_parquet(output_dir / "simulated_baseline.parquet")

    # Report compilation
    report_data = build_report_data(
        canonical_df,
        attr_df,
        policy=policy,
        cluster=cluster_cfg,
        include_simulation=True,
    )

    # Write report outputs
    (output_dir / "report.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    md_content = render_markdown_report(report_data)
    (output_dir / "report.md").write_text(md_content, encoding="utf-8")
    csv_content = render_csv_report(report_data)
    (output_dir / "report.csv").write_text(csv_content, encoding="utf-8")

    typer.echo(md_content)


if __name__ == "__main__":
    app()
