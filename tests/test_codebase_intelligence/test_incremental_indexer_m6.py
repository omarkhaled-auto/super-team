"""Tests for IncrementalIndexer -- Milestone 6 SemanticIndexer integration.

Covers the new step 7 (semantic indexing) wiring added in M6:
full pipeline with SemanticIndexer, backward compatibility when
SemanticIndexer is None, error handling, and the interaction
between semantic errors and overall pipeline success.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

import pytest

from src.codebase_intelligence.services.incremental_indexer import IncrementalIndexer
from src.shared.models.codebase import (
    ImportReference,
    Language,
    SymbolDefinition,
    SymbolKind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_SOURCE = b"class MyClass:\n    pass\n"

_SYMBOL = SymbolDefinition(
    file_path="test.py",
    symbol_name="MyClass",
    kind=SymbolKind.CLASS,
    language=Language.PYTHON,
    line_start=1,
    line_end=2,
)

_IMPORT = ImportReference(
    source_file="test.py",
    target_file="utils.py",
    imported_names=["helper"],
    line=1,
)


def _make_mocks(*, with_semantic: bool = True) -> dict:
    """Create the full set of mock dependencies for IncrementalIndexer.

    Parameters
    ----------
    with_semantic:
        When *True* a ``MagicMock`` is returned for ``semantic_indexer``;
        when *False* it is set to ``None`` to test backward compatibility.

    Returns
    -------
    dict
        Keys match IncrementalIndexer constructor parameter names.
    """
    ast_parser = MagicMock()
    ast_parser.detect_language.return_value = "python"
    ast_parser.parse_file.return_value = {
        "language": "python",
        "symbols": [{"name": "MyClass", "kind": SymbolKind.CLASS}],
        "tree": MagicMock(),
    }

    symbol_extractor = MagicMock()
    symbol_extractor.extract_symbols.return_value = [_SYMBOL]

    import_resolver = MagicMock()
    import_resolver.resolve_imports.return_value = [_IMPORT]

    graph_builder = MagicMock()
    symbol_db = MagicMock()
    graph_db = MagicMock()

    semantic_indexer: MagicMock | None = None
    if with_semantic:
        semantic_indexer = MagicMock()
        semantic_indexer.index_symbols.return_value = []

    return {
        "ast_parser": ast_parser,
        "symbol_extractor": symbol_extractor,
        "import_resolver": import_resolver,
        "graph_builder": graph_builder,
        "symbol_db": symbol_db,
        "graph_db": graph_db,
        "semantic_indexer": semantic_indexer,
    }


def _build_indexer(mocks: dict) -> IncrementalIndexer:
    """Construct an ``IncrementalIndexer`` from the mock dict."""
    return IncrementalIndexer(**mocks)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullPipelineWithSemanticIndexer:
    """index_file calls semantic_indexer.index_symbols when a
    SemanticIndexer is provided."""

    def test_index_file_calls_semantic_index_symbols(self) -> None:
        """When a SemanticIndexer is wired in, index_file must invoke
        ``index_symbols`` with the extracted symbols and the raw source."""
        mocks = _make_mocks(with_semantic=True)
        indexer = _build_indexer(mocks)

        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        # Semantic indexer should have been called exactly once.
        semantic = mocks["semantic_indexer"]
        semantic.index_symbols.assert_called_once_with(
            [_SYMBOL],
            _SAMPLE_SOURCE,
        )

        # The overall result should be successful.
        assert result["indexed"] is True
        assert result["errors"] == []


class TestBackwardCompatibilityWithoutSemanticIndexer:
    """When semantic_indexer is None the pipeline still succeeds and logs a
    debug message."""

    def test_no_semantic_indexer_still_works(self, caplog: pytest.LogCaptureFixture) -> None:
        """Passing ``semantic_indexer=None`` must not break index_file; a
        debug-level log about skipping embeddings is emitted."""
        mocks = _make_mocks(with_semantic=False)
        indexer = _build_indexer(mocks)

        with caplog.at_level(logging.DEBUG):
            result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert result["indexed"] is True
        assert result["errors"] == []
        # Verify the debug message was emitted.
        assert any(
            "SemanticIndexer not configured" in record.message
            for record in caplog.records
        )


class TestSemanticIndexerFailureAddedToErrors:
    """When SemanticIndexer.index_symbols raises, the error is caught and
    appended to the errors list."""

    def test_semantic_error_appended_to_errors(self) -> None:
        """A RuntimeError from index_symbols must appear in errors."""
        mocks = _make_mocks(with_semantic=True)
        semantic = mocks["semantic_indexer"]
        semantic.index_symbols.side_effect = RuntimeError("embedding service down")

        indexer = _build_indexer(mocks)
        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert len(result["errors"]) == 1
        assert "Semantic indexing failed" in result["errors"][0]
        assert "embedding service down" in result["errors"][0]


class TestFileIndexingProducesCorrectCounts:
    """index_file returns correct symbols_found and dependencies_found
    counts."""

    def test_correct_symbol_and_dependency_counts(self) -> None:
        """symbols_found must equal the number of symbols from the extractor,
        and dependencies_found must equal the number of resolved imports."""
        mocks = _make_mocks(with_semantic=True)

        # Return two symbols and three imports to check counts.
        second_symbol = SymbolDefinition(
            file_path="test.py",
            symbol_name="helper",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=4,
            line_end=6,
        )
        mocks["symbol_extractor"].extract_symbols.return_value = [_SYMBOL, second_symbol]

        second_import = ImportReference(
            source_file="test.py",
            target_file="models.py",
            imported_names=["User"],
            line=2,
        )
        third_import = ImportReference(
            source_file="test.py",
            target_file="config.py",
            imported_names=["Settings"],
            line=3,
        )
        mocks["import_resolver"].resolve_imports.return_value = [
            _IMPORT,
            second_import,
            third_import,
        ]

        indexer = _build_indexer(mocks)
        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert result["symbols_found"] == 2
        assert result["dependencies_found"] == 3


class TestSemanticErrorDoesNotPreventPipelineSuccess:
    """A semantic indexing error must NOT prevent the rest of the pipeline
    from succeeding -- symbols and imports are still counted correctly."""

    def test_pipeline_counts_survive_semantic_failure(self) -> None:
        """Even when semantic indexing raises, the symbols_found and
        dependencies_found fields should still be populated and the
        database persistence calls should have been made."""
        mocks = _make_mocks(with_semantic=True)
        semantic = mocks["semantic_indexer"]
        semantic.index_symbols.side_effect = ValueError("bad embedding dimensions")

        indexer = _build_indexer(mocks)
        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        # Counts are correct despite the semantic failure.
        assert result["symbols_found"] == 1
        assert result["dependencies_found"] == 1

        # Database persistence still happened.
        mocks["symbol_db"].save_file.assert_called_once()
        mocks["symbol_db"].save_symbols.assert_called_once()
        mocks["symbol_db"].save_imports.assert_called_once()
        mocks["graph_db"].save_edges.assert_called_once()

        # The error is recorded.
        assert len(result["errors"]) == 1
        assert "Semantic indexing failed" in result["errors"][0]


class TestReturnDictIncludesIndexedTrue:
    """When there are zero errors the return dict has indexed=True."""

    def test_indexed_true_when_no_errors(self) -> None:
        """A clean run -- no exception anywhere -- must return
        ``indexed=True``."""
        mocks = _make_mocks(with_semantic=True)
        indexer = _build_indexer(mocks)

        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert result["indexed"] is True
        assert result["errors"] == []
        assert result["symbols_found"] >= 0
        assert result["dependencies_found"] >= 0

    def test_indexed_false_when_semantic_error(self) -> None:
        """If the only error is a semantic one, indexed must be False because
        the errors list is non-empty."""
        mocks = _make_mocks(with_semantic=True)
        mocks["semantic_indexer"].index_symbols.side_effect = RuntimeError("boom")

        indexer = _build_indexer(mocks)
        result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert result["indexed"] is False
        assert len(result["errors"]) == 1


class TestSemanticIndexerReceivesCorrectArguments:
    """Verify the exact arguments that reach index_symbols match what
    the earlier pipeline stages produced."""

    def test_symbols_and_source_forwarded(self) -> None:
        """index_symbols must receive the list returned by
        symbol_extractor.extract_symbols and the original source bytes."""
        mocks = _make_mocks(with_semantic=True)
        custom_source = b"def greet():\n    return 'hi'\n"
        custom_symbol = SymbolDefinition(
            file_path="greet.py",
            symbol_name="greet",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=1,
            line_end=2,
        )
        mocks["symbol_extractor"].extract_symbols.return_value = [custom_symbol]

        indexer = _build_indexer(mocks)
        indexer.index_file("greet.py", source=custom_source)

        mocks["semantic_indexer"].index_symbols.assert_called_once_with(
            [custom_symbol],
            custom_source,
        )


class TestSemanticIndexerLogsOnSuccess:
    """On successful semantic indexing an info-level log is emitted with the
    chunk count."""

    def test_info_log_on_semantic_success(self, caplog: pytest.LogCaptureFixture) -> None:
        """After index_symbols returns, an info message should mention the
        number of chunks created."""
        mocks = _make_mocks(with_semantic=True)
        # Simulate 3 chunks returned.
        mocks["semantic_indexer"].index_symbols.return_value = [
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]

        indexer = _build_indexer(mocks)
        with caplog.at_level(logging.INFO):
            result = indexer.index_file("test.py", source=_SAMPLE_SOURCE)

        assert result["indexed"] is True
        assert any(
            "3 chunks created" in record.message
            for record in caplog.records
        )
