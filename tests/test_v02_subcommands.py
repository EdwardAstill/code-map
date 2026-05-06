"""End-to-end tests for the v0.2.0 subcommands: find, source, outline, context, status, schema.

Each test seeds a clean copy of the polyglot fixture, runs build, then exercises
the subcommand via the installed `code-map` binary.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"
CODE_MAP_BIN = PROJECT_ROOT / ".venv" / "bin" / "code-map"


@pytest.fixture
def built_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    subprocess.check_call(
        [str(CODE_MAP_BIN), "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(CODE_MAP_BIN), *args],
        cwd=str(repo), text=True, capture_output=True,
    )


# ── find ─────────────────────────────────────────────────────────────────────


def test_find_substring_match(built_repo: Path):
    r = _run(built_repo, "find", "greet")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) >= 1
    assert all("greet" in (row["name"] + row["qualified_name"]).lower() for row in rows)
    assert all("score" in row for row in rows)


def test_find_glob_match(built_repo: Path):
    r = _run(built_repo, "find", "b::*")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert all(row["qualified_name"].startswith("b::") for row in rows)


def test_find_markdown_format(built_repo: Path):
    r = _run(built_repo, "find", "greet", "--format", "markdown")
    assert r.returncode == 0, r.stderr
    assert "### `find" in r.stdout
    assert "greet" in r.stdout


def test_find_kind_filter(built_repo: Path):
    r = _run(built_repo, "find", "greet", "--kind", "function")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert all(row["kind"] == "function" for row in rows)


def test_find_limit(built_repo: Path):
    r = _run(built_repo, "find", "*", "--limit", "2")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) <= 2


# ── source ───────────────────────────────────────────────────────────────────


def test_source_returns_text(built_repo: Path):
    r = _run(built_repo, "source", "b::greet")
    assert r.returncode == 0, r.stderr
    assert "pub fn greet" in r.stdout


def test_source_markdown_fenced(built_repo: Path):
    r = _run(built_repo, "source", "b::greet", "--format", "markdown")
    assert r.returncode == 0, r.stderr
    assert "```rust" in r.stdout
    assert "### `b::greet`" in r.stdout
    assert "```" in r.stdout.replace("```rust", "")


def test_source_unknown_symbol_exits_3(built_repo: Path):
    r = _run(built_repo, "source", "definitely_not_a_real_symbol")
    assert r.returncode == 3
    assert "not found" in r.stderr.lower()


# ── outline ──────────────────────────────────────────────────────────────────


def test_outline_text_tree(built_repo: Path):
    r = _run(built_repo, "outline", "python/b.py")
    assert r.returncode == 0, r.stderr
    assert "python/b.py" in r.stdout
    assert "[function]" in r.stdout or "[class]" in r.stdout
    assert "greet" in r.stdout


def test_outline_json(built_repo: Path):
    r = _run(built_repo, "outline", "python/b.py", "--format", "json")
    assert r.returncode == 0, r.stderr
    nodes = json.loads(r.stdout)
    assert isinstance(nodes, list) and len(nodes) >= 1
    assert all("children" in n for n in nodes)


def test_outline_unknown_file_exits_3(built_repo: Path):
    r = _run(built_repo, "outline", "no/such/file.py")
    assert r.returncode == 3


# ── context ──────────────────────────────────────────────────────────────────


def test_context_finds_containing_symbol(built_repo: Path):
    r = _run(built_repo, "context", "python/b.py:5")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert rows
    assert rows[0]["name"] == "greet"


def test_context_unknown_location_exits_3(built_repo: Path):
    r = _run(built_repo, "context", "python/b.py:9999")
    assert r.returncode == 3


# ── status ───────────────────────────────────────────────────────────────────


def test_status_fresh(built_repo: Path):
    r = _run(built_repo, "status")
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert set(info.keys()) >= {"artifact_dir", "built_at", "languages", "files_total", "files_changed_since_build", "stale"}
    assert info["stale"] is False


def test_status_stale_after_edit(built_repo: Path):
    (built_repo / "python" / "c.py").write_text("def shout(t): return t + '!'\n")
    r = _run(built_repo, "status")
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert info["stale"] is True
    assert info["files_changed_since_build"] >= 1


def test_status_fail_on_stale_exits_4(built_repo: Path):
    (built_repo / "python" / "c.py").write_text("def shout(t): return t + '!'\n")
    r = _run(built_repo, "status", "--fail-on-stale")
    assert r.returncode == 4


def test_status_no_artifact_exits_2(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty, "status")
    assert r.returncode == 2
    assert "no code map" in r.stderr


# ── schema ───────────────────────────────────────────────────────────────────


def test_schema_emits_valid_json_schema(built_repo: Path):
    r = _run(built_repo, "schema")
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert "$schema" in doc and "draft/2020-12" in doc["$schema"]
    assert "$defs" in doc
    for required_def in ("Symbol", "Edge", "Manifest"):
        assert required_def in doc["$defs"], f"missing $def: {required_def}"


# ── ranked + globbed query (regressions on existing query) ───────────────────


def test_query_results_carry_score(built_repo: Path):
    r = _run(built_repo, "query", "callers-of b::greet")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert all("score" in row for row in rows)


def test_query_glob_callers_of(built_repo: Path):
    r = _run(built_repo, "query", "callers-of b::*")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert isinstance(rows, list)
    assert all("score" in row for row in rows)


def test_query_markdown_format(built_repo: Path):
    r = _run(built_repo, "query", "callers-of b::greet", "--format", "markdown")
    assert r.returncode == 0, r.stderr
    assert "### `callers-of b::greet`" in r.stdout


def test_query_limit(built_repo: Path):
    r = _run(built_repo, "query", "callers-of b::*", "--limit", "1")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) <= 1
