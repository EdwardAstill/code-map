"""End-to-end CLI test for `code-map render` subcommand."""
import shutil
import subprocess
from pathlib import Path

import tiktoken

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = Path(__file__).resolve().parent / "fixtures" / "sample-poly"


def test_render_subcommand_rewrites_map_md(tmp_path: Path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, repo)
    subprocess.check_call(
        ["uv", "run", "--directory", str(PROJECT_ROOT), "code-map", "build", "--repo", str(repo)],
        cwd=str(PROJECT_ROOT),
    )
    map_path = repo / ".code-map" / "MAP.md"
    map_path.unlink()
    subprocess.check_call(
        ["uv", "run", "--directory", str(PROJECT_ROOT), "code-map", "render", "--repo", str(repo), "--map-tokens", "300"],
        cwd=str(PROJECT_ROOT),
    )
    text = map_path.read_text()
    encoder = tiktoken.get_encoding("cl100k_base")
    assert len(encoder.encode(text)) <= 300
