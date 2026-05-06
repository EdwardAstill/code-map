import sqlite3
from pathlib import Path

from code_map.schema import init_db


def test_schema_matches_spec(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"))
    names = {r[0] for r in rows}
    expected_tables = {"files", "symbols", "edges"}
    expected_indexes = {"idx_edges_dst", "idx_edges_src", "idx_symbols_name", "idx_symbols_qname"}
    assert expected_tables.issubset(names), f"missing tables: {expected_tables - names}"
    assert expected_indexes.issubset(names), f"missing indexes: {expected_indexes - names}"

    file_cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    assert file_cols == {"path", "language", "content_hash", "loc", "pagerank", "last_indexed"}

    sym_cols = {r[1] for r in conn.execute("PRAGMA table_info(symbols)")}
    assert sym_cols == {"id", "file_path", "kind", "name", "qualified_name", "line_start", "line_end", "signature"}

    edge_cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)")}
    assert edge_cols == {"src_symbol", "dst_symbol", "kind", "certainty", "source_type"}

    # NOT NULL constraints (notnull column = 1 means NOT NULL).
    # SQLite PRAGMA does not report INTEGER PRIMARY KEY or PRIMARY KEY columns as notnull,
    # but they are NOT NULL by table-level constraint — so PK columns are excluded here.
    file_notnull = {r[1] for r in conn.execute("PRAGMA table_info(files)") if r[3] == 1}
    assert file_notnull >= {"language", "content_hash", "loc", "last_indexed"}

    sym_notnull = {r[1] for r in conn.execute("PRAGMA table_info(symbols)") if r[3] == 1}
    assert sym_notnull >= {"file_path", "kind", "name", "qualified_name", "line_start", "line_end"}

    edge_notnull = {r[1] for r in conn.execute("PRAGMA table_info(edges)") if r[3] == 1}
    assert edge_notnull >= {"kind", "certainty", "source_type"}

    # Foreign keys with ON DELETE CASCADE.
    sym_fks = list(conn.execute("PRAGMA foreign_key_list(symbols)"))
    assert any(fk[2] == "files" and fk[6] == "CASCADE" for fk in sym_fks)
    edge_fks = list(conn.execute("PRAGMA foreign_key_list(edges)"))
    assert sum(1 for fk in edge_fks if fk[2] == "symbols" and fk[6] == "CASCADE") == 2
