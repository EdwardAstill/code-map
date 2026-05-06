from pathlib import Path

from code_map.extract import for_language

FIXTURE = Path(__file__).parent / "fixtures" / "sample-poly" / "rust"


def test_rust_extractor_finds_pub_fn():
    ex = for_language("rust")
    result = ex.extract(FIXTURE / "src/b.rs", source_root=FIXTURE / "src")
    assert any(s.name == "greet" and s.kind == "function" for s in result.symbols)


def test_rust_extractor_resolves_intra_crate_call():
    ex = for_language("rust")
    result = ex.extract(FIXTURE / "src/a.rs", source_root=FIXTURE / "src")
    targets = {(Path(e.target_file).name, e.target_name, e.kind, e.certainty) for e in result.edges}
    assert ("b.rs", "greet", "calls", "definite") in targets or \
           ("b.rs", "greet", "calls", "probable") in targets
