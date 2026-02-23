"""Pattern store -- ChromaDB-backed semantic storage for violation patterns."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from src.build3_shared.models import ScanViolation

logger = logging.getLogger(__name__)

# Distance threshold for cosine similarity: below this = "same pattern".
# Cosine distance in ChromaDB: 0 = identical, 2 = opposite.
# 0.3 is a reasonable threshold for "semantically similar".
_SIMILARITY_THRESHOLD = 0.3


class PatternStore:
    """Semantic pattern storage for violation patterns and fix examples.

    Uses ChromaDB ``PersistentClient`` with two collections:

    - ``violation_patterns``: stores violation messages with metadata
      (scan_code, severity, tech_stack, was_fixed, run_count).
    - ``fix_examples``: stores diffs and descriptions with metadata
      (scan_code, tech_stack, success).

    All methods are independently try/excepted so that a ``PatternStore``
    failure **never** raises into the pipeline.

    Args:
        chroma_path: Filesystem path where ChromaDB persists its data.
    """

    def __init__(self, chroma_path: str | Path) -> None:
        try:
            import chromadb
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self._client = chromadb.PersistentClient(path=str(chroma_path))
            self._embedding_fn = DefaultEmbeddingFunction()

            self._violations = self._client.get_or_create_collection(
                name="violation_patterns",
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            self._fixes = self._client.get_or_create_collection(
                name="fix_examples",
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
        except Exception as exc:
            logger.warning("PatternStore init failed (degraded mode): %s", exc)
            self._available = False

    # ------------------------------------------------------------------
    # Violation patterns
    # ------------------------------------------------------------------

    def add_violation_pattern(
        self,
        violation: ScanViolation,
        tech_stack: str,
        code_context: str = "",
        was_fixed: bool = False,
    ) -> None:
        """Store or update a violation pattern.

        Uses upsert with ID ``{scan_code}::{hash(message)}`` so that
        repeated patterns increment ``run_count`` in metadata.
        """
        if not self._available:
            return
        try:
            doc = f"{violation.message} | {code_context}" if code_context else violation.message
            pattern_id = f"{violation.code}::{hashlib.md5(violation.message.encode()).hexdigest()}"

            # Check if pattern already exists to increment run_count
            existing = self._violations.get(ids=[pattern_id])
            run_count = 1
            if existing and existing["ids"]:
                meta = existing["metadatas"][0] if existing["metadatas"] else {}
                run_count = int(meta.get("run_count", 0)) + 1

            self._violations.upsert(
                ids=[pattern_id],
                documents=[doc],
                metadatas=[{
                    "scan_code": violation.code,
                    "severity": violation.severity,
                    "tech_stack": tech_stack,
                    "was_fixed": 1 if was_fixed else 0,
                    "run_count": run_count,
                }],
            )
        except Exception as exc:
            logger.warning("PatternStore.add_violation_pattern failed: %s", exc)

    def find_similar_patterns(
        self,
        message: str,
        tech_stack: str,
        limit: int = 5,
    ) -> list[dict]:
        """Find violation patterns semantically similar to *message*.

        Filters by ``tech_stack`` and returns only results above the
        similarity threshold.

        Returns:
            List of dicts with keys: document, metadata, distance.
        """
        if not self._available:
            return []
        try:
            results = self._violations.query(
                query_texts=[message],
                n_results=limit,
                where={"tech_stack": tech_stack},
            )
            if not results or not results["ids"] or not results["ids"][0]:
                return []

            output: list[dict[str, Any]] = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 1.0
                if distance <= _SIMILARITY_THRESHOLD:
                    output.append({
                        "id": doc_id,
                        "document": results["documents"][0][i] if results["documents"] else "",
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": distance,
                    })
            return output
        except Exception as exc:
            logger.warning("PatternStore.find_similar_patterns failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Fix examples
    # ------------------------------------------------------------------

    def add_fix_example(
        self,
        diff: str,
        description: str,
        scan_code: str,
        tech_stack: str,
    ) -> None:
        """Store a fix example (diff + description) for a scan code."""
        if not self._available:
            return
        try:
            doc = f"{diff}\n{description}"
            fix_id = f"{scan_code}::{hashlib.md5(doc.encode()).hexdigest()}"
            self._fixes.upsert(
                ids=[fix_id],
                documents=[doc],
                metadatas=[{
                    "scan_code": scan_code,
                    "tech_stack": tech_stack,
                    "success": 1,
                }],
            )
        except Exception as exc:
            logger.warning("PatternStore.add_fix_example failed: %s", exc)

    def find_fix_examples(
        self,
        scan_code: str,
        tech_stack: str,
        limit: int = 3,
    ) -> list[dict]:
        """Find fix examples for a scan code and tech stack.

        Returns:
            List of dicts with keys: document, metadata, distance.
        """
        if not self._available:
            return []
        try:
            results = self._fixes.query(
                query_texts=[f"Fix for {scan_code}"],
                n_results=limit,
                where={"$and": [
                    {"scan_code": scan_code},
                    {"tech_stack": tech_stack},
                ]},
            )
            if not results or not results["ids"] or not results["ids"][0]:
                return []

            output: list[dict[str, Any]] = []
            for i, doc_id in enumerate(results["ids"][0]):
                output.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 1.0,
                })
            return output
        except Exception as exc:
            logger.warning("PatternStore.find_fix_examples failed: %s", exc)
            return []
