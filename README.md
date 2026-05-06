# code-map

AI-consumable code-map artifact for polyglot repos. Produces a durable
`.code-map/` (or `.warden/maps/<repo-slug>/` when `.warden/` is present)
holding a SQLite graph, JSONL mirrors, and a token-budgeted Markdown
overview. Designed for LLM agents that need to answer "how does this
codebase link together?" or "what is the blast radius of symbol X?"
without re-reading every source file.

## Languages

Tier-1 (v0.1.0): Python, TypeScript / JavaScript, Rust — all via tree-sitter.

## Install

```bash
uv tool install git+https://github.com/EdwardAstill/code-map
```

Or as a project dependency:

```bash
uv add git+https://github.com/EdwardAstill/code-map
```

## Usage

```bash
code-map build [--repo .] [--lang python,typescript,rust] [--map-tokens 4000]
code-map refresh [--paths <glob>] [--json]
code-map query 'callers-of <symbol>'    # also: callees-of, blast-radius, defined-in
code-map render
```

After `build`, the artifact lives at `.code-map/` (or
`.warden/maps/<repo-slug>/` if `.warden/` exists in the repo root).
Read the `README.md` inside the artifact directory first when opening
the artifact cold — it documents the SQLite schema, the JSONL line
shape, and the static-analysis blind spots the artifact does **not**
cover.

## Artifact

```
.code-map/
├── README.md       # cold-load instructions for any agent that opens the dir
├── MAP.md          # token-budgeted overview ordered by PageRank
├── manifest.json   # languages, grammar versions, last-built timestamp, content-hash cache
├── graph.db        # SQLite source of truth (files, symbols, edges)
├── edges.jsonl     # one edge per line; grep-friendly
├── symbols.jsonl   # one symbol per line; grep-friendly
└── packages/
    └── <pkg>.md    # per-directory symbol list
```

Edges carry `certainty` (`definite | probable | speculative`) and
`source_type` (`direct | dynamic_dispatch | reflection | callback | plugin`)
so consumers can filter by confidence.

## Honesty contract

The current backbone (tree-sitter + heuristics) does **not** resolve:

- Python `getattr` / `setattr` / `__import__` / `eval` / `exec`
- JS / TS `eval`, dynamic `import()`, `Reflect.*`
- Async chains: `.then(callback)` breaks the call edge at the Promise boundary
- Rust trait dispatch on `dyn Trait` — flagged `probable`, not `definite`
- Dependency-injection container resolution
- Plugin systems / dynamic loading (only `speculative` edges when a candidate exists)

Treat `probable` and `speculative` edges as approximations.

## Provenance

Tree-sitter `.scm` queries under `queries/` are derived from
[aider](https://github.com/Aider-AI/aider) under Apache-2.0;
see `queries/ATTRIBUTION.md`. Adapted for this project's edge schema.

## License

MIT (project). Vendored `.scm` queries remain Apache-2.0 with attribution.
