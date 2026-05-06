"""Writer for the in-artifact README.md (LLM cold-load instructions)."""
from __future__ import annotations

from pathlib import Path

README_BODY = """# Code Map Artifact

This directory holds the AI-consumable code map for the surrounding repo.

## Files

- `graph.db` — SQLite source of truth. Tables: `files`, `symbols`, `edges`. See spec §4.
- `edges.jsonl`, `symbols.jsonl` — append-only JSONL mirrors. One JSON object per line.
- `MAP.md` — token-budgeted overview ordered by file PageRank.
- `packages/*.md` — per-directory symbol lists.
- `manifest.json` — languages indexed, grammar versions, last-built timestamp, content-hash cache.

## Querying

```bash
warden code-map query "callers-of <symbol>"
warden code-map query "callees-of <symbol>"
warden code-map query "blast-radius <symbol> --depth 5"
warden code-map query "defined-in <file>"
```

For ad-hoc SQL: `sqlite3 graph.db "SELECT ... FROM edges JOIN symbols ..."`.

Edges carry `certainty` (`definite | probable | speculative`) and `source_type`
(`direct | dynamic_dispatch | reflection | callback | plugin`). Filter by
these when an analysis must be conservative.

## Static analysis blind spots

Edges are only as accurate as static analysis allows. The following are not
fully resolved by the current backbone (tree-sitter):

- Python: `getattr`, `setattr`, `__import__`, `eval`, `exec`.
- JavaScript / TypeScript: `eval`, dynamic import (`import()`), `Reflect.*`.
- Async chains: `.then(callback)` breaks the call edge at the Promise boundary.
- Rust: trait dispatch on `dyn Trait` is flagged `probable`, not `definite`.
- Frameworks using dependency injection: containers are not introspected.
- Plugin systems / dynamic loading: only emitted as `speculative` edges when a concrete candidate exists.
- Macro-expanded code (Rust `macro_rules!`) is parsed but not expanded.

When in doubt, treat `probable` and `speculative` edges as approximations.
"""


def write_readme(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(README_BODY)
