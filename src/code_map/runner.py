"""Top-level orchestrators for build and refresh."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from code_map.extract import Edge, Symbol, for_language
from code_map.manifest import (
    Manifest,
    derive_repo_slug,
    file_content_hash,
    load_manifest,
    save_manifest,
)
from code_map.mirrors import append_edges, append_symbols
from code_map.pagerank import compute_pagerank
from code_map.readme import write_readme
from code_map.render import render_map_md, render_packages
from code_map.schema import init_db


_LANG_EXT: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "typescript": (".ts", ".tsx"),
    "javascript": (".js", ".jsx"),
    "rust": (".rs",),
}

_SKIP_DIRS = {".git", "node_modules", ".venv", "target", "__pycache__"}


def run_build(*, repo: str, languages: tuple[str, ...], map_tokens: int) -> None:
    from code_map.manifest import artifact_root
    repo_root = Path(repo).resolve()
    artifact = artifact_root(repo_root)

    # Wipe prior artifact so build is deterministic.
    if artifact.exists():
        for child in artifact.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(artifact.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()

    conn = init_db(artifact / "graph.db")
    try:
        _build_inner(conn, repo_root, languages, artifact, map_tokens)
    finally:
        conn.close()


def _build_inner(conn, repo_root: Path, languages: tuple[str, ...], artifact: Path, map_tokens: int) -> None:
    files_indexed: dict[str, dict[str, str]] = {}
    grammar_versions = _grammar_versions(languages)

    sym_id = 0
    sym_lookup: dict[tuple[str, str], int] = {}
    file_imports: list[tuple[str, str]] = []
    pending_edges: list[Edge] = []
    persisted_symbols: list[Symbol] = []

    for src_path, lang in _iter_files(repo_root, languages):
        rel = str(src_path.relative_to(repo_root))
        try:
            text = src_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        loc = text.count("\n") + 1
        h = file_content_hash(src_path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "INSERT OR REPLACE INTO files (path, language, content_hash, loc, pagerank, last_indexed)"
            " VALUES (?,?,?,?,?,?)",
            (rel, lang, h, loc, None, now),
        )
        files_indexed[rel] = {"content_hash": h, "last_indexed": now}

        ex = for_language(lang)
        try:
            result = ex.extract(src_path, source_root=repo_root)
        except Exception:
            result_symbols: list[Symbol] = []
            result_edges: list[Edge] = []
        else:
            result_symbols = result.symbols
            result_edges = result.edges

        for s in result_symbols:
            # Normalise to repo-relative path.
            s_path = Path(s.file_path)
            if s_path.is_absolute():
                try:
                    sym_rel = str(s_path.relative_to(repo_root))
                except ValueError:
                    sym_rel = s.file_path
            else:
                sym_rel = s.file_path

            sym_id += 1
            conn.execute(
                "INSERT INTO symbols"
                " (id, file_path, kind, name, qualified_name, line_start, line_end, signature)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sym_id, sym_rel, s.kind, s.name, s.qualified_name, s.line_start, s.line_end, s.signature),
            )
            sym_lookup[(sym_rel, s.name)] = sym_id
            # Append to mirror only after the INSERT succeeds — if the INSERT
            # contract ever weakens (e.g. INSERT OR IGNORE), the mirror still
            # matches what's actually in graph.db.
            persisted_symbols.append(
                Symbol(
                    file_path=sym_rel,
                    kind=s.kind,
                    name=s.name,
                    qualified_name=s.qualified_name,
                    line_start=s.line_start,
                    line_end=s.line_end,
                    signature=s.signature,
                )
            )

        for e in result_edges:
            src_rel = _rel_path(e.source_file, repo_root)
            tgt_rel = _rel_path(e.target_file, repo_root) if e.target_file else e.target_file
            pending_edges.append(
                Edge(
                    source_file=src_rel,
                    source_name=e.source_name,
                    target_file=tgt_rel,
                    target_name=e.target_name,
                    kind=e.kind,
                    certainty=e.certainty,
                    source_type=e.source_type,
                )
            )
            if e.kind == "import" and tgt_rel:
                file_imports.append((src_rel, tgt_rel))

    # Resolve edges to symbol IDs and persist.
    persisted_edges: list[Edge] = []
    for e in pending_edges:
        src_id = sym_lookup.get((e.source_file, e.source_name))
        tgt_id = sym_lookup.get((e.target_file, e.target_name))
        if src_id is None or tgt_id is None:
            continue
        try:
            conn.execute(
                "INSERT INTO edges (src_symbol, dst_symbol, kind, certainty, source_type) VALUES (?,?,?,?,?)",
                (src_id, tgt_id, e.kind, e.certainty, e.source_type),
            )
            persisted_edges.append(e)
        except sqlite3.IntegrityError:
            pass  # duplicate edge

    # PageRank over file graph.
    file_paths = list(files_indexed.keys())
    pr = compute_pagerank(files=file_paths, import_edges=file_imports)
    for path, score in pr.items():
        conn.execute("UPDATE files SET pagerank = ? WHERE path = ?", (score, path))
    conn.commit()

    # Append-only JSONL mirrors.
    append_symbols(artifact / "symbols.jsonl", persisted_symbols)
    append_edges(artifact / "edges.jsonl", persisted_edges)

    # Manifest.
    manifest = Manifest(
        languages=list(languages),
        grammar_versions=grammar_versions,
        last_built=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        files=files_indexed,
    )
    save_manifest(artifact / "manifest.json", manifest)

    # Render + README.
    render_map_md(conn=conn, out_path=artifact / "MAP.md", map_tokens=map_tokens)
    render_packages(conn=conn, out_dir=artifact / "packages")
    write_readme(artifact / "README.md")


def _rel_path(file_path: str, repo_root: Path) -> str:
    """Return a repo-relative path string from an absolute or already-relative path."""
    p = Path(file_path)
    if p.is_absolute():
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            return file_path
    return file_path


def _iter_files(repo_root: Path, languages: tuple[str, ...]) -> list[tuple[Path, str]]:
    """Walk repo_root and yield (path, language) pairs for each matching source file.

    Skip directories in _SKIP_DIRS and the `.warden/maps` subtree specifically.
    """
    out: list[tuple[Path, str]] = []
    warden_maps = repo_root / ".warden" / "maps"
    for lang in languages:
        exts = _LANG_EXT.get(lang, ())
        for ext in exts:
            for p in repo_root.rglob(f"*{ext}"):
                # Skip the artifact output directory itself.
                try:
                    p.relative_to(warden_maps)
                    continue
                except ValueError:
                    pass
                parts = set(p.relative_to(repo_root).parts)
                if parts & _SKIP_DIRS:
                    continue
                out.append((p, lang))
    return out


def _grammar_versions(languages: tuple[str, ...]) -> dict[str, str]:
    """Return {lang -> tree-sitter package version} for each language.

    `javascript` reuses `tree_sitter_typescript`; fall back to "unknown" on
    any import error.
    """
    out: dict[str, str] = {}
    for lang in languages:
        pkg_name = "tree_sitter_typescript" if lang == "javascript" else f"tree_sitter_{lang}"
        try:
            mod = __import__(pkg_name)
            out[lang] = getattr(mod, "__version__", "unknown")
        except Exception:
            out[lang] = "unknown"
    return out


def run_refresh(*, paths: str | None, json_summary: bool) -> None:
    import fnmatch
    from code_map.manifest import artifact_root

    repo_root = Path.cwd()
    artifact = artifact_root(repo_root)
    manifest_path = artifact / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"no code map at {artifact} — run `code-map build` first")

    manifest = load_manifest(manifest_path)
    languages = tuple(manifest.languages)
    candidates = list(_iter_files(repo_root, languages))
    if paths:
        patterns = [p.strip() for p in paths.split(",") if p.strip()]
        def _matches(p: Path) -> bool:
            rel = str(p.relative_to(repo_root))
            return any(fnmatch.fnmatch(rel, pat) for pat in patterns)
        candidates = [(p, lang) for p, lang in candidates if _matches(p)]

    conn = sqlite3.connect(artifact / "graph.db")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        summary = _refresh_inner(conn, repo_root, manifest, manifest_path, candidates)
    finally:
        conn.close()

    if json_summary:
        print(json.dumps(summary))


def _refresh_inner(conn, repo_root: Path, manifest: Manifest, manifest_path: Path, candidates: list) -> dict:
    parsed = 0
    skipped = 0
    edges_added = 0
    edges_removed = 0
    pagerank_recomputed = False
    start = time.time()

    for src_path, lang in candidates:
        rel = str(src_path.relative_to(repo_root))
        h = file_content_hash(src_path)
        cached = manifest.files.get(rel, {}).get("content_hash")
        if cached == h:
            skipped += 1
            continue
        parsed += 1
        # CASCADE deletes edges on EITHER side, so count both.
        old_out = conn.execute(
            "SELECT COUNT(*) FROM edges e JOIN symbols s ON e.src_symbol = s.id WHERE s.file_path = ?",
            (rel,),
        ).fetchone()[0]
        old_in = conn.execute(
            "SELECT COUNT(*) FROM edges e JOIN symbols s ON e.dst_symbol = s.id"
            " WHERE s.file_path = ? AND e.src_symbol NOT IN (SELECT id FROM symbols WHERE file_path = ?)",
            (rel, rel),
        ).fetchone()[0]
        conn.execute("DELETE FROM symbols WHERE file_path = ?", (rel,))
        edges_removed += old_out + old_in

        text = src_path.read_text(encoding="utf-8", errors="replace")
        loc = text.count("\n") + 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "INSERT OR REPLACE INTO files (path, language, content_hash, loc, pagerank, last_indexed)"
            " VALUES (?,?,?,?,COALESCE((SELECT pagerank FROM files WHERE path=?),0.0),?)",
            (rel, lang, h, loc, rel, now),
        )
        manifest.files[rel] = {"content_hash": h, "last_indexed": now}

        ex = for_language(lang)
        try:
            result = ex.extract(src_path, source_root=repo_root)
        except Exception:
            # Mid-edit / malformed file — skip extraction this turn rather than
            # aborting the entire refresh.
            continue

        sym_lookup_local: dict[tuple[str, str], int] = {}
        for s in result.symbols:
            sym_rel = _rel_path(s.file_path, repo_root) if s.file_path else rel
            cur = conn.execute(
                "INSERT INTO symbols (file_path, kind, name, qualified_name, line_start, line_end, signature)"
                " VALUES (?,?,?,?,?,?,?)",
                (sym_rel, s.kind, s.name, s.qualified_name, s.line_start, s.line_end, s.signature),
            )
            assert cur.lastrowid is not None  # INTEGER PRIMARY KEY always sets lastrowid
            sym_lookup_local[(sym_rel, s.name)] = cur.lastrowid

        for e in result.edges:
            src_rel = _rel_path(e.source_file, repo_root)
            tgt_rel = _rel_path(e.target_file, repo_root) if e.target_file else e.target_file
            src_id = sym_lookup_local.get((src_rel, e.source_name)) or _lookup_sym(conn, src_rel, e.source_name)
            tgt_id = _lookup_sym(conn, tgt_rel, e.target_name)
            if not (src_id and tgt_id):
                continue
            try:
                conn.execute(
                    "INSERT INTO edges (src_symbol, dst_symbol, kind, certainty, source_type) VALUES (?,?,?,?,?)",
                    (src_id, tgt_id, e.kind, e.certainty, e.source_type),
                )
                edges_added += 1
            except sqlite3.IntegrityError:
                pass

    if parsed > 0:
        files = [r[0] for r in conn.execute("SELECT path FROM files")]
        imports = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT s_src.file_path, s_dst.file_path FROM edges e"
                " JOIN symbols s_src ON e.src_symbol = s_src.id"
                " JOIN symbols s_dst ON e.dst_symbol = s_dst.id"
                " WHERE e.kind = 'import'"
            )
        ]
        pr = compute_pagerank(files=files, import_edges=imports)
        for path, score in pr.items():
            conn.execute("UPDATE files SET pagerank = ? WHERE path = ?", (score, path))
        pagerank_recomputed = True

    conn.commit()
    manifest.last_built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_manifest(manifest_path, manifest)

    return {
        "parsed_files": parsed,
        "skipped_files": skipped,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
        "pagerank_recomputed": pagerank_recomputed,
        "elapsed_ms": int((time.time() - start) * 1000),
    }


def _lookup_sym(conn: sqlite3.Connection, file_path: str | None, name: str) -> int | None:
    if not file_path:
        return None
    row = conn.execute(
        "SELECT id FROM symbols WHERE file_path = ? AND name = ?", (file_path, name)
    ).fetchone()
    return row[0] if row else None
