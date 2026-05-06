import json
from pathlib import Path

from code_map.manifest import (
    Manifest,
    derive_repo_slug,
    file_content_hash,
    load_manifest,
    save_manifest,
)


def test_repo_slug_collapses_non_alnum():
    assert derive_repo_slug(Path("/home/eastill/projects/warden")) == "warden"
    assert derive_repo_slug(Path("/tmp/My Project!")) == "my-project"


def test_file_content_hash_is_sha256_hex(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("hello\n")
    h = file_content_hash(p)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_save_and_load_manifest_roundtrip(tmp_path: Path):
    m = Manifest(
        languages=["python", "typescript", "rust"],
        grammar_versions={"python": "0.23.0", "typescript": "0.23.0", "rust": "0.23.0"},
        last_built="2026-05-06T12:00:00Z",
        files={"a.py": {"content_hash": "abc", "last_indexed": "2026-05-06T12:00:00Z"}},
    )
    out = tmp_path / "manifest.json"
    save_manifest(out, m)
    raw = json.loads(out.read_text())
    assert set(raw.keys()) == {"languages", "grammar_versions", "last_built", "files"}
    loaded = load_manifest(out)
    assert loaded == m
