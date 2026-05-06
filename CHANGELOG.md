# Changelog

All notable changes to `code-map` will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.3.0] — 2026-05-06

Surfaced by dogfooding v0.2.1 on a 276-file polyglot repo (warden). All five
fixes are extractor / runner correctness — no schema or CLI surface change.

### Fixed

- **Refresh now garbage-collects rows for files deleted from disk.** Prior to
  this release, deleting a file left orphaned `files` / `symbols` / `edges`
  rows behind, and `code-map status` reported `stale: true` permanently
  (`files_missing_since_build` never dropped). `refresh` now diffs the manifest
  against the current walk and removes stale rows; the JSON summary gains a
  new `files_removed` field.
- **`inherits` and `implements` edges are now emitted.** v0.2.x DBs contained
  only `calls` edges (1382/1382 on warden) — the schema declared 5 kinds but
  4 of them were unimplemented. Now:
  - **Python**: `class Child(Parent):` → `Child --inherits--> Parent`.
    Multiple bases supported. Dotted bases (`pkg.Base`) resolve by rightmost
    name.
  - **TypeScript**: `class C extends B implements I, J { … }` →
    one `inherits` and N `implements` edges. Interfaces are now indexed as
    symbols (kind=class) so they resolve as edge targets.
  - **Rust**: `impl Trait for Type { … }` → `Type --implements--> Trait`.
    Inherent impls (`impl Type { … }`) emit no edge.
  Cross-file resolution is name-only and demoted to `certainty=probable`;
  ambiguous matches are dropped rather than guessed.
- **Python method extraction undercount.** v0.2.x emitted ~1 method per ~6
  classes (12 / 69 on warden) because `function_definition` captures fired
  before `method_definition`, then the `(name, line_start)` dedup dropped
  the method capture. Method captures now process first; methods correctly
  carry `kind=method` and `qualified_name=<module>.<Class>.<method>`.
- **Python import resolution for nested-package layouts.** The flat-only
  resolver missed `from warden import plan_exec` against
  `core/tools/python/src/warden/plan_exec.py`. Three-strategy resolver
  added: flat → `src/`-style → unique basename match across the repo
  (skip-dirs respected). Ambiguous matches still drop.
- **Submodule from-imports resolve.** `from pkg.sub import mod` where
  `pkg/sub/mod.py` is a submodule now emits a module-level edge to
  `mod.py` instead of a name-import to `__init__.py` that would never
  resolve.
- **PageRank degeneracy.** v0.2.x DBs had every file at `pagerank=1.0`
  because no import edges were extracted (resolver miss + `<module>`
  symbols not synthesized). With imports actually landing in the DB,
  PageRank now distinguishes hub files from leaf files.

### Added

- **Synthetic `<module>` symbol per file** — needed so module-level edges
  (`import os`, submodule imports, wildcard imports) can resolve to a
  symbol ID rather than being silently dropped at persistence time.
- **`code-map find --kind module`** now works as a side-effect.

### Changed

- **`callers-of` / `callees-of` / `blast-radius` now include `inherits` and
  `implements` edges**, not only `calls` / `references`. Previously asking
  "what depends on `BaseNode`?" returned `[]` even when 5 subclasses inherited
  from it, because the type-relationship edges were excluded from the
  dependency view. Static-analysis dependents are dependents — the verbs now
  treat them uniformly.
- **Default skip-dirs expanded** to cover `dist`, `build`, `venv`, `.env`,
  `.warden`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`,
  `.next`, `.nuxt`, `.hg`, `.svn`. The `.warden/maps` special-case is
  gone (subsumed by `.warden`). Test fixtures, vendored caches, and
  build outputs no longer leak into the index.

### Tests

- 9 new tests in `tests/test_v03_fixes.py` covering each bug end-to-end
  (build → assert).
- Pre-existing perf-gate test fixed (it read stdout but `# query_ms:`
  has been on stderr since v0.2.0).
- Suite now: 62 tests, all passing.

## [v0.2.1] — 2026-05-06

### Changed

- `code-map query 'blast-radius <sym>' --depth` default lowered from 5 to 3.
  Per RepoGraph (ICLR 2025): 1-hop ego-graphs already contain comprehensive
  information; 2-hop expansion costs ~5× tokens for worse downstream resolve
  rate. `--depth 5+` is still available; the new default just stops surprising
  agents with context bloat.
- `--map-tokens` now accepts presets: `small` (1 500), `medium` (4 000,
  default — same as before), `full` (effectively uncapped), or any integer.

### Notes

- No new subcommands or breaking schema changes. CLI surface count stays at 10.

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
