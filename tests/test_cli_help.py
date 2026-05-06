import subprocess
from pathlib import Path

# test_cli_help.py -> tests -> code-map (project root)
PROJECT_ROOT = Path(__file__).parents[1]


def test_code_map_help_lists_subcommands():
    result = subprocess.run(
        ["uv", "run", "--directory", str(PROJECT_ROOT), "code-map", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for sub in ("build", "refresh", "query", "render"):
        assert sub in out, f"subcommand {sub!r} missing from --help output"
