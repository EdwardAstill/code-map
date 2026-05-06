"""End-to-end test for `code-map build` on the polyglot fixture."""
import json
import sqlite3
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"


def _run_build(repo: Path) -> int:
    return subprocess.call(
        ["uv", "run", "--directory", str(PROJECT_ROOT), "code-map", "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )


def test_build_emits_full_artifact(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # copy the polyglot fixture into a clean repo dir so the artifact is local
    for child in FIXTURE_REPO.rglob("*"):
        if child.is_file():
            dst = repo / child.relative_to(FIXTURE_REPO)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(child.read_bytes())

    start = time.time()
    rc = _run_build(repo)
    elapsed = time.time() - start
    assert rc == 0, f"build exited with code {rc}"
    assert elapsed < 10.0, f"build took {elapsed:.2f}s"

    # Standalone tool default: .code-map/ (no .warden/ in fixture).
    art = repo / ".code-map"
    for f in ("graph.db", "MAP.md", "manifest.json", "edges.jsonl", "symbols.jsonl", "README.md"):
        assert (art / f).exists(), f"missing artifact file: {f}"
    assert any((art / "packages").iterdir()), "packages/ directory is empty"

    conn = sqlite3.connect(art / "graph.db")
    sym_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert sym_count > 0, "symbols table is empty"
    conn.close()

    manifest = json.loads((art / "manifest.json").read_text())
    assert set(manifest.keys()) == {"languages", "grammar_versions", "last_built", "files"}, (
        f"unexpected manifest keys: {set(manifest.keys())}"
    )

    edges_text = (art / "edges.jsonl").read_text().strip()
    if edges_text:
        for line in edges_text.splitlines():
            obj = json.loads(line)
            assert obj["kind"] in ("import", "calls", "inherits", "implements", "references"), (
                f"invalid edge kind: {obj['kind']!r}"
            )
            assert obj["certainty"] in ("definite", "probable", "speculative"), (
                f"invalid certainty: {obj['certainty']!r}"
            )
            assert obj["source_type"] in ("direct", "dynamic_dispatch", "reflection", "callback", "plugin"), (
                f"invalid source_type: {obj['source_type']!r}"
            )
