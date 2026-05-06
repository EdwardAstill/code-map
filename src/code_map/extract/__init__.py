"""Per-language extractors. Each implements the Extractor protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Symbol:
    file_path: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    signature: str = ""


@dataclass(frozen=True)
class Edge:
    source_file: str
    source_name: str
    target_file: str
    target_name: str
    kind: str
    certainty: str
    source_type: str


@dataclass
class ExtractResult:
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


class Extractor(Protocol):
    language: str
    file_extensions: tuple[str, ...]

    def extract(self, path: Path, *, source_root: Path) -> ExtractResult: ...


def for_language(name: str) -> Extractor:
    if name == "python":
        from code_map.extract.python import PythonExtractor
        return PythonExtractor()
    if name in ("typescript", "javascript"):
        from code_map.extract.typescript import TypeScriptExtractor
        return TypeScriptExtractor(flavour=name)
    if name == "rust":
        from code_map.extract.rust import RustExtractor
        return RustExtractor()
    raise ValueError(f"unknown language: {name}")
