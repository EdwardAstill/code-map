"""SQLite schema for the code-map artifact. See spec §4 for the contract."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS files (
  path          TEXT PRIMARY KEY,
  language      TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  loc           INTEGER NOT NULL,
  pagerank      REAL,
  last_indexed  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
  id              INTEGER PRIMARY KEY,
  file_path       TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  kind            TEXT NOT NULL,
  name            TEXT NOT NULL,
  qualified_name  TEXT NOT NULL,
  line_start      INTEGER NOT NULL,
  line_end        INTEGER NOT NULL,
  signature       TEXT
);

CREATE TABLE IF NOT EXISTS edges (
  src_symbol   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  dst_symbol   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL,
  certainty    TEXT NOT NULL,
  source_type  TEXT NOT NULL,
  PRIMARY KEY (src_symbol, dst_symbol, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_dst     ON edges(dst_symbol);
CREATE INDEX IF NOT EXISTS idx_edges_src     ON edges(src_symbol);
CREATE INDEX IF NOT EXISTS idx_symbols_name  ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qname ON symbols(qualified_name);
"""

KIND_VALUES = ("import", "calls", "inherits", "implements", "references")
CERTAINTY_VALUES = ("definite", "probable", "speculative")
SOURCE_TYPE_VALUES = ("direct", "dynamic_dispatch", "reflection", "callback", "plugin")


def init_db(path: Path) -> sqlite3.Connection:
    """Create or open the SQLite database with the spec schema applied.

    `PRAGMA foreign_keys = ON` is set before `executescript` so DDL referencing
    foreign keys is enforced for this connection. Note: the pragma is per
    connection — callers that open their own `sqlite3.connect` to the same
    file must re-issue it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    conn.commit()
    return conn
