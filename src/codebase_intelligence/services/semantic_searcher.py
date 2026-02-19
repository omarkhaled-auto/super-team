"""Semantic code search using ChromaDB vector similarity."""
from __future__ import annotations

import logging

from src.codebase_intelligence.storage.chroma_store import ChromaStore
from src.shared.models.codebase import SemanticSearchResult

logger = logging.getLogger(__name__)


class SemanticSearcher:
    """Searches code chunks by semantic similarity via ChromaDB.

    Wraps :class:`ChromaStore` to provide a high-level search interface
    that returns :class:`SemanticSearchResult` objects with optional
    language and service-name filtering.

    Parameters
    ----------
    chroma_store:
        An initialised :class:`ChromaStore` instance used for vector
        similarity queries.
    """

    def __init__(self, chroma_store: ChromaStore) -> None:
        self._chroma_store = chroma_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        language: str | None = None,
        service_name: str | None = None,
        top_k: int = 10,
    ) -> list[SemanticSearchResult]:
        """Run a semantic similarity search over indexed code chunks.

        Parameters
        ----------
        query:
            Natural-language or code query string.
        language:
            Optional language filter (e.g. ``"python"``, ``"typescript"``).
        service_name:
            Optional service name filter.
        top_k:
            Maximum number of results to return. Defaults to ``10``.

        Returns
        -------
        list[SemanticSearchResult]
            Results sorted by descending similarity score.  Each score
            is derived from cosine distance as ``1.0 - distance``,
            clamped to ``[0.0, 1.0]``.
        """
        where_filter = self._build_where_filter(language, service_name)

        try:
            results = self._chroma_store.query(
                query_text=query,
                n_results=top_k,
                where=where_filter,
            )
        except (ValueError, RuntimeError):
            logger.exception("ChromaDB query failed for: %s", query[:80])
            return []

        return self._convert_results(results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where_filter(
        language: str | None,
        service_name: str | None,
    ) -> dict | None:
        """Build a ChromaDB ``where`` filter dict from optional filters.

        Uses the ``$and`` operator when both *language* and *service_name*
        are provided; a simple equality filter when only one is given;
        and ``None`` when neither is specified.
        """
        conditions: list[dict] = []

        if language is not None:
            conditions.append({"language": language})
        if service_name is not None:
            conditions.append({"service_name": service_name})

        if len(conditions) == 2:
            return {"$and": conditions}
        if len(conditions) == 1:
            return conditions[0]
        return None

    @staticmethod
    def _convert_results(results: dict) -> list[SemanticSearchResult]:
        """Convert raw ChromaDB result dict to a list of search results.

        Handles edge-cases such as empty result sets, metadata values
        stored as empty strings instead of ``None``, and line numbers
        that may be strings rather than integers.
        """
        # Guard against empty / malformed results
        if (
            not results
            or not results.get("ids")
            or not results["ids"][0]
        ):
            return []

        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        search_results: list[SemanticSearchResult] = []

        for i in range(len(ids)):
            try:
                metadata = metadatas[i]
                distance = distances[i]
                score = max(0.0, min(1.0, 1.0 - distance))

                # ChromaDB stores None as "" -- convert back
                symbol_name = metadata.get("symbol_name") or None
                service_name_val = metadata.get("service_name") or None

                # line numbers may arrive as str from some ChromaDB backends
                try:
                    line_start = int(metadata["line_start"])
                except (KeyError, TypeError, ValueError):
                    line_start = 1

                try:
                    line_end = int(metadata["line_end"])
                except (KeyError, TypeError, ValueError):
                    line_end = line_start

                search_results.append(
                    SemanticSearchResult(
                        chunk_id=ids[i],
                        file_path=metadata["file_path"],
                        symbol_name=symbol_name,
                        content=documents[i],
                        score=score,
                        language=metadata["language"],
                        service_name=service_name_val,
                        line_start=line_start,
                        line_end=line_end,
                    )
                )
            except (KeyError, IndexError, TypeError) as exc:
                logger.warning("Failed to convert search result at index %d: %s", i, exc)

        # Ensure descending score order (should already be, but enforce)
        search_results.sort(key=lambda r: r.score, reverse=True)

        return search_results
