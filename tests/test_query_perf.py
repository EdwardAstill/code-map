"""Perf gate: blast-radius SQL must complete in <100 ms on a real-world repo.

This test builds the standalone `code-map` repo itself as the perf fixture
(small, but exercises real codebase scale at thousands of symbols once
combined with `.venv` if not gitignored — see fixture-shape note below).
For genuine 50 kLOC perf gating, point this at a larger repo via the
CODE_MAP_PERF_REPO environment variable.
"""
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_MAP_BIN = PROJECT_ROOT / ".venv" / "bin" / "code-map"


@pytest.mark.slow
def test_blast_radius_under_100ms(tmp_path: Path):
    """Verify blast-radius SQL is <100 ms wall-clock-excluded.

    The CLI prints `# query_ms: <n>` from an in-process perf_counter; we
    parse that line and assert it is <100 ms. `uv run` cold-start dominates
    wall-clock and is not the quantity under test.
    """
    perf_repo = Path(os.environ.get("CODE_MAP_PERF_REPO", PROJECT_ROOT))
    subprocess.check_call(
        [str(CODE_MAP_BIN), "build", "--repo", str(perf_repo)],
        cwd=str(PROJECT_ROOT),
    )
    # Pick a known-defined symbol from the standalone tool itself.
    target = "runner.run_build"
    out = subprocess.check_output(
        [str(CODE_MAP_BIN), "query", f"blast-radius {target}", "--depth", "3"],
        cwd=str(perf_repo),
        text=True,
    )
    line = next((l for l in out.splitlines() if l.startswith("# query_ms:")), None)
    assert line is not None, f"code-map did not emit a `# query_ms:` line. stdout was:\n{out}"
    query_ms = float(line.split(":", 1)[1].strip())
    assert query_ms < 100.0, f"blast-radius SQL took {query_ms:.2f}ms (>100ms gate)"
