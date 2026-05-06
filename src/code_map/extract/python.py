"""Python tree-sitter extractor.

Emits Symbol rows for function_definition, class_definition, methods, and
module-level constants.  Emits Edge rows for resolved import statements and
same-file calls (direct) and method calls via attribute access (dynamic_dispatch).

Reflection calls (getattr, setattr, __import__, eval, exec) emit NO edges.
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_python
from tree_sitter import Language, Parser, Query, QueryCursor

from code_map.extract import Edge, ExtractResult, Symbol

_REFLECTION_NAMES = frozenset({"getattr", "setattr", "__import__", "eval", "exec"})

# Module-level language, parser, query — compiled once at import time.
LANG = Language(tree_sitter_python.language())
PARSER = Parser(LANG)

# Locate the vendored .scm relative to this file (shipped inside the package).
# python.py -> extract/ -> code_map/ -> queries/
_QUERY_PATH = Path(__file__).resolve().parent.parent / "queries" / "python.scm"
QUERY = Query(LANG, _QUERY_PATH.read_text())


class PythonExtractor:
    language = "python"
    file_extensions = (".py",)

    def extract(self, path: Path, *, source_root: Path) -> ExtractResult:
        source = path.read_bytes()
        tree = PARSER.parse(source)
        cursor = QueryCursor(QUERY)
        captures = cursor.captures(tree.root_node)
        result = ExtractResult()
        defined: dict[str, Symbol] = {}

        # --- Symbols ---
        # symbol.class may appear twice for the same class node (once from the
        # pattern with body, once from the bare pattern).  Deduplicate by name
        # + line_start so we don't emit duplicates.
        seen_sym: set[tuple[str, int]] = set()

        for cap_name in ("symbol.function", "symbol.class", "symbol.method", "symbol.constant"):
            for node in captures.get(cap_name, []):
                kind = cap_name.split(".", 1)[1]  # function | class | method | constant
                name = node.text.decode()
                # The captured node is the identifier (name token); span the
                # full definition by walking up to its enclosing definition.
                span_node = _enclosing_definition(node) or node
                line_start = span_node.start_point[0] + 1
                line_end = span_node.end_point[0] + 1
                key = (name, line_start)
                if key in seen_sym:
                    continue
                seen_sym.add(key)
                # Qualified name: stem.name (or stem.ClassName.methodName for methods)
                enclosing = _enclosing_class_name(node) if kind == "method" else None
                if enclosing:
                    qualified = f"{path.stem}.{enclosing}.{name}"
                else:
                    qualified = f"{path.stem}.{name}"
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
                # Track top-level defined names for direct-call resolution.
                if kind in ("function", "class"):
                    defined[name] = sym

        # --- Edges: import_statement (import os, import a.b) ---
        for node in captures.get("import.module", []):
            module_text = node.text.decode()
            target = _resolve_python_import(module_text, source_root)
            if target is None:
                continue
            result.edges.append(Edge(
                source_file=str(path),
                source_name="<module>",
                target_file=str(target),
                target_name="<module>",
                kind="import",
                certainty="definite",
                source_type="direct",
            ))

        # --- Edges: import_from_statement (from b import greet) ---
        # captures returns parallel lists; zip them by walking the AST directly
        # because the capture lists may not align 1:1.
        _emit_from_import_edges(tree.root_node, path, source_root, result, captures)

        # --- Edges: same-file direct calls ---
        for node in captures.get("call.callee", []):
            name = node.text.decode()
            if name in _REFLECTION_NAMES:
                continue
            if name in defined:
                result.edges.append(Edge(
                    source_file=str(path),
                    source_name=_enclosing_symbol_name(node),
                    target_file=str(path),
                    target_name=name,
                    kind="calls",
                    certainty="definite",
                    source_type="direct",
                ))

        # --- Edges: method calls via attribute access ---
        receiver_nodes = captures.get("call.receiver", [])
        method_nodes = captures.get("call.method", [])
        for _recv_node, meth_node in zip(receiver_nodes, method_nodes):
            method_name = meth_node.text.decode()
            if method_name in _REFLECTION_NAMES:
                continue
            result.edges.append(Edge(
                source_file=str(path),
                source_name=_enclosing_symbol_name(meth_node),
                target_file="",
                target_name=method_name,
                kind="calls",
                certainty="probable",
                source_type="dynamic_dispatch",
            ))

        return result


def _emit_from_import_edges(
    root,
    path: Path,
    source_root: Path,
    result: ExtractResult,
    captures: dict,
) -> None:
    """Walk import_from_statement nodes directly to pair module+name correctly.

    The query captures `import.from.module` and `import.from.name` but the
    QueryCursor aggregates all captures across all nodes into flat lists.  We
    walk the AST instead so each statement emits its own set of (module, name)
    pairs without cross-contamination between multiple import_from_statements.
    """
    def walk(node):
        if node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            if module_node is None:
                return
            module_text = module_node.text.decode()
            target = _resolve_python_import(module_text, source_root)
            if target is None:
                return
            # Collect imported names from the names list.
            names_node = node.child_by_field_name("name")
            if names_node is None:
                return
            # names_node can be a single dotted_name / aliased_import,
            # or a wildcard_import.  It may also be a list of them when
            # parenthesised — those appear as siblings, not children.
            _emit_name_edges(names_node, path, target, result)
            # Also walk siblings for parenthesised multi-import.
            sibling = names_node.next_named_sibling
            while sibling is not None:
                _emit_name_edges(sibling, path, target, result)
                sibling = sibling.next_named_sibling
        else:
            for child in node.children:
                walk(child)

    walk(root)


def _emit_name_edges(names_node, path: Path, target: Path, result: ExtractResult) -> None:
    """Emit one import edge for each name in an import_from_statement names clause."""
    if names_node.type == "dotted_name":
        imported_name = names_node.text.decode()
        result.edges.append(Edge(
            source_file=str(path),
            source_name="<module>",
            target_file=str(target),
            target_name=imported_name,
            kind="import",
            certainty="definite",
            source_type="direct",
        ))
    elif names_node.type == "aliased_import":
        name_child = names_node.child_by_field_name("name")
        if name_child is not None:
            imported_name = name_child.text.decode()
            result.edges.append(Edge(
                source_file=str(path),
                source_name="<module>",
                target_file=str(target),
                target_name=imported_name,
                kind="import",
                certainty="definite",
                source_type="direct",
            ))
    elif names_node.type == "wildcard_import":
        # from x import * — emit a single module-level edge
        result.edges.append(Edge(
            source_file=str(path),
            source_name="<module>",
            target_file=str(target),
            target_name="*",
            kind="import",
            certainty="definite",
            source_type="direct",
        ))


def _enclosing_symbol_name(node) -> str:
    """Walk up to find the enclosing function or class name."""
    cur = node.parent
    while cur is not None:
        if cur.type in ("function_definition", "class_definition"):
            name_child = cur.child_by_field_name("name")
            if name_child is not None:
                return name_child.text.decode()
        cur = cur.parent
    return "<module>"


def _enclosing_definition(node):
    """Return the enclosing function_definition / class_definition / assignment
    node for an identifier capture, or None if the identifier is not nested
    inside one (defensive — should not happen for our query patterns)."""
    cur = node.parent
    while cur is not None:
        if cur.type in ("function_definition", "class_definition", "assignment"):
            return cur
        cur = cur.parent
    return None


def _enclosing_class_name(node) -> str | None:
    """Walk up to find the enclosing class_definition name, if any."""
    cur = node.parent
    while cur is not None:
        if cur.type == "class_definition":
            name_child = cur.child_by_field_name("name")
            if name_child is not None:
                return name_child.text.decode()
        cur = cur.parent
    return None


def _resolve_python_import(module: str, source_root: Path) -> Path | None:
    """Resolve a dotted module name to a file path within source_root.

    Supports both plain module imports (``import os``) and the module part of
    from-imports (``from b import greet`` → module=``b``).

    Returns None if the module does not resolve to a file inside source_root.
    """
    parts = module.split(".")
    candidate = source_root.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    pkg_init = source_root.joinpath(*parts, "__init__.py")
    if pkg_init.exists():
        return pkg_init
    return None
