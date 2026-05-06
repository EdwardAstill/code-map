# Contributing to code-map

Thanks for the interest. This is a small, tightly-scoped tool — please read
the scope rules below before opening an issue or PR.

## Scope rules (what `code-map` is and is not)

`code-map` is the **structural** half of an AI-agent code-context toolkit. It
ships nothing more, nothing less than what real LLM agents demonstrably
consume in 2026 (see the validation research linked from the README).

**In scope:**

- Better tree-sitter coverage on tier-1 languages.
- New tier-1 languages where tree-sitter has a maintained grammar (Go, Java,
  C/C++, Ruby — open an issue first).
- CLI ergonomics (better error messages, more output formats, glob patterns,
  exit-code refinements).
- Performance on large repos.
- Honesty: better classification of edge `certainty` and `source_type`.

**Out of scope (will be closed):**

- MCP server. Agents that need MCP can wrap the CLI; the CLI stays the source
  of truth.
- Daemon / LSP server.
- Embeddings or vector search. (Different artifact; pair with a separate
  embedding index if you need both.)
- Per-symbol doc-strings.
- Parsed type AST (textual signatures stay).
- Visibility flags (`pub` / `private` / `export`).
- def-vs-decl-vs-impl distinction.
- Test↔code links.
- Side-effect / mutation annotations.
- Cross-language edges (Python → Rust extension etc.).
- Macro expansion.

If you have a use case that requires one of the above, the pattern is to
ship a sibling tool that consumes `code-map`'s artifact and adds the layer
you need.

## Development

```bash
git clone https://github.com/EdwardAstill/code-map
cd code-map
uv sync
uv run pytest tests/ --ignore=tests/test_query_perf.py
uv tool run ruff check src/ tests/
uv tool run ruff format src/ tests/
```

The slow `tests/test_query_perf.py` builds the project itself as a perf
fixture; run it explicitly with `uv run pytest tests/test_query_perf.py -v -m slow`.

## PR conventions

- One feature per PR.
- New subcommand → new module under `src/code_map/<name>.py`, wire into
  `cli.py`, add tests in `tests/test_v0X_subcommands.py`.
- New edge `kind` or `source_type` enum value → update `schema.py` constants
  AND `schema_cmd.py`'s `ARTIFACT_SCHEMA` AND README's honesty contract.
- Failing tests are not "to be fixed in a follow-up". Either pass or skip with
  a documented reason.

## Releasing

1. Bump `version` in `pyproject.toml`.
2. Add a `CHANGELOG.md` entry under `## [vX.Y.Z]` with date.
3. Commit, tag `vX.Y.Z`, push tag.
4. CI runs on tag; release artifacts are not auto-built (no PyPI publish yet).
