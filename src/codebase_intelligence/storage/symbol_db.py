"""SQLite-backed storage for code symbols, files, and import references."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.shared.db.connection import ConnectionPool
from src.shared.models.codebase import (
    DependencyRelation,
    ImportReference,
    Language,
    SymbolDefinition,
    SymbolKind,
)

logger = logging.getLogger(__name__)


class SymbolDB:
    """Stores and retrieves code symbols using SQLite via ConnectionPool.

    Provides CRUD operations for indexed files, symbol definitions,
    and import references that map to the schema created by
    ``init_symbols_db``.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Indexed files
    # ------------------------------------------------------------------

    def save_file(
        self,
        file_path: str,
        language: str,
        service_name: str | None,
        file_hash: str,
        loc: int,
    ) -> None:
        """Insert or update an indexed file record.

        Parameters
        ----------
        file_path:
            Absolute path to the source file (primary key).
        language:
            Programming language of the file.
        service_name:
            Owning micro-service name, if applicable.
        file_hash:
            Content hash used for change detection.
        loc:
            Lines of code in the file.
        """
        conn = self._pool.get()
        conn.execute(
            """
            INSERT OR REPLACE INTO indexed_files
                (file_path, language, service_name, file_hash, loc, indexed_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (file_path, language, service_name, file_hash, loc),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------

    def save_symbols(self, symbols: list[SymbolDefinition]) -> None:
        """Save a list of symbol definitions to the database.

        Each :class:`SymbolDefinition` is mapped to a row in the
        ``symbols`` table.  The boolean ``is_exported`` field is
        persisted as an ``INTEGER`` (0 or 1).
        """
        if not symbols:
            return

        conn = self._pool.get()
        for sym in symbols:
            conn.execute(
                """
                INSERT OR REPLACE INTO symbols
                    (id, file_path, symbol_name, kind, language,
                     service_name, line_start, line_end, signature,
                     docstring, is_exported, parent_symbol, chroma_id,
                     indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    sym.id,
                    sym.file_path,
                    sym.symbol_name,
                    sym.kind.value if isinstance(sym.kind, SymbolKind) else sym.kind,
                    sym.language.value if isinstance(sym.language, Language) else sym.language,
                    sym.service_name,
                    sym.line_start,
                    sym.line_end,
                    sym.signature,
                    sym.docstring,
                    int(sym.is_exported),
                    sym.parent_symbol,
                    None,  # chroma_id populated later by vector store
                ),
            )
        conn.commit()
        logger.debug("Saved %d symbols to database", len(symbols))

    # ------------------------------------------------------------------
    # Import references
    # ------------------------------------------------------------------

    def save_imports(self, imports: list[ImportReference]) -> None:
        """Save import references to the database.

        ``imported_names`` is stored as a JSON-encoded array string and
        ``is_relative`` is stored as an ``INTEGER`` (0 or 1).
        """
        if not imports:
            return

        conn = self._pool.get()
        for imp in imports:
            conn.execute(
                """
                INSERT OR REPLACE INTO import_references
                    (source_file, target_file, imported_names, line, is_relative)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    imp.source_file,
                    imp.target_file,
                    json.dumps(imp.imported_names),
                    imp.line,
                    int(imp.is_relative),
                ),
            )
        conn.commit()
        logger.debug("Saved %d import references to database", len(imports))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def query_by_name(
        self, name: str, kind: str | None = None
    ) -> list[SymbolDefinition]:
        """Query symbols by name, optionally filtered by kind.

        Parameters
        ----------
        name:
            Exact symbol name to search for.
        kind:
            Optional :class:`SymbolKind` value to narrow results.

        Returns
        -------
        list[SymbolDefinition]
            Matching symbol definitions.
        """
        conn = self._pool.get()

        if kind is not None:
            cursor = conn.execute(
                "SELECT * FROM symbols WHERE symbol_name = ? AND kind = ?",
                (name, kind),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM symbols WHERE symbol_name = ?",
                (name,),
            )

        return [self._row_to_symbol(row) for row in cursor.fetchall()]

    def query_by_file(self, file_path: str) -> list[SymbolDefinition]:
        """Query all symbols in a file.

        Parameters
        ----------
        file_path:
            Absolute path to the source file.

        Returns
        -------
        list[SymbolDefinition]
            All symbols defined in *file_path*.
        """
        conn = self._pool.get()
        cursor = conn.execute(
            "SELECT * FROM symbols WHERE file_path = ?",
            (file_path,),
        )
        return [self._row_to_symbol(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_chroma_id(self, symbol_id: str, chroma_id: str) -> None:
        """Update the chroma vector-store ID for a symbol.

        Parameters
        ----------
        symbol_id:
            Primary key of the symbol row to update.
        chroma_id:
            Chroma collection ID to associate with the symbol.
        """
        conn = self._pool.get()
        conn.execute(
            "UPDATE symbols SET chroma_id = ? WHERE id = ?",
            (chroma_id, symbol_id),
        )
        conn.commit()
        logger.debug("Updated chroma_id for symbol %s", symbol_id)

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_by_file(self, file_path: str) -> None:
        """Delete all data for a file.

        Removes the ``indexed_files`` row which cascades to ``symbols``
        and ``import_references`` via foreign-key constraints.
        ``dependency_edges`` are cleaned up explicitly since they do not
        have a cascading FK to ``indexed_files``.
        """
        conn = self._pool.get()
        # Cascade takes care of symbols and import_references
        conn.execute(
            "DELETE FROM indexed_files WHERE file_path = ?",
            (file_path,),
        )
        # dependency_edges do not cascade from indexed_files, clean up manually
        conn.execute(
            "DELETE FROM dependency_edges WHERE source_file = ? OR target_file = ?",
            (file_path, file_path),
        )
        conn.commit()
        logger.debug("Deleted all data for file: %s", file_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_symbol(row: object) -> SymbolDefinition:
        """Convert a ``sqlite3.Row`` to a :class:`SymbolDefinition`."""
        return SymbolDefinition(
            id=row["id"],
            file_path=row["file_path"],
            symbol_name=row["symbol_name"],
            kind=SymbolKind(row["kind"]),
            language=Language(row["language"]),
            service_name=row["service_name"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            signature=row["signature"],
            docstring=row["docstring"],
            is_exported=bool(row["is_exported"]),
            parent_symbol=row["parent_symbol"],
        )
