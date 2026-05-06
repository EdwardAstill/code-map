"""v0.3.0 bug-fix tests — surfaced by dogfooding code-map on the warden repo.

Five fixes:
- B1: refresh garbage-collects rows for files deleted from disk
- B2: inherits / implements / nested-package import edges actually emitted
- B3: PageRank is non-degenerate after build (>= 2 distinct scores)
- B4: Python methods are tagged kind=method, not kind=function
- B5: default skip-dirs cover dist/build/.pytest_cache/.warden/etc.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"


def _copy_fixture(dst: Path) -> None:
    """Copy the polyglot fixture into `dst` so build can write its artifact."""
    for child in FIXTURE_REPO.rglob("*"):
        if child.is_file():
            target = dst / child.relative_to(FIXTURE_REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(child.read_bytes())


def _build(repo: Path) -> int:
    return subprocess.call(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            "code-map",
            "build",
            "--repo",
            str(repo),
        ],
        cwd=str(PROJECT_ROOT),
    )


def _refresh(repo: Path) -> dict:
    out = subprocess.check_output(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "refresh", "--json"],
        cwd=str(repo),
        text=True,
    )
    return json.loads(out.strip().splitlines()[-1])


def _status(repo: Path) -> dict:
    out = subprocess.check_output(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "status"],
        cwd=str(repo),
        text=True,
    )
    return json.loads(out)


# ── B5: default skip-dirs ─────────────────────────────────────────────────────


def test_build_skips_default_ignore_dirs(tmp_path: Path):
    """Files inside dist/, build/, .pytest_cache/, node_modules/, .venv/, etc.
    are excluded from the indexed file set."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _copy_fixture(repo)

    # Plant decoy .py files in directories we expect to be skipped.
    # `.warden` is exercised by test_build_skips_warden_dir (separate test —
    # creating it here would relocate the artifact to .warden/maps/<slug>/
    # and complicate this assertion).
    decoy_dirs = (
        "dist",
        "build",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".next",
    )
    for d in decoy_dirs:
        (repo / d).mkdir(parents=True)
        (repo / d / "decoy.py").write_text("def should_not_be_indexed(): pass\n")

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    paths = {r[0] for r in conn.execute("SELECT path FROM files")}
    conn.close()

    for d in decoy_dirs:
        bad = f"{d}/decoy.py"
        assert bad not in paths, f"skip-dir {d!r} leaked into indexed files"


def test_build_skips_warden_dir(tmp_path: Path):
    """When `.warden/` exists, the artifact lands at .warden/maps/<slug>/, but
    files under .warden/specs etc. should NOT be indexed as source."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _copy_fixture(repo)
    (repo / ".warden" / "specs").mkdir(parents=True)
    (repo / ".warden" / "specs" / "leak.py").write_text("def leaked(): pass\n")

    rc = _build(repo)
    assert rc == 0

    art = repo / ".warden" / "maps"
    # The artifact dir name is derive_repo_slug-dependent; pick the only child.
    children = [p for p in art.iterdir() if p.is_dir()]
    assert len(children) == 1, (
        f"expected one slug subdir under .warden/maps, got {children}"
    )
    db = children[0] / "graph.db"

    conn = sqlite3.connect(db)
    paths = {r[0] for r in conn.execute("SELECT path FROM files")}
    conn.close()
    assert ".warden/specs/leak.py" not in paths, (
        f".warden/ leaked into indexed files: {paths}"
    )


# ── B4: Python methods tagged correctly ───────────────────────────────────────


def test_python_methods_are_kind_method(tmp_path: Path):
    """A class with multiple def-children should produce kind=method symbols
    (not kind=function), with qualified_name=<module>.<Class>.<method>."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text(
        "class Widget:\n"
        "    def red(self): pass\n"
        "    def green(self): pass\n"
        "    def blue(self): pass\n"
    )

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    rows = list(
        conn.execute(
            "SELECT name, kind, qualified_name FROM symbols WHERE file_path = 'm.py' ORDER BY line_start"
        )
    )
    conn.close()

    by_name = {r[0]: r for r in rows}
    assert "Widget" in by_name and by_name["Widget"][1] == "class"
    for color in ("red", "green", "blue"):
        assert color in by_name, f"method {color!r} missing"
        assert by_name[color][1] == "method", (
            f"{color!r} should be kind=method, got {by_name[color][1]!r}"
        )
        assert by_name[color][2] == f"m.Widget.{color}", (
            f"{color!r} qualified_name wrong: {by_name[color][2]!r}"
        )


# ── B2: inherits / implements / nested-package imports ────────────────────────


def test_python_inherits_edges_emitted(tmp_path: Path):
    """class Child(Parent): emits an inherits edge from Child to Parent."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "h.py").write_text(
        "class Parent:\n"
        "    pass\n"
        "\n"
        "class Child(Parent):\n"
        "    pass\n"
        "\n"
        "class Grandchild(Child):\n"
        "    pass\n"
    )

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    rows = list(
        conn.execute(
            "SELECT s_src.name, s_dst.name, e.kind FROM edges e"
            " JOIN symbols s_src ON e.src_symbol = s_src.id"
            " JOIN symbols s_dst ON e.dst_symbol = s_dst.id"
            " WHERE e.kind = 'inherits'"
        )
    )
    conn.close()

    pairs = {(s, d) for s, d, _ in rows}
    assert ("Child", "Parent") in pairs, f"missing Child→Parent inherits; got {pairs}"
    assert ("Grandchild", "Child") in pairs, (
        f"missing Grandchild→Child inherits; got {pairs}"
    )


def test_typescript_extends_and_implements_edges_emitted(tmp_path: Path):
    """class C extends B implements I, J → 1 inherits + 2 implements edges."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "h.ts").write_text(
        "class Base { hello(): void {} }\n"
        "interface IFoo { foo(): void }\n"
        "interface IBar { bar(): void }\n"
        "class Child extends Base implements IFoo, IBar {\n"
        "  foo(): void {}\n"
        "  bar(): void {}\n"
        "}\n"
    )
    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    rows = list(
        conn.execute(
            "SELECT s_src.name, s_dst.name, e.kind FROM edges e"
            " JOIN symbols s_src ON e.src_symbol = s_src.id"
            " JOIN symbols s_dst ON e.dst_symbol = s_dst.id"
            " WHERE e.kind IN ('inherits','implements')"
        )
    )
    conn.close()

    triples = {(s, d, k) for s, d, k in rows}
    assert ("Child", "Base", "inherits") in triples, (
        f"missing extends edge; got {triples}"
    )
    assert ("Child", "IFoo", "implements") in triples, (
        f"missing IFoo implements; got {triples}"
    )
    assert ("Child", "IBar", "implements") in triples, (
        f"missing IBar implements; got {triples}"
    )


def test_rust_implements_edge_emitted(tmp_path: Path):
    """impl Trait for Type → implements edge from Type to Trait."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "lib.rs").write_text(
        "pub trait Greet { fn greet(&self); }\n"
        "pub struct Greeter;\n"
        "impl Greet for Greeter { fn greet(&self) {} }\n"
    )
    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    rows = list(
        conn.execute(
            "SELECT s_src.name, s_dst.name, e.kind FROM edges e"
            " JOIN symbols s_src ON e.src_symbol = s_src.id"
            " JOIN symbols s_dst ON e.dst_symbol = s_dst.id"
            " WHERE e.kind = 'implements'"
        )
    )
    conn.close()

    pairs = {(s, d) for s, d, _ in rows}
    assert ("Greeter", "Greet") in pairs, (
        f"missing Greeter→Greet implements; got {pairs}"
    )


def test_python_nested_package_import_resolves(tmp_path: Path):
    """`from pkg.sub import mod` resolves even when pkg is nested under
    src/, so import edges land in the DB for non-flat layouts."""
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg" / "sub"
    nested.mkdir(parents=True)
    (repo / "src" / "pkg" / "__init__.py").write_text("")
    (repo / "src" / "pkg" / "sub" / "__init__.py").write_text("")
    (nested / "mod.py").write_text("def hello(): return 1\n")
    (repo / "caller.py").write_text(
        "from pkg.sub import mod\n\ndef use(): return mod.hello()\n"
    )

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    rows = list(
        conn.execute(
            "SELECT s_src.file_path, s_dst.file_path FROM edges e"
            " JOIN symbols s_src ON e.src_symbol = s_src.id"
            " JOIN symbols s_dst ON e.dst_symbol = s_dst.id"
            " WHERE e.kind = 'import'"
        )
    )
    conn.close()

    pairs = {(s, d) for s, d in rows}
    # Either resolution is acceptable: the package's __init__.py (we know
    # caller.py imports the package) or the submodule mod.py (we know the
    # import target name was `mod`). Both are correct interpretations.
    acceptable = {"src/pkg/sub/__init__.py", "src/pkg/sub/mod.py"}
    assert any(d in acceptable for _, d in pairs), (
        f"nested-package import did not resolve into the package; got {pairs}"
    )


# ── B3: PageRank non-degeneracy ───────────────────────────────────────────────


def test_pagerank_is_non_degenerate(tmp_path: Path):
    """After building the polyglot fixture, PageRank should not collapse to
    a single uniform value — at least 2 distinct scores."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _copy_fixture(repo)

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    scores = {
        round(r[0], 6)
        for r in conn.execute("SELECT pagerank FROM files WHERE pagerank IS NOT NULL")
    }
    conn.close()

    assert len(scores) >= 2, (
        f"PageRank degenerate — every file has the same score {scores}. "
        "Likely no import edges are being extracted."
    )


# ── B1: refresh garbage-collects deleted files ────────────────────────────────


def test_refresh_garbage_collects_deleted_files(tmp_path: Path):
    """Build → delete a file → refresh: the file's row + symbols + edges
    are removed from the DB and from manifest.json, and `status` reports
    zero missing files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text("def stay(): pass\n")
    (repo / "drop.py").write_text("def gone(): pass\n")

    rc = _build(repo)
    assert rc == 0

    db = repo / ".code-map" / "graph.db"
    conn = sqlite3.connect(db)
    paths_before = {r[0] for r in conn.execute("SELECT path FROM files")}
    sym_count_before = conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE file_path = 'drop.py'"
    ).fetchone()[0]
    conn.close()
    assert "drop.py" in paths_before
    assert sym_count_before > 0

    # Delete the file from disk.
    (repo / "drop.py").unlink()

    summary = _refresh(repo)
    assert summary.get("files_removed", 0) >= 1, (
        f"refresh did not GC deleted file: {summary}"
    )

    conn = sqlite3.connect(db)
    paths_after = {r[0] for r in conn.execute("SELECT path FROM files")}
    sym_count_after = conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE file_path = 'drop.py'"
    ).fetchone()[0]
    conn.close()
    assert "drop.py" not in paths_after, f"deleted file still in DB: {paths_after}"
    assert sym_count_after == 0, f"symbols for deleted file leaked: {sym_count_after}"

    manifest = json.loads((repo / ".code-map" / "manifest.json").read_text())
    assert "drop.py" not in manifest["files"], "deleted file still in manifest"

    s = _status(repo)
    assert s["files_missing_since_build"] == 0, f"status still reports missing: {s}"
    assert s["stale"] is False
