"""Append-only JSONL mirrors of symbols and edges."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Iterable

from code_map.extract import Edge, Symbol


def append_symbols(path: Path, symbols: Iterable[Symbol]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for s in symbols:
            f.write(json.dumps(dataclasses.asdict(s), ensure_ascii=False) + "\n")


def append_edges(path: Path, edges: Iterable[Edge]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(dataclasses.asdict(e), ensure_ascii=False) + "\n")
