"""`code-map context <file>:<line>` — reverse lookup: which symbol contains this line?"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from code_map.query import EXIT_NO_ARTIFACT, EXIT_NOT_FOUND


def run_context(*, location: str, fmt: str) -> None:
    from code_map.manifest import artifact_root

    if ":" not in location:
        print(f"location must be `<file>:<line>`, got {location!r}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    file_path, _, line_str = location.rpartition(":")
    try:
        line = int(line_str)
    except ValueError:
        print(f"line must be an integer, got {line_str!r}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        print(f"no code map at {db_path.parent} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Innermost (smallest containing range) wins.
        rows = conn.execute(
            "SELECT qualified_name, name, kind, line_start, line_end "
            "FROM symbols WHERE file_path = ? AND line_start <= ? AND line_end >= ? "
            "ORDER BY (line_end - line_start) ASC",
            (file_path, line, line),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"no symbol contains {file_path}:{line}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    payload = [dict(r) for r in rows]

    if fmt == "markdown":
        innermost = payload[0]
        print(f"### Symbol containing `{file_path}:{line}`\n")
        print(
            f"- `{innermost['qualified_name']}` _{innermost['kind']}_ "
            f"L{innermost['line_start']}-{innermost['line_end']}"
        )
        if len(payload) > 1:
            print("\n_Enclosing scopes:_")
            for r in payload[1:]:
                print(f"  - `{r['qualified_name']}` _{r['kind']}_ L{r['line_start']}-{r['line_end']}")
    else:
        print(json.dumps(payload, indent=2))
