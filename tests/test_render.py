import sqlite3
from pathlib import Path

import tiktoken

from code_map.render import render_map_md, render_packages
from code_map.schema import init_db


def _seed(conn: sqlite3.Connection) -> None:
    files = [
        ("a.py", "python", "h1", 50, 0.4, "2026-05-06T12:00:00Z"),
        ("b.py", "python", "h2", 30, 0.6, "2026-05-06T12:00:00Z"),
    ]
    conn.executemany("INSERT INTO files VALUES (?,?,?,?,?,?)", files)
    syms = [
        (1, "a.py", "function", "main", "a.main", 1, 5, "def main()"),
        (2, "b.py", "function", "greet", "b.greet", 1, 3, "def greet(name)"),
    ]
    conn.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?)", syms)
    conn.execute("INSERT INTO edges VALUES (1, 2, 'calls', 'definite', 'direct')")
    conn.commit()


def test_render_map_md_respects_token_budget(tmp_path: Path):
    db = tmp_path / "graph.db"
    conn = init_db(db)
    _seed(conn)
    out = tmp_path / "MAP.md"
    render_map_md(conn=conn, out_path=out, map_tokens=200)
    text = out.read_text()
    encoder = tiktoken.get_encoding("cl100k_base")
    assert len(encoder.encode(text)) <= 200
    assert "b.py" in text  # higher PageRank, must be present


def test_render_packages_writes_one_file_per_directory(tmp_path: Path):
    db = tmp_path / "graph.db"
    conn = init_db(db)
    _seed(conn)
    pkg_dir = tmp_path / "packages"
    render_packages(conn=conn, out_dir=pkg_dir)
    files = list(pkg_dir.iterdir())
    # Both seeded symbols are in the same directory ('.'), so exactly one
    # package file is the correct output.
    assert len(files) == 1, f"expected 1 package file, got {len(files)}: {files}"


def test_render_map_md_under_tight_budget_does_not_overflow(tmp_path: Path):
    """Boundary check for ac8: even when budget is tight, the trailing
    newline must be inside the predicate so the written bytes do not exceed
    map_tokens by one token (the bare '\\n' is its own cl100k_base token)."""
    db = tmp_path / "graph.db"
    conn = init_db(db)
    # Many files so the loop has to truncate.
    rows = [(f"f{i:03d}.py", "python", f"h{i}", 100, 0.5, "2026-05-06T00:00:00Z") for i in range(50)]
    conn.executemany("INSERT INTO files VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    out = tmp_path / "MAP.md"
    # Budgets at and above what the header+footer alone consume.
    # Header for 50 files is ~70 tokens; below that, the header itself
    # cannot fit and the budget is effectively operator error.
    for budget in (100, 150, 200, 300, 1000):
        render_map_md(conn=conn, out_path=out, map_tokens=budget)
        actual = len(tiktoken.get_encoding("cl100k_base").encode(out.read_text()))
        assert actual <= budget, f"budget={budget} but rendered {actual} tokens"
