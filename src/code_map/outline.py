"""`code-map outline <file>` — tree-style outline of a file."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from code_map.query import EXIT_NO_ARTIFACT, EXIT_NOT_FOUND


def run_outline(*, file_path: str, fmt: str) -> None:
    from code_map.manifest import artifact_root

    repo_root = Path.cwd()
    db_path = artifact_root(repo_root) / "graph.db"
    if not db_path.exists():
        print(f"no code map at {db_path.parent} — run `code-map build` first", file=sys.stderr)
        sys.exit(EXIT_NO_ARTIFACT)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, qualified_name, kind, line_start, line_end, signature "
            "FROM symbols WHERE file_path = ? ORDER BY line_start",
            (file_path,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"no symbols indexed for file: {file_path!r}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    nodes = [dict(r) for r in rows]
    nested = _nest(nodes)

    if fmt == "json":
        print(json.dumps(nested, indent=2))
    elif fmt == "markdown":
        print(f"### Outline: `{file_path}`\n")
        for n in nested:
            _emit_md(n, depth=0)
    else:  # text (tree)
        print(file_path)
        for i, n in enumerate(nested):
            _emit_tree(n, prefix="", is_last=(i == len(nested) - 1))


def _nest(nodes: list[dict]) -> list[dict]:
    """Group methods inside their enclosing class by line containment."""
    classes = [n for n in nodes if n["kind"] == "class"]
    out: list[dict] = []
    consumed: set[int] = set()
    for cls in classes:
        cls_with = dict(cls)
        cls_with["children"] = []
        for i, n in enumerate(nodes):
            if n is cls or i in consumed:
                continue
            if n["kind"] == "method" and cls["line_start"] <= n["line_start"] <= cls["line_end"]:
                cls_with["children"].append(dict(n))
                consumed.add(i)
        out.append(cls_with)
    # Top-level (non-class, non-nested-method) symbols
    for i, n in enumerate(nodes):
        if n["kind"] == "class" or i in consumed:
            continue
        out.append({**n, "children": []})
    out.sort(key=lambda r: r["line_start"])
    return out


def _emit_tree(node: dict, *, prefix: str, is_last: bool) -> None:
    branch = "└── " if is_last else "├── "
    sig = node.get("signature") or ""
    sig_part = f" {sig}" if sig else ""
    print(f"{prefix}{branch}[{node['kind']}] {node['name']}  L{node['line_start']}-{node['line_end']}{sig_part}")
    children = node.get("children", [])
    next_prefix = prefix + ("    " if is_last else "│   ")
    for i, c in enumerate(children):
        _emit_tree(c, prefix=next_prefix, is_last=(i == len(children) - 1))


def _emit_md(node: dict, *, depth: int) -> None:
    indent = "  " * depth
    sig = node.get("signature") or ""
    sig_part = f" — `{sig}`" if sig else ""
    print(f"{indent}- **{node['name']}** _{node['kind']}_ L{node['line_start']}-{node['line_end']}{sig_part}")
    for c in node.get("children", []):
        _emit_md(c, depth=depth + 1)
