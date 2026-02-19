"""Tests for SemanticIndexer -- converts SymbolDefinitions to CodeChunks and indexes them.

Covers basic indexing, empty input, content extraction, ChromaStore interaction,
SymbolDB back-linking, edge cases (line range overflow, empty content), and
multiple symbols from the same file.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call

from src.codebase_intelligence.services.semantic_indexer import SemanticIndexer
from src.shared.models.codebase import SymbolDefinition, SymbolKind, Language, CodeChunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SOURCE = b"""class UserService:
    \"\"\"User service class.\"\"\"

    def get_user(self, user_id: int):
        return self.db.get(user_id)

    def create_user(self, data: dict):
        return self.db.create(data)
"""


@pytest.fixture()
def chroma_store() -> MagicMock:
    """Mock ChromaStore with add_chunks method."""
    return MagicMock()


@pytest.fixture()
def symbol_db() -> MagicMock:
    """Mock SymbolDB with update_chroma_id method."""
    return MagicMock()


@pytest.fixture()
def indexer(chroma_store: MagicMock, symbol_db: MagicMock) -> SemanticIndexer:
    """SemanticIndexer wired with mocked dependencies."""
    return SemanticIndexer(chroma_store=chroma_store, symbol_db=symbol_db)


def _make_symbol(
    *,
    file_path: str = "services/user.py",
    symbol_name: str = "UserService",
    kind: SymbolKind = SymbolKind.CLASS,
    language: Language = Language.PYTHON,
    service_name: str | None = "user-service",
    line_start: int = 1,
    line_end: int = 8,
) -> SymbolDefinition:
    """Helper to build a SymbolDefinition with sensible defaults."""
    return SymbolDefinition(
        file_path=file_path,
        symbol_name=symbol_name,
        kind=kind,
        language=language,
        service_name=service_name,
        line_start=line_start,
        line_end=line_end,
    )


# ---------------------------------------------------------------------------
# 1. Basic indexing: symbols are converted to CodeChunks with correct metadata
# ---------------------------------------------------------------------------


class TestBasicIndexing:
    """Symbols are converted to CodeChunks with correct metadata."""

    def test_single_symbol_produces_one_chunk(
        self, indexer: SemanticIndexer
    ) -> None:
        """A single symbol should produce exactly one CodeChunk."""
        symbols = [_make_symbol()]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        assert len(chunks) == 1

    def test_chunk_metadata_matches_symbol(
        self, indexer: SemanticIndexer
    ) -> None:
        """The CodeChunk fields should mirror the source SymbolDefinition."""
        sym = _make_symbol(
            file_path="services/user.py",
            symbol_name="UserService",
            kind=SymbolKind.CLASS,
            language=Language.PYTHON,
            service_name="user-service",
            line_start=1,
            line_end=8,
        )
        chunks = indexer.index_symbols([sym], SAMPLE_SOURCE)

        chunk = chunks[0]
        assert chunk.id == "services/user.py::UserService"
        assert chunk.file_path == "services/user.py"
        assert chunk.language == "python"
        assert chunk.service_name == "user-service"
        assert chunk.symbol_name == "UserService"
        assert chunk.symbol_kind == SymbolKind.CLASS
        assert chunk.line_start == 1
        assert chunk.line_end == 8

    def test_chunk_is_codechunk_instance(
        self, indexer: SemanticIndexer
    ) -> None:
        """Each item in the returned list should be a CodeChunk model."""
        chunks = indexer.index_symbols([_make_symbol()], SAMPLE_SOURCE)

        assert isinstance(chunks[0], CodeChunk)


# ---------------------------------------------------------------------------
# 2. Empty symbols list returns empty list
# ---------------------------------------------------------------------------


class TestEmptySymbols:
    """An empty symbols list returns an empty list without side effects."""

    def test_empty_list_returns_empty(
        self,
        indexer: SemanticIndexer,
        chroma_store: MagicMock,
        symbol_db: MagicMock,
    ) -> None:
        """Passing an empty list should return [] immediately."""
        result = indexer.index_symbols([], SAMPLE_SOURCE)

        assert result == []

    def test_empty_list_does_not_call_chroma(
        self,
        indexer: SemanticIndexer,
        chroma_store: MagicMock,
    ) -> None:
        """No ChromaStore interaction when the symbol list is empty."""
        indexer.index_symbols([], SAMPLE_SOURCE)

        chroma_store.add_chunks.assert_not_called()

    def test_empty_list_does_not_call_symbol_db(
        self,
        indexer: SemanticIndexer,
        symbol_db: MagicMock,
    ) -> None:
        """No SymbolDB interaction when the symbol list is empty."""
        indexer.index_symbols([], SAMPLE_SOURCE)

        symbol_db.update_chroma_id.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Content extraction: correct source lines are extracted for each symbol
# ---------------------------------------------------------------------------


class TestContentExtraction:
    """The correct source lines are extracted into chunk.content."""

    def test_full_class_content(self, indexer: SemanticIndexer) -> None:
        """Extracting lines 1-8 should capture the entire UserService class."""
        sym = _make_symbol(line_start=1, line_end=8)
        chunks = indexer.index_symbols([sym], SAMPLE_SOURCE)

        content = chunks[0].content
        assert "class UserService:" in content
        assert "def get_user" in content
        assert "def create_user" in content

    def test_single_method_content(self, indexer: SemanticIndexer) -> None:
        """Extracting only the get_user method lines."""
        sym = _make_symbol(
            symbol_name="get_user",
            kind=SymbolKind.METHOD,
            line_start=4,
            line_end=5,
        )
        chunks = indexer.index_symbols([sym], SAMPLE_SOURCE)

        content = chunks[0].content
        assert "def get_user" in content
        assert "return self.db.get(user_id)" in content
        # The class definition should NOT be in this extract
        assert "class UserService:" not in content

    def test_content_preserves_indentation(
        self, indexer: SemanticIndexer
    ) -> None:
        """Extracted content should preserve original indentation."""
        sym = _make_symbol(
            symbol_name="get_user",
            kind=SymbolKind.METHOD,
            line_start=4,
            line_end=5,
        )
        chunks = indexer.index_symbols([sym], SAMPLE_SOURCE)

        # The method body line should be indented
        lines = chunks[0].content.splitlines()
        assert any(line.startswith("    ") for line in lines)


# ---------------------------------------------------------------------------
# 4. ChromaStore.add_chunks is called with the right chunks
# ---------------------------------------------------------------------------


class TestChromaStoreInteraction:
    """ChromaStore.add_chunks is called with the correct chunks."""

    def test_add_chunks_called_once(
        self, indexer: SemanticIndexer, chroma_store: MagicMock
    ) -> None:
        """add_chunks should be called exactly once per index_symbols call."""
        symbols = [_make_symbol()]
        indexer.index_symbols(symbols, SAMPLE_SOURCE)

        chroma_store.add_chunks.assert_called_once()

    def test_add_chunks_receives_all_chunks(
        self, indexer: SemanticIndexer, chroma_store: MagicMock
    ) -> None:
        """add_chunks should receive a list containing every produced chunk."""
        symbols = [
            _make_symbol(symbol_name="UserService", line_start=1, line_end=8),
            _make_symbol(
                symbol_name="get_user",
                kind=SymbolKind.METHOD,
                line_start=4,
                line_end=5,
            ),
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        chroma_store.add_chunks.assert_called_once_with(chunks)

    def test_add_chunks_receives_codechunk_objects(
        self, indexer: SemanticIndexer, chroma_store: MagicMock
    ) -> None:
        """The list passed to add_chunks should contain CodeChunk instances."""
        indexer.index_symbols([_make_symbol()], SAMPLE_SOURCE)

        passed_chunks = chroma_store.add_chunks.call_args[0][0]
        assert all(isinstance(c, CodeChunk) for c in passed_chunks)


# ---------------------------------------------------------------------------
# 5. SymbolDB.update_chroma_id is called for each chunk
# ---------------------------------------------------------------------------


class TestSymbolDBBackLink:
    """SymbolDB.update_chroma_id is called for each produced chunk."""

    def test_update_chroma_id_called_for_single_chunk(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """One symbol should trigger one update_chroma_id call."""
        indexer.index_symbols([_make_symbol()], SAMPLE_SOURCE)

        symbol_db.update_chroma_id.assert_called_once()

    def test_update_chroma_id_called_for_each_chunk(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """N valid symbols should trigger N update_chroma_id calls."""
        symbols = [
            _make_symbol(symbol_name="UserService", line_start=1, line_end=8),
            _make_symbol(
                symbol_name="get_user",
                kind=SymbolKind.METHOD,
                line_start=4,
                line_end=5,
            ),
        ]
        indexer.index_symbols(symbols, SAMPLE_SOURCE)

        assert symbol_db.update_chroma_id.call_count == 2

    def test_update_chroma_id_called_with_correct_ids(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """update_chroma_id should be called with (chunk.id, chunk.id) for each chunk."""
        sym = _make_symbol(
            file_path="services/user.py",
            symbol_name="UserService",
        )
        indexer.index_symbols([sym], SAMPLE_SOURCE)

        expected_id = "services/user.py::UserService"
        symbol_db.update_chroma_id.assert_called_once_with(expected_id, expected_id)

    def test_update_chroma_id_calls_match_all_chunks(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """The set of update_chroma_id calls should match the set of returned chunks."""
        symbols = [
            _make_symbol(symbol_name="UserService", line_start=1, line_end=8),
            _make_symbol(
                symbol_name="get_user",
                kind=SymbolKind.METHOD,
                line_start=4,
                line_end=5,
            ),
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        expected_calls = [call(c.id, c.id) for c in chunks]
        symbol_db.update_chroma_id.assert_has_calls(expected_calls, any_order=False)


# ---------------------------------------------------------------------------
# 6. Edge case: symbol line range exceeds source length (skipped)
# ---------------------------------------------------------------------------


class TestLineRangeExceedsSource:
    """Symbols whose line_start exceeds the source length are skipped."""

    def test_out_of_range_symbol_skipped(
        self, indexer: SemanticIndexer
    ) -> None:
        """A symbol starting beyond the source should produce no chunks."""
        # SAMPLE_SOURCE has ~9 lines; line_start=100 is far beyond that
        sym = _make_symbol(line_start=100, line_end=110)
        result = indexer.index_symbols([sym], SAMPLE_SOURCE)

        assert result == []

    def test_out_of_range_symbol_no_chroma_call(
        self, indexer: SemanticIndexer, chroma_store: MagicMock
    ) -> None:
        """When all symbols are out of range, ChromaStore should not be called."""
        sym = _make_symbol(line_start=100, line_end=110)
        indexer.index_symbols([sym], SAMPLE_SOURCE)

        chroma_store.add_chunks.assert_not_called()

    def test_out_of_range_symbol_no_db_call(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """When all symbols are out of range, SymbolDB should not be called."""
        sym = _make_symbol(line_start=100, line_end=110)
        indexer.index_symbols([sym], SAMPLE_SOURCE)

        symbol_db.update_chroma_id.assert_not_called()

    def test_end_clamped_to_source_length(
        self, indexer: SemanticIndexer
    ) -> None:
        """A symbol whose line_end exceeds the source is clamped, not skipped."""
        # line_start=1 is valid but line_end=999 exceeds the source
        sym = _make_symbol(line_start=1, line_end=999)
        result = indexer.index_symbols([sym], SAMPLE_SOURCE)

        assert len(result) == 1
        assert "class UserService:" in result[0].content


# ---------------------------------------------------------------------------
# 7. Edge case: symbol produces empty content (skipped)
# ---------------------------------------------------------------------------


class TestEmptyContent:
    """Symbols that resolve to empty (whitespace-only) content are skipped."""

    def test_blank_lines_only_skipped(
        self, indexer: SemanticIndexer
    ) -> None:
        """A symbol spanning only blank lines should be skipped."""
        # Line 3 of SAMPLE_SOURCE is an empty/whitespace-only line
        sym = _make_symbol(symbol_name="blank", line_start=3, line_end=3)
        result = indexer.index_symbols([sym], SAMPLE_SOURCE)

        assert result == []

    def test_blank_content_no_chroma_call(
        self, indexer: SemanticIndexer, chroma_store: MagicMock
    ) -> None:
        """When all content is blank, add_chunks should not be called."""
        sym = _make_symbol(symbol_name="blank", line_start=3, line_end=3)
        indexer.index_symbols([sym], SAMPLE_SOURCE)

        chroma_store.add_chunks.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Multiple symbols from the same file
# ---------------------------------------------------------------------------


class TestMultipleSymbolsSameFile:
    """Multiple symbols from one file are all indexed correctly."""

    def test_multiple_symbols_produce_multiple_chunks(
        self, indexer: SemanticIndexer
    ) -> None:
        """Three valid symbols should produce three CodeChunks."""
        symbols = [
            _make_symbol(symbol_name="UserService", kind=SymbolKind.CLASS, line_start=1, line_end=8),
            _make_symbol(symbol_name="get_user", kind=SymbolKind.METHOD, line_start=4, line_end=5),
            _make_symbol(symbol_name="create_user", kind=SymbolKind.METHOD, line_start=7, line_end=8),
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        assert len(chunks) == 3

    def test_each_chunk_has_unique_id(
        self, indexer: SemanticIndexer
    ) -> None:
        """Each chunk should have a distinct id derived from file_path::symbol_name."""
        symbols = [
            _make_symbol(symbol_name="UserService", kind=SymbolKind.CLASS, line_start=1, line_end=8),
            _make_symbol(symbol_name="get_user", kind=SymbolKind.METHOD, line_start=4, line_end=5),
            _make_symbol(symbol_name="create_user", kind=SymbolKind.METHOD, line_start=7, line_end=8),
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        ids = [c.id for c in chunks]
        assert len(set(ids)) == 3
        assert "services/user.py::UserService" in ids
        assert "services/user.py::get_user" in ids
        assert "services/user.py::create_user" in ids

    def test_each_chunk_has_correct_content(
        self, indexer: SemanticIndexer
    ) -> None:
        """Each chunk content should correspond to its symbol's line range."""
        symbols = [
            _make_symbol(symbol_name="UserService", kind=SymbolKind.CLASS, line_start=1, line_end=2),
            _make_symbol(symbol_name="get_user", kind=SymbolKind.METHOD, line_start=4, line_end=5),
            _make_symbol(symbol_name="create_user", kind=SymbolKind.METHOD, line_start=7, line_end=8),
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        chunk_map = {c.symbol_name: c for c in chunks}

        assert "class UserService:" in chunk_map["UserService"].content
        assert "def get_user" in chunk_map["get_user"].content
        assert "def create_user" in chunk_map["create_user"].content

    def test_valid_and_invalid_symbols_mixed(
        self, indexer: SemanticIndexer, symbol_db: MagicMock
    ) -> None:
        """Only valid symbols produce chunks; invalid ones are silently skipped."""
        symbols = [
            _make_symbol(symbol_name="UserService", line_start=1, line_end=8),
            _make_symbol(symbol_name="ghost", line_start=200, line_end=210),  # out of range
        ]
        chunks = indexer.index_symbols(symbols, SAMPLE_SOURCE)

        assert len(chunks) == 1
        assert chunks[0].symbol_name == "UserService"
        # Only one update_chroma_id call for the valid chunk
        symbol_db.update_chroma_id.assert_called_once()
