"""Incremental file indexing pipeline."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from src.shared.models.codebase import ImportReference, SymbolDefinition
from src.codebase_intelligence.services.ast_parser import ASTParser
from src.codebase_intelligence.services.symbol_extractor import SymbolExtractor
from src.codebase_intelligence.services.import_resolver import ImportResolver
from src.codebase_intelligence.services.graph_builder import GraphBuilder
from src.codebase_intelligence.storage.symbol_db import SymbolDB
from src.codebase_intelligence.storage.graph_db import GraphDB
from src.codebase_intelligence.services.semantic_indexer import SemanticIndexer

logger = logging.getLogger(__name__)


class IncrementalIndexer:
    """Orchestrates the full indexing pipeline for a single file.

    Pipeline steps:
    1. Detect language from file extension
    2. Parse AST with tree-sitter
    3. Extract symbols (classes, functions, etc.)
    4. Resolve imports
    5. Update dependency graph
    6. Persist to database
    7. Semantic indexing (generate embeddings via SemanticIndexer)
    """

    def __init__(
        self,
        ast_parser: ASTParser,
        symbol_extractor: SymbolExtractor,
        import_resolver: ImportResolver,
        graph_builder: GraphBuilder,
        symbol_db: SymbolDB,
        graph_db: GraphDB,
        semantic_indexer: SemanticIndexer | None = None,
    ):
        self._ast_parser = ast_parser
        self._symbol_extractor = symbol_extractor
        self._import_resolver = import_resolver
        self._graph_builder = graph_builder
        self._symbol_db = symbol_db
        self._graph_db = graph_db
        self._semantic_indexer = semantic_indexer

    def index_file(
        self,
        file_path: str,
        source: bytes | None = None,
        service_name: str | None = None,
        project_root: str | None = None,
    ) -> dict:
        """Index a single file through the full pipeline.

        Args:
            file_path: Path to the file to index
            source: Raw source bytes (if None, reads from disk)
            service_name: Optional service name
            project_root: Project root for import resolution

        Returns:
            Dict with: indexed (bool), symbols_found (int),
            dependencies_found (int), errors (list[str])
        """
        errors: list[str] = []

        # Read file if source not provided
        if source is None:
            try:
                source = Path(file_path).read_bytes()
            except (FileNotFoundError, OSError) as exc:
                return {
                    "indexed": False,
                    "symbols_found": 0,
                    "dependencies_found": 0,
                    "errors": [f"Cannot read file: {exc}"],
                }

        # Detect language
        language = self._ast_parser.detect_language(file_path)
        if language is None:
            return {
                "indexed": False,
                "symbols_found": 0,
                "dependencies_found": 0,
                "errors": [f"Unsupported file type: {file_path}"],
            }

        # Compute file hash
        file_hash = hashlib.sha256(source).hexdigest()
        loc = source.count(b"\n") + 1

        # These are declared here so the return dict can reference them
        # even if the try block fails partway through.
        symbols: list[SymbolDefinition] = []
        imports: list[ImportReference] = []

        try:
            # Step 1-2: Parse AST
            parse_result = self._ast_parser.parse_file(source, file_path)
            raw_symbols = parse_result["symbols"]

            # Step 3: Extract typed symbols
            symbols = self._symbol_extractor.extract_symbols(
                raw_symbols, file_path, language, service_name
            )

            # Step 4: Resolve imports
            imports = self._import_resolver.resolve_imports(
                source, file_path, project_root
            )

            # Step 5: Update graph
            self._graph_builder.add_file(
                file_path, imports, language=language, service_name=service_name
            )

            # Step 6: Persist to database
            self._symbol_db.save_file(file_path, language, service_name, file_hash, loc)
            self._symbol_db.save_symbols(symbols)
            self._symbol_db.save_imports(imports)
            self._graph_db.save_edges([])  # Edge extraction is done at graph level

            # Step 7: Semantic indexing
            if self._semantic_indexer is not None:
                try:
                    chunks = self._semantic_indexer.index_symbols(symbols, source)
                    logger.info(
                        "Semantic indexing complete for %s: %d chunks created",
                        file_path, len(chunks),
                    )
                except (ValueError, RuntimeError) as semantic_exc:
                    logger.warning(
                        "Semantic indexing failed for %s: %s",
                        file_path, semantic_exc,
                    )
                    errors.append(f"Semantic indexing failed: {semantic_exc}")
            else:
                logger.debug(
                    "SemanticIndexer not configured, skipping embedding for %s",
                    file_path,
                )

        except (FileNotFoundError, ValueError, OSError) as exc:
            errors.append(str(exc))
            logger.error("Indexing failed for %s: %s", file_path, exc)

        return {
            "indexed": len(errors) == 0,
            "symbols_found": len(symbols),
            "dependencies_found": len(imports),
            "errors": errors,
        }
