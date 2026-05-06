import json
from pathlib import Path

from code_map.extract import Edge, Symbol
from code_map.mirrors import append_edges, append_symbols


def test_append_symbols_emits_valid_jsonl(tmp_path: Path):
    sym = Symbol(file_path="a.py", kind="function", name="foo", qualified_name="a.foo", line_start=1, line_end=2, signature="def foo()")
    out = tmp_path / "symbols.jsonl"
    append_symbols(out, [sym])
    append_symbols(out, [sym])
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert record["name"] == "foo"
        assert record["qualified_name"] == "a.foo"


def test_append_edges_emits_valid_jsonl(tmp_path: Path):
    edge = Edge(source_file="a.py", source_name="foo", target_file="b.py", target_name="bar", kind="calls", certainty="definite", source_type="direct")
    out = tmp_path / "edges.jsonl"
    append_edges(out, [edge])
    record = json.loads(out.read_text().splitlines()[0])
    assert record["kind"] == "calls"
    assert record["certainty"] == "definite"
    assert record["source_type"] == "direct"
