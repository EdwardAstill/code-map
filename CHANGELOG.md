# Changelog

All notable changes to `code-map` will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.2.0] — 2026-05-06

### Added

- `code-map find <pattern>` — substring / glob symbol search across `name` and
  `qualified_name`. `--kind` filter, `--limit`, `--format json|markdown`.
- `code-map source <symbol>` — fetch the source lines for a symbol; `--format
  markdown` wraps in a fenced block with the right language tag.
- `code-map outline <file>` — tree-style outline with class > method nesting;
  formats: text (tree), markdown (heading hierarchy), json (nested objects).
- `code-map context <file>:<line>` — reverse lookup; returns the symbol
  containing the given line. Useful for stack-trace and bug-report parsing.
- `code-map status [--fail-on-stale]` — JSON freshness report:
  `{artifact_dir, built_at, languages, files_total, files_changed_since_build,
  files_missing_since_build, stale}`. `--fail-on-stale` exits 4 if stale.
- `code-map schema` — emits the JSON Schema 2020-12 describing the artifact
  contract (edges, symbols, manifest, query result rows, exit codes,
  subcommands).
- `--format json|markdown` flag on every query subcommand.
- `--limit N` flag on every query subcommand (default 50, capped at 100 unless
  `--no-limit`).
- Symbol globbing (`*`, `?`) on `callers-of`, `callees-of`, `blast-radius`,
  `defined-in`. Translates to SQL `LIKE` with proper escaping.
- `score: float` column on every query result row (PageRank for callers/callees;
  PageRank ÷ (1 + depth) for blast-radius). Results are score-desc ordered.
- Distinct exit codes documented in README and emitted by every read-only
  subcommand: 0 ok, 2 no artifact, 3 not found, 4 stale.
- GitHub Actions CI: ruff + pytest on push.

### Changed

- `code-map query` and friends now write the `# query_ms:` line to **stderr**
  instead of stdout, so `stdout` is strictly machine-parseable JSON.
- README expanded with concrete output examples, Claude Code integration recipe,
  and a comparison table vs aider repo-map / SCIP / universal-ctags.

### Validation

Driven by 2026-05-06 research into what AI coding agents actually consume from
codebase indexes (see `EdwardAstill/warden:.warden/research/2026-05-06-code-map-feature-validation/REPORT.md`).
The v0.2.0 surface is the minimum + sufficient set for an agent that shells out
— nothing more, nothing less.

Explicitly **not** added (failed the "agents demonstrably consume this" test):
MCP server, daemon, LSP, embeddings, per-symbol doc-strings, parsed type AST,
visibility flags, def/decl/impl distinction, test↔code links, side-effect
annotations, cross-language edges, macro expansion.

## [v0.1.0] — 2026-05-06

### Added

- Initial release. Extracted from [`EdwardAstill/warden`](https://github.com/EdwardAstill/warden)
  where the implementation, spec, and review history were originally developed.
- Tree-sitter based extraction for Python, TypeScript / JavaScript, Rust.
- SQLite (`graph.db`) source of truth + JSONL mirrors + manifest.json
  (content-hash cache) + token-budgeted MAP.md (PageRank-ordered).
- Subcommands: `build`, `refresh`, `query` (`callers-of` / `callees-of` /
  `blast-radius` / `defined-in`), `render`.
- Edges carry `certainty ∈ {definite, probable, speculative}` and
  `source_type ∈ {direct, dynamic_dispatch, reflection, callback, plugin}` —
  honest about static-analysis blind spots.
- Auto-detection of Warden-managed repos: artifact lives at
  `.warden/maps/<repo-slug>/` if `.warden/` exists, else `.code-map/`.
- 30 unit tests covering extractors, schema, mirrors, manifest, render,
  refresh-incremental, build-e2e, query golden files, and CLI smoke.
