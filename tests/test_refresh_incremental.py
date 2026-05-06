"""Incremental refresh tests: verify content-hash cache skips unchanged files."""
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    return repo


def test_refresh_with_no_changes_reports_zero_parsed(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    subprocess.check_call(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )
    out = subprocess.check_output(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "refresh", "--json"],
        cwd=str(repo),
        text=True,
    )
    summary = json.loads(out)
    assert summary["parsed_files"] == 0
    assert summary["skipped_files"] > 0


def test_refresh_after_edit_parses_only_changed_file(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    subprocess.check_call(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )
    (repo / "python/c.py").write_text("def shout(text):\n    return text + '!'\n")
    out = subprocess.check_output(
        ["uv", "run", "--project", str(PROJECT_ROOT), "code-map", "refresh", "--json"],
        cwd=str(repo),
        text=True,
    )
    summary = json.loads(out)
    assert summary["parsed_files"] == 1
    assert summary["skipped_files"] >= 1
