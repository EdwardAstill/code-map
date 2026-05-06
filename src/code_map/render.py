"""MAP.md and packages/*.md rendering with tiktoken token budgeting."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

import tiktoken


def run_render(*, map_tokens: int, repo: str = ".") -> None:
    """CLI entry point. Resolves the artifact path, opens graph.db, re-renders."""
    from code_map.manifest import artifact_root
    repo_root = Path(repo).resolve()
    artifact_dir = artifact_root(repo_root)
    db_path = artifact_dir / "graph.db"
    if not db_path.exists():
        raise SystemExit(f"no code map at {artifact_dir} — run `code-map build` first")
    conn = sqlite3.connect(db_path)
    try:
        render_map_md(conn=conn, out_path=artifact_dir / "MAP.md", map_tokens=map_tokens)
        render_packages(conn=conn, out_dir=artifact_dir / "packages")
    finally:
        conn.close()


def render_map_md(*, conn: sqlite3.Connection, out_path: Path, map_tokens: int) -> None:
    encoder = tiktoken.get_encoding("cl100k_base")
    files = list(conn.execute(
        "SELECT path, language, loc, COALESCE(pagerank, 0.0) FROM files ORDER BY COALESCE(pagerank, 0.0) DESC, path ASC"
    ))
    sym_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    langs = sorted({row[1] for row in files})
    last_built = conn.execute("SELECT MAX(last_indexed) FROM files").fetchone()[0] or ""

    header_lines = [
        f"# Code Map",
        "",
        f"- files: {len(files)}",
        f"- symbols: {sym_count}",
        f"- edges: {edge_count}",
        f"- languages: {', '.join(langs)}",
        f"- last built: {last_built}",
        "",
        "## Top files (by PageRank)",
        "",
    ]
    body_lines: list[str] = []
    for path, lang, loc, rank in files:
        in_count = conn.execute("SELECT COUNT(*) FROM edges e JOIN symbols s ON e.dst_symbol = s.id WHERE s.file_path = ?", (path,)).fetchone()[0]
        out_count = conn.execute("SELECT COUNT(*) FROM edges e JOIN symbols s ON e.src_symbol = s.id WHERE s.file_path = ?", (path,)).fetchone()[0]
        top_syms = list(conn.execute("SELECT name, kind FROM symbols WHERE file_path = ? ORDER BY name LIMIT 8", (path,)))
        sym_summary = ", ".join(f"`{name}` ({kind})" for name, kind in top_syms)
        line = f"- `{path}` [{lang}, {loc} loc, rank {rank:.4f}, in {in_count} / out {out_count}] — {sym_summary}"
        body_lines.append(line)

    footer = ["", "See `README.md` in this directory for the schema and the static-analysis blind-spot list."]

    rendered = "\n".join(header_lines)
    footer_text = "\n".join(footer) + "\n"

    # If the header+footer alone overflows the budget, fall back to a minimal
    # header so the written file is always within budget.
    if len(encoder.encode(rendered + footer_text)) > map_tokens:
        rendered = "# Code Map\n\n"
        # Even the minimal header may be over budget for an absurdly small
        # value; in that case, write only the footer (or empty) — never
        # exceed the requested budget.
        if len(encoder.encode(rendered + footer_text)) > map_tokens:
            rendered = ""

    for line in body_lines:
        candidate = rendered + line + "\n"
        # Predicate measures the exact bytes that will be written.
        if len(encoder.encode(candidate + footer_text)) > map_tokens:
            break
        rendered = candidate
    rendered = rendered + footer_text
    # Final safety: never write past budget.
    if len(encoder.encode(rendered)) > map_tokens:
        # Trim from the end until we fit.
        toks = encoder.encode(rendered)[:map_tokens]
        rendered = encoder.decode(toks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")


def render_packages(*, conn: sqlite3.Connection, out_dir: Path) -> None:
    by_dir: dict[str, list[tuple]] = defaultdict(list)
    for row in conn.execute("SELECT file_path, name, kind, qualified_name, signature FROM symbols ORDER BY file_path, name"):
        pkg = str(Path(row[0]).parent) or "."
        by_dir[pkg].append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    for pkg, rows in by_dir.items():
        slug = pkg.replace("/", "_") or "root"
        out = out_dir / f"{slug}.md"
        lines = [f"# Package: {pkg}", ""]
        cur_file = None
        for file_path, name, kind, qname, sig in rows:
            if file_path != cur_file:
                lines += ["", f"## `{file_path}`", ""]
                cur_file = file_path
            lines.append(f"- `{name}` ({kind}) — `{qname}`" + (f" — `{sig}`" if sig else ""))
        out.write_text("\n".join(lines) + "\n")
