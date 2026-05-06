"""Read-only query surface over graph.db.

Exit codes (CLI contract):
- 0: success
- 2: no artifact (run `code-map build` first)
- 3: target symbol or file not found
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_NO_ARTIFACT = 2
EXIT_NOT_FOUND = 3
EXIT_STALE = 4


def _glob_to_like(pattern: str) -> tuple[str, bool]:
    """Translate a shell-style glob to a SQL LIKE pattern.

    Returns (translated, is_glob). `*` → `%`, `?` → `_`, escapes the
    SQL wildcards so they're treated as literal if the pattern contains them.
    """
    if "*" not in pattern and "?" not in pattern:
        return pattern, False
    # Escape SQL wildcards in the input first.
    escaped = pattern.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return escaped.replace("*", "%").replace("?", "_"), True


def run_query(
    *,
    expression: str,
    depth: int,
    json_out: bool = True,
    fmt: str = "json",
    limit: int = 50,
    no_limit: bool = False,
) -> None:
    _ = json_out
    from code_map.manifest import artifact_root
    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        print(f"no code map at {db_path.parent} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        op, _, target = expression.partition(" ")
        target = target.strip()
        if not target:
            print(f"missing target for query: {expression!r}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)

        effective_limit = None if no_limit else min(max(limit, 1), 100)

        start = time.perf_counter()
        if op == "callers-of":
            rows = _callers_of(conn, target, limit=effective_limit)
        elif op == "callees-of":
            rows = _callees_of(conn, target, limit=effective_limit)
        elif op == "blast-radius":
            rows = _blast_radius(conn, target, depth=depth, limit=effective_limit)
        elif op == "defined-in":
            rows = _defined_in(conn, target, limit=effective_limit)
        else:
            print(f"unknown query: {op!r}", file=sys.stderr)
            sys.exit(EXIT_NOT_FOUND)
        elapsed_ms = (time.perf_counter() - start) * 1000

        payload = [dict(r) for r in rows]

        if fmt == "markdown":
            print(_render_markdown(op, target, payload))
        else:
            print(json.dumps(payload, indent=2))
        print(f"# query_ms: {elapsed_ms:.2f}", file=sys.stderr, flush=True)
    finally:
        conn.close()


def _maybe_glob(target: str, column_expr: str) -> tuple[str, str]:
    """Return (sql_predicate, sql_value) for either exact match or LIKE."""
    pattern, is_glob = _glob_to_like(target)
    if is_glob:
        return f"{column_expr} LIKE ? ESCAPE '\\'", pattern
    return f"{column_expr} = ?", target


def _callers_of(conn: sqlite3.Connection, target: str, *, limit: int | None):
    pred, val = _maybe_glob(target, "s_dst.qualified_name")
    sql = (
        "SELECT s_src.qualified_name, s_src.name, s_src.kind, "
        "       COALESCE(f.pagerank, 0.0) AS score "
        "FROM edges e "
        "JOIN symbols s_dst ON e.dst_symbol = s_dst.id "
        "JOIN symbols s_src ON e.src_symbol = s_src.id "
        "LEFT JOIN files f ON s_src.file_path = f.path "
        f"WHERE {pred} AND e.kind IN ('calls','references','inherits','implements') "
        "ORDER BY score DESC, s_src.qualified_name ASC"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (val,)).fetchall()


def _callees_of(conn: sqlite3.Connection, target: str, *, limit: int | None):
    pred, val = _maybe_glob(target, "s_src.qualified_name")
    sql = (
        "SELECT s_dst.qualified_name, s_dst.name, s_dst.kind, "
        "       COALESCE(f.pagerank, 0.0) AS score "
        "FROM edges e "
        "JOIN symbols s_src ON e.src_symbol = s_src.id "
        "JOIN symbols s_dst ON e.dst_symbol = s_dst.id "
        "LEFT JOIN files f ON s_dst.file_path = f.path "
        f"WHERE {pred} AND e.kind IN ('calls','references','inherits','implements') "
        "ORDER BY score DESC, s_dst.qualified_name ASC"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (val,)).fetchall()


def _blast_radius(conn: sqlite3.Connection, target: str, *, depth: int, limit: int | None):
    pred, val = _maybe_glob(target, "qualified_name")
    sql = f"""
    WITH RECURSIVE callers(id, depth) AS (
      SELECT id, 0 FROM symbols WHERE {pred}
      UNION
      SELECT e.src_symbol, c.depth + 1
      FROM edges e JOIN callers c ON e.dst_symbol = c.id
      WHERE c.depth < ? AND e.kind IN ('calls','references','inherits','implements')
    )
    SELECT s.qualified_name, s.name, s.kind, c.depth,
           (COALESCE(f.pagerank, 0.0) / (1.0 + c.depth)) AS score
    FROM callers c
    JOIN symbols s ON s.id = c.id
    LEFT JOIN files f ON s.file_path = f.path
    WHERE c.depth > 0
    ORDER BY score DESC, c.depth ASC, s.qualified_name ASC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (val, depth)).fetchall()


def _defined_in(conn: sqlite3.Connection, file_path: str, *, limit: int | None):
    pred, val = _maybe_glob(file_path, "file_path")
    sql = (
        "SELECT qualified_name, name, kind, line_start, line_end "
        f"FROM symbols WHERE {pred} ORDER BY line_start"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (val,)).fetchall()


def _render_markdown(op: str, target: str, payload: list[dict]) -> str:
    """Compact markdown render of query results for prompt-paste use."""
    if not payload:
        return f"_no results for `{op} {target}`_"
    lines = [f"### `{op} {target}` ({len(payload)} result{'s' if len(payload) != 1 else ''})", ""]
    for row in payload:
        qname = row.get("qualified_name", row.get("name", "?"))
        kind = row.get("kind", "?")
        depth = row.get("depth")
        score = row.get("score")
        bits = [f"`{qname}` _{kind}_"]
        if depth is not None:
            bits.append(f"depth={depth}")
        if score is not None:
            bits.append(f"score={score:.4f}")
        if "line_start" in row:
            bits.append(f"L{row['line_start']}-{row.get('line_end', '?')}")
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines)
