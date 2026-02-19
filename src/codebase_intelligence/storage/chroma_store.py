"""ChromaDB-backed vector storage for semantic code search."""
from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from src.shared.models.codebase import CodeChunk, SymbolKind

logger = logging.getLogger(__name__)


class ChromaStore:
    """Wraps :class:`chromadb.PersistentClient` for code-chunk storage.

    Uses the ``all-MiniLM-L6-v2`` sentence-transformer via ChromaDB's
    :class:`DefaultEmbeddingFunction` and cosine distance for similarity
    search over code chunks.

    Parameters
    ----------
    chroma_path:
        Filesystem path where ChromaDB persists its data.
    """

    _COLLECTION_NAME = "code_chunks"

    def __init__(self, chroma_path: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._embedding_fn = DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=self._COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaStore initialised (path=%s, collection=%s, count=%d)",
            chroma_path,
            self._COLLECTION_NAME,
            self._collection.count(),
        )

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[CodeChunk]) -> None:
        """Add code chunks to the vector store.

        Each chunk is stored with its ``content`` as the document and
        rich metadata derived from the :class:`CodeChunk` fields.  IDs
        are generated as ``file_path::symbol_name``.  ``None`` metadata
        values are converted to empty strings because ChromaDB does not
        accept ``None`` in metadata dictionaries.

        Parameters
        ----------
        chunks:
            Code chunks to insert or update.
        """
        if not chunks:
            return

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_id = f"{chunk.file_path}::{chunk.symbol_name or ''}"
            ids.append(chunk_id)
            documents.append(chunk.content)
            metadatas.append(self._build_metadata(chunk))

        self._collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        logger.debug("Added %d chunks to ChromaDB", len(chunks))

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        n_results: int = 10,
        where: dict[str, Any] | None = None,
    ) -> dict[str, list[list[Any]]]:
        """Run a semantic similarity query against the collection.

        Parameters
        ----------
        query_text:
            Natural-language or code query string.
        n_results:
            Maximum number of results to return.
        where:
            Optional ChromaDB metadata filter.  Supports equality,
            ``$gt``, ``$and``, and ``$in`` operators.

        Returns
        -------
        dict[str, list[list[Any]]]
            ChromaDB result dictionary with keys ``ids``, ``documents``,
            ``metadatas``, and ``distances``.  Each value is a list of
            lists (one inner list per query text).  Access results as
            ``results["ids"][0]``, ``results["documents"][0]``, etc.
        """
        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where is not None:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)
        logger.debug(
            "Query returned %d results for: %s",
            len(results["ids"][0]) if results["ids"] else 0,
            query_text[:80],
        )
        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_by_file(self, file_path: str) -> None:
        """Delete all chunks belonging to a given file.

        Uses a ChromaDB ``where`` filter on the ``file_path`` metadata
        field to locate and remove all matching chunks.

        Parameters
        ----------
        file_path:
            Path of the file whose chunks should be removed.
        """
        self._collection.delete(where={"file_path": file_path})
        logger.debug("Deleted chunks for file: %s", file_path)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> int:
        """Return the total number of chunks stored in the collection.

        This value feeds into :class:`IndexStats.total_chunks`.
        """
        count: int = self._collection.count()
        logger.debug("ChromaDB collection count: %d", count)
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_metadata(chunk: CodeChunk) -> dict[str, Any]:
        """Build a ChromaDB-compatible metadata dict from a CodeChunk.

        ChromaDB does not allow ``None`` values in metadata, so any
        ``None`` field is converted to an empty string.  The
        ``symbol_kind`` enum is stored as its string value.
        """
        symbol_kind_value: str = ""
        if chunk.symbol_kind is not None:
            symbol_kind_value = (
                chunk.symbol_kind.value
                if isinstance(chunk.symbol_kind, SymbolKind)
                else str(chunk.symbol_kind)
            )

        return {
            "file_path": chunk.file_path,
            "symbol_name": chunk.symbol_name or "",
            "symbol_kind": symbol_kind_value,
            "language": chunk.language,
            "service_name": chunk.service_name or "",
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
        }
