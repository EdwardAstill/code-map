"""`code-map find <pattern>` — fuzzy / glob symbol search."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from code_map.query import _glob_to_like, EXIT_NO_ARTIFACT


def run_find(*, pattern: str, fmt: str, limit: int, no_limit: bool, kind: str | None) -> None:
    from code_map.manifest import artifact_root

    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        print(f"no code map at {db_path.parent} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)

    # Treat any pattern without explicit globs as a substring search by wrapping
    # in `*…*`. Explicit globs (`b::*`, `*foo*`) pass through unchanged.
    if "*" not in pattern and "?" not in pattern:
        pattern = f"*{pattern}*"
    like, _is_glob = _glob_to_like(pattern)

    effective_limit = None if no_limit else min(max(limit, 1), 100)

    sql = (
        "SELECT s.qualified_name, s.name, s.kind, s.file_path, s.line_start, s.line_end, "
        "       COALESCE(f.pagerank, 0.0) AS score "
        "FROM symbols s "
        "LEFT JOIN files f ON s.file_path = f.path "
        "WHERE (s.qualified_name LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\')"
    )
    params: list = [like, like]
    if kind:
        sql += " AND s.kind = ?"
        params.append(kind)
    sql += " ORDER BY score DESC, s.qualified_name ASC"
    if effective_limit is not None:
        sql += f" LIMIT {int(effective_limit)}"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()

    if fmt == "markdown":
        print(_render_markdown(pattern, rows))
    else:
        print(json.dumps(rows, indent=2))


def _render_markdown(pattern: str, rows: list[dict]) -> str:
    if not rows:
        return f"_no symbols match `{pattern}`_"
    lines = [f"### `find {pattern}` ({len(rows)} match{'es' if len(rows) != 1 else ''})", ""]
    for r in rows:
        lines.append(
            f"- `{r['qualified_name']}` _{r['kind']}_ — "
            f"`{r['file_path']}:{r['line_start']}-{r['line_end']}`"
            + (f" · score={r['score']:.4f}" if r.get("score") is not None else "")
        )
    return "\n".join(lines)
