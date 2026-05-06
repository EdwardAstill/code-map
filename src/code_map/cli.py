"""CLI surface for `code-map`. Subcommands wired in their own modules."""
from __future__ import annotations

import typer

app = typer.Typer(help="Build and query the AI-consumable code-map artifact.")


def _run() -> None:
    """Console-script entry point (see [project.scripts] in pyproject.toml)."""
    app()


@app.command()
def build(
    repo: str = typer.Option(".", "--repo", help="Repo root to index."),
    lang: str = typer.Option("python,typescript,rust", "--lang", help="Comma-separated language list."),
    map_tokens: int = typer.Option(4000, "--map-tokens", help="Token budget for MAP.md."),
):
    """Full code-map build."""
    from code_map.runner import run_build
    run_build(repo=repo, languages=tuple(lang.split(",")), map_tokens=map_tokens)


@app.command()
def refresh(
    paths: str = typer.Option("", "--paths", help="Optional glob restricting which files to consider."),
    json_out: bool = typer.Option(False, "--json", help="Emit a JSON summary of the run."),
):
    """Content-hash-gated incremental rebuild."""
    from code_map.runner import run_refresh
    run_refresh(paths=paths or None, json_summary=json_out)


@app.command()
def query(
    expression: str = typer.Argument(..., help="Query expression: callers-of <sym>, callees-of <sym>, blast-radius <sym> [--depth N], defined-in <file>."),
    depth: int = typer.Option(5, "--depth", help="Depth limit for blast-radius."),
    json_out: bool = typer.Option(True, "--json", help="JSON output (default; flag accepted for explicitness)."),
):
    """Read-only query against graph.db."""
    from code_map.query import run_query
    run_query(expression=expression, depth=depth, json_out=json_out)


@app.command()
def render(
    repo: str = typer.Option(".", "--repo", help="Repo root (defaults to cwd)."),
    map_tokens: int = typer.Option(4000, "--map-tokens", help="Token budget for MAP.md."),
):
    """Re-derive MAP.md and packages/*.md from graph.db."""
    from code_map.render import run_render
    run_render(repo=repo, map_tokens=map_tokens)
