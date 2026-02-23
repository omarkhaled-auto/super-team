"""Graph RAG Indexer -- 5-phase build pipeline for the knowledge graph.

Phases:
    1. Load existing data from CI, Architect, and Contract databases
    2. Build base graph (files, symbols, services, dependency edges)
    3. Add contract nodes, domain entities, and service interface events
    4. Compute metrics (PageRank, communities) and embed into ChromaDB
    5. Persist snapshot to the Graph RAG database
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import networkx as nx

from src.graph_rag.graph_rag_store import GraphRAGStore
from src.graph_rag.knowledge_graph import KnowledgeGraph
from src.shared.db.connection import ConnectionPool
from src.shared.models.graph_rag import (
    EdgeType,
    GraphRAGBuildResult,
    GraphRAGContextRecord,
    GraphRAGNodeRecord,
    GraphRAGSourceData,
    NodeType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Relation-to-EdgeType mapping (CI dependency_edges.relation -> EdgeType)
# ---------------------------------------------------------------------------
_RELATION_TO_EDGE_TYPE: dict[str, EdgeType] = {
    "imports": EdgeType.IMPORTS,
    "calls": EdgeType.CALLS,
    "inherits": EdgeType.INHERITS,
    "implements": EdgeType.IMPLEMENTS,
    "uses": EdgeType.CALLS,  # "uses" is a weaker form of "calls"
}

# Suffixes to strip when matching symbols to domain entities
_SYMBOL_SUFFIXES = (
    "Service",
    "Model",
    "Schema",
    "Entity",
    "Repository",
    "Controller",
    "Handler",
)

# Shared-utility path fragments to skip when deriving service edges
_SHARED_UTILITY_PATTERNS = ("shared/", "common/", "utils/", "lib/", "helpers/")


class GraphRAGIndexer:
    """Builds the unified knowledge graph from cross-service data sources.

    The ``build()`` method runs five sequential phases, each fault-tolerant,
    and returns a :class:`GraphRAGBuildResult` summarising what was indexed.
    """

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        store: GraphRAGStore,
        pool: ConnectionPool,
        ci_pool: ConnectionPool | None = None,
        architect_pool: ConnectionPool | None = None,
        contract_pool: ConnectionPool | None = None,
    ) -> None:
        self._kg = knowledge_graph
        self._store = store
        self._pool = pool  # Graph RAG's own database
        self._ci_pool = ci_pool
        self._architect_pool = architect_pool
        self._contract_pool = contract_pool

    # ======================================================================
    # Public API
    # ======================================================================

    def build(
        self,
        project_name: str = "",
        service_interfaces: dict[str, dict] | None = None,
    ) -> GraphRAGBuildResult:
        """Execute the full 5-phase build pipeline.

        Args:
            project_name: Optional project name for scoping Architect queries.
            service_interfaces: Optional dict mapping service_name to an
                interface dict containing ``events_published`` and
                ``events_consumed`` lists.

        Returns:
            A :class:`GraphRAGBuildResult` with statistics and any errors.
        """
        if service_interfaces is None:
            service_interfaces = {}

        errors: list[str] = []
        t_start = time.monotonic()

        # Phase 1 -- Load existing data ----------------------------------
        logger.info("Phase 1/5: Loading existing data")
        source_data = self._load_existing_data(project_name, service_interfaces)
        errors.extend(source_data.errors if hasattr(source_data, "errors") else [])

        # Phase 2 -- Build base graph ------------------------------------
        logger.info("Phase 2/5: Building base graph")
        phase2_errors = self._build_base_graph(source_data)
        errors.extend(phase2_errors)

        # Phase 3 -- Contracts & entities --------------------------------
        logger.info("Phase 3/5: Adding contracts and entity nodes")
        phase3_errors = self._add_contract_and_entity_nodes(source_data)
        errors.extend(phase3_errors)

        # Phase 4 -- Metrics & embed -------------------------------------
        logger.info("Phase 4/5: Computing metrics and embedding")
        phase4_errors = self._compute_metrics_and_embed()
        errors.extend(phase4_errors)

        # Phase 5 -- Persist snapshot ------------------------------------
        logger.info("Phase 5/5: Persisting snapshot")
        phase5_errors = self._persist_snapshot()
        errors.extend(phase5_errors)

        # Assemble result ------------------------------------------------
        t_end = time.monotonic()
        build_time_ms = int((t_end - t_start) * 1000)

        node_types = self._count_node_types()
        edge_types = self._count_edge_types()
        services_indexed = self._collect_services_indexed()
        community_count = self._count_communities()

        result = GraphRAGBuildResult(
            success=len(errors) == 0,
            node_count=self._kg.node_count(),
            edge_count=self._kg.edge_count(),
            node_types=node_types,
            edge_types=edge_types,
            community_count=community_count,
            build_time_ms=build_time_ms,
            services_indexed=services_indexed,
            errors=errors,
        )
        logger.info(
            "Build complete: %d nodes, %d edges, %d communities, %d errors in %dms",
            result.node_count,
            result.edge_count,
            result.community_count,
            len(errors),
            build_time_ms,
        )
        return result

    # ======================================================================
    # Phase 1: Load existing data
    # ======================================================================

    def _load_existing_data(
        self,
        project_name: str,
        service_interfaces: dict[str, dict],
    ) -> GraphRAGSourceData:
        """Load data from CI, Architect, and Contract databases."""
        source = GraphRAGSourceData(service_interfaces=service_interfaces)
        errors: list[str] = []

        # -- CI: graph snapshot ------------------------------------------
        if self._ci_pool is not None:
            try:
                conn = self._ci_pool.get()
                row = conn.execute(
                    "SELECT graph_json FROM graph_snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    source.existing_graph = nx.node_link_graph(
                        json.loads(row["graph_json"]),
                        edges="edges",
                    )
                    logger.debug(
                        "Loaded existing graph with %d nodes",
                        source.existing_graph.number_of_nodes(),
                    )
            except Exception as exc:
                errors.append(f"Failed to load graph snapshot from CI: {exc}")

            # -- CI: symbols ---------------------------------------------
            try:
                conn = self._ci_pool.get()
                rows = conn.execute(
                    "SELECT file_path, symbol_name, kind, language, service_name, "
                    "line_start, line_end, signature, docstring, is_exported, "
                    "parent_symbol, chroma_id FROM symbols"
                ).fetchall()
                source.symbols = [dict(r) for r in rows]
                logger.debug("Loaded %d symbols", len(source.symbols))
            except Exception as exc:
                errors.append(f"Failed to load symbols from CI: {exc}")

            # -- CI: dependency_edges ------------------------------------
            try:
                conn = self._ci_pool.get()
                rows = conn.execute(
                    "SELECT source_symbol_id, target_symbol_id, relation, "
                    "source_file, target_file, line FROM dependency_edges"
                ).fetchall()
                source.dependency_edges = [dict(r) for r in rows]
                logger.debug("Loaded %d dependency edges", len(source.dependency_edges))
            except Exception as exc:
                errors.append(f"Failed to load dependency edges from CI: {exc}")

        # -- Architect: service map --------------------------------------
        if self._architect_pool is not None:
            try:
                conn = self._architect_pool.get()
                if project_name:
                    row = conn.execute(
                        "SELECT map_json FROM service_maps WHERE project_name = ? "
                        "ORDER BY generated_at DESC LIMIT 1",
                        (project_name,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT map_json FROM service_maps "
                        "ORDER BY generated_at DESC LIMIT 1"
                    ).fetchone()
                if row:
                    source.service_map = json.loads(row["map_json"])
                    logger.debug("Loaded service map")
            except Exception as exc:
                errors.append(f"Failed to load service map from Architect: {exc}")

            # -- Architect: domain model ---------------------------------
            try:
                conn = self._architect_pool.get()
                if project_name:
                    row = conn.execute(
                        "SELECT model_json FROM domain_models WHERE project_name = ? "
                        "ORDER BY generated_at DESC LIMIT 1",
                        (project_name,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT model_json FROM domain_models "
                        "ORDER BY generated_at DESC LIMIT 1"
                    ).fetchone()
                if row:
                    source.domain_model = json.loads(row["model_json"])
                    logger.debug("Loaded domain model")
            except Exception as exc:
                errors.append(f"Failed to load domain model from Architect: {exc}")

        # -- Contracts ---------------------------------------------------
        if self._contract_pool is not None:
            try:
                conn = self._contract_pool.get()
                rows = conn.execute(
                    "SELECT id, type AS contract_type, version, service_name, "
                    "spec_json, status FROM contracts WHERE status != 'deprecated'"
                ).fetchall()
                source.contracts = [dict(r) for r in rows]
                logger.debug("Loaded %d contracts", len(source.contracts))
            except Exception as exc:
                errors.append(f"Failed to load contracts: {exc}")

        # Stash errors on the source data object (non-field attribute)
        # GraphRAGSourceData does not have an errors field, so we attach it
        # as a transient attribute for the caller to read.
        object.__setattr__(source, "errors", errors)
        return source

    # ======================================================================
    # Phase 2: Build base graph
    # ======================================================================

    def _build_base_graph(self, source_data: GraphRAGSourceData) -> list[str]:
        """Build the base knowledge graph from CI data and service map."""
        errors: list[str] = []

        # Clear existing knowledge graph
        self._kg.clear()

        # -- Copy nodes from the CI graph snapshot -----------------------
        if source_data.existing_graph is not None:
            try:
                existing: nx.DiGraph | nx.MultiDiGraph = source_data.existing_graph
                for node_id, attrs in existing.nodes(data=True):
                    node_type = NodeType.FILE.value  # conservative default
                    if str(node_id).startswith("file::"):
                        node_type = NodeType.FILE.value
                    new_attrs = dict(attrs)
                    new_attrs.setdefault("node_type", node_type)
                    self._kg.add_node(str(node_id), **new_attrs)

                # Copy edges
                if isinstance(existing, nx.MultiDiGraph):
                    for u, v, key, attrs in existing.edges(keys=True, data=True):
                        self._kg.add_edge(str(u), str(v), key=str(key), **attrs)
                else:
                    for u, v, attrs in existing.edges(data=True):
                        edge_key = attrs.get("relation", "IMPORTS")
                        self._kg.add_edge(str(u), str(v), key=str(edge_key), **attrs)
            except Exception as exc:
                errors.append(f"Failed to copy existing graph nodes/edges: {exc}")

        # -- Build a symbol lookup: file_path -> list[symbol_row] --------
        symbols_by_file: dict[str, list[dict]] = defaultdict(list)
        symbols_by_id: dict[str, dict] = {}
        for sym in source_data.symbols:
            fp = sym.get("file_path", "")
            symbols_by_file[fp].append(sym)
            # Build symbol ID the same way we create symbol nodes
            sym_id = f"symbol::{fp}::{sym.get('symbol_name', '')}"
            symbols_by_id[sym_id] = sym

        # Attach service_name to existing file nodes from symbols
        for fp, syms in symbols_by_file.items():
            file_node_id = f"file::{fp}"
            if file_node_id in self._kg.graph:
                svc = syms[0].get("service_name", "") if syms else ""
                if svc:
                    self._kg.graph.nodes[file_node_id]["service_name"] = svc

        # -- Create service nodes from service map -----------------------
        services_list: list[dict[str, Any]] = []
        if source_data.service_map:
            services_list = source_data.service_map.get("services", [])

        for service_def in services_list:
            try:
                svc_name = service_def.get("name", "")
                if not svc_name:
                    continue
                svc_node_id = f"service::{svc_name}"
                self._kg.add_node(
                    svc_node_id,
                    node_type=NodeType.SERVICE.value,
                    service_name=svc_name,
                    domain=service_def.get("domain", ""),
                    description=service_def.get("description", ""),
                    stack=json.dumps(service_def.get("stack", [])),
                    estimated_loc=service_def.get("estimated_loc", 0),
                )

                # Create CONTAINS_FILE edges: service -> file nodes
                # Match by service_name attribute on file nodes
                for node_id, attrs in list(self._kg.graph.nodes(data=True)):
                    if (
                        attrs.get("node_type") == NodeType.FILE.value
                        and attrs.get("service_name") == svc_name
                    ):
                        self._kg.add_edge(
                            svc_node_id,
                            node_id,
                            key=EdgeType.CONTAINS_FILE.value,
                            relation=EdgeType.CONTAINS_FILE.value,
                        )
            except Exception as exc:
                errors.append(f"Failed to create service node '{service_def}': {exc}")

        # -- Create symbol nodes -----------------------------------------
        for sym in source_data.symbols:
            try:
                fp = sym.get("file_path", "")
                sym_name = sym.get("symbol_name", "")
                if not fp or not sym_name:
                    continue
                sym_node_id = f"symbol::{fp}::{sym_name}"
                self._kg.add_node(
                    sym_node_id,
                    node_type=NodeType.SYMBOL.value,
                    file_path=fp,
                    symbol_name=sym_name,
                    kind=sym.get("kind", ""),
                    language=sym.get("language", ""),
                    service_name=sym.get("service_name", ""),
                    line_start=sym.get("line_start", 0),
                    line_end=sym.get("line_end", 0),
                    signature=sym.get("signature", "") or "",
                    docstring=sym.get("docstring", "") or "",
                    is_exported=sym.get("is_exported", 1),
                    parent_symbol=sym.get("parent_symbol", "") or "",
                )

                # Create DEFINES_SYMBOL edge: file -> symbol
                file_node_id = f"file::{fp}"
                if file_node_id not in self._kg.graph:
                    # Ensure file node exists
                    self._kg.add_node(
                        file_node_id,
                        node_type=NodeType.FILE.value,
                        file_path=fp,
                        language=sym.get("language", ""),
                        service_name=sym.get("service_name", ""),
                    )
                self._kg.add_edge(
                    file_node_id,
                    sym_node_id,
                    key=EdgeType.DEFINES_SYMBOL.value,
                    relation=EdgeType.DEFINES_SYMBOL.value,
                )
            except Exception as exc:
                errors.append(f"Failed to create symbol node: {exc}")

        # -- Create symbol-to-symbol edges from dependency_edges ---------
        for dep in source_data.dependency_edges:
            try:
                src_id = f"symbol::{dep.get('source_symbol_id', '')}"
                tgt_id = f"symbol::{dep.get('target_symbol_id', '')}"
                relation = dep.get("relation", "imports")
                edge_type = _RELATION_TO_EDGE_TYPE.get(relation, EdgeType.IMPORTS)

                # Ensure source and target nodes exist
                if src_id not in self._kg.graph:
                    self._kg.add_node(
                        src_id,
                        node_type=NodeType.SYMBOL.value,
                        source_file=dep.get("source_file", ""),
                    )
                if tgt_id not in self._kg.graph:
                    self._kg.add_node(
                        tgt_id,
                        node_type=NodeType.SYMBOL.value,
                        target_file=dep.get("target_file", ""),
                    )

                self._kg.add_edge(
                    src_id,
                    tgt_id,
                    key=edge_type.value,
                    relation=edge_type.value,
                    source_file=dep.get("source_file", ""),
                    target_file=dep.get("target_file", ""),
                    line=dep.get("line"),
                )
            except Exception as exc:
                errors.append(f"Failed to create dependency edge: {exc}")

        return errors

    # ======================================================================
    # Phase 3: Add contract and entity nodes
    # ======================================================================

    def _add_contract_and_entity_nodes(
        self, source_data: GraphRAGSourceData
    ) -> list[str]:
        """Add contracts, endpoints, domain entities, and service interface events."""
        errors: list[str] = []

        # -- Contract nodes ----------------------------------------------
        for contract in source_data.contracts:
            try:
                contract_id = contract.get("id", "")
                contract_type = contract.get("contract_type", "")
                version = contract.get("version", "")
                svc_name = contract.get("service_name", "")
                spec_json_str = contract.get("spec_json", "{}")
                status = contract.get("status", "active")

                contract_node_id = f"contract::{contract_id}"
                self._kg.add_node(
                    contract_node_id,
                    node_type=NodeType.CONTRACT.value,
                    contract_type=contract_type,
                    version=version,
                    service_name=svc_name,
                    status=status,
                )

                # PROVIDES_CONTRACT: service -> contract
                svc_node_id = f"service::{svc_name}"
                if svc_node_id in self._kg.graph:
                    self._kg.add_edge(
                        svc_node_id,
                        contract_node_id,
                        key=EdgeType.PROVIDES_CONTRACT.value,
                        relation=EdgeType.PROVIDES_CONTRACT.value,
                    )

                # Parse endpoints/events from the spec
                try:
                    spec = json.loads(spec_json_str) if isinstance(spec_json_str, str) else spec_json_str
                except (json.JSONDecodeError, TypeError):
                    spec = {}

                endpoint_errors = self._parse_contract_endpoints(
                    contract_node_id, contract_type, spec, svc_name
                )
                errors.extend(endpoint_errors)

            except Exception as exc:
                errors.append(f"Failed to create contract node: {exc}")

        # -- Domain entity nodes -----------------------------------------
        if source_data.domain_model:
            entities = source_data.domain_model.get("entities", [])
            for entity in entities:
                try:
                    entity_name = entity.get("name", "")
                    if not entity_name:
                        continue
                    entity_node_id = f"domain_entity::{entity_name.lower()}"
                    owning_service = entity.get("owning_service", "")
                    description = entity.get("description", "")
                    fields = entity.get("fields", [])
                    fields_summary = ", ".join(
                        f.get("name", "") if isinstance(f, dict) else str(f)
                        for f in fields[:10]
                    )
                    relationships = entity.get("relationships", [])

                    self._kg.add_node(
                        entity_node_id,
                        node_type=NodeType.DOMAIN_ENTITY.value,
                        entity_name=entity_name,
                        description=description,
                        owning_service=owning_service,
                        fields_summary=fields_summary,
                    )

                    # OWNS_ENTITY: service -> entity
                    if owning_service:
                        svc_node_id = f"service::{owning_service}"
                        if svc_node_id in self._kg.graph:
                            self._kg.add_edge(
                                svc_node_id,
                                entity_node_id,
                                key=EdgeType.OWNS_ENTITY.value,
                                relation=EdgeType.OWNS_ENTITY.value,
                            )

                    # REFERENCES_ENTITY: other services referencing this entity
                    for rel in relationships:
                        ref_entity_name = rel.get("target", "")
                        if ref_entity_name:
                            ref_node_id = f"domain_entity::{ref_entity_name.lower()}"
                            self._kg.add_edge(
                                entity_node_id,
                                ref_node_id,
                                key=EdgeType.DOMAIN_RELATIONSHIP.value,
                                relation=EdgeType.DOMAIN_RELATIONSHIP.value,
                                relationship_type=rel.get("type", ""),
                                cardinality=rel.get("cardinality", ""),
                            )

                    # REFERENCES_ENTITY from consuming services
                    for ref_svc in entity.get("referenced_by", []):
                        ref_svc_id = f"service::{ref_svc}"
                        if ref_svc_id in self._kg.graph:
                            self._kg.add_edge(
                                ref_svc_id,
                                entity_node_id,
                                key=EdgeType.REFERENCES_ENTITY.value,
                                relation=EdgeType.REFERENCES_ENTITY.value,
                            )

                except Exception as exc:
                    errors.append(f"Failed to create domain entity node: {exc}")

        # -- Match symbols to entities -----------------------------------
        try:
            self._match_symbols_to_entities()
        except Exception as exc:
            errors.append(f"Failed to match symbols to entities: {exc}")

        # -- Service interface events ------------------------------------
        try:
            self._add_service_interface_nodes(source_data.service_interfaces)
        except Exception as exc:
            errors.append(f"Failed to add service interface nodes: {exc}")

        # -- Match handlers to endpoints (HANDLES_ENDPOINT) ---------------
        try:
            self._match_handlers_to_endpoints(source_data.service_interfaces)
        except Exception as exc:
            errors.append(f"Failed to match handlers to endpoints: {exc}")

        return errors

    # ======================================================================
    # Phase 4: Compute metrics and embed into ChromaDB
    # ======================================================================

    def _compute_metrics_and_embed(self) -> list[str]:
        """Compute PageRank, communities, and upsert to ChromaDB."""
        errors: list[str] = []

        # -- PageRank ----------------------------------------------------
        try:
            pageranks = self._kg.compute_pagerank()
            for node_id, pr in pageranks.items():
                self._kg.graph.nodes[node_id]["pagerank"] = pr
        except Exception as exc:
            errors.append(f"Failed to compute PageRank: {exc}")
            pageranks = {}

        # -- Community detection -----------------------------------------
        communities: list[set[str]] = []
        try:
            communities = self._kg.compute_communities()
            for community_idx, community_set in enumerate(communities):
                for node_id in community_set:
                    if node_id in self._kg.graph:
                        self._kg.graph.nodes[node_id]["community_id"] = community_idx
        except Exception as exc:
            errors.append(f"Failed to compute communities: {exc}")

        # -- Build ChromaDB node records ---------------------------------
        node_records: list[GraphRAGNodeRecord] = []
        try:
            for node_id, attrs in self._kg.graph.nodes(data=True):
                node_type = attrs.get("node_type", NodeType.FILE.value)
                document = self._build_node_document(node_id, attrs)
                if not document:
                    continue
                node_records.append(
                    GraphRAGNodeRecord(
                        id=node_id,
                        document=document,
                        node_type=node_type,
                        service_name=attrs.get("service_name", ""),
                        language=attrs.get("language", ""),
                        community_id=attrs.get("community_id", -1),
                        pagerank=attrs.get("pagerank", 0.0),
                    )
                )
        except Exception as exc:
            errors.append(f"Failed to build node records: {exc}")

        # -- Upsert nodes to ChromaDB -----------------------------------
        try:
            self._store.delete_all_nodes()
            if node_records:
                self._store.upsert_nodes(node_records)
            logger.debug("Upserted %d node records to ChromaDB", len(node_records))
        except Exception as exc:
            errors.append(f"Failed to upsert nodes to ChromaDB: {exc}")

        # -- Build context records (service summaries + community summaries)
        context_records: list[GraphRAGContextRecord] = []
        try:
            context_records = self._build_context_records(communities)
        except Exception as exc:
            errors.append(f"Failed to build context records: {exc}")

        # -- Upsert contexts to ChromaDB --------------------------------
        try:
            self._store.delete_all_contexts()
            if context_records:
                self._store.upsert_contexts(context_records)
            logger.debug("Upserted %d context records to ChromaDB", len(context_records))
        except Exception as exc:
            errors.append(f"Failed to upsert contexts to ChromaDB: {exc}")

        return errors

    # ======================================================================
    # Phase 5: Persist snapshot
    # ======================================================================

    def _persist_snapshot(self) -> list[str]:
        """Serialize and persist the graph snapshot to the Graph RAG database."""
        errors: list[str] = []

        # Derive service-level edges before persisting
        try:
            self._derive_service_edges()
        except Exception as exc:
            errors.append(f"Failed to derive service edges: {exc}")

        try:
            graph_json = self._kg.to_json()
            node_count = self._kg.node_count()
            edge_count = self._kg.edge_count()
            community_count = self._count_communities()
            services_indexed = json.dumps(self._collect_services_indexed())
            created_at = datetime.now(timezone.utc).isoformat()

            conn = self._pool.get()
            conn.execute(
                "INSERT INTO graph_rag_snapshots "
                "(snapshot_data, node_count, edge_count, community_count, "
                "services_indexed, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    graph_json,
                    node_count,
                    edge_count,
                    community_count,
                    services_indexed,
                    created_at,
                ),
            )
            conn.commit()
            logger.info(
                "Persisted snapshot: %d nodes, %d edges, %d communities",
                node_count,
                edge_count,
                community_count,
            )
        except Exception as exc:
            errors.append(f"Failed to persist snapshot: {exc}")

        return errors

    # ======================================================================
    # Contract endpoint / event parsing
    # ======================================================================

    def _parse_contract_endpoints(
        self,
        contract_node_id: str,
        contract_type: str,
        spec: dict[str, Any],
        service_name: str,
    ) -> list[str]:
        """Parse contract spec to create endpoint/event nodes.

        For OpenAPI: creates endpoint nodes and EXPOSES_ENDPOINT edges.
        For AsyncAPI: creates event nodes and PUBLISHES_EVENT/CONSUMES_EVENT edges.
        """
        errors: list[str] = []

        if contract_type == "openapi":
            paths = spec.get("paths", {})
            for path, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                for method, operation in methods.items():
                    if method.startswith("x-") or method == "parameters":
                        continue
                    try:
                        method_upper = method.upper()
                        endpoint_node_id = (
                            f"endpoint::{service_name}::{method_upper}::{path}"
                        )
                        summary = ""
                        if isinstance(operation, dict):
                            summary = operation.get("summary", "") or operation.get(
                                "description", ""
                            )
                        self._kg.add_node(
                            endpoint_node_id,
                            node_type=NodeType.ENDPOINT.value,
                            service_name=service_name,
                            method=method_upper,
                            path=path,
                            summary=summary,
                        )
                        # EXPOSES_ENDPOINT: contract -> endpoint
                        self._kg.add_edge(
                            contract_node_id,
                            endpoint_node_id,
                            key=EdgeType.EXPOSES_ENDPOINT.value,
                            relation=EdgeType.EXPOSES_ENDPOINT.value,
                        )
                    except Exception as exc:
                        errors.append(
                            f"Failed to create endpoint node {method} {path}: {exc}"
                        )

        elif contract_type == "asyncapi":
            channels = spec.get("channels", {})
            for channel_name, channel_def in channels.items():
                if not isinstance(channel_def, dict):
                    continue
                try:
                    # Determine event name from channel
                    event_name = channel_name
                    event_node_id = f"event::{event_name}"
                    self._kg.add_node(
                        event_node_id,
                        node_type=NodeType.EVENT.value,
                        event_name=event_name,
                        channel=channel_name,
                        service_name=service_name,
                    )

                    svc_node_id = f"service::{service_name}"

                    # Check publish/subscribe semantics
                    if "publish" in channel_def or "subscribe" in channel_def:
                        # AsyncAPI v2: publish = service publishes, subscribe = service subscribes
                        if "publish" in channel_def:
                            if svc_node_id in self._kg.graph:
                                self._kg.add_edge(
                                    svc_node_id,
                                    event_node_id,
                                    key=EdgeType.PUBLISHES_EVENT.value,
                                    relation=EdgeType.PUBLISHES_EVENT.value,
                                )
                        if "subscribe" in channel_def:
                            if svc_node_id in self._kg.graph:
                                self._kg.add_edge(
                                    svc_node_id,
                                    event_node_id,
                                    key=EdgeType.CONSUMES_EVENT.value,
                                    relation=EdgeType.CONSUMES_EVENT.value,
                                )
                    else:
                        # Default: assume the service publishing the contract publishes the event
                        if svc_node_id in self._kg.graph:
                            self._kg.add_edge(
                                svc_node_id,
                                event_node_id,
                                key=EdgeType.PUBLISHES_EVENT.value,
                                relation=EdgeType.PUBLISHES_EVENT.value,
                            )
                except Exception as exc:
                    errors.append(
                        f"Failed to create event node for channel {channel_name}: {exc}"
                    )

        return errors

    # ======================================================================
    # Symbol-to-entity matching
    # ======================================================================

    def _match_symbols_to_entities(self) -> None:
        """Match symbol nodes to domain entity nodes by name similarity.

        For each symbol of kind in (class, interface, type), strip common
        suffixes and compare lowercase to entity names. On match, add an
        IMPLEMENTS_ENTITY edge.
        """
        # Build a lookup: normalized_name -> entity_node_id
        entity_lookup: dict[str, str] = {}
        for node_id, attrs in self._kg.graph.nodes(data=True):
            if attrs.get("node_type") == NodeType.DOMAIN_ENTITY.value:
                entity_name = attrs.get("entity_name", "")
                if entity_name:
                    entity_lookup[entity_name.lower()] = node_id

        if not entity_lookup:
            return

        # Scan symbol nodes
        for node_id, attrs in list(self._kg.graph.nodes(data=True)):
            if attrs.get("node_type") != NodeType.SYMBOL.value:
                continue
            kind = attrs.get("kind", "")
            if kind not in ("class", "interface", "type"):
                continue

            symbol_name = attrs.get("symbol_name", "")
            if not symbol_name:
                continue

            # Strip known suffixes
            stripped = symbol_name
            for suffix in _SYMBOL_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix):
                    stripped = stripped[: -len(suffix)]
                    break

            normalized = stripped.lower()
            if normalized in entity_lookup:
                entity_node_id = entity_lookup[normalized]
                self._kg.add_edge(
                    node_id,
                    entity_node_id,
                    key=EdgeType.IMPLEMENTS_ENTITY.value,
                    relation=EdgeType.IMPLEMENTS_ENTITY.value,
                )

    # ======================================================================
    # Handler-to-endpoint matching (HANDLES_ENDPOINT)
    # ======================================================================

    def _match_handlers_to_endpoints(
        self, service_interfaces: dict[str, dict],
    ) -> None:
        """Create HANDLES_ENDPOINT edges from symbol nodes to endpoint nodes.

        For each service's endpoints in the service interface data, match
        the handler function name to a symbol node in the same service.
        """
        if not service_interfaces:
            return

        G = self._kg.graph

        # Build lookup: (service_name, handler_name) -> symbol_node_id
        symbol_lookup: dict[tuple[str, str], str] = {}
        for node_id, attrs in G.nodes(data=True):
            if attrs.get("node_type") != NodeType.SYMBOL.value:
                continue
            svc = attrs.get("service_name", "")
            name = attrs.get("symbol_name", "")
            if svc and name:
                symbol_lookup[(svc, name)] = node_id
                # Also index by short name (without file prefix)
                short = name.rsplit("::", 1)[-1] if "::" in name else name
                symbol_lookup[(svc, short)] = node_id

        for svc_name, iface in service_interfaces.items():
            for ep in iface.get("endpoints", []):
                handler = ep.get("handler", "") or ep.get("handler_function", "")
                method = (ep.get("method", "") or "").upper()
                path = ep.get("path", "")
                if not handler or not method or not path:
                    continue

                endpoint_node_id = f"endpoint::{svc_name}::{method}::{path}"
                if endpoint_node_id not in G:
                    continue

                # Try to find matching symbol
                sym_id = (
                    symbol_lookup.get((svc_name, handler))
                    or symbol_lookup.get((svc_name, handler.split(".")[-1]))
                )
                if sym_id and sym_id in G:
                    G.add_edge(
                        sym_id,
                        endpoint_node_id,
                        key=EdgeType.HANDLES_ENDPOINT.value,
                        relation=EdgeType.HANDLES_ENDPOINT.value,
                    )
                    # Update handler_symbol on endpoint node
                    G.nodes[endpoint_node_id]["handler_symbol"] = sym_id

    # ======================================================================
    # Service interface nodes (events from runtime interfaces)
    # ======================================================================

    def _add_service_interface_nodes(
        self, service_interfaces: dict[str, dict]
    ) -> None:
        """Add event nodes from service interface definitions.

        ``service_interfaces`` maps service_name to an interface dict with
        ``events_published`` and ``events_consumed`` lists.
        """
        for svc_name, interface in service_interfaces.items():
            svc_node_id = f"service::{svc_name}"

            # Events published
            for event in interface.get("events_published", []):
                event_name = event if isinstance(event, str) else event.get("name", "")
                if not event_name:
                    continue
                event_node_id = f"event::{event_name}"
                if event_node_id not in self._kg.graph:
                    self._kg.add_node(
                        event_node_id,
                        node_type=NodeType.EVENT.value,
                        event_name=event_name,
                        channel=event_name,
                        service_name=svc_name,
                    )
                if svc_node_id in self._kg.graph:
                    self._kg.add_edge(
                        svc_node_id,
                        event_node_id,
                        key=EdgeType.PUBLISHES_EVENT.value,
                        relation=EdgeType.PUBLISHES_EVENT.value,
                    )

            # Events consumed
            for event in interface.get("events_consumed", []):
                event_name = event if isinstance(event, str) else event.get("name", "")
                if not event_name:
                    continue
                event_node_id = f"event::{event_name}"
                if event_node_id not in self._kg.graph:
                    self._kg.add_node(
                        event_node_id,
                        node_type=NodeType.EVENT.value,
                        event_name=event_name,
                        channel=event_name,
                    )
                if svc_node_id in self._kg.graph:
                    self._kg.add_edge(
                        svc_node_id,
                        event_node_id,
                        key=EdgeType.CONSUMES_EVENT.value,
                        relation=EdgeType.CONSUMES_EVENT.value,
                    )

    # ======================================================================
    # Derive service-level edges
    # ======================================================================

    def _derive_service_edges(self) -> None:
        """Derive SERVICE_CALLS edges between services.

        Iterate IMPORTS edges between files. If source and target belong to
        different services (and neither is a shared utility), create one
        SERVICE_CALLS edge per unique (source_service, target_service) pair.
        """
        service_pairs: dict[tuple[str, str], str] = {}

        for u, v, key, attrs in self._kg.graph.edges(keys=True, data=True):
            relation = attrs.get("relation", "")
            if relation != EdgeType.IMPORTS.value:
                continue

            u_attrs = self._kg.graph.nodes.get(u, {})
            v_attrs = self._kg.graph.nodes.get(v, {})

            src_service = u_attrs.get("service_name", "")
            tgt_service = v_attrs.get("service_name", "")

            if not src_service or not tgt_service:
                continue
            if src_service == tgt_service:
                continue

            # Skip shared utilities
            src_file = u_attrs.get("file_path", str(u))
            tgt_file = v_attrs.get("file_path", str(v))
            if self._is_shared_utility(src_file) or self._is_shared_utility(tgt_file):
                continue

            pair = (src_service, tgt_service)

            # Try to find via_endpoint (first match wins)
            if pair not in service_pairs:
                service_pairs[pair] = ""
            if service_pairs[pair]:
                continue  # Already found an endpoint for this pair

            for tgt_neighbor in self._kg.graph.successors(v):
                edge_data = self._kg.graph.get_edge_data(v, tgt_neighbor)
                if edge_data:
                    for _, e_attrs in edge_data.items():
                        if e_attrs.get("relation") == EdgeType.HANDLES_ENDPOINT.value:
                            service_pairs[pair] = tgt_neighbor
                            break
                if service_pairs[pair]:
                    break

        # Create SERVICE_CALLS edges
        for (src_svc, tgt_svc), via_endpoint in service_pairs.items():
            src_node = f"service::{src_svc}"
            tgt_node = f"service::{tgt_svc}"
            if src_node in self._kg.graph and tgt_node in self._kg.graph:
                self._kg.add_edge(
                    src_node,
                    tgt_node,
                    key=EdgeType.SERVICE_CALLS.value,
                    relation=EdgeType.SERVICE_CALLS.value,
                    via_endpoint=via_endpoint,
                )

    # ======================================================================
    # Document templates for ChromaDB
    # ======================================================================

    def _build_node_document(self, node_id: str, attrs: dict[str, Any]) -> str:
        """Build a text document for a node based on its type."""
        node_type = attrs.get("node_type", "")

        if node_type == NodeType.FILE.value:
            file_path = attrs.get("file_path", node_id.replace("file::", "", 1))
            language = attrs.get("language", "")
            service_name = attrs.get("service_name", "")
            return (
                f"File: {file_path}. "
                f"Language: {language}. "
                f"Service: {service_name}."
            )

        if node_type == NodeType.SYMBOL.value:
            symbol_name = attrs.get("symbol_name", "")
            kind = attrs.get("kind", "")
            file_path = attrs.get("file_path", "")
            signature = attrs.get("signature", "")
            service_name = attrs.get("service_name", "")
            return (
                f"Symbol: {symbol_name} ({kind}) in {file_path}. "
                f"Signature: {signature}. "
                f"Service: {service_name}."
            )

        if node_type == NodeType.SERVICE.value:
            service_name = attrs.get("service_name", "")
            domain = attrs.get("domain", "")
            description = attrs.get("description", "")
            stack = attrs.get("stack", "[]")
            return (
                f"Service: {service_name}. "
                f"Domain: {domain}. "
                f"Description: {description}. "
                f"Stack: {stack}."
            )

        if node_type == NodeType.CONTRACT.value:
            contract_type = attrs.get("contract_type", "")
            version = attrs.get("version", "")
            service_name = attrs.get("service_name", "")
            status = attrs.get("status", "")
            return (
                f"Contract: {contract_type} v{version} for {service_name}. "
                f"Status: {status}."
            )

        if node_type == NodeType.ENDPOINT.value:
            method = attrs.get("method", "")
            path = attrs.get("path", "")
            service_name = attrs.get("service_name", "")
            return (
                f"Endpoint: {method} {path} on {service_name}."
            )

        if node_type == NodeType.DOMAIN_ENTITY.value:
            entity_name = attrs.get("entity_name", "")
            description = attrs.get("description", "")
            owning_service = attrs.get("owning_service", "")
            fields_summary = attrs.get("fields_summary", "")
            return (
                f"Domain Entity: {entity_name}. "
                f"Description: {description}. "
                f"Owned by: {owning_service}. "
                f"Fields: {fields_summary}."
            )

        if node_type == NodeType.EVENT.value:
            event_name = attrs.get("event_name", "")
            channel = attrs.get("channel", "")
            return (
                f"Event: {event_name} on channel {channel}."
            )

        # Fallback for unknown node types
        return f"Node: {node_id}."

    # ======================================================================
    # Context records (service + community summaries)
    # ======================================================================

    def _build_context_records(
        self, communities: list[set[str]]
    ) -> list[GraphRAGContextRecord]:
        """Build context records for services and communities."""
        records: list[GraphRAGContextRecord] = []

        # -- Service context records -------------------------------------
        service_nodes: dict[str, dict[str, Any]] = {}
        for node_id, attrs in self._kg.graph.nodes(data=True):
            if attrs.get("node_type") == NodeType.SERVICE.value:
                service_nodes[node_id] = attrs

        for svc_node_id, svc_attrs in service_nodes.items():
            svc_name = svc_attrs.get("service_name", "")
            # Count nodes and edges belonging to this service
            svc_node_count = 0
            svc_edge_count = 0
            node_ids_in_service: set[str] = set()

            for nid, n_attrs in self._kg.graph.nodes(data=True):
                if n_attrs.get("service_name") == svc_name:
                    svc_node_count += 1
                    node_ids_in_service.add(nid)

            for u, v, _key, _e_attrs in self._kg.graph.edges(keys=True, data=True):
                if u in node_ids_in_service or v in node_ids_in_service:
                    svc_edge_count += 1

            # Build context document
            description = svc_attrs.get("description", "")
            domain = svc_attrs.get("domain", "")
            stack = svc_attrs.get("stack", "[]")
            community_id = svc_attrs.get("community_id", -1)

            doc = (
                f"Service: {svc_name}. Domain: {domain}. "
                f"Description: {description}. Stack: {stack}. "
                f"Contains {svc_node_count} nodes and {svc_edge_count} edges."
            )

            records.append(
                GraphRAGContextRecord(
                    id=f"ctx::service::{svc_name}",
                    document=doc,
                    context_type="service",
                    service_name=svc_name,
                    community_id=community_id,
                    node_count=svc_node_count,
                    edge_count=svc_edge_count,
                )
            )

        # -- Community context records -----------------------------------
        for community_idx, community_set in enumerate(communities):
            if not community_set:
                continue

            # Gather info about this community
            node_types_in_community: dict[str, int] = defaultdict(int)
            services_in_community: set[str] = set()
            for nid in community_set:
                n_attrs = self._kg.graph.nodes.get(nid, {})
                nt = n_attrs.get("node_type", "unknown")
                node_types_in_community[nt] += 1
                sn = n_attrs.get("service_name", "")
                if sn:
                    services_in_community.add(sn)

            # Count edges within community
            community_edge_count = 0
            for u, v, _key, _e_attrs in self._kg.graph.edges(keys=True, data=True):
                if u in community_set and v in community_set:
                    community_edge_count += 1

            types_summary = ", ".join(
                f"{count} {nt}" for nt, count in sorted(node_types_in_community.items())
            )
            services_summary = ", ".join(sorted(services_in_community)) or "none"

            doc = (
                f"Community {community_idx}: {len(community_set)} nodes, "
                f"{community_edge_count} edges. "
                f"Node types: {types_summary}. "
                f"Services: {services_summary}."
            )

            records.append(
                GraphRAGContextRecord(
                    id=f"ctx::community::{community_idx}",
                    document=doc,
                    context_type="community",
                    community_id=community_idx,
                    node_count=len(community_set),
                    edge_count=community_edge_count,
                )
            )

        return records

    # ======================================================================
    # Utility helpers
    # ======================================================================

    @staticmethod
    def _is_shared_utility(file_path: str) -> bool:
        """Check if a file path belongs to a shared utility directory."""
        normalized = file_path.replace("\\", "/").lower()
        return any(pat in normalized for pat in _SHARED_UTILITY_PATTERNS)

    def _count_node_types(self) -> dict[str, int]:
        """Count nodes grouped by node_type."""
        counts: dict[str, int] = defaultdict(int)
        for _, attrs in self._kg.graph.nodes(data=True):
            nt = attrs.get("node_type", "unknown")
            counts[nt] += 1
        return dict(counts)

    def _count_edge_types(self) -> dict[str, int]:
        """Count edges grouped by relation/edge_type."""
        counts: dict[str, int] = defaultdict(int)
        for _, _, _, attrs in self._kg.graph.edges(keys=True, data=True):
            rel = attrs.get("relation", "unknown")
            counts[rel] += 1
        return dict(counts)

    def _collect_services_indexed(self) -> list[str]:
        """Collect unique service names from service nodes."""
        services: set[str] = set()
        for _, attrs in self._kg.graph.nodes(data=True):
            if attrs.get("node_type") == NodeType.SERVICE.value:
                sn = attrs.get("service_name", "")
                if sn:
                    services.add(sn)
        return sorted(services)

    def _count_communities(self) -> int:
        """Count unique community IDs assigned to nodes."""
        community_ids: set[int] = set()
        for _, attrs in self._kg.graph.nodes(data=True):
            cid = attrs.get("community_id")
            if cid is not None and cid >= 0:
                community_ids.add(cid)
        return len(community_ids)
