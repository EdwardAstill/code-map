"""Read-only query surface over graph.db."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from code_map.manifest import derive_repo_slug


def run_query(*, expression: str, depth: int, json_out: bool = True) -> None:
    _ = json_out  # accepted for explicitness; output is always JSON
    from code_map.manifest import artifact_root
    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        raise SystemExit(f"no code map at {db_path.parent} — run `code-map build` first")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        op, _, target = expression.partition(" ")
        target = target.strip()
        if not target:
            raise SystemExit(f"missing target for query: {expression!r}")

        start = time.perf_counter()
        if op == "callers-of":
            rows = _callers_of(conn, target)
        elif op == "callees-of":
            rows = _callees_of(conn, target)
        elif op == "blast-radius":
            rows = _blast_radius(conn, target, depth=depth)
        elif op == "defined-in":
            rows = _defined_in(conn, target)
        else:
            raise SystemExit(f"unknown query: {op!r}")
        elapsed_ms = (time.perf_counter() - start) * 1000

        payload = [dict(r) for r in rows]
        print(json.dumps(payload, indent=2))
        print(f"# query_ms: {elapsed_ms:.2f}", flush=True)
    finally:
        conn.close()


def _callers_of(conn: sqlite3.Connection, target: str):
    return conn.execute(
        "SELECT s_src.qualified_name, s_src.name, s_src.kind "
        "FROM edges e "
        "JOIN symbols s_dst ON e.dst_symbol = s_dst.id "
        "JOIN symbols s_src ON e.src_symbol = s_src.id "
        "WHERE s_dst.qualified_name = ? AND e.kind IN ('calls','references') "
        "ORDER BY s_src.qualified_name",
        (target,),
    ).fetchall()


def _callees_of(conn: sqlite3.Connection, target: str):
    return conn.execute(
        "SELECT s_dst.qualified_name, s_dst.name, s_dst.kind "
        "FROM edges e "
        "JOIN symbols s_src ON e.src_symbol = s_src.id "
        "JOIN symbols s_dst ON e.dst_symbol = s_dst.id "
        "WHERE s_src.qualified_name = ? AND e.kind IN ('calls','references') "
        "ORDER BY s_dst.qualified_name",
        (target,),
    ).fetchall()


def _blast_radius(conn: sqlite3.Connection, target: str, *, depth: int):
    sql = """
    WITH RECURSIVE callers(id, depth) AS (
      SELECT id, 0 FROM symbols WHERE qualified_name = ?
      UNION
      SELECT e.src_symbol, c.depth + 1
      FROM edges e JOIN callers c ON e.dst_symbol = c.id
      WHERE c.depth < ? AND e.kind IN ('calls','references')
    )
    SELECT s.qualified_name, s.name, s.kind, c.depth
    FROM callers c JOIN symbols s ON s.id = c.id
    WHERE c.depth > 0
    ORDER BY c.depth, s.qualified_name
    """
    return conn.execute(sql, (target, depth)).fetchall()


def _defined_in(conn: sqlite3.Connection, file_path: str):
    return conn.execute(
        "SELECT qualified_name, name, kind, line_start, line_end FROM symbols WHERE file_path = ? ORDER BY line_start",
        (file_path,),
    ).fetchall()
