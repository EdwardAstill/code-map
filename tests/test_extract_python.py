from pathlib import Path

from code_map.extract import for_language
from code_map.schema import KIND_VALUES, CERTAINTY_VALUES, SOURCE_TYPE_VALUES

FIXTURE = Path(__file__).parent / "fixtures" / "sample-poly" / "python"


def test_python_extractor_finds_known_symbols():
    extractor = for_language("python")
    result_b = extractor.extract(FIXTURE / "b.py", source_root=FIXTURE)
    sym_names = {s.name for s in result_b.symbols}
    assert "greet" in sym_names

    result_c = extractor.extract(FIXTURE / "c.py", source_root=FIXTURE)
    assert "shout" in {s.name for s in result_c.symbols}


def test_python_extractor_finds_import_edge_to_resolved_module():
    extractor = for_language("python")
    result_a = extractor.extract(FIXTURE / "a.py", source_root=FIXTURE)
    targets = {(e.target_file, e.target_name, e.kind) for e in result_a.edges}
    assert (str(FIXTURE / "b.py"), "greet", "import") in targets


def test_python_extractor_emits_only_enumerated_values():
    extractor = for_language("python")
    for path in (FIXTURE / "a.py", FIXTURE / "b.py", FIXTURE / "c.py"):
        result = extractor.extract(path, source_root=FIXTURE)
        for edge in result.edges:
            assert edge.kind in KIND_VALUES
            assert edge.certainty in CERTAINTY_VALUES
            assert edge.source_type in SOURCE_TYPE_VALUES
