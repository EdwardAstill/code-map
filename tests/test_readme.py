from pathlib import Path

from code_map.readme import write_readme


def test_readme_lists_required_blind_spots(tmp_path: Path):
    out = tmp_path / "README.md"
    write_readme(out)
    body = out.read_text()
    assert "blind spots" in body
    for token in ("getattr", "eval", "dynamic import", "dyn Trait", "dependency injection"):
        assert token in body, f"README missing required blind-spot token: {token}"


def test_readme_includes_query_examples(tmp_path: Path):
    out = tmp_path / "README.md"
    write_readme(out)
    body = out.read_text()
    for cmd in ("callers-of", "callees-of", "blast-radius", "defined-in"):
        assert cmd in body
    assert "graph.db" in body and "edges.jsonl" in body
