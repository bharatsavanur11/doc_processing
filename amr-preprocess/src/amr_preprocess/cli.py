from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from amr_preprocess.eval_runner import run_eval
from amr_preprocess.pipeline import process_path
from amr_preprocess.samples import write_samples

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _default(path: Path) -> Path:
    return path if path.is_absolute() else PACKAGE_ROOT / path


@app.command()
def process(
    source: Path = typer.Argument(..., help="File or directory to process"),
    out: Path = typer.Option(
        Path("artifacts/runs"),
        "--out",
        help="Artifact root (a new run directory is created under this)",
    ),
    render_pages: bool = typer.Option(True, help="Write page PNGs for the retrieval hook"),
    llm_context: bool = typer.Option(
        False,
        "--llm-context",
        help="Also write prompt-ready markdown (<doc_id>.llm.md) with page anchors",
    ),
    llm_max_tokens: int = typer.Option(
        None,
        "--llm-max-tokens",
        help="Approximate token budget per LLM context chunk (splits into .partNN.md files)",
    ),
) -> None:
    """Ingest, extract, normalize, and write versioned artifacts."""
    out = _default(out)
    source = source.expanduser()
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    manifest, run_dir, docs = process_path(
        source,
        out,
        render_pages=render_pages,
        llm_context=llm_context or llm_max_tokens is not None,
        llm_max_tokens=llm_max_tokens,
    )
    table = Table(title=f"Run {manifest.run_id}")
    table.add_column("doc_id")
    table.add_column("class")
    table.add_column("file")
    table.add_column("tables")
    table.add_column("pages")
    for d in docs:
        table.add_row(
            d.doc_id,
            d.doc_class.value,
            d.filename,
            str(len(d.tables)),
            str(d.page_count),
        )
    console.print(table)
    console.print(f"artifacts: {run_dir}")
    if manifest.warnings:
        console.print(f"[yellow]{len(manifest.warnings)} warning(s)[/yellow]")


@app.command("eval")
def eval_cmd(
    fixtures: Path = typer.Option(
        Path("evals/fixtures"),
        "--fixtures",
        help="Golden fixture directory",
    ),
    config: Path = typer.Option(Path("evals/config.yaml"), "--config"),
) -> None:
    """Replay the pipeline on goldens and print a scorecard."""
    report = run_eval(_default(fixtures), _default(config))
    table = Table(title="Eval scorecard")
    table.add_column("scorer")
    table.add_column("score")
    table.add_column("threshold")
    table.add_column("gate")
    failed = False
    for row in report["scores"]:
        gate = "PASS" if row["pass"] else "FAIL"
        if not row["pass"]:
            failed = True
        table.add_row(row["name"], f"{row['score']:.3f}", f"{row['threshold']:.3f}", gate)
    console.print(table)
    console.print(f"latency_ms: {report['latency_ms']}")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def sample(
    dest: Path = typer.Option(Path("samples"), "--dest"),
    fixtures: Path = typer.Option(Path("evals/fixtures"), "--fixtures"),
) -> None:
    """Write synthetic AMR sample documents and golden eval fixtures."""
    from amr_preprocess.samples import write_eval_fixtures

    written = write_samples(_default(dest))
    cases = write_eval_fixtures(_default(fixtures))
    for p in written + cases:
        console.print(str(p))


if __name__ == "__main__":
    app()
