"""Rust tree-sitter extractor.

Emits Symbol rows for function_item, struct_item, enum_item, trait_item,
impl methods, and const_item.  Emits Edge rows for use declarations (imports)
and call expressions (direct, scoped, and field-expression).

Edge certainty assignments (per spec §5):
- Direct intra-crate call resolving to a single symbol: definite / direct
- Scoped call (b::greet) resolving to a file: definite / direct
- Field-expression call (self.method()): probable / dynamic_dispatch
- use declaration: definite / direct (treated as import edge)
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_rust
from tree_sitter import Language, Parser, Query, QueryCursor

from code_map.extract import Edge, ExtractResult, Symbol

# Module-level language, parser, query — compiled once at import time.
LANG = Language(tree_sitter_rust.language())
PARSER = Parser(LANG)

# Locate the vendored .scm relative to this file (shipped inside the package).
# rust.py -> extract/ -> code_map/ -> queries/
_QUERY_PATH = Path(__file__).resolve().parent.parent / "queries" / "rust.scm"
QUERY = Query(LANG, _QUERY_PATH.read_text())


class RustExtractor:
    language = "rust"
    file_extensions = (".rs",)

    def extract(self, path: Path, *, source_root: Path) -> ExtractResult:
        source = path.read_bytes()
        tree = PARSER.parse(source)
        cursor = QueryCursor(QUERY)
        captures = cursor.captures(tree.root_node)
        result = ExtractResult()
        defined: dict[str, Symbol] = {}

        seen_sym: set[tuple[str, int]] = set()

        # --- Symbols ---
        for cap_name in (
            "symbol.function",
            "symbol.type",
            "symbol.method",
            "symbol.constant",
        ):
            for node in captures.get(cap_name, []):
                kind = cap_name.split(".", 1)[1]  # function | type | method | constant
                name = node.text.decode()
                span_node = _enclosing_definition(node) or node
                line_start = span_node.start_point[0] + 1
                line_end = span_node.end_point[0] + 1
                key = (name, line_start)
                if key in seen_sym:
                    continue
                seen_sym.add(key)
                enclosing = _enclosing_impl_type(node) if kind == "method" else None
                if enclosing:
                    qualified = f"{path.stem}::{enclosing}::{name}"
                else:
                    qualified = f"{path.stem}::{name}"
                sym = Symbol(
                    file_path=str(path),
                    kind=kind,
                    name=name,
                    qualified_name=qualified,
                    line_start=line_start,
                    line_end=line_end,
                    signature="",
                )
                result.symbols.append(sym)
                if kind == "function":
                    defined[name] = sym

        # --- Edges: use declarations ---
        for node in captures.get("use.path", []):
            # node is a scoped_identifier like `crate::b` or `b`
            # Extract the last segment as the module name to resolve.
            use_text = node.text.decode()
            # Take the last component of `a::b::c` → `c`
            last_segment = use_text.split("::")[-1]
            target = _resolve_rust_module(last_segment, source_root, from_file=path)
            if target is None:
                continue
            result.edges.append(
                Edge(
                    source_file=str(path),
                    source_name="<module>",
                    target_file=str(target),
                    target_name="<module>",
                    kind="import",
                    certainty="definite",
                    source_type="direct",
                )
            )

        # --- Edges: direct identifier calls (same-file) ---
        for node in captures.get("call.callee", []):
            name = node.text.decode()
            if name in defined:
                result.edges.append(
                    Edge(
                        source_file=str(path),
                        source_name=_enclosing_fn_name(node),
                        target_file=str(path),
                        target_name=name,
                        kind="calls",
                        certainty="definite",
                        source_type="direct",
                    )
                )

        # --- Edges: scoped calls (receiver::method) ---
        # QueryCursor's call.receiver / call.method capture lists can't be
        # blindly zipped because field_expression matches also populate
        # call.method but produce no call.receiver. Walk the AST instead and
        # pair captures per call_expression node.
        _emit_call_edges(tree.root_node, path, source_root, result)

        # --- Edges: impl Trait for Type → implements ---
        _emit_impl_edges(tree.root_node, path, result)

        return result


def _emit_impl_edges(root, path: Path, result: ExtractResult) -> None:
    """Emit `implements` edges for every `impl Trait for Type` block.

    Inherent impls (`impl Type { ... }`) have no `trait` field and emit no
    edge. Cross-file resolution is name-only (see runner._build_inner).
    """

    def walk(node):
        if node.type == "impl_item":
            trait_node = node.child_by_field_name("trait")
            type_node = node.child_by_field_name("type")
            if trait_node is not None and type_node is not None:
                trait_name = _last_ident(trait_node)
                type_name = _last_ident(type_node)
                if trait_name and type_name:
                    result.edges.append(
                        Edge(
                            source_file=str(path),
                            source_name=type_name,
                            target_file="",
                            target_name=trait_name,
                            kind="implements",
                            certainty="definite",
                            source_type="direct",
                        )
                    )
        for child in node.children:
            walk(child)

    walk(root)


def _last_ident(node) -> str | None:
    """Return the rightmost type/identifier text from a Rust type node.

    Handles `Foo`, `pkg::Foo`, `Foo<T>` — returns `Foo` in each case.
    """
    if node.type in ("type_identifier", "identifier"):
        return node.text.decode()
    if node.type == "scoped_type_identifier":
        name = node.child_by_field_name("name")
        if name is not None:
            return name.text.decode()
    if node.type == "generic_type":
        inner = node.child_by_field_name("type")
        if inner is not None:
            return _last_ident(inner)
    # Fallback: walk children for the first type/identifier we find.
    for child in node.children:
        result = _last_ident(child)
        if result:
            return result
    return None


def _emit_call_edges(
    root,
    path: Path,
    source_root: Path,
    result: ExtractResult,
) -> None:
    """Walk call_expression nodes to emit scoped and field-expression edges."""

    def walk(node):
        if node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node is not None:
                if fn_node.type == "scoped_identifier":
                    # b::greet — path child is the module, name child is the fn.
                    path_child = fn_node.child_by_field_name("path")
                    name_child = fn_node.child_by_field_name("name")
                    if path_child is not None and name_child is not None:
                        # Only emit when the path is a plain identifier (not `crate`, `super`, etc.)
                        if path_child.type == "identifier":
                            module_name = path_child.text.decode()
                            fn_name = name_child.text.decode()
                            target = _resolve_rust_module(
                                module_name, source_root, from_file=path
                            )
                            if target is not None:
                                result.edges.append(
                                    Edge(
                                        source_file=str(path),
                                        source_name=_enclosing_fn_name(node),
                                        target_file=str(target),
                                        target_name=fn_name,
                                        kind="calls",
                                        certainty="definite",
                                        source_type="direct",
                                    )
                                )
                elif fn_node.type == "field_expression":
                    field_child = fn_node.child_by_field_name("field")
                    if field_child is not None:
                        fn_name = field_child.text.decode()
                        result.edges.append(
                            Edge(
                                source_file=str(path),
                                source_name=_enclosing_fn_name(node),
                                target_file="",
                                target_name=fn_name,
                                kind="calls",
                                certainty="probable",
                                source_type="dynamic_dispatch",
                            )
                        )
        for child in node.children:
            walk(child)

    walk(root)


def _enclosing_fn_name(node) -> str:
    """Walk up to find the enclosing function_item name."""
    cur = node.parent
    while cur is not None:
        if cur.type == "function_item":
            name_child = cur.child_by_field_name("name")
            if name_child is not None:
                return name_child.text.decode()
        cur = cur.parent
    return "<module>"


def _enclosing_definition(node):
    """Return the enclosing definition node for a name-identifier capture."""
    cur = node.parent
    while cur is not None:
        if cur.type in (
            "function_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "impl_item",
            "const_item",
        ):
            return cur
        cur = cur.parent
    return None


def _enclosing_impl_type(node) -> str | None:
    """Walk up to find the type name of an enclosing impl_item."""
    cur = node.parent
    while cur is not None:
        if cur.type == "impl_item":
            type_child = cur.child_by_field_name("type")
            if type_child is not None:
                return type_child.text.decode()
        cur = cur.parent
    return None


def _resolve_rust_module(
    module_name: str, source_root: Path, *, from_file: Path | None = None
) -> Path | None:
    """Resolve a Rust module name to a .rs file.

    Search order:
    1. Adjacent to `from_file` (sibling): `<from_file_dir>/<module_name>.rs` or
       `<from_file_dir>/<module_name>/mod.rs` — the common case for a module
       referencing a sibling within the same directory.
    2. From `source_root` as a fallback for crate-root-style references.

    Returns None if no candidate exists. Does not honour `pub use` re-exports.
    """
    search_dirs: list[Path] = []
    if from_file is not None:
        search_dirs.append(from_file.parent)
    if not search_dirs or search_dirs[0] != source_root:
        search_dirs.append(source_root)
    for base in search_dirs:
        candidate = base / f"{module_name}.rs"
        if candidate.exists():
            return candidate
        mod_rs = base / module_name / "mod.rs"
        if mod_rs.exists():
            return mod_rs
    return None
