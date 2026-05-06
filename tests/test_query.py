"""Golden-file tests for `code-map query`.

The fixture repo (sample-poly) has Rust sources where a::main_a calls b::greet
(a definite call edge). The Python extractor only emits cross-file *import*
edges, not call edges, so `callers-of b.greet` returns []. We use Rust here
where a definite call edge exists.
"""
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"
GOLDEN = Path(__file__).resolve().parent / "golden"
CODE_MAP_BIN = PROJECT_ROOT / ".venv" / "bin" / "code-map"


def _build(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    subprocess.check_call(
        [str(CODE_MAP_BIN), "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )
    return repo


def _query(repo: Path, expr: str, *extra: str) -> list[dict]:
    out = subprocess.check_output(
        [str(CODE_MAP_BIN), "query", expr, *extra],
        cwd=str(repo),
        text=True,
    )
    # Strip the trailing `# query_ms: ...` line before parsing JSON
    json_lines = [line for line in out.splitlines() if not line.startswith("# ")]
    return json.loads("\n".join(json_lines))


def _strip_volatile(rows: list[dict]) -> list[dict]:
    keep = ("qualified_name", "name", "kind", "depth")
    return sorted(
        ({k: r[k] for k in keep if k in r} for r in rows),
        key=lambda r: (r.get("depth", 0), r.get("qualified_name", "")),
    )


def test_callers_of_greet_matches_golden(tmp_path: Path):
    """callers-of b::greet (Rust) — expects a::main_a from the definite call edge."""
    repo = _build(tmp_path)
    rows = _query(repo, "callers-of b::greet")
    expected = json.loads((GOLDEN / "callers-of-greet.json").read_text())
    assert _strip_volatile(rows) == _strip_volatile(expected)


def test_blast_radius_greet_matches_golden(tmp_path: Path):
    """blast-radius b::greet (Rust) --depth 3 — expects a::main_a at depth 1."""
    repo = _build(tmp_path)
    rows = _query(repo, "blast-radius b::greet", "--depth", "3")
    expected = json.loads((GOLDEN / "blast-radius-greet.json").read_text())
    assert _strip_volatile(rows) == _strip_volatile(expected)
