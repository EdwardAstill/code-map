from pathlib import Path

ROOT = Path(__file__).parent / "fixtures" / "sample-poly"


def test_python_fixture_has_known_call_chain():
    a = (ROOT / "python/a.py").read_text()
    b = (ROOT / "python/b.py").read_text()
    c = (ROOT / "python/c.py").read_text()
    assert "from b import greet" in a or "import b" in a
    assert "def greet" in b
    assert "shout" in b
    assert "def shout" in c


def test_typescript_fixture_has_import():
    a = (ROOT / "typescript/a.ts").read_text()
    b = (ROOT / "typescript/b.ts").read_text()
    assert "from './b'" in a or "from \"./b\"" in a
    assert "export function" in b


def test_rust_fixture_has_call_chain():
    lib = (ROOT / "rust/src/lib.rs").read_text()
    a = (ROOT / "rust/src/a.rs").read_text()
    b = (ROOT / "rust/src/b.rs").read_text()
    assert "mod a" in lib and "mod b" in lib
    assert "b::" in a
    assert "pub fn" in b
