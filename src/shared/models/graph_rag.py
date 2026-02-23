"""Data models for the Graph RAG module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    """Types of nodes in the knowledge graph."""
    FILE = "file"
    SYMBOL = "symbol"
    SERVICE = "service"
    CONTRACT = "contract"
    ENDPOINT = "endpoint"
    DOMAIN_ENTITY = "domain_entity"
    EVENT = "event"


class EdgeType(str, Enum):
    """Types of edges in the knowledge graph."""
    CONTAINS_FILE = "CONTAINS_FILE"
    DEFINES_SYMBOL = "DEFINES_SYMBOL"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    PROVIDES_CONTRACT = "PROVIDES_CONTRACT"
    EXPOSES_ENDPOINT = "EXPOSES_ENDPOINT"
    HANDLES_ENDPOINT = "HANDLES_ENDPOINT"
    OWNS_ENTITY = "OWNS_ENTITY"
    REFERENCES_ENTITY = "REFERENCES_ENTITY"
    IMPLEMENTS_ENTITY = "IMPLEMENTS_ENTITY"
    PUBLISHES_EVENT = "PUBLISHES_EVENT"
    CONSUMES_EVENT = "CONSUMES_EVENT"
    SERVICE_CALLS = "SERVICE_CALLS"
    DOMAIN_RELATIONSHIP = "DOMAIN_RELATIONSHIP"


@dataclass
class GraphRAGBuildResult:
    """Result of building/rebuilding the knowledge graph."""
    success: bool
    node_count: int = 0
    edge_count: int = 0
    node_types: dict[str, int] = field(default_factory=dict)
    edge_types: dict[str, int] = field(default_factory=dict)
    community_count: int = 0
    build_time_ms: int = 0
    services_indexed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class GraphRAGNodeRecord:
    """A record to upsert into the graph-rag-nodes ChromaDB collection."""
    id: str
    document: str
    node_type: str
    service_name: str = ""
    language: str = ""
    community_id: int = -1
    pagerank: float = 0.0


@dataclass
class GraphRAGContextRecord:
    """A record to upsert into the graph-rag-context ChromaDB collection."""
    id: str
    document: str
    context_type: str
    service_name: str = ""
    community_id: int = -1
    node_count: int = 0
    edge_count: int = 0


@dataclass
class GraphRAGSearchResult:
    """A single result from a Graph RAG query."""
    node_id: str
    node_type: str
    score: float
    semantic_score: float = 0.0
    graph_score: float = 0.0
    distance: int = -1
    document: str = ""
    metadata: dict[str, str | int | float] = field(default_factory=dict)


@dataclass
class ServiceContext:
    """Complete context for a service, ready for builder injection."""
    service_name: str
    provided_endpoints: list[dict[str, str]] = field(default_factory=list)
    consumed_endpoints: list[dict[str, str]] = field(default_factory=list)
    events_published: list[dict[str, str]] = field(default_factory=list)
    events_consumed: list[dict[str, str]] = field(default_factory=list)
    owned_entities: list[dict[str, str | list]] = field(default_factory=list)
    referenced_entities: list[dict[str, str | list]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    depended_on_by: list[str] = field(default_factory=list)
    context_text: str = ""


@dataclass
class CrossServiceImpact:
    """Result of cross-service impact analysis."""
    source_node: str
    source_service: str
    impacted_services: list[dict[str, str | int | list]] = field(default_factory=list)
    impacted_contracts: list[dict[str, str | list]] = field(default_factory=list)
    impacted_entities: list[dict[str, str]] = field(default_factory=list)
    total_impacted_nodes: int = 0


@dataclass
class EventValidationResult:
    """Result of cross-service event validation."""
    orphaned_events: list[dict[str, str | list]] = field(default_factory=list)
    unmatched_consumers: list[dict[str, str | list]] = field(default_factory=list)
    matched_events: list[dict[str, str | list]] = field(default_factory=list)
    total_events: int = 0
    match_rate: float = 0.0


@dataclass
class ServiceBoundaryValidation:
    """Result of service boundary validation via community detection."""
    communities_detected: int = 0
    services_declared: int = 0
    alignment_score: float = 0.0
    misplaced_files: list[dict[str, str | float]] = field(default_factory=list)
    isolated_files: list[str] = field(default_factory=list)
    service_coupling: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class GraphRAGSourceData:
    """All source data loaded for knowledge graph construction."""
    existing_graph: object | None = None
    symbols: list[dict] = field(default_factory=list)
    service_map: dict | None = None
    domain_model: dict | None = None
    contracts: list[dict] = field(default_factory=list)
    service_interfaces: dict[str, dict] = field(default_factory=dict)
    dependency_edges: list[dict] = field(default_factory=list)
