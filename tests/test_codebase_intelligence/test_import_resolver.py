"""Tests for ImportResolver — resolves import statements to file paths.

Covers Python absolute imports, from-imports, relative imports (single and
double dot), TypeScript relative and package imports, unsupported languages,
line-number correctness, multiple imports in one file, and TypeScript
parent-relative imports.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.codebase_intelligence.services.import_resolver import ImportResolver
from src.shared.models.codebase import ImportReference


@pytest.fixture()
def resolver() -> ImportResolver:
    """Return a fresh ImportResolver instance for each test."""
    return ImportResolver()


class TestPythonAbsoluteImport:
    """import os — absolute module import."""

    def test_python_absolute_import(self, resolver: ImportResolver) -> None:
        """Plain ``import os`` resolves to ``os.py`` with is_relative=False."""
        source = b"import os\n"
        results = resolver.resolve_imports(source, "src/main.py")

        assert len(results) == 1
        ref = results[0]
        assert ref.source_file == "src/main.py"
        assert ref.target_file == "os.py"
        assert ref.is_relative is False
        assert ref.imported_names == []


class TestPythonFromImport:
    """from datetime import datetime — extracts imported_names."""

    def test_python_from_import(self, resolver: ImportResolver) -> None:
        """``from datetime import datetime`` extracts 'datetime' in imported_names."""
        source = b"from datetime import datetime\n"
        results = resolver.resolve_imports(source, "src/app.py")

        assert len(results) == 1
        ref = results[0]
        assert ref.target_file == "datetime.py"
        assert "datetime" in ref.imported_names
        assert ref.is_relative is False


class TestPythonRelativeImportDot:
    """from .models import User — single-dot relative import."""

    def test_python_relative_import_dot(self, resolver: ImportResolver) -> None:
        """Single-dot relative import resolves relative to file directory,
        with is_relative=True."""
        source = b"from .models import User\n"
        results = resolver.resolve_imports(source, "src/auth/views.py")

        assert len(results) == 1
        ref = results[0]
        # Single dot means same directory as file_dir => src/auth/models.py
        expected_target = str(Path("src/auth") / "models.py")
        assert ref.target_file == expected_target
        assert ref.is_relative is True
        assert "User" in ref.imported_names


class TestPythonRelativeImportDoubleDot:
    """from ..shared import config — double-dot relative import."""

    def test_python_relative_import_double_dot(self, resolver: ImportResolver) -> None:
        """Double-dot import goes up two levels from the file directory."""
        source = b"from ..shared import config\n"
        results = resolver.resolve_imports(source, "src/auth/views.py")

        assert len(results) == 1
        ref = results[0]
        # Double dot: from src/auth go up one level => src, then resolve shared.
        # The resolver checks the filesystem.  If src/shared/__init__.py exists
        # on disk it returns the package form; otherwise it falls back to
        # src/shared.py.  We accept either valid resolution.
        normalised = str(Path(ref.target_file))
        assert normalised in (
            str(Path("src") / "shared.py"),
            str(Path("src") / "shared" / "__init__.py"),
        )
        assert ref.is_relative is True
        assert "config" in ref.imported_names


class TestTypescriptRelativeImport:
    """import { User } from './models' — TypeScript relative import."""

    def test_typescript_relative_import(self, resolver: ImportResolver) -> None:
        """Relative TS import resolves with .ts extension appended."""
        source = b"import { User } from './models';\n"
        results = resolver.resolve_imports(source, "src/auth/views.ts")

        assert len(results) == 1
        ref = results[0]
        # Relative specifier './models' resolved from src/auth => src/auth/models.ts
        expected_target = str(Path("src/auth") / "models.ts")
        assert ref.target_file == expected_target
        assert ref.is_relative is True
        assert "User" in ref.imported_names


class TestTypescriptPackageImport:
    """import express from 'express' — package (non-relative) import."""

    def test_typescript_package_import(self, resolver: ImportResolver) -> None:
        """Package import sets is_relative=False and target_file to the package name."""
        source = b"import express from 'express';\n"
        results = resolver.resolve_imports(source, "src/server.ts")

        assert len(results) == 1
        ref = results[0]
        assert ref.target_file == "express"
        assert ref.is_relative is False
        assert "express" in ref.imported_names


class TestUnsupportedLanguage:
    """A .go file returns an empty list."""

    def test_unsupported_language(self, resolver: ImportResolver) -> None:
        """Files with unsupported extensions return no import references."""
        source = b'package main\nimport "fmt"\n'
        results = resolver.resolve_imports(source, "cmd/main.go")

        assert results == []


class TestLineNumbersCorrect:
    """Line numbers are 1-indexed."""

    def test_line_numbers_correct(self, resolver: ImportResolver) -> None:
        """Import on the first line of a file reports line=1."""
        source = b"import os\n"
        results = resolver.resolve_imports(source, "app.py")

        assert len(results) == 1
        assert results[0].line == 1

    def test_line_numbers_for_later_lines(self, resolver: ImportResolver) -> None:
        """Import on line 3 reports line=3 (1-indexed, not 0-indexed)."""
        source = b"# comment\n# another comment\nimport sys\n"
        results = resolver.resolve_imports(source, "app.py")

        assert len(results) == 1
        assert results[0].line == 3


class TestPythonMultipleImports:
    """Multiple imports in one file are all captured."""

    def test_python_multiple_imports(self, resolver: ImportResolver) -> None:
        """Several import statements in a single file produce one
        ImportReference per statement."""
        source = b"import os\nimport sys\nfrom pathlib import Path\n"
        results = resolver.resolve_imports(source, "src/util.py")

        assert len(results) == 3
        target_files = {r.target_file for r in results}
        assert "os.py" in target_files
        assert "sys.py" in target_files
        assert "pathlib.py" in target_files

    def test_python_from_import_multiple_names(self, resolver: ImportResolver) -> None:
        """``from os.path import join, exists`` captures both names."""
        source = b"from os.path import join, exists\n"
        results = resolver.resolve_imports(source, "src/util.py")

        assert len(results) == 1
        ref = results[0]
        assert "join" in ref.imported_names
        assert "exists" in ref.imported_names


class TestTypescriptRelativeDotDot:
    """import { config } from '../shared/config' — TS parent-relative import."""

    def test_typescript_relative_dotdot(self, resolver: ImportResolver) -> None:
        """TypeScript ``../`` import resolves correctly to the parent directory."""
        source = b"import { config } from '../shared/config';\n"
        results = resolver.resolve_imports(source, "src/auth/views.ts")

        assert len(results) == 1
        ref = results[0]
        # '../shared/config' from src/auth => src/auth/../shared/config.ts
        # The resolver joins the specifier as-is; normalise before comparing.
        normalised = str(Path(ref.target_file).resolve())
        expected = str((Path("src/auth") / ".." / "shared" / "config.ts").resolve())
        assert normalised == expected
        assert ref.is_relative is True
        assert "config" in ref.imported_names
