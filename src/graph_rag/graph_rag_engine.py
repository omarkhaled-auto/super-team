"""Core query engine for Graph RAG -- implements all 7 tool algorithms.

This module provides ``GraphRAGEngine``, the synchronous query layer that
backs each MCP tool registered in ``mcp_server.py``.  All public methods
return plain ``dict`` results ready for JSON serialisation.

Algorithms are faithful to GRAPH_RAG_DESIGN.md Section 6.1 (Tools 2-7).
Tool 1 (``build_knowledge_graph``) lives in the indexer pipeline; this
engine only handles read-path queries.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any

import networkx as nx

from src.graph_rag.context_assembler import ContextAssembler
from src.graph_rag.graph_rag_store import GraphRAGStore
from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.shared.models.graph_rag import (
    CrossServiceImpact,
    EventValidationResult,
    ServiceBoundaryValidation,
    ServiceContext,
)

logger = logging.getLogger(__name__)


class GraphRAGEngine:
    """Synchronous query engine over the unified knowledge graph.

    Parameters
    ----------
    knowledge_graph:
        The populated ``KnowledgeGraph`` instance.
    store:
        The ``GraphRAGStore`` wrapping the two ChromaDB collections.
    assembler:
        Optional ``ContextAssembler`` for formatting context blocks.
        A default instance is created when *None*.
    """

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        store: GraphRAGStore,
        assembler: ContextAssembler | None = None,
    ) -> None:
        self._knowledge_graph = knowledge_graph
        self._store = store
        self._assembler = assembler or ContextAssembler()
        self._cached_undirected: nx.MultiGraph | None = None

    # ==================================================================
    # Tool 2 -- get_service_context
    # ==================================================================

    def get_service_context(
        self,
        service_name: str,
        include_consumed_apis: bool = True,
        include_provided_apis: bool = True,
        include_events: bool = True,
        include_entities: bool = True,
        include_dependencies: bool = True,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Retrieve a structured context block for *service_name*.

        Traverses the knowledge graph to collect provided/consumed APIs,
        published/consumed events, owned/referenced domain entities, and
        the dependency topology.  The result includes a pre-formatted
        ``context_text`` field suitable for builder prompt injection.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 2.
        """
        G = self._knowledge_graph.graph
        service_node_id = f"service::{service_name}"

        if service_node_id not in G:
            return {
                "service_name": service_name,
                "error": "Service not found in knowledge graph",
            }

        # -- 2. Provided endpoints (PROVIDES_CONTRACT -> EXPOSES_ENDPOINT) --
        provided_endpoints: list[dict[str, str]] = []
        if include_provided_apis:
            provided_contracts = [
                (u, v, k, d)
                for u, v, k, d in G.out_edges(
                    service_node_id, keys=True, data=True
                )
                if k == "PROVIDES_CONTRACT"
            ]
            for _, contract_node, _, _ in provided_contracts:
                for _, ep_node, ep_key, _ep_data in G.out_edges(
                    contract_node, keys=True, data=True
                ):
                    if ep_key == "EXPOSES_ENDPOINT":
                        ep_attrs = G.nodes[ep_node]
                        provided_endpoints.append(
                            {
                                "method": ep_attrs.get("method", ""),
                                "path": ep_attrs.get("path", ""),
                                "handler": ep_attrs.get("handler_symbol", ""),
                                "contract_id": G.nodes[contract_node].get(
                                    "contract_id", ""
                                ),
                            }
                        )

        # -- 3. Consumed endpoints (SERVICE_CALLS, via_endpoint) -----------
        consumed_endpoints: list[dict[str, str]] = []
        if include_consumed_apis:
            for _, target_service, k, d in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if k == "SERVICE_CALLS":
                    via_endpoint = d.get("via_endpoint", "")
                    if via_endpoint and via_endpoint in G:
                        ep_attrs = G.nodes[via_endpoint]
                        consumed_endpoints.append(
                            {
                                "method": ep_attrs.get("method", ""),
                                "path": ep_attrs.get("path", ""),
                                "provider_service": G.nodes[target_service].get(
                                    "service_name", ""
                                ),
                            }
                        )

        # -- 4. Events published (PUBLISHES_EVENT) -------------------------
        events_published: list[dict[str, str]] = []
        if include_events:
            for _, event_node, k, _ in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if k == "PUBLISHES_EVENT":
                    ev = G.nodes[event_node]
                    events_published.append(
                        {
                            "event_name": ev.get("event_name", ""),
                            "channel": ev.get("channel", ""),
                        }
                    )

        # -- 5. Events consumed (CONSUMES_EVENT, find publisher) -----------
        events_consumed: list[dict[str, str]] = []
        if include_events:
            for _, event_node, k, _ in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if k == "CONSUMES_EVENT":
                    ev = G.nodes[event_node]
                    publishers = [
                        u
                        for u, _, ek, _ in G.in_edges(
                            event_node, keys=True, data=True
                        )
                        if ek == "PUBLISHES_EVENT"
                    ]
                    publisher_name = (
                        G.nodes[publishers[0]].get("service_name", "")
                        if publishers
                        else ""
                    )
                    events_consumed.append(
                        {
                            "event_name": ev.get("event_name", ""),
                            "publisher_service": publisher_name,
                        }
                    )

        # -- 6. Owned entities (OWNS_ENTITY) -------------------------------
        owned_entities: list[dict[str, str | list]] = []
        if include_entities:
            for _, entity_node, k, _ in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if k == "OWNS_ENTITY":
                    ent = G.nodes[entity_node]
                    fields_raw = ent.get("fields_json", "[]")
                    try:
                        fields = json.loads(fields_raw)
                    except (json.JSONDecodeError, TypeError):
                        fields = []
                    owned_entities.append(
                        {"name": ent.get("entity_name", ""), "fields": fields}
                    )

        # -- 7. Referenced entities (REFERENCES_ENTITY) --------------------
        referenced_entities: list[dict[str, str | list]] = []
        if include_entities:
            for _, entity_node, k, _ in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if k == "REFERENCES_ENTITY":
                    ent = G.nodes[entity_node]
                    fields_raw = ent.get("fields_json", "[]")
                    try:
                        fields = json.loads(fields_raw)
                    except (json.JSONDecodeError, TypeError):
                        fields = []
                    referenced_entities.append(
                        {
                            "name": ent.get("entity_name", ""),
                            "owning_service": ent.get("owning_service", ""),
                            "fields": fields,
                        }
                    )

        # -- 8. Depends on / depended on by (SERVICE_CALLS) ----------------
        depends_on: list[str] = []
        depended_on_by: list[str] = []
        if include_dependencies:
            for _, target, k, _ in G.out_edges(
                service_node_id, keys=True, data=True
            ):
                if (
                    k == "SERVICE_CALLS"
                    and G.nodes[target].get("node_type") == "service"
                ):
                    svc_name = G.nodes[target].get("service_name", "")
                    if svc_name and svc_name not in depends_on:
                        depends_on.append(svc_name)

            for source, _, k, _ in G.in_edges(
                service_node_id, keys=True, data=True
            ):
                if (
                    k == "SERVICE_CALLS"
                    and G.nodes[source].get("node_type") == "service"
                ):
                    svc_name = G.nodes[source].get("service_name", "")
                    if svc_name and svc_name not in depended_on_by:
                        depended_on_by.append(svc_name)

        # -- 9. Assemble context_text via assembler ------------------------
        context_text = self._assembler.assemble_service_context(
            service_name=service_name,
            provided_endpoints=provided_endpoints,
            consumed_endpoints=consumed_endpoints,
            events_published=events_published,
            events_consumed=events_consumed,
            owned_entities=owned_entities,
            referenced_entities=referenced_entities,
            depends_on=depends_on,
            depended_on_by=depended_on_by,
        )

        return {
            "service_name": service_name,
            "provided_endpoints": provided_endpoints,
            "consumed_endpoints": consumed_endpoints,
            "events_published": events_published,
            "events_consumed": events_consumed,
            "owned_entities": owned_entities,
            "referenced_entities": referenced_entities,
            "depends_on": depends_on,
            "depended_on_by": depended_on_by,
            "context_text": context_text,
        }

    # ==================================================================
    # Tool 3 -- query_graph_neighborhood
    # ==================================================================

    def query_graph_neighborhood(
        self,
        node_id: str,
        radius: int = 2,
        undirected: bool = True,
        filter_node_types: str = "",
        filter_edge_types: str = "",
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        """Extract the N-hop neighborhood around *node_id*.

        The returned subgraph is ranked by distance then PageRank, capped
        at *max_nodes*.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 3.
        """
        G = self._knowledge_graph.graph

        if node_id not in G:
            return {
                "center_node": {},
                "nodes": [],
                "edges": [],
                "total_nodes_in_neighborhood": 0,
                "truncated": False,
            }

        # 1. Extract ego subgraph via KnowledgeGraph helper
        subgraph = self._knowledge_graph.get_ego_subgraph(
            node_id, radius=radius, undirected=undirected
        )

        # 2. Apply node type filter
        if filter_node_types:
            allowed_types = set(
                t.strip() for t in filter_node_types.split(",") if t.strip()
            )
            keep_nodes = [
                n
                for n in subgraph.nodes()
                if G.nodes[n].get("node_type") in allowed_types or n == node_id
            ]
            subgraph = subgraph.subgraph(keep_nodes).copy()

        # 3. Apply edge type filter
        if filter_edge_types:
            allowed_edges = set(
                t.strip() for t in filter_edge_types.split(",") if t.strip()
            )
            remove_edges = [
                (u, v, k)
                for u, v, k in subgraph.edges(keys=True)
                if k not in allowed_edges
            ]
            for u, v, k in remove_edges:
                subgraph.remove_edge(u, v, key=k)

        # 4. Rank by distance, then by PageRank (descending)
        try:
            distances = nx.single_source_shortest_path_length(subgraph, node_id)
        except nx.NetworkXError:
            distances = {node_id: 0}

        ranked = sorted(
            subgraph.nodes(),
            key=lambda n: (
                distances.get(n, 999),
                -G.nodes[n].get("pagerank", 0.0),
            ),
        )

        # 5. Cap at max_nodes
        total = len(ranked)
        truncated = total > max_nodes
        ranked = ranked[:max_nodes]

        # 6. Build result
        final_subgraph = subgraph.subgraph(ranked)
        center_node = {"id": node_id, **dict(G.nodes[node_id])}
        nodes = [{"id": n, **dict(G.nodes[n])} for n in final_subgraph.nodes()]
        edges = [
            {"source": u, "target": v, "relation": k, **dict(d)}
            for u, v, k, d in final_subgraph.edges(keys=True, data=True)
        ]

        return {
            "center_node": center_node,
            "nodes": nodes,
            "edges": edges,
            "total_nodes_in_neighborhood": total,
            "truncated": truncated,
        }

    # ==================================================================
    # Tool 4 -- hybrid_search
    # ==================================================================

    def hybrid_search(
        self,
        query: str,
        n_results: int = 10,
        anchor_node_id: str = "",
        node_types: str = "",
        service_name: str = "",
        semantic_weight: float = 0.6,
        graph_weight: float = 0.4,
    ) -> dict[str, Any]:
        """Combine semantic vector search with graph-structural re-ranking.

        When *anchor_node_id* is provided, results are re-ranked by graph
        distance to the anchor.  Otherwise, PageRank is used as the graph
        signal.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 4.
        """
        G = self._knowledge_graph.graph

        # 1. Parse node_types
        parsed_types: list[str] | None = None
        if node_types:
            parsed_types = [t.strip() for t in node_types.split(",") if t.strip()]

        # 2. Semantic search via ChromaDB store
        semantic_results = self._store.query_nodes(
            query_text=query,
            n_results=n_results * 3,
            node_types=parsed_types,
            service_name=service_name or None,
        )

        if not semantic_results:
            return {
                "results": [],
                "query": query,
                "anchor_node_id": anchor_node_id,
            }

        # 3. Convert to candidate list with semantic scores
        candidates: list[dict[str, Any]] = []
        for sr in semantic_results:
            semantic_score = 1.0 - sr.get("distance", 1.0)
            candidates.append(
                {
                    "node_id": sr["id"],
                    "semantic_score": max(0.0, semantic_score),
                    "document": sr.get("document", ""),
                    "metadata": sr.get("metadata", {}),
                }
            )

        # 4. Graph-structural re-ranking
        if anchor_node_id and anchor_node_id in G:
            # Use cached undirected graph to avoid O(V+E) copy per call (NX-3)
            self._cached_undirected = (
                self._cached_undirected
                or self._knowledge_graph.graph.to_undirected()
            )
            try:
                path_lengths = nx.single_source_shortest_path_length(
                    self._cached_undirected, anchor_node_id
                )
            except nx.NetworkXError:
                path_lengths = {}

            max_distance = max(path_lengths.values()) if path_lengths else 1
            for c in candidates:
                dist = path_lengths.get(c["node_id"], max_distance + 1)
                c["distance"] = dist
                c["graph_score"] = 1.0 - (dist / (max_distance + 1))
        else:
            # No anchor: use PageRank as graph score
            max_pr = (
                max(
                    (G.nodes[n].get("pagerank", 0.0) for n in G.nodes()),
                    default=1.0,
                )
                or 1.0
            )
            for c in candidates:
                pr = G.nodes.get(c["node_id"], {}).get("pagerank", 0.0)
                c["graph_score"] = pr / max_pr
                c["distance"] = -1

        # 5. Compute combined score
        for c in candidates:
            c["score"] = (semantic_weight * c["semantic_score"]) + (
                graph_weight * c["graph_score"]
            )

        # 6. Sort by combined score descending, take top n_results
        candidates.sort(key=lambda c: -c["score"])
        results = candidates[:n_results]

        # 7. Enrich with node attributes from the graph
        for r in results:
            node_id = r["node_id"]
            if node_id in G:
                attrs = dict(G.nodes[node_id])
                r["node_type"] = attrs.get("node_type", "")
                r.update(attrs)

        return {
            "results": results,
            "query": query,
            "anchor_node_id": anchor_node_id,
        }

    # ==================================================================
    # Tool 5 -- find_cross_service_impact
    # ==================================================================

    def find_cross_service_impact(
        self,
        node_id: str,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Find all cross-service entities impacted by a change at *node_id*.

        Performs bidirectional BFS (forward via out_edges, backward via
        in_edges) then groups impacted nodes by service and computes
        shortest paths.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 5.
        """
        G = self._knowledge_graph.graph

        if node_id not in G:
            return {
                "source_node": node_id,
                "source_service": "",
                "impacted_services": [],
                "impacted_contracts": [],
                "impacted_entities": [],
                "total_impacted_nodes": 0,
            }

        # 1. BFS forward (out_edges) -- descendants
        descendants_set: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        visited: set[str] = {node_id}
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for _, successor, _key, _ in G.out_edges(
                current, keys=True, data=True
            ):
                if successor not in visited:
                    visited.add(successor)
                    descendants_set.add(successor)
                    queue.append((successor, depth + 1))

        # 2. BFS backward (in_edges) -- predecessors
        predecessors_set: set[str] = set()
        queue = deque([(node_id, 0)])
        visited_rev: set[str] = {node_id}
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for predecessor, _, _key, _ in G.in_edges(
                current, keys=True, data=True
            ):
                if predecessor not in visited_rev:
                    visited_rev.add(predecessor)
                    predecessors_set.add(predecessor)
                    queue.append((predecessor, depth + 1))

        all_impacted = descendants_set | predecessors_set

        # 3. Group by service (exclude source service)
        source_service = G.nodes[node_id].get("service_name", "")
        impacted_by_service: dict[str, list[str]] = {}
        for n in all_impacted:
            svc = G.nodes[n].get("service_name", "")
            if svc and svc != source_service:
                impacted_by_service.setdefault(svc, []).append(n)

        # 4. Find impacted contracts
        impacted_contracts_raw = [
            n
            for n in all_impacted
            if G.nodes.get(n, {}).get("node_type") == "contract"
        ]
        impacted_contracts: list[dict[str, str | list]] = []
        for contract_node in impacted_contracts_raw:
            c_attrs = G.nodes[contract_node]
            # Find endpoints exposed by this contract
            endpoints_affected = [
                G.nodes[ep].get("path", ep)
                for _, ep, ek, _ in G.out_edges(
                    contract_node, keys=True, data=True
                )
                if ek == "EXPOSES_ENDPOINT"
            ]
            impacted_contracts.append(
                {
                    "contract_id": c_attrs.get("contract_id", contract_node),
                    "service_name": c_attrs.get("service_name", ""),
                    "endpoints_affected": endpoints_affected,
                }
            )

        # 5. Find impacted entities
        impacted_entities: list[dict[str, str]] = [
            {
                "entity_name": G.nodes[n].get("entity_name", n),
                "owning_service": G.nodes[n].get("owning_service", ""),
            }
            for n in all_impacted
            if G.nodes.get(n, {}).get("node_type") == "domain_entity"
        ]

        # 6. Compute shortest paths to impacted service nodes
        self._cached_undirected = (
            self._cached_undirected
            or self._knowledge_graph.graph.to_undirected()
        )
        impacted_services: list[dict[str, str | int | list]] = []
        for svc, nodes in impacted_by_service.items():
            paths: list[list[str]] = []
            svc_node = f"service::{svc}"
            if svc_node in G:
                try:
                    path = nx.shortest_path(
                        self._cached_undirected, node_id, svc_node
                    )
                    paths.append(path)
                except nx.NetworkXNoPath:
                    pass
                except nx.NodeNotFound:
                    pass
            impacted_services.append(
                {
                    "service_name": svc,
                    "impact_count": len(nodes),
                    "impact_paths": paths,
                }
            )

        return {
            "source_node": node_id,
            "source_service": source_service,
            "impacted_services": impacted_services,
            "impacted_contracts": impacted_contracts,
            "impacted_entities": impacted_entities,
            "total_impacted_nodes": len(all_impacted),
        }

    # ==================================================================
    # Tool 6 -- validate_service_boundaries
    # ==================================================================

    def validate_service_boundaries(
        self,
        resolution: float = 1.0,
    ) -> dict[str, Any]:
        """Use Louvain community detection to validate service boundaries.

        Compares detected file-level communities against declared
        ``service_name`` attributes to find misplaced files and compute
        an alignment score.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 6.
        """
        G = self._knowledge_graph.graph

        # 1. Extract file-level subgraph
        file_nodes = [
            n for n in G.nodes() if G.nodes[n].get("node_type") == "file"
        ]

        if not file_nodes:
            return {
                "communities_detected": 0,
                "services_declared": 0,
                "alignment_score": 1.0,
                "misplaced_files": [],
                "isolated_files": [],
                "service_coupling": [],
            }

        file_subgraph = G.subgraph(file_nodes).copy()
        file_undirected = file_subgraph.to_undirected()

        # 2. Run Louvain community detection
        if len(file_undirected) == 0:
            communities: list[set[str]] = []
        else:
            communities = list(
                nx.community.louvain_communities(
                    file_undirected, resolution=resolution, seed=42
                )
            )

        # 3. For each community, find the dominant service_name
        community_service_map: dict[int, str] = {}
        for i, community in enumerate(communities):
            service_counts: dict[str, int] = {}
            for node in community:
                svc = G.nodes[node].get("service_name", "")
                if svc:
                    service_counts[svc] = service_counts.get(svc, 0) + 1
            dominant = (
                max(service_counts, key=service_counts.get)
                if service_counts
                else ""
            )
            community_service_map[i] = dominant

        # 4. Find misplaced files
        misplaced: list[dict[str, str | float]] = []
        for i, community in enumerate(communities):
            dominant = community_service_map[i]
            if not dominant:
                continue
            for node in community:
                declared = G.nodes[node].get("service_name", "")
                if declared and declared != dominant:
                    total_in_community = len(community)
                    same_service_count = sum(
                        1
                        for n in community
                        if G.nodes[n].get("service_name") == dominant
                    )
                    confidence = (
                        same_service_count / total_in_community
                        if total_in_community > 0
                        else 0.0
                    )
                    misplaced.append(
                        {
                            "file": G.nodes[node].get("file_path", node),
                            "declared_service": declared,
                            "community_service": dominant,
                            "confidence": round(confidence, 3),
                        }
                    )

        # 5. Compute services_declared (COMP-5)
        services_declared = len(
            {
                G.nodes[n].get("service_name", "")
                for n in file_nodes
                if G.nodes[n].get("service_name", "")
            }
        )

        # 6. Compute isolated_files (COMP-4)
        isolated_files = [
            G.nodes[n].get("file_path", n)
            for n in file_nodes
            if file_undirected.degree(n) == 0
        ]

        # 7. Compute alignment_score
        total_files = len(file_nodes)
        aligned = total_files - len(misplaced)
        alignment_score = aligned / total_files if total_files > 0 else 1.0

        # 8. Compute service coupling (cross-service edges)
        coupling: dict[tuple[str, str], int] = {}
        for u, v, _k, _d in G.edges(keys=True, data=True):
            u_svc = G.nodes.get(u, {}).get("service_name", "")
            v_svc = G.nodes.get(v, {}).get("service_name", "")
            if u_svc and v_svc and u_svc != v_svc:
                pair = tuple(sorted([u_svc, v_svc]))
                coupling[pair] = coupling.get(pair, 0) + 1

        service_coupling = [
            {"service_a": a, "service_b": b, "cross_edges": count}
            for (a, b), count in sorted(
                coupling.items(), key=lambda x: -x[1]
            )
        ]

        return {
            "communities_detected": len(communities),
            "services_declared": services_declared,
            "alignment_score": round(alignment_score, 4),
            "misplaced_files": misplaced,
            "isolated_files": isolated_files,
            "service_coupling": service_coupling,
        }

    # ==================================================================
    # Tool 7 -- check_cross_service_events
    # ==================================================================

    def check_cross_service_events(
        self,
        service_name: str = "",
    ) -> dict[str, Any]:
        """Validate that published events have consumers and vice versa.

        Directly addresses ADV-001/ADV-002 false-positive reduction.

        Algorithm: GRAPH_RAG_DESIGN.md Section 6.1, Tool 7.
        """
        G = self._knowledge_graph.graph

        # 1. Collect event nodes
        event_nodes = [
            n for n in G.nodes() if G.nodes[n].get("node_type") == "event"
        ]

        # Filter by service if specified.  Event nodes use shared identity
        # (SCH-1) and have no service_name attribute; filter by checking
        # connected services via PUBLISHES_EVENT / CONSUMES_EVENT edges.
        if service_name:
            event_nodes = [
                n
                for n in event_nodes
                if any(
                    G.nodes[u].get("service_name") == service_name
                    for u, _, k, _ in G.in_edges(n, keys=True, data=True)
                    if k in ("PUBLISHES_EVENT", "CONSUMES_EVENT")
                )
            ]

        orphaned: list[dict[str, str | list]] = []
        unmatched: list[dict[str, str | list]] = []
        matched: list[dict[str, str | list]] = []

        for event_node in event_nodes:
            ev = G.nodes[event_node]
            # Both PUBLISHES_EVENT and CONSUMES_EVENT are directed
            # service -> event, so they appear as in_edges of the event node.
            publishers = [
                u
                for u, _, k, _ in G.in_edges(event_node, keys=True, data=True)
                if k == "PUBLISHES_EVENT"
            ]
            consumers = [
                u
                for u, _, k, _ in G.in_edges(event_node, keys=True, data=True)
                if k == "CONSUMES_EVENT"
            ]

            entry: dict[str, str | list] = {
                "event_name": ev.get("event_name", ""),
                "channel": ev.get("channel", ""),
                "publishers": [
                    G.nodes[p].get("service_name", "") for p in publishers
                ],
                "consumers": [
                    G.nodes[c].get("service_name", "") for c in consumers
                ],
            }

            if publishers and consumers:
                matched.append(entry)
            elif publishers and not consumers:
                orphaned.append(entry)
            elif consumers and not publishers:
                unmatched.append(entry)

        total = len(event_nodes)
        match_rate = len(matched) / total if total > 0 else 1.0

        return {
            "orphaned_events": orphaned,
            "unmatched_consumers": unmatched,
            "matched_events": matched,
            "total_events": total,
            "match_rate": round(match_rate, 4),
        }

    # ==================================================================
    # Cache management
    # ==================================================================

    def update_undirected_cache(self) -> None:
        """Refresh the cached undirected graph projection.

        Should be called after any graph mutation (e.g., rebuild) to
        ensure ``hybrid_search`` and ``find_cross_service_impact`` use
        the latest topology.
        """
        self._cached_undirected = (
            self._knowledge_graph.graph.to_undirected()
        )
