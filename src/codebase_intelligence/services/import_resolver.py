"""Import resolver for Python and TypeScript source files.

Resolves import statements found via tree-sitter AST queries into concrete
file paths, producing ``ImportReference`` objects that feed the dependency
graph.

Uses tree-sitter 0.25.2 API: ``Query(lang, pattern)`` then
``QueryCursor(query).matches(node)``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser, Query, QueryCursor

from src.shared.models.codebase import ImportReference

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tree-sitter query patterns
# ---------------------------------------------------------------------------

_PY_IMPORT_QUERY = "(import_statement) @import"
_PY_IMPORT_FROM_QUERY = "(import_from_statement) @import_from"

_TS_IMPORT_QUERY = "(import_statement) @import"

# ---------------------------------------------------------------------------
# File extensions
# ---------------------------------------------------------------------------

_PYTHON_EXTENSIONS = {".py", ".pyi"}
_TYPESCRIPT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}


class ImportResolver:
    """Resolves import statements to file paths for Python and TypeScript.

    Parses source files with tree-sitter, extracts import / from-import
    statements, and maps each to an ``ImportReference`` with a best-effort
    ``target_file`` path.
    """

    def __init__(self) -> None:
        self._py_lang: Language = Language(tree_sitter_python.language())
        self._ts_lang: Language = Language(tree_sitter_typescript.language_typescript())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_imports(
        self,
        source: bytes,
        file_path: str,
        project_root: str | None = None,
    ) -> list[ImportReference]:
        """Resolve import statements in source code to ImportReference objects.

        Args:
            source: Raw source bytes of the file.
            file_path: Path to the source file.
            project_root: Root directory of the project (used when resolving
                relative and aliased paths).

        Returns:
            List of ``ImportReference`` objects with resolved ``target_file``
            paths.
        """
        language = self._detect_language(file_path)

        if language == "python":
            return self._resolve_python_imports(source, file_path, project_root)
        elif language == "typescript":
            return self._resolve_typescript_imports(source, file_path, project_root)

        logger.debug("Unsupported language for import resolution: %s", file_path)
        return []

    # ------------------------------------------------------------------
    # Python import resolution
    # ------------------------------------------------------------------

    def _resolve_python_imports(
        self,
        source: bytes,
        file_path: str,
        project_root: str | None,
    ) -> list[ImportReference]:
        """Extract and resolve all Python import statements.

        Handles both ``import x.y.z`` and ``from x.y import z`` forms,
        including relative imports (leading dots).
        """
        parser = Parser(self._py_lang)
        tree = parser.parse(source)
        root = tree.root_node

        results: list[ImportReference] = []
        file_dir = str(Path(file_path).parent)

        # --- plain import statements (import os, import os.path) ----------
        import_query = Query(self._py_lang, _PY_IMPORT_QUERY)
        import_cursor = QueryCursor(import_query)

        for _pattern_idx, captures in import_cursor.matches(root):
            nodes = captures.get("import", [])
            if not nodes:
                continue
            node = nodes[0]
            line = node.start_point.row + 1

            # Collect dotted names.  Children of type ``dotted_name``
            # represent the imported modules.
            module_names = self._py_plain_import_names(node)
            for module_name in module_names:
                target = self._py_module_to_path(module_name, project_root)
                results.append(
                    ImportReference(
                        source_file=file_path,
                        target_file=target,
                        imported_names=[],
                        line=line,
                        is_relative=False,
                    )
                )

        # --- from ... import ... statements --------------------------------
        from_query = Query(self._py_lang, _PY_IMPORT_FROM_QUERY)
        from_cursor = QueryCursor(from_query)

        for _pattern_idx, captures in from_cursor.matches(root):
            nodes = captures.get("import_from", [])
            if not nodes:
                continue
            node = nodes[0]
            line = node.start_point.row + 1

            module_name, dot_count = self._py_from_module_name(node)
            imported_names = self._py_from_imported_names(node)
            is_relative = dot_count > 0

            if is_relative:
                target = self._py_resolve_relative(
                    module_name, dot_count, file_dir
                )
            else:
                target = self._py_module_to_path(module_name, project_root)

            results.append(
                ImportReference(
                    source_file=file_path,
                    target_file=target,
                    imported_names=imported_names,
                    line=line,
                    is_relative=is_relative,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Python AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _py_plain_import_names(node: Any) -> list[str]:
        """Return dotted module names from a plain ``import`` statement.

        Example: ``import os, sys`` -> ``["os", "sys"]``
        """
        names: list[str] = []
        for child in node.named_children:
            if child.type == "dotted_name":
                names.append(child.text.decode())
            elif child.type == "aliased_import":
                # ``import os.path as osp`` — the dotted_name is the first
                # named child of the aliased_import node.
                for sub in child.named_children:
                    if sub.type == "dotted_name":
                        names.append(sub.text.decode())
                        break
        return names

    @staticmethod
    def _py_from_module_name(node: Any) -> tuple[str, int]:
        """Extract the module name and leading-dot count from a
        ``from ... import ...`` statement.

        Returns:
            A tuple of ``(module_name, dot_count)``.  For ``from ..models
            import User`` this returns ``("models", 2)``.  For
            ``from . import foo`` this returns ``("", 1)``.
        """
        module_name = ""
        dot_count = 0

        # Only examine children that appear BEFORE the ``import`` keyword.
        # After ``import``, the children are the imported names, not the
        # module path.
        for child in node.children:
            if child.type == "import" or child.text == b"import":
                break
            # Leading dots are represented as individual "." tokens or a
            # single ``relative_import`` / ``import_prefix`` node depending
            # on the grammar version.
            if child.type == ".":
                dot_count += 1
            elif child.type == "dotted_name":
                module_name = child.text.decode()
            elif child.type == "relative_import":
                # The relative_import node contains the dots and optionally
                # a dotted_name.
                for sub in child.children:
                    if sub.type == "." or sub.type == "import_prefix":
                        text = sub.text.decode().strip()
                        dot_count += len(text)
                    elif sub.type == "dotted_name":
                        module_name = sub.text.decode()
            elif child.type == "import_prefix":
                dot_count = len(child.text.decode().strip())

        return module_name, dot_count

    @staticmethod
    def _py_from_imported_names(node: Any) -> list[str]:
        """Extract the list of names from the ``import`` clause of a
        ``from ... import ...`` statement.

        Returns names like ``["User", "Role"]`` from
        ``from models import User, Role``.  Handles aliased imports
        (``User as U``) by recording the original name.
        """
        names: list[str] = []
        # Walk through children looking for identifiers that appear after
        # the ``import`` keyword.
        past_import_keyword = False
        for child in node.children:
            if child.type == "import" or (
                child.type != "import" and child.text == b"import"
            ):
                past_import_keyword = True
                continue

            if not past_import_keyword:
                continue

            if child.type == "dotted_name":
                names.append(child.text.decode())
            elif child.type == "aliased_import":
                for sub in child.named_children:
                    if sub.type in ("dotted_name", "identifier"):
                        names.append(sub.text.decode())
                        break
            elif child.type == "identifier":
                names.append(child.text.decode())
            elif child.type == "wildcard_import":
                names.append("*")

        return names

    @staticmethod
    def _py_module_to_path(module_name: str, project_root: str | None) -> str:
        """Convert a dotted Python module name to a file-system path.

        Tries ``<module>.py`` first; if *project_root* is set and
        ``<module>/__init__.py`` exists on disk, that path is preferred.
        """
        if not module_name:
            return ""

        parts_path = Path(module_name.replace(".", "/"))
        candidate_file = str(parts_path.with_suffix(".py"))
        candidate_pkg = str(parts_path / "__init__.py")

        if project_root:
            root = Path(project_root)
            if (root / candidate_pkg).is_file():
                return candidate_pkg
            if (root / candidate_file).is_file():
                return candidate_file

        # Default: return the .py form even when we cannot verify on disk.
        return candidate_file

    @staticmethod
    def _py_resolve_relative(
        module_name: str, dot_count: int, file_dir: str
    ) -> str:
        """Resolve a relative Python import to a file path.

        Args:
            module_name: Module name after the dots (may be empty for
                ``from . import foo``).
            dot_count: Number of leading dots (1 = current package, 2 =
                parent package, etc.).
            file_dir: Directory of the file containing the import.
        """
        # Walk up directories: one dot means the current directory, each
        # additional dot means one level up.
        base = Path(file_dir)
        for _ in range(dot_count - 1):
            base = base.parent

        if module_name:
            parts = module_name.split(".")
            target_dir = base.joinpath(*parts[:-1]) if len(parts) > 1 else base
            leaf = parts[-1]

            candidate_file = target_dir / f"{leaf}.py"
            candidate_pkg = target_dir / leaf / "__init__.py"

            if candidate_pkg.is_file():
                return str(candidate_pkg)
            if candidate_file.is_file():
                return str(candidate_file)

            # Fallback: return the .py form.
            return str(target_dir / f"{leaf}.py")

        # ``from . import foo`` — point to the package __init__.py.
        init = base / "__init__.py"
        if init.is_file():
            return str(init)
        return str(base)

    # ------------------------------------------------------------------
    # TypeScript import resolution
    # ------------------------------------------------------------------

    def _resolve_typescript_imports(
        self,
        source: bytes,
        file_path: str,
        project_root: str | None,
    ) -> list[ImportReference]:
        """Extract and resolve all TypeScript / JavaScript import statements."""
        parser = Parser(self._ts_lang)
        tree = parser.parse(source)
        root = tree.root_node

        results: list[ImportReference] = []
        file_dir = str(Path(file_path).parent)

        ts_paths = self._load_tsconfig_paths(project_root)

        import_query = Query(self._ts_lang, _TS_IMPORT_QUERY)
        import_cursor = QueryCursor(import_query)

        for _pattern_idx, captures in import_cursor.matches(root):
            nodes = captures.get("import", [])
            if not nodes:
                continue
            node = nodes[0]
            line = node.start_point.row + 1

            module_specifier = self._ts_module_specifier(node)
            if module_specifier is None:
                continue

            imported_names = self._ts_imported_names(node)

            if module_specifier.startswith("."):
                # ---- Relative import ------------------------------------
                target = self._ts_resolve_relative(module_specifier, file_dir)
                results.append(
                    ImportReference(
                        source_file=file_path,
                        target_file=target,
                        imported_names=imported_names,
                        line=line,
                        is_relative=True,
                    )
                )
            elif ts_paths and self._ts_match_path_alias(module_specifier, ts_paths):
                # ---- Path alias (e.g., @/utils) -------------------------
                resolved = self._ts_match_path_alias(module_specifier, ts_paths)
                target = self._ts_resolve_alias(
                    resolved, project_root or file_dir
                )
                results.append(
                    ImportReference(
                        source_file=file_path,
                        target_file=target,
                        imported_names=imported_names,
                        line=line,
                        is_relative=False,
                    )
                )
            else:
                # ---- Package import (e.g., 'express') -------------------
                results.append(
                    ImportReference(
                        source_file=file_path,
                        target_file=module_specifier,
                        imported_names=imported_names,
                        line=line,
                        is_relative=False,
                    )
                )

        return results

    # ------------------------------------------------------------------
    # TypeScript AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ts_module_specifier(node: Any) -> str | None:
        """Extract the module specifier string from an import statement node.

        Searches for the ``string`` child (the ``'./foo'`` part) and strips
        surrounding quotes.
        """
        source_node = node.child_by_field_name("source")
        if source_node is not None:
            raw = source_node.text.decode()
            return raw.strip("\"'")

        # Fallback: walk children looking for a string node.
        for child in node.named_children:
            if child.type == "string":
                raw = child.text.decode()
                return raw.strip("\"'")

        return None

    @staticmethod
    def _ts_imported_names(node: Any) -> list[str]:
        """Extract named imports from an import statement.

        Handles default imports, named imports (``{ A, B }``), namespace
        imports (``* as ns``), and combinations.
        """
        names: list[str] = []

        import_clause = node.child_by_field_name("import")
        if import_clause is None:
            # Try to find the import clause by walking children.
            for child in node.named_children:
                if child.type == "import_clause":
                    import_clause = child
                    break

        if import_clause is None:
            return names

        for child in import_clause.named_children:
            if child.type == "identifier":
                # Default import.
                names.append(child.text.decode())
            elif child.type == "named_imports":
                for spec in child.named_children:
                    if spec.type == "import_specifier":
                        name_node = spec.child_by_field_name("name")
                        if name_node is not None:
                            names.append(name_node.text.decode())
                        else:
                            # Fallback: first identifier child.
                            for sub in spec.named_children:
                                if sub.type == "identifier":
                                    names.append(sub.text.decode())
                                    break
            elif child.type == "namespace_import":
                # ``* as ns`` — record the alias.
                for sub in child.named_children:
                    if sub.type == "identifier":
                        names.append(sub.text.decode())
                        break

        return names

    @staticmethod
    def _ts_resolve_relative(specifier: str, file_dir: str) -> str:
        """Resolve a relative TypeScript import to a file path.

        Tries common extensions (.ts, .tsx, /index.ts, /index.tsx) and
        returns the first match found on disk; otherwise returns the
        specifier with ``.ts`` appended.
        """
        base = Path(file_dir) / specifier
        extensions = [".ts", ".tsx", ".js", ".jsx"]
        index_files = ["index.ts", "index.tsx", "index.js", "index.jsx"]

        # If the specifier already has an extension that exists, use it.
        if base.is_file():
            return str(base)

        # Try appending common extensions.
        for ext in extensions:
            candidate = Path(f"{base}{ext}")
            if candidate.is_file():
                return str(candidate)

        # Try index files inside a directory.
        for idx in index_files:
            candidate = base / idx
            if candidate.is_file():
                return str(candidate)

        # Fallback: assume .ts extension.
        return str(Path(f"{base}.ts"))

    @staticmethod
    def _load_tsconfig_paths(
        project_root: str | None,
    ) -> dict[str, list[str]] | None:
        """Load path aliases from tsconfig.json if available.

        Returns the ``compilerOptions.paths`` mapping, or ``None`` if the
        file is missing or doesn't define paths.
        """
        if not project_root:
            return None

        tsconfig_path = str(Path(project_root) / "tsconfig.json")
        try:
            with open(tsconfig_path, "r", encoding="utf-8") as fh:
                config = json.loads(fh.read())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

        paths: dict[str, list[str]] | None = (
            config.get("compilerOptions", {}).get("paths")
        )
        return paths if paths else None

    @staticmethod
    def _ts_match_path_alias(
        specifier: str, paths: dict[str, list[str]]
    ) -> str | None:
        """Match a module specifier against tsconfig path aliases.

        Supports wildcard patterns such as ``"@/*": ["src/*"]``.

        Returns:
            The resolved path template (with the wildcard portion
            substituted), or ``None`` if no alias matches.
        """
        for pattern, targets in paths.items():
            if "*" in pattern:
                prefix = pattern.split("*")[0]
                if specifier.startswith(prefix):
                    suffix = specifier[len(prefix):]
                    if targets:
                        return targets[0].replace("*", suffix)
            elif specifier == pattern:
                if targets:
                    return targets[0]
        return None

    @staticmethod
    def _ts_resolve_alias(resolved_path: str, base_dir: str) -> str:
        """Turn a tsconfig-resolved relative path into an absolute path and
        try common TypeScript extensions.
        """
        full = Path(base_dir) / resolved_path
        extensions = [".ts", ".tsx", ".js", ".jsx"]
        index_files = ["index.ts", "index.tsx", "index.js", "index.jsx"]

        if full.is_file():
            return str(full)

        for ext in extensions:
            candidate = Path(f"{full}{ext}")
            if candidate.is_file():
                return str(candidate)

        for idx in index_files:
            candidate = full / idx
            if candidate.is_file():
                return str(candidate)

        # Fallback: return as-is (with .ts extension).
        if not full.suffix:
            return str(Path(f"{full}.ts"))
        return str(full)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(file_path: str) -> str:
        """Detect the language of a file based on its extension.

        Returns:
            ``"python"``, ``"typescript"``, or ``"unknown"``.
        """
        ext = Path(file_path).suffix.lower()
        if ext in _PYTHON_EXTENSIONS:
            return "python"
        if ext in _TYPESCRIPT_EXTENSIONS:
            return "typescript"
        return "unknown"
