"""Semantic indexer -- creates CodeChunks from symbols and indexes them."""
from __future__ import annotations

import logging

from src.shared.models.codebase import CodeChunk, SymbolDefinition
from src.codebase_intelligence.storage.chroma_store import ChromaStore
from src.codebase_intelligence.storage.symbol_db import SymbolDB

logger = logging.getLogger(__name__)


class SemanticIndexer:
    """Converts :class:`SymbolDefinition` instances into :class:`CodeChunk`
    objects, stores them in the ChromaDB vector store, and back-links each
    symbol to its Chroma ID in the relational database.

    Parameters
    ----------
    chroma_store:
        ChromaDB storage backend for vector embeddings.
    symbol_db:
        SQLite-backed symbol database for relational metadata.
    """

    def __init__(self, chroma_store: ChromaStore, symbol_db: SymbolDB) -> None:
        self._chroma_store = chroma_store
        self._symbol_db = symbol_db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_symbols(
        self,
        symbols: list[SymbolDefinition],
        source: bytes,
    ) -> list[CodeChunk]:
        """Create code chunks from symbols and index them in the vector store.

        For each symbol the corresponding source-code lines are extracted
        from *source* and wrapped into a :class:`CodeChunk`.  The chunks
        are then persisted via :meth:`ChromaStore.add_chunks` and the
        ``chroma_id`` column in the symbols table is updated.

        Parameters
        ----------
        symbols:
            Symbol definitions to index.  Each symbol must carry valid
            ``line_start`` / ``line_end`` values that refer to lines
            inside *source*.
        source:
            Raw file contents (bytes) from which code snippets are
            extracted.

        Returns
        -------
        list[CodeChunk]
            The created chunks (one per symbol).
        """
        if not symbols:
            logger.debug("index_symbols called with empty symbol list; nothing to do")
            return []

        source_lines = source.decode("utf-8", errors="replace").splitlines()
        total_lines = len(source_lines)

        chunks: list[CodeChunk] = []
        for symbol in symbols:
            chunk = self._symbol_to_chunk(symbol, source_lines, total_lines)
            if chunk is not None:
                chunks.append(chunk)

        if not chunks:
            logger.warning("No valid chunks produced from %d symbols", len(symbols))
            return []

        # Persist to vector store
        self._chroma_store.add_chunks(chunks)
        logger.info("Indexed %d chunks in ChromaDB", len(chunks))

        # Back-link each symbol to its Chroma ID
        for chunk in chunks:
            self._symbol_db.update_chroma_id(chunk.id, chunk.id)

        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _symbol_to_chunk(
        symbol: SymbolDefinition,
        source_lines: list[str],
        total_lines: int,
    ) -> CodeChunk | None:
        """Convert a single symbol into a :class:`CodeChunk`.

        Returns ``None`` when the symbol's line range falls entirely
        outside the source or produces an empty content string.
        """
        # Clamp line range to available source
        start = max(symbol.line_start, 1)
        end = min(symbol.line_end, total_lines)

        if start > total_lines:
            logger.warning(
                "Symbol %s has line_start=%d which exceeds source length (%d lines); skipping",
                symbol.symbol_name,
                symbol.line_start,
                total_lines,
            )
            return None

        content = "\n".join(source_lines[start - 1 : end])
        if not content.strip():
            logger.warning(
                "Symbol %s at lines %d-%d produced empty content; skipping",
                symbol.symbol_name,
                symbol.line_start,
                symbol.line_end,
            )
            return None

        chunk_id = f"{symbol.file_path}::{symbol.symbol_name}"

        return CodeChunk(
            id=chunk_id,
            file_path=symbol.file_path,
            content=content,
            language=symbol.language.value,
            service_name=symbol.service_name,
            symbol_name=symbol.symbol_name,
            symbol_kind=symbol.kind,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
        )
