"""ChromaDB wrapper for the two Graph RAG collections."""
from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from src.shared.models.graph_rag import GraphRAGContextRecord, GraphRAGNodeRecord

logger = logging.getLogger(__name__)


class GraphRAGStore:
    """Manages the two ChromaDB collections for Graph RAG.

    Collections:
        - ``graph-rag-nodes``: node descriptions for semantic retrieval
        - ``graph-rag-context``: pre-assembled service/community summaries

    Both use ``DefaultEmbeddingFunction()`` (all-MiniLM-L6-v2, 384 dims)
    with cosine distance, matching the existing ``code_chunks`` collection
    pattern.
    """

    _BATCH_SIZE = 300

    def __init__(self, chroma_path: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._embedding_fn = DefaultEmbeddingFunction()

        self._nodes_collection = self._client.get_or_create_collection(
            name="graph-rag-nodes",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self._contexts_collection = self._client.get_or_create_collection(
            name="graph-rag-context",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert_nodes(self, records: list[GraphRAGNodeRecord]) -> None:
        """Batch upsert node records into the graph-rag-nodes collection."""
        for i in range(0, len(records), self._BATCH_SIZE):
            batch = records[i : i + self._BATCH_SIZE]
            ids = [r.id for r in batch]
            documents = [r.document for r in batch]
            metadatas = [
                {
                    "node_id": r.id,
                    "node_type": r.node_type,
                    "service_name": r.service_name or "",
                    "language": r.language or "",
                    "community_id": r.community_id if r.community_id is not None else -1,
                    "pagerank": r.pagerank if r.pagerank is not None else 0.0,
                }
                for r in batch
            ]
            self._nodes_collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

    def upsert_contexts(self, records: list[GraphRAGContextRecord]) -> None:
        """Batch upsert context records into the graph-rag-context collection."""
        for i in range(0, len(records), self._BATCH_SIZE):
            batch = records[i : i + self._BATCH_SIZE]
            ids = [r.id for r in batch]
            documents = [r.document for r in batch]
            metadatas = [
                {
                    "context_type": r.context_type,
                    "service_name": r.service_name or "",
                    "community_id": r.community_id if r.community_id is not None else -1,
                    "node_count": r.node_count,
                    "edge_count": r.edge_count,
                }
                for r in batch
            ]
            self._contexts_collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query_nodes(
        self,
        query_text: str,
        n_results: int = 10,
        where: dict | None = None,
        node_types: list[str] | None = None,
        service_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic query on the graph-rag-nodes collection."""
        where_filter = where
        if where_filter is None:
            conditions: list[dict] = []
            if node_types:
                if len(node_types) == 1:
                    conditions.append({"node_type": node_types[0]})
                else:
                    conditions.append({"node_type": {"$in": node_types}})
            if service_name:
                conditions.append({"service_name": service_name})
            if len(conditions) == 1:
                where_filter = conditions[0]
            elif len(conditions) > 1:
                where_filter = {"$and": conditions}

        # Guard against n_results > collection size
        count = self._nodes_collection.count()
        effective_n = min(n_results, count) if count > 0 else 1

        if count == 0:
            return []

        try:
            results = self._nodes_collection.query(
                query_texts=[query_text],
                n_results=effective_n,
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # Fallback: retry without where filter
            try:
                results = self._nodes_collection.query(
                    query_texts=[query_text],
                    n_results=effective_n,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception:
                return []

        output: list[dict[str, Any]] = []
        if results and results["ids"] and results["ids"][0]:
            for i, node_id in enumerate(results["ids"][0]):
                output.append(
                    {
                        "id": node_id,
                        "document": results["documents"][0][i] if results["documents"] else "",
                        "distance": results["distances"][0][i] if results["distances"] else 1.0,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    }
                )
        return output

    def query_contexts(
        self,
        query_text: str,
        n_results: int = 5,
        context_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic query on the graph-rag-context collection."""
        where_filter = None
        if context_type:
            where_filter = {"context_type": context_type}

        count = self._contexts_collection.count()
        effective_n = min(n_results, count) if count > 0 else 1

        if count == 0:
            return []

        try:
            results = self._contexts_collection.query(
                query_texts=[query_text],
                n_results=effective_n,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        output: list[dict[str, Any]] = []
        if results and results["ids"] and results["ids"][0]:
            for i, ctx_id in enumerate(results["ids"][0]):
                output.append(
                    {
                        "id": ctx_id,
                        "document": results["documents"][0][i] if results["documents"] else "",
                        "distance": results["distances"][0][i] if results["distances"] else 1.0,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    }
                )
        return output

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    def get_node_by_id(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a single node by its ID."""
        try:
            result = self._nodes_collection.get(
                ids=[node_id],
                include=["documents", "metadatas"],
            )
        except Exception:
            return None

        if result and result["ids"]:
            return {
                "id": result["ids"][0],
                "document": result["documents"][0] if result["documents"] else "",
                "metadata": result["metadatas"][0] if result["metadatas"] else {},
            }
        return None

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_all_nodes(self) -> None:
        """Clear the graph-rag-nodes collection (delete + recreate)."""
        self._client.delete_collection("graph-rag-nodes")
        self._nodes_collection = self._client.get_or_create_collection(
            name="graph-rag-nodes",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def delete_all_contexts(self) -> None:
        """Clear the graph-rag-context collection (delete + recreate)."""
        self._client.delete_collection("graph-rag-context")
        self._contexts_collection = self._client.get_or_create_collection(
            name="graph-rag-context",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """Return the number of records in the nodes collection."""
        return self._nodes_collection.count()

    def context_count(self) -> int:
        """Return the number of records in the contexts collection."""
        return self._contexts_collection.count()
