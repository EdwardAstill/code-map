"""`code-map source <symbol>` — fetch source lines for a symbol."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from code_map.query import EXIT_NO_ARTIFACT, EXIT_NOT_FOUND


_LANG_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".rs": "rust",
}


def run_source(*, symbol: str, fmt: str) -> None:
    from code_map.manifest import artifact_root

    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        print(f"no code map at {db_path.parent} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT file_path, line_start, line_end, kind FROM symbols WHERE qualified_name = ? "
            "ORDER BY line_start LIMIT 1",
            (symbol,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"symbol not found: {symbol!r}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    file_path, line_start, line_end, kind = row
    full_path = repo_root / file_path
    if not full_path.exists():
        print(f"file referenced by symbol no longer exists: {file_path}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    text = full_path.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    # line_start / line_end are 1-indexed.
    slice_lines = all_lines[max(line_start - 1, 0):line_end]
    body = "\n".join(slice_lines)

    if fmt == "markdown":
        lang = _LANG_BY_EXT.get(Path(file_path).suffix, "")
        print(f"### `{symbol}` _{kind}_ — `{file_path}:{line_start}-{line_end}`\n")
        print(f"```{lang}")
        print(body)
        print("```")
    else:
        print(body)
