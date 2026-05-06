"""`code-map schema` — emit the JSON Schema 2020-12 describing the artifact contract."""
from __future__ import annotations

import json

# Single source of truth for the artifact's wire shape. Update when adding
# new columns to schema.py or new subcommands that emit JSON.
ARTIFACT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/EdwardAstill/code-map/schema/v0.2.0",
    "title": "code-map artifact",
    "description": "Wire shape of the code-map artifact directory (graph.db tables, JSONL line records, manifest.json).",
    "type": "object",
    "$defs": {
        "Symbol": {
            "type": "object",
            "required": ["file_path", "kind", "name", "qualified_name", "line_start", "line_end"],
            "properties": {
                "file_path": {"type": "string", "description": "Repo-relative path."},
                "kind": {"enum": ["function", "class", "method", "type", "constant"]},
                "name": {"type": "string", "description": "Short identifier (last segment)."},
                "qualified_name": {"type": "string", "description": "Stem.Class.method form; canonical query target."},
                "line_start": {"type": "integer", "minimum": 1},
                "line_end": {"type": "integer", "minimum": 1},
                "signature": {"type": "string", "description": "Textual function/method signature; may be empty."},
            },
        },
        "Edge": {
            "type": "object",
            "required": ["source_file", "source_name", "target_file", "target_name", "kind", "certainty", "source_type"],
            "properties": {
                "source_file": {"type": "string"},
                "source_name": {"type": "string"},
                "target_file": {"type": "string"},
                "target_name": {"type": "string"},
                "kind": {"enum": ["import", "calls", "inherits", "implements", "references"]},
                "certainty": {
                    "enum": ["definite", "probable", "speculative"],
                    "description": "definite = static-resolvable; probable = dynamic dispatch with known candidates; speculative = reflection / DI / plugin best-guess.",
                },
                "source_type": {
                    "enum": ["direct", "dynamic_dispatch", "reflection", "callback", "plugin"],
                    "description": "Origin of the edge — see honesty contract in artifact README.",
                },
            },
        },
        "Manifest": {
            "type": "object",
            "required": ["languages", "grammar_versions", "last_built", "files"],
            "properties": {
                "languages": {"type": "array", "items": {"type": "string"}},
                "grammar_versions": {"type": "object", "additionalProperties": {"type": "string"}},
                "last_built": {"type": "string", "format": "date-time"},
                "files": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "required": ["content_hash", "last_indexed"],
                        "properties": {
                            "content_hash": {"type": "string", "minLength": 64, "maxLength": 64},
                            "last_indexed": {"type": "string", "format": "date-time"},
                        },
                    },
                },
            },
        },
        "QueryResultRow": {
            "type": "object",
            "description": "One row of `code-map query` JSON output.",
            "properties": {
                "qualified_name": {"type": "string"},
                "name": {"type": "string"},
                "kind": {"type": "string"},
                "depth": {"type": "integer", "description": "Present on blast-radius rows only."},
                "score": {"type": "number", "description": "PageRank-derived; higher is more important."},
                "line_start": {"type": "integer"},
                "line_end": {"type": "integer"},
            },
        },
    },
    "properties": {
        "graph.db": {
            "type": "object",
            "description": "SQLite source of truth. Tables: files, symbols, edges. See `schema.py` in this package for the DDL.",
        },
        "edges.jsonl": {
            "type": "array",
            "items": {"$ref": "#/$defs/Edge"},
            "description": "One Edge object per line. Append-only mirror of graph.db `edges` table.",
        },
        "symbols.jsonl": {
            "type": "array",
            "items": {"$ref": "#/$defs/Symbol"},
            "description": "One Symbol object per line. Append-only mirror of graph.db `symbols` table.",
        },
        "manifest.json": {"$ref": "#/$defs/Manifest"},
    },
    "exitCodes": {
        "0": "success",
        "2": "no artifact (run `code-map build` first)",
        "3": "target symbol or file not found",
        "4": "artifact stale (only emitted by `code-map status --fail-on-stale`)",
    },
    "subcommands": {
        "build": "Full code-map build.",
        "refresh": "Content-hash-gated incremental rebuild. Add --json for the run summary.",
        "render": "Re-derive MAP.md and packages/*.md from graph.db.",
        "query": "callers-of / callees-of / blast-radius / defined-in. Supports symbol globs (* and ?). Results carry `score` and are score-desc ordered.",
        "find": "Substring or glob symbol search. Searches both name and qualified_name.",
        "source": "Fetch source lines for a symbol. --format markdown for fenced output.",
        "outline": "Tree outline of a file with class > method nesting.",
        "context": "Reverse lookup: <file>:<line> → containing symbol.",
        "status": "Artifact freshness report. --fail-on-stale exits 4 if any source file changed since build.",
        "schema": "Emit this schema document.",
    },
}


def run_schema() -> None:
    print(json.dumps(ARTIFACT_SCHEMA, indent=2))
