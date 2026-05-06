# code-map

[![CI](https://github.com/EdwardAstill/code-map/actions/workflows/ci.yml/badge.svg)](https://github.com/EdwardAstill/code-map/actions/workflows/ci.yml)

AI-consumable code-map artifact for polyglot repos. Produces a durable
`.code-map/` directory holding a SQLite call/import graph, JSONL mirrors, and a
token-budgeted Markdown overview. Designed for LLM agents that need to answer
**"how does this codebase link together?"** or **"what is the blast radius of
symbol X?"** without re-reading every source file.

CLI-only — every primitive is one shell command. Pipe-friendly, JSON or markdown
output, distinct exit codes. No daemon, no MCP, no embeddings.

## Languages

Tier-1 (v0.2.0): Python, TypeScript / JavaScript, Rust — all via tree-sitter.

## Install

```bash
uv tool install git+https://github.com/EdwardAstill/code-map
```

Or as a project dependency:

```bash
uv add git+https://github.com/EdwardAstill/code-map
```

## Quick start

```bash
cd ~/your/repo
code-map build
code-map find parse_args             # fuzzy search by name
code-map source parser.parse_args    # source code for a symbol
code-map query 'callers-of parser.parse_args'
code-map outline src/parser.py       # tree outline of a file
code-map status                      # is the index stale?
```

## Subcommand reference

| Command | What it does |
|---|---|
| `code-map build` | Walk the repo, parse via tree-sitter, write the artifact. |
| `code-map refresh [--json]` | Content-hash-gated incremental rebuild. `--json` emits a run summary. |
| `code-map render` | Re-derive `MAP.md` and `packages/*.md` from `graph.db`. |
| `code-map find <pattern>` | Substring or glob search across `name` and `qualified_name`. Add `--kind function` to filter. |
| `code-map source <symbol>` | Print the source lines for a symbol. `--format markdown` wraps in a fenced block. |
| `code-map outline <file>` | Tree-style outline (class > method nesting). Formats: `text` (default), `markdown`, `json`. |
| `code-map context <file>:<line>` | Reverse lookup: which symbol contains this line? Use after parsing a stack trace. |
| `code-map query <expr>` | `callers-of <sym>` · `callees-of <sym>` · `blast-radius <sym> --depth N` · `defined-in <file>`. Symbol globs (`*`, `?`) honoured. Results carry a PageRank-derived `score`. |
| `code-map status [--fail-on-stale]` | `{built_at, files_total, files_changed_since_build, stale}`. Exit 4 if stale and `--fail-on-stale`. |
| `code-map schema` | Emit JSON Schema 2020-12 for the artifact contract. |

Every query subcommand accepts:
- `--format json|markdown` — JSON for parsing, markdown for prompt-paste.
- `--limit N` — capped at 100 unless `--no-limit`. Default 50.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | no artifact — run `code-map build` first |
| 3 | symbol or file not found |
| 4 | artifact stale (only from `status --fail-on-stale`) |

## Examples

### `code-map find` — fuzzy symbol search

```console
$ code-map find greet
[
  {
    "qualified_name": "b::greet",
    "name": "greet",
    "kind": "function",
    "file_path": "rust/src/b.rs",
    "line_start": 1,
    "line_end": 3,
    "score": 0.1907
  },
  {
    "qualified_name": "b.greet",
    "name": "greet",
    "kind": "function",
    "file_path": "python/b.py",
    "line_start": 5,
    "line_end": 6,
    "score": 0.1031
  }
]
```

### `code-map source` — fetch symbol source

```console
$ code-map source b::greet --format markdown
### `b::greet` _function_ — `rust/src/b.rs:1-3`

​```rust
pub fn greet(name: &str) -> String {
    format!("hello {name}")
}
​```
```

### `code-map outline` — file tree

```console
$ code-map outline python/b.py
python/b.py
├── [function] greet  L5-6 def greet(name)
└── [class] Greeter  L8-15
    ├── [method] __init__  L9-11
    └── [method] greet  L12-15
```

### `code-map query` — call-graph queries

```console
$ code-map query 'blast-radius b::greet' --depth 3 --format markdown
### `blast-radius b::greet` (1 result)

- `a::main_a` _function_ · depth=1 · score=0.1031
```

### `code-map status` — freshness check

```console
$ code-map status
{
  "artifact_dir": "/home/me/repo/.code-map",
  "built_at": "2026-05-06T12:34:56+00:00",
  "languages": ["python", "typescript", "rust"],
  "files_total": 8,
  "files_changed_since_build": 0,
  "files_missing_since_build": 0,
  "stale": false
}
```

## Artifact layout

```
.code-map/                    # or .warden/maps/<slug>/ if the repo is Warden-managed
├── README.md       # cold-load instructions for any agent that opens the dir
├── MAP.md          # token-budgeted overview ordered by PageRank
├── manifest.json   # languages, grammar versions, last-built timestamp, file→hash cache
├── graph.db        # SQLite source of truth (files, symbols, edges)
├── edges.jsonl     # one edge per line; grep-friendly; jq -c .
├── symbols.jsonl   # one symbol per line; grep-friendly; jq -c .
└── packages/
    └── <pkg>.md    # per-directory symbol list
```

Edges carry `certainty` (`definite | probable | speculative`) and
`source_type` (`direct | dynamic_dispatch | reflection | callback | plugin`)
so consumers can filter by confidence — e.g. a refactor tool ignores
`speculative`; an exhaustive impact analysis includes them with a caveat.

For the full machine-readable contract:

```bash
code-map schema | jq .
```

## Honesty contract

The current backbone (tree-sitter + heuristics) does **not** resolve:

- Python `getattr` / `setattr` / `__import__` / `eval` / `exec`
- JS / TS `eval`, dynamic `import()`, `Reflect.*`
- Async chains: `.then(callback)` breaks the call edge at the Promise boundary
- Rust trait dispatch on `dyn Trait` — flagged `probable`, not `definite`
- Dependency-injection container resolution
- Plugin systems / dynamic loading (only `speculative` edges when a candidate exists)

Treat `probable` and `speculative` edges as approximations.

## Integration with Claude Code

In a Claude Code session inside any repo:

```bash
code-map build                             # one-time
cat .code-map/MAP.md                       # drop into context for orientation
code-map query 'callers-of foo' --format markdown   # paste straight into a follow-up
code-map source foo                        # see the actual implementation
code-map status                            # check before refresh
code-map refresh                           # incremental update after edits
```

The `code-mapping` skill in [`EdwardAstill/warden`](https://github.com/EdwardAstill/warden)
wraps this CLI for Warden-managed projects, but the tool stands alone — any
agent that can shell out to a binary can use it.

## How `code-map` differs from existing tools

| | code-map | aider repo-map | SCIP indexers | universal-ctags |
|---|---|---|---|---|
| Polyglot via tree-sitter | ✅ | ✅ | per-language indexer install | ✅ (40+ langs, weaker) |
| Symbol + edge graph | ✅ | symbols only | ✅ | symbols only |
| Edge confidence labels | ✅ (`definite/probable/speculative` + 5 source types) | ❌ | ❌ | ❌ |
| Queryable artifact (CLI / SQL) | ✅ (CLI subcommands + SQLite) | embedded library only | protobuf binary | text grep |
| Blast-radius (transitive callers) | ✅ (recursive CTE, scored) | ❌ | possible via SCIP semantic relationships | ❌ |
| Token-budgeted markdown render | ✅ | ✅ (the original idea) | ❌ | ❌ |
| Standalone install | ✅ (single `uv tool install`) | bundled with aider | per-language binaries | system pkg |
| Honest about static-analysis gaps | ✅ (in-artifact README + `certainty` column) | implicit | implicit | implicit |

`code-map` borrows aider's tree-sitter `.scm` queries (Apache-2.0, attributed in
`src/code_map/queries/ATTRIBUTION.md`) and adapts them for an edge schema with
explicit confidence metadata.

## Provenance

Tree-sitter `.scm` queries under `src/code_map/queries/` are derived from
[aider](https://github.com/Aider-AI/aider) under Apache-2.0; see
`src/code_map/queries/ATTRIBUTION.md`. Adapted for this project's edge schema.

## License

MIT (project). Vendored `.scm` queries remain Apache-2.0 with attribution.
