"""TypeScript / JavaScript tree-sitter extractor.

Handles .ts, .tsx (TypeScript), .js, .jsx (JavaScript via tsx grammar superset).
Emits Symbol rows for function_declaration, class_declaration, method_definition,
and exported lexical constants.  Emits Edge rows for resolved import statements,
same-file direct calls, and method calls via member expressions (dynamic_dispatch).

Module resolution for relative imports:
  - Strip leading './' from the import path.
  - Try appending '.ts', then '.tsx', then '.js', then '.jsx' in order.
  - Resolve against the importing file's directory.
  - If a tsconfig.json is found at source_root with compilerOptions.paths,
    substitute matching path alias prefixes before resolution.
  - If resolution fails inside the repo, drop the edge (no 'external' edges).

Edge certainty / source_type assignments:
  import statement        → certainty=definite, source_type=direct
  same-file direct call   → certainty=definite, source_type=direct
  method/attribute call   → certainty=probable,  source_type=dynamic_dispatch
"""

from __future__ import annotations

import json
from pathlib import Path

import tree_sitter_typescript
from tree_sitter import Language, Parser, Query, QueryCursor

from code_map.extract import Edge, ExtractResult, Symbol

# ── Languages (compiled once at import time) ──────────────────────────────────

_LANG_TS = Language(tree_sitter_typescript.language_typescript())
_LANG_TSX = Language(tree_sitter_typescript.language_tsx())

_PARSER_TS = Parser(_LANG_TS)
_PARSER_TSX = Parser(_LANG_TSX)

# ── Query file (shared; both grammars understand the same patterns) ───────────
# typescript.py -> extract/ -> code_map/ -> queries/  (shipped inside the package)
_QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"

_QUERY_TS = Query(_LANG_TS, (_QUERIES_DIR / "typescript.scm").read_text())
# .tsx files in a TypeScript project: TS query patterns compiled against the
# tsx grammar so TS-specific captures still fire on .tsx files.
_QUERY_TSX = Query(_LANG_TSX, (_QUERIES_DIR / "typescript.scm").read_text())
_QUERY_JS = Query(_LANG_TSX, (_QUERIES_DIR / "javascript.scm").read_text())

# Extensions tried in order when resolving a relative import path.
_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


class TypeScriptExtractor:
    """Extracts symbols and edges from TypeScript and JavaScript source files."""

    def __init__(self, flavour: str = "typescript") -> None:
        """
        Args:
            flavour: One of ``"typescript"`` or ``"javascript"``.
                     TypeScript uses the ts grammar; JavaScript uses the tsx
                     grammar (a superset that correctly parses plain JS).
        """
        if flavour == "javascript":
            self.language = "javascript"
            self.file_extensions = (".js", ".jsx")
            self._lang = _LANG_TSX
            self._parser = _PARSER_TSX
            self._query = _QUERY_JS
        else:
            self.language = "typescript"
            self.file_extensions = (".ts", ".tsx")
            self._lang = _LANG_TS
            self._parser = _PARSER_TS
            self._query = _QUERY_TS

    # ── Public interface ──────────────────────────────────────────────────────

    def extract(self, path: Path, *, source_root: Path) -> ExtractResult:
        source = path.read_bytes()
        # Pick (parser, query) by file suffix:
        # - .tsx  → tsx grammar + TS query (TS-specific captures still fire)
        # - .jsx  → tsx grammar + JS query
        # - .ts   → ts grammar + TS query
        # - .js   → tsx grammar + JS query (tsx is a JS superset)
        if path.suffix == ".tsx":
            parser, query = _PARSER_TSX, _QUERY_TSX
        elif path.suffix == ".jsx":
            parser, query = _PARSER_TSX, _QUERY_JS
        else:
            parser = self._parser
            query = self._query

        tree = parser.parse(source)
        cursor = QueryCursor(query)
        captures = cursor.captures(tree.root_node)
        result = ExtractResult()
        defined: dict[str, Symbol] = {}

        # Load tsconfig paths mapping once per extraction (cached per call).
        path_aliases = _load_tsconfig_paths(source_root)

        # ── Symbols ───────────────────────────────────────────────────────────
        seen_sym: set[tuple[str, int]] = set()

        for cap_name in (
            "symbol.function",
            "symbol.class",
            "symbol.method",
            "symbol.constant",
        ):
            for node in captures.get(cap_name, []):
                kind = cap_name.split(".", 1)[1]
                name = node.text.decode()
                span_node = _enclosing_definition(node) or node
                line_start = span_node.start_point[0] + 1
                line_end = span_node.end_point[0] + 1
                key = (name, line_start)
                if key in seen_sym:
                    continue
                seen_sym.add(key)
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
                if kind in ("function", "class"):
                    defined[name] = sym

        # ── Edges: class extends / implements ─────────────────────────────────
        _emit_heritage_edges(tree.root_node, path, result)

        # ── Edges: import statements ──────────────────────────────────────────
        _emit_import_edges(
            tree.root_node, path, source_root, result, captures, path_aliases
        )

        # ── Edges: same-file direct calls ─────────────────────────────────────
        for node in captures.get("call.callee", []):
            name = node.text.decode()
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

        # ── Edges: method calls via member expression ─────────────────────────
        receiver_nodes = captures.get("call.receiver", [])
        method_nodes = captures.get("call.method", [])
        if len(receiver_nodes) != len(method_nodes):
            # Defensive: tree-sitter QueryCursor pairs sibling captures from
            # the same match in order, so this should not happen for our
            # query. If it does, prefer truncation over crashing — but flag
            # via a counter that downstream tests can catch.
            import warnings

            warnings.warn(
                f"call.receiver/call.method length mismatch: "
                f"{len(receiver_nodes)} vs {len(method_nodes)} in {path}",
                RuntimeWarning,
                stacklevel=2,
            )
        for _recv_node, meth_node in zip(receiver_nodes, method_nodes):
            result.edges.append(
                Edge(
                    source_file=str(path),
                    source_name=_enclosing_symbol_name(meth_node),
                    target_file="",
                    target_name=meth_node.text.decode(),
                    kind="calls",
                    certainty="probable",
                    source_type="dynamic_dispatch",
                )
            )

        return result


# ── Heritage edge emission (extends / implements) ────────────────────────────


def _emit_heritage_edges(root, path: Path, result: ExtractResult) -> None:
    """Emit `inherits` (extends) and `implements` edges for class declarations.

    Walks every class_declaration; inspects its class_heritage child for
    extends_clause and implements_clause. Cross-file resolution is name-only
    (see runner._build_inner): target_file is left blank.
    """

    def walk(node):
        if node.type == "class_declaration":
            class_name_node = node.child_by_field_name("name")
            if class_name_node is not None:
                class_name = class_name_node.text.decode()
                for child in node.children:
                    if child.type == "class_heritage":
                        for clause in child.children:
                            if clause.type == "extends_clause":
                                for name in _heritage_names(clause):
                                    if name == class_name:
                                        continue
                                    result.edges.append(
                                        Edge(
                                            source_file=str(path),
                                            source_name=class_name,
                                            target_file="",
                                            target_name=name,
                                            kind="inherits",
                                            certainty="definite",
                                            source_type="direct",
                                        )
                                    )
                            elif clause.type == "implements_clause":
                                for name in _heritage_names(clause):
                                    result.edges.append(
                                        Edge(
                                            source_file=str(path),
                                            source_name=class_name,
                                            target_file="",
                                            target_name=name,
                                            kind="implements",
                                            certainty="definite",
                                            source_type="direct",
                                        )
                                    )
        for child in node.children:
            walk(child)

    walk(root)


def _heritage_names(clause) -> list[str]:
    """Yield the rightmost identifier from each name expression in a clause."""
    out: list[str] = []
    for child in clause.children:
        if child.type in ("identifier", "type_identifier"):
            out.append(child.text.decode())
        elif child.type == "member_expression":
            prop = child.child_by_field_name("property")
            if prop is not None:
                out.append(prop.text.decode())
        elif child.type in ("generic_type",):
            # extends Foo<T>: pick out the underlying name
            name_child = child.child_by_field_name(
                "name"
            ) or _first_named_child_of_types(child, ("identifier", "type_identifier"))
            if name_child is not None:
                out.append(name_child.text.decode())
    return out


# ── Import edge emission ──────────────────────────────────────────────────────


def _emit_import_edges(
    root,
    path: Path,
    source_root: Path,
    result: ExtractResult,
    captures: dict,
    path_aliases: dict[str, str],
) -> None:
    """Walk import_statement nodes to emit correctly paired (name, module) edges.

    For ``import { greet } from './b'`` we emit one edge per named import with
    ``target_name=greet``.  For bare ``import './side-effect'`` we emit a
    module-level edge with ``target_name='<module>'``.
    """

    def walk(node):
        if node.type == "import_statement":
            _process_import_statement(node, path, source_root, result, path_aliases)
        else:
            for child in node.children:
                walk(child)

    walk(root)


def _process_import_statement(
    node,
    path: Path,
    source_root: Path,
    result: ExtractResult,
    path_aliases: dict[str, str],
) -> None:
    """Emit edge(s) for a single import_statement node."""
    # Find the source string child (the module specifier).
    source_node = None
    for child in node.children:
        if child.type == "string":
            source_node = child
            break
    if source_node is None:
        return

    raw_spec = source_node.text.decode().strip("\"'")
    target = _resolve_ts_import(raw_spec, path.parent, source_root, path_aliases)
    if target is None:
        return

    # Collect named imports from import_clause / named_imports.
    named: list[str] = []
    for child in node.children:
        if child.type == "import_clause":
            _collect_named_imports(child, named)

    if named:
        for name in named:
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
    else:
        # Bare import or namespace import — module-level edge.
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


def _collect_named_imports(import_clause_node, names: list[str]) -> None:
    """Recursively collect identifier names from an import_clause node."""
    for child in import_clause_node.children:
        if child.type == "named_imports":
            for grandchild in child.children:
                if grandchild.type == "import_specifier":
                    # The first identifier child is the original export name.
                    name_node = grandchild.child_by_field_name("name")
                    if name_node is None:
                        # Fallback: first identifier child.
                        for gc in grandchild.children:
                            if gc.type == "identifier":
                                names.append(gc.text.decode())
                                break
                    else:
                        names.append(name_node.text.decode())
        elif child.type == "import_clause":
            _collect_named_imports(child, names)


# ── Module resolution ─────────────────────────────────────────────────────────


def _resolve_ts_import(
    spec: str,
    from_dir: Path,
    source_root: Path,
    path_aliases: dict[str, str],
) -> Path | None:
    """Resolve a module specifier to an absolute Path inside source_root.

    Handles:
    - Relative paths (``./b``, ``../utils/helpers``)
    - Path aliases from tsconfig.json ``compilerOptions.paths``

    Non-relative, non-aliased specifiers (bare npm packages) are ignored and
    return None.
    """
    # Apply tsconfig path aliases first.
    spec = _apply_path_aliases(spec, path_aliases, source_root)

    if not spec.startswith("."):
        # Not a relative or aliased-to-relative path — external package.
        return None

    base = (from_dir / spec).resolve()

    # Exact-match short-circuit: import "./module.ts" must find module.ts as-is
    # before any extension probing.
    if base.exists() and base.is_file() and _is_inside(base, source_root):
        return base

    # Try with extensions appended (covers extensionless specifiers like "./b").
    for ext in _TS_EXTENSIONS:
        candidate = Path(str(base) + ext)
        if candidate.exists() and _is_inside(candidate, source_root):
            return candidate

    # Try as a directory with an index file.
    for ext in _TS_EXTENSIONS:
        candidate = base / f"index{ext}"
        if candidate.exists() and _is_inside(candidate, source_root):
            return candidate

    return None


def _apply_path_aliases(spec: str, aliases: dict[str, str], source_root: Path) -> str:
    """Substitute tsconfig path aliases in a module specifier.

    ``aliases`` maps a prefix (possibly ending in ``*``) to a replacement
    directory path relative to source_root.  Returns the potentially rewritten
    spec (which will be relative if successfully aliased).
    """
    for pattern, replacement in aliases.items():
        if pattern.endswith("/*"):
            prefix = pattern[:-2]  # strip trailing /*
            if spec.startswith(prefix + "/"):
                suffix = spec[len(prefix) + 1 :]
                # replacement may also end in /*
                repl_base = replacement.rstrip("/*").rstrip("/")
                abs_replacement = (source_root / repl_base / suffix).resolve()
                try:
                    rel = abs_replacement.relative_to(source_root.resolve())
                    return "./" + str(rel)
                except ValueError:
                    pass
        elif spec == pattern:
            abs_replacement = (source_root / replacement).resolve()
            try:
                rel = abs_replacement.relative_to(source_root.resolve())
                return "./" + str(rel)
            except ValueError:
                pass
    return spec


def _is_inside(path: Path, root: Path) -> bool:
    """Return True if path is inside root (both resolved)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_tsconfig_paths(source_root: Path) -> dict[str, str]:
    """Parse compilerOptions.paths from tsconfig.json at source_root.

    Returns an empty dict if the file is absent or malformed.
    Each value list is flattened to the first entry (wildcards preserved).
    """
    tsconfig = source_root / "tsconfig.json"
    if not tsconfig.exists():
        return {}
    try:
        data = json.loads(tsconfig.read_text())
        raw_paths = data.get("compilerOptions", {}).get("paths", {})
        # Flatten: pattern -> first path entry.
        return {
            pattern: entries[0]
            for pattern, entries in raw_paths.items()
            if isinstance(entries, list) and entries
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


# ── AST helpers ───────────────────────────────────────────────────────────────


def _enclosing_symbol_name(node) -> str:
    """Walk up to find the enclosing function or class name."""
    cur = node.parent
    while cur is not None:
        if cur.type in (
            "function_declaration",
            "method_definition",
            "class_declaration",
        ):
            name_node = cur.child_by_field_name("name") or _first_named_child_of_types(
                cur, ("identifier", "property_identifier", "type_identifier")
            )
            if name_node is not None:
                return name_node.text.decode()
        cur = cur.parent
    return "<module>"


def _enclosing_definition(node):
    """Return the enclosing definition node for an identifier capture."""
    cur = node.parent
    while cur is not None:
        if cur.type in (
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "method_definition",
            "lexical_declaration",
            "variable_declarator",
        ):
            return cur
        cur = cur.parent
    return None


def _enclosing_class_name(node) -> str | None:
    """Walk up to find the enclosing class_declaration name, if any."""
    cur = node.parent
    while cur is not None:
        if cur.type == "class_declaration":
            name_node = cur.child_by_field_name("name") or _first_named_child_of_types(
                cur, ("type_identifier",)
            )
            if name_node is not None:
                return name_node.text.decode()
        cur = cur.parent
    return None


def _first_named_child_of_types(node, types: tuple[str, ...]):
    """Return the first named child whose type is in ``types``, or None."""
    for child in node.children:
        if child.type in types:
            return child
    return None
