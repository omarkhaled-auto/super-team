"""Tests for src.codebase_intelligence.services.semantic_searcher.SemanticSearcher.

Covers the search method including:
    1. Basic search returns a list of SemanticSearchResult
    2. Language filter applied correctly
    3. Service name filter applied correctly
    4. Combined filters use $and operator
    5. Score conversion: distance 0.0 -> score 1.0, distance 0.5 -> score 0.5
    6. top_k parameter passed correctly
    7. Empty results return empty list
    8. ChromaDB error returns empty list (graceful degradation)
    9. Metadata empty strings converted to None
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.codebase_intelligence.services.semantic_searcher import SemanticSearcher
from src.shared.models.codebase import SemanticSearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chroma_result(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    distances: list[float],
) -> dict:
    """Build a ChromaDB-shaped result dict with outer wrapping lists."""
    return {
        "ids": [ids],
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [distances],
    }


def _default_chroma_result() -> dict:
    """Return a two-hit ChromaDB result used by most tests."""
    return _make_chroma_result(
        ids=["file.py::MyClass", "file.py::my_func"],
        documents=["class MyClass:\n    pass", "def my_func():\n    pass"],
        metadatas=[
            {
                "file_path": "file.py",
                "symbol_name": "MyClass",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "auth",
                "line_start": 1,
                "line_end": 2,
            },
            {
                "file_path": "file.py",
                "symbol_name": "my_func",
                "symbol_kind": "function",
                "language": "python",
                "service_name": "",
                "line_start": 4,
                "line_end": 5,
            },
        ],
        distances=[0.1, 0.3],
    )


def _make_searcher(chroma_result: dict | None = None) -> tuple[SemanticSearcher, MagicMock]:
    """Build a SemanticSearcher backed by a MagicMock ChromaStore.

    Returns both the searcher and the mock store so tests can inspect
    the calls made to the store.
    """
    mock_store = MagicMock()
    if chroma_result is not None:
        mock_store.query.return_value = chroma_result
    else:
        mock_store.query.return_value = _default_chroma_result()
    return SemanticSearcher(mock_store), mock_store


# ---------------------------------------------------------------------------
# 1. Basic search returns SemanticSearchResult list
# ---------------------------------------------------------------------------

class TestBasicSearch:
    """A simple search with no filters returns correctly typed results."""

    def test_basic_search_returns_semantic_search_result_list(self) -> None:
        """search() with only a query must return a list of
        SemanticSearchResult instances with fields populated from the
        ChromaDB result."""
        searcher, mock_store = _make_searcher()

        results = searcher.search("find MyClass")

        assert isinstance(results, list)
        assert len(results) == 2
        for r in results:
            assert isinstance(r, SemanticSearchResult)

        # Verify first result fields
        first = results[0]
        assert first.chunk_id == "file.py::MyClass"
        assert first.file_path == "file.py"
        assert first.symbol_name == "MyClass"
        assert first.language == "python"
        assert first.content == "class MyClass:\n    pass"
        assert first.line_start == 1
        assert first.line_end == 2

        # Verify store was called with no where filter
        mock_store.query.assert_called_once_with(
            query_text="find MyClass",
            n_results=10,
            where=None,
        )


# ---------------------------------------------------------------------------
# 2. Language filter applied correctly
# ---------------------------------------------------------------------------

class TestLanguageFilter:
    """Providing a language filter should produce a where dict with the
    language key."""

    def test_language_filter_passed_to_chroma(self) -> None:
        """When language='typescript' is provided, the where filter must
        be ``{"language": "typescript"}``."""
        searcher, mock_store = _make_searcher()

        searcher.search("find class", language="typescript")

        mock_store.query.assert_called_once_with(
            query_text="find class",
            n_results=10,
            where={"language": "typescript"},
        )


# ---------------------------------------------------------------------------
# 3. Service name filter applied correctly
# ---------------------------------------------------------------------------

class TestServiceNameFilter:
    """Providing a service_name filter should produce a where dict with
    the service_name key."""

    def test_service_name_filter_passed_to_chroma(self) -> None:
        """When service_name='auth' is provided, the where filter must
        be ``{"service_name": "auth"}``."""
        searcher, mock_store = _make_searcher()

        searcher.search("auth logic", service_name="auth")

        mock_store.query.assert_called_once_with(
            query_text="auth logic",
            n_results=10,
            where={"service_name": "auth"},
        )


# ---------------------------------------------------------------------------
# 4. Combined filters use $and operator
# ---------------------------------------------------------------------------

class TestCombinedFilters:
    """When both language and service_name are provided the where filter
    must use the ``$and`` operator to combine them."""

    def test_combined_filters_use_and_operator(self) -> None:
        """Providing both language='python' and service_name='auth'
        should produce a where filter with ``$and``."""
        searcher, mock_store = _make_searcher()

        searcher.search("handler", language="python", service_name="auth")

        expected_where = {
            "$and": [
                {"language": "python"},
                {"service_name": "auth"},
            ],
        }
        mock_store.query.assert_called_once_with(
            query_text="handler",
            n_results=10,
            where=expected_where,
        )


# ---------------------------------------------------------------------------
# 5. Score conversion: distance 0.0 -> score 1.0, distance 0.5 -> score 0.5
# ---------------------------------------------------------------------------

class TestScoreConversion:
    """Scores must be derived as ``1.0 - distance`` and clamped to [0, 1]."""

    def test_distance_zero_gives_score_one(self) -> None:
        """A distance of 0.0 should produce a perfect score of 1.0."""
        chroma_result = _make_chroma_result(
            ids=["a.py::Foo"],
            documents=["class Foo: pass"],
            metadatas=[{
                "file_path": "a.py",
                "symbol_name": "Foo",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "svc",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[0.0],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("exact match")

        assert len(results) == 1
        assert results[0].score == pytest.approx(1.0)

    def test_distance_half_gives_score_half(self) -> None:
        """A distance of 0.5 should produce a score of 0.5."""
        chroma_result = _make_chroma_result(
            ids=["b.py::Bar"],
            documents=["class Bar: pass"],
            metadatas=[{
                "file_path": "b.py",
                "symbol_name": "Bar",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "svc",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[0.5],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("half match")

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.5)

    def test_distance_one_gives_score_zero(self) -> None:
        """A distance of 1.0 should produce a score of 0.0."""
        chroma_result = _make_chroma_result(
            ids=["c.py::Baz"],
            documents=["class Baz: pass"],
            metadatas=[{
                "file_path": "c.py",
                "symbol_name": "Baz",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "svc",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[1.0],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("no match")

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.0)

    def test_negative_distance_clamped_to_one(self) -> None:
        """A negative distance (e.g. -0.1) would compute ``1 - (-0.1) = 1.1``
        but the score must be clamped to a maximum of 1.0."""
        chroma_result = _make_chroma_result(
            ids=["d.py::Qux"],
            documents=["class Qux: pass"],
            metadatas=[{
                "file_path": "d.py",
                "symbol_name": "Qux",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "svc",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[-0.1],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("over-match")

        assert len(results) == 1
        assert results[0].score == pytest.approx(1.0)

    def test_large_distance_clamped_to_zero(self) -> None:
        """A distance > 1.0 (e.g. 1.5) would compute ``1 - 1.5 = -0.5``
        but the score must be clamped to a minimum of 0.0."""
        chroma_result = _make_chroma_result(
            ids=["e.py::Quux"],
            documents=["class Quux: pass"],
            metadatas=[{
                "file_path": "e.py",
                "symbol_name": "Quux",
                "symbol_kind": "class",
                "language": "python",
                "service_name": "svc",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[1.5],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("far away")

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 6. top_k parameter passed correctly
# ---------------------------------------------------------------------------

class TestTopKParameter:
    """The top_k argument must be forwarded as n_results to the store."""

    def test_top_k_forwarded_as_n_results(self) -> None:
        """Calling search with top_k=5 should pass n_results=5 to the
        underlying ChromaStore.query."""
        searcher, mock_store = _make_searcher()

        searcher.search("widgets", top_k=5)

        mock_store.query.assert_called_once_with(
            query_text="widgets",
            n_results=5,
            where=None,
        )

    def test_default_top_k_is_ten(self) -> None:
        """When top_k is not specified it should default to 10."""
        searcher, mock_store = _make_searcher()

        searcher.search("gadgets")

        mock_store.query.assert_called_once_with(
            query_text="gadgets",
            n_results=10,
            where=None,
        )


# ---------------------------------------------------------------------------
# 7. Empty results return empty list
# ---------------------------------------------------------------------------

class TestEmptyResults:
    """Various forms of empty ChromaDB output must all return ``[]``."""

    def test_empty_ids_returns_empty_list(self) -> None:
        """When ChromaDB returns ids=[[]], the result should be an empty list."""
        chroma_result = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("nothing")

        assert results == []

    def test_none_result_returns_empty_list(self) -> None:
        """When ChromaDB returns None or an empty dict, the result should be
        an empty list."""
        searcher, mock_store = _make_searcher()
        mock_store.query.return_value = {}

        results = searcher.search("nothing")

        assert results == []

    def test_missing_ids_key_returns_empty_list(self) -> None:
        """When the result dict lacks the 'ids' key entirely, the result
        should be an empty list."""
        searcher, mock_store = _make_searcher()
        mock_store.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        results = searcher.search("missing")

        assert results == []


# ---------------------------------------------------------------------------
# 8. ChromaDB error returns empty list (graceful degradation)
# ---------------------------------------------------------------------------

class TestChromaDBError:
    """If ChromaStore.query raises an exception, search must return ``[]``
    instead of propagating the error."""

    def test_runtime_error_returns_empty_list(self) -> None:
        """A RuntimeError from the store should be swallowed and an empty
        list returned."""
        searcher, mock_store = _make_searcher()
        mock_store.query.side_effect = RuntimeError("ChromaDB is down")

        results = searcher.search("boom")

        assert results == []

    def test_value_error_returns_empty_list(self) -> None:
        """A ValueError from the store should also be caught gracefully."""
        searcher, mock_store = _make_searcher()
        mock_store.query.side_effect = ValueError("bad query")

        results = searcher.search("bad")

        assert results == []

    def test_generic_exception_returns_empty_list(self) -> None:
        """A RuntimeError should be caught and result in ``[]``."""
        searcher, mock_store = _make_searcher()
        mock_store.query.side_effect = RuntimeError("unexpected")

        results = searcher.search("oops")

        assert results == []


# ---------------------------------------------------------------------------
# 9. Metadata empty strings converted to None
# ---------------------------------------------------------------------------

class TestEmptyStringConversion:
    """ChromaDB stores None metadata values as empty strings.
    SemanticSearcher must convert them back to None."""

    def test_empty_service_name_becomes_none(self) -> None:
        """A service_name of '' in metadata should be converted to None in
        the result."""
        searcher, _ = _make_searcher()  # default result has service_name=""

        results = searcher.search("functions")

        # The second result in the default fixture has service_name=""
        second = [r for r in results if r.chunk_id == "file.py::my_func"][0]
        assert second.service_name is None

    def test_non_empty_service_name_preserved(self) -> None:
        """A service_name of 'auth' in metadata should be preserved as-is."""
        searcher, _ = _make_searcher()

        results = searcher.search("classes")

        first = [r for r in results if r.chunk_id == "file.py::MyClass"][0]
        assert first.service_name == "auth"

    def test_empty_symbol_name_becomes_none(self) -> None:
        """A symbol_name of '' in metadata should be converted to None."""
        chroma_result = _make_chroma_result(
            ids=["anon.py::"],
            documents=["x = 42"],
            metadatas=[{
                "file_path": "anon.py",
                "symbol_name": "",
                "symbol_kind": "",
                "language": "python",
                "service_name": "",
                "line_start": 1,
                "line_end": 1,
            }],
            distances=[0.2],
        )
        searcher, _ = _make_searcher(chroma_result)

        results = searcher.search("anonymous")

        assert len(results) == 1
        assert results[0].symbol_name is None
        assert results[0].service_name is None
