# core/tools/python/tests/code_map/test_extract_typescript.py
from pathlib import Path

from code_map.extract import for_language

FIXTURE = Path(__file__).parent / "fixtures" / "sample-poly" / "typescript"


def test_typescript_extractor_finds_exported_function():
    ex = for_language("typescript")
    result = ex.extract(FIXTURE / "b.ts", source_root=FIXTURE)
    assert any(s.name == "greet" and s.kind == "function" for s in result.symbols)


def test_typescript_extractor_resolves_relative_import():
    ex = for_language("typescript")
    result = ex.extract(FIXTURE / "a.ts", source_root=FIXTURE)
    targets = {(e.target_file, e.target_name, e.kind) for e in result.edges}
    assert (str(FIXTURE / "b.ts"), "greet", "import") in targets
