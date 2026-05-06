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
        # ORDER MATTERS: process methods BEFORE functions. The bare
        # function_definition pattern (symbol.function) also matches def-children
        # of class bodies; processing method first means the (name, line_start)
        # entry is recorded as kind=method and the later function capture
        # dedups out. Reverse order produced 12 methods for 69 classes on
        # warden in v0.2.1 (B4 dogfooding bug).
        seen_sym: set[tuple[str, int]] = set()

        for cap_name in (
            "symbol.method",
            "symbol.class",
            "symbol.function",
            "symbol.constant",
        ):
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

        # --- Edges: class inheritance (class Child(Parent, Base): ...) ---
        # Walked directly because the .scm capture would need a per-class
        # repetition that's awkward to express; tree walk is simpler.
        _emit_inherits_edges(tree.root_node, path, result)

        # --- Edges: import_statement (import os, import a.b) ---
        for node in captures.get("import.module", []):
            module_text = node.text.decode()
            target = _resolve_python_import(module_text, source_root)
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
                result.edges.append(
                    Edge(
                        source_file=str(path),
                        source_name=_enclosing_symbol_name(node),
                        target_file=str(path),
                        target_name=name,
                        kind="calls",
                        certainty="definite",
                        source_type="direct",
                    )
                )

        # --- Edges: method calls via attribute access ---
        receiver_nodes = captures.get("call.receiver", [])
        method_nodes = captures.get("call.method", [])
        for _recv_node, meth_node in zip(receiver_nodes, method_nodes):
            method_name = meth_node.text.decode()
            if method_name in _REFLECTION_NAMES:
                continue
            result.edges.append(
                Edge(
                    source_file=str(path),
                    source_name=_enclosing_symbol_name(meth_node),
                    target_file="",
                    target_name=method_name,
                    kind="calls",
                    certainty="probable",
                    source_type="dynamic_dispatch",
                )
            )

        return result


def _emit_inherits_edges(root, path: Path, result: ExtractResult) -> None:
    """Emit `inherits` edges for `class Child(Parent, Base): ...`.

    For each class_definition with a `superclasses` argument_list, take every
    plain identifier or attribute access as a base class name. For attribute
    access (`pkg.Base`) we use the rightmost identifier as the target name —
    cross-file resolution is name-only by design (see runner._build_inner).

    target_file is left blank; the runner's name-only fallback resolves it
    (definite when the base is in the same file, probable when uniquely
    matched cross-file, dropped when ambiguous).
    """

    def walk(node):
        if node.type == "class_definition":
            class_name_node = node.child_by_field_name("name")
            superclasses = node.child_by_field_name("superclasses")
            if class_name_node is not None and superclasses is not None:
                class_name = class_name_node.text.decode()
                for child in superclasses.children:
                    base_name = _base_class_name(child)
                    if base_name is None or base_name == class_name:
                        continue
                    result.edges.append(
                        Edge(
                            source_file=str(path),
                            source_name=class_name,
                            target_file="",
                            target_name=base_name,
                            kind="inherits",
                            certainty="definite",
                            source_type="direct",
                        )
                    )
        for child in node.children:
            walk(child)

    walk(root)


def _base_class_name(node) -> str | None:
    """Extract a base-class name from a superclass argument node.

    Handles plain identifiers, dotted attribute access (returns rightmost
    name), and `keyword_argument` (skipped — `metaclass=`, etc.).
    """
    if node.type == "identifier":
        return node.text.decode()
    if node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        if attr is not None:
            return attr.text.decode()
    return None


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


def _emit_name_edges(
    names_node, path: Path, target: Path, result: ExtractResult
) -> None:
    """Emit one import edge for each name in an import_from_statement names clause.

    For each imported name, first check whether it's actually a submodule of
    the target package — `from pkg.sub import mod` where `pkg/sub/mod.py`
    exists is semantically a module-import, not a name-import. In that case
    we emit a module-level edge (target_file=submodule, target_name="<module>")
    so the runner's <module>-symbol synthesis can resolve it. Otherwise we
    fall back to the name-import shape (target_name=imported_name).
    """

    def emit(name: str) -> None:
        # Submodule check: target is a package's __init__.py — try its dir.
        submod_target: Path | None = None
        if target.name == "__init__.py":
            pkg_dir = target.parent
            if (pkg_dir / f"{name}.py").exists():
                submod_target = pkg_dir / f"{name}.py"
            elif (pkg_dir / name / "__init__.py").exists():
                submod_target = pkg_dir / name / "__init__.py"
        if submod_target is not None:
            result.edges.append(
                Edge(
                    source_file=str(path),
                    source_name="<module>",
                    target_file=str(submod_target),
                    target_name="<module>",
                    kind="import",
                    certainty="definite",
                    source_type="direct",
                )
            )
        else:
            result.edges.append(
                Edge(
                    source_file=str(path),
                    source_name="<module>",
                    target_file=str(target),
                    target_name=name,
                    kind="import",
                    certainty="definite",
                    source_type="direct",
                )
            )

    if names_node.type == "dotted_name":
        emit(names_node.text.decode())
    elif names_node.type == "aliased_import":
        name_child = names_node.child_by_field_name("name")
        if name_child is not None:
            emit(name_child.text.decode())
    elif names_node.type == "wildcard_import":
        # from x import * — emit a single module-level edge to the package.
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

    Three search strategies, in order:

    1. Flat layout: ``source_root/<parts>.py`` or ``source_root/<parts>/__init__.py``.
    2. Common src-style layout: try ``source_root/src/<parts>...`` next.
    3. Basename fallback: walk the repo for any ``<last_part>.py`` or
       ``<last_part>/__init__.py``. Accept only when there is exactly one
       match (ambiguous → drop, because we'd rather miss an edge than emit
       a wrong one). This catches monorepo / nested-package layouts like
       ``core/tools/python/src/<pkg>/...``.

    Returns ``None`` if the module does not resolve to a file inside source_root.
    """
    parts = module.split(".")

    # Strategy 1: flat layout.
    candidate = source_root.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    pkg_init = source_root.joinpath(*parts, "__init__.py")
    if pkg_init.exists():
        return pkg_init

    # Strategy 2: src/ layout.
    src_candidate = source_root.joinpath("src", *parts).with_suffix(".py")
    if src_candidate.exists():
        return src_candidate
    src_init = source_root.joinpath("src", *parts, "__init__.py")
    if src_init.exists():
        return src_init

    # Strategy 3: basename fallback. Only accept unique matches.
    last = parts[-1]
    matches: list[Path] = []
    for hit in source_root.rglob(f"{last}.py"):
        if any(part in _RGLOB_SKIP for part in hit.relative_to(source_root).parts):
            continue
        matches.append(hit)
        if len(matches) > 1:
            return None  # ambiguous
    for hit in source_root.rglob(f"{last}/__init__.py"):
        if any(part in _RGLOB_SKIP for part in hit.relative_to(source_root).parts):
            continue
        matches.append(hit)
        if len(matches) > 1:
            return None
    if len(matches) == 1:
        return matches[0]
    return None


# Skip-dirs for the basename fallback so we don't pull in vendored / cached
# copies of a module name. Keep in sync with runner._SKIP_DIRS.
_RGLOB_SKIP = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".warden",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".next",
        ".nuxt",
    }
)
