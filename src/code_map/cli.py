"""CLI surface for `code-map`. Subcommands wired in their own modules.

Exit codes (consistent across query-style subcommands):
- 0: success
- 2: no artifact (run `code-map build` first)
- 3: target symbol or file not found
- 4: artifact stale (only emitted by `code-map status` when explicitly checking)
"""
from __future__ import annotations

import typer

app = typer.Typer(
    help="Build and query the AI-consumable code-map artifact.",
    no_args_is_help=True,
)


# Token-budget presets for `--map-tokens`. Names map to int; passing an int via
# the flag still works directly. Research: RepoGraph 1-hop (~2.3 K tokens) often
# outperforms 2-hop (~10.5 K), so smaller is usually better than larger.
_MAP_TOKEN_PRESETS = {
    "small": 1500,
    "medium": 4000,
    "full": 1_000_000_000,  # effectively uncapped
}


def _resolve_map_tokens(value: str) -> int:
    """Translate `--map-tokens small|medium|full|<int>` to an int."""
    if value in _MAP_TOKEN_PRESETS:
        return _MAP_TOKEN_PRESETS[value]
    try:
        return int(value)
    except ValueError as e:
        raise typer.BadParameter(
            f"--map-tokens must be one of {sorted(_MAP_TOKEN_PRESETS)} or an integer; got {value!r}"
        ) from e


def _run() -> None:
    """Console-script entry point (see [project.scripts] in pyproject.toml)."""
    app()


# ── Build / refresh / render (writers) ───────────────────────────────────────


@app.command()
def build(
    repo: str = typer.Option(".", "--repo", help="Repo root to index."),
    lang: str = typer.Option("python,typescript,rust", "--lang", help="Comma-separated language list."),
    map_tokens: str = typer.Option(
        "medium", "--map-tokens",
        help="Token budget for MAP.md: small (1.5K) | medium (4K, default) | full (uncapped) | <int>.",
    ),
):
    """Full code-map build."""
    from code_map.runner import run_build
    run_build(repo=repo, languages=tuple(lang.split(",")), map_tokens=_resolve_map_tokens(map_tokens))


@app.command()
def refresh(
    paths: str = typer.Option("", "--paths", help="Optional glob restricting which files to consider."),
    json_out: bool = typer.Option(False, "--json", help="Emit a JSON summary of the run."),
):
    """Content-hash-gated incremental rebuild."""
    from code_map.runner import run_refresh
    run_refresh(paths=paths or None, json_summary=json_out)


@app.command()
def render(
    repo: str = typer.Option(".", "--repo", help="Repo root (defaults to cwd)."),
    map_tokens: str = typer.Option(
        "medium", "--map-tokens",
        help="Token budget for MAP.md: small (1.5K) | medium (4K, default) | full (uncapped) | <int>.",
    ),
):
    """Re-derive MAP.md and packages/*.md from graph.db."""
    from code_map.render import run_render
    run_render(repo=repo, map_tokens=_resolve_map_tokens(map_tokens))


# ── Read-only queries ─────────────────────────────────────────────────────────


@app.command()
def query(
    expression: str = typer.Argument(..., help="Query expression: callers-of <sym>, callees-of <sym>, blast-radius <sym> [--depth N], defined-in <file>. Symbol globs (* and ?) are honoured."),
    depth: int = typer.Option(3, "--depth", help="Depth limit for blast-radius. Default 3 — RepoGraph (ICLR 2025) shows 1-hop often beats N-hop; use --depth 5+ only when needed."),
    fmt: str = typer.Option("json", "--format", help="Output format: json (default, machine-parseable) or markdown (prompt-paste-ready)."),
    limit: int = typer.Option(50, "--limit", help="Max results (capped at 100 unless --no-limit)."),
    no_limit: bool = typer.Option(False, "--no-limit", help="Disable result cap."),
):
    """Read-only query against graph.db. Results carry a `score` field (PageRank-derived) and are score-desc ordered."""
    from code_map.query import run_query
    run_query(
        expression=expression, depth=depth,
        fmt=fmt, limit=limit, no_limit=no_limit,
    )


@app.command()
def find(
    pattern: str = typer.Argument(..., help="Substring or shell-style glob to match against symbol name OR qualified_name."),
    fmt: str = typer.Option("json", "--format", help="Output format: json or markdown."),
    limit: int = typer.Option(50, "--limit", help="Max results (cap 100 unless --no-limit)."),
    no_limit: bool = typer.Option(False, "--no-limit", help="Disable result cap."),
    kind: str = typer.Option("", "--kind", help="Optional symbol-kind filter (function, class, method, type, constant)."),
):
    """Fuzzy/substring symbol search by name or qualified_name. Use this when you don't know the exact qualified name."""
    from code_map.find import run_find
    run_find(pattern=pattern, fmt=fmt, limit=limit, no_limit=no_limit, kind=kind or None)


@app.command()
def source(
    symbol: str = typer.Argument(..., help="Exact qualified_name of the symbol."),
    fmt: str = typer.Option("text", "--format", help="Output format: text (default, raw source) or markdown (fenced block with language)."),
):
    """Fetch the source lines for a symbol (resolves file_path + line_start/end and prints the slice)."""
    from code_map.source import run_source
    run_source(symbol=symbol, fmt=fmt)


@app.command()
def outline(
    file_path: str = typer.Argument(..., help="Repo-relative path to the file."),
    fmt: str = typer.Option("text", "--format", help="Output format: text (tree) or markdown (heading hierarchy) or json."),
):
    """Tree-style outline of a file with class > method nesting."""
    from code_map.outline import run_outline
    run_outline(file_path=file_path, fmt=fmt)


@app.command()
def context(
    location: str = typer.Argument(..., help="`<file>:<line>` — return the symbol containing this line. For agents reading stack traces."),
    fmt: str = typer.Option("json", "--format", help="Output format: json or markdown."),
):
    """Reverse lookup: which symbol contains this file:line?"""
    from code_map.context import run_context
    run_context(location=location, fmt=fmt)


@app.command()
def status(
    fmt: str = typer.Option("json", "--format", help="Output format: json (default) or text."),
    fail_on_stale: bool = typer.Option(False, "--fail-on-stale", help="Exit 4 if artifact is stale (any source file newer than the artifact)."),
):
    """Report artifact freshness: built_at, files_total, files_changed_since_build, stale."""
    from code_map.status import run_status
    run_status(fmt=fmt, fail_on_stale=fail_on_stale)


@app.command()
def schema():
    """Emit the JSON Schema 2020-12 describing the artifact contract (graph.db tables, JSONL line shapes, manifest.json) to stdout."""
    from code_map.schema_cmd import run_schema
    run_schema()
