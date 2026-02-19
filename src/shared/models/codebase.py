"""Codebase intelligence Pydantic v2 data models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SymbolKind(str, Enum):
    """Types of code symbols."""
    CLASS = "class"
    FUNCTION = "function"
    INTERFACE = "interface"
    TYPE = "type"
    ENUM = "enum"
    VARIABLE = "variable"
    METHOD = "method"


class Language(str, Enum):
    """Supported programming languages."""
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    CSHARP = "csharp"
    GO = "go"


class DependencyRelation(str, Enum):
    """Types of dependency relationships."""
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    USES = "uses"


class SymbolDefinition(BaseModel):
    """Definition of a code symbol."""
    id: str = ""
    file_path: str
    symbol_name: str
    kind: SymbolKind
    language: Language
    service_name: str | None = None
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    signature: str | None = None
    docstring: str | None = None
    is_exported: bool = True
    parent_symbol: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def generate_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            file_path = data.get("file_path", "")
            symbol_name = data.get("symbol_name", "")
            if file_path and symbol_name and not data.get("id"):
                data["id"] = f"{file_path}::{symbol_name}"
        return data


class ImportReference(BaseModel):
    """Reference to an import statement."""
    source_file: str
    target_file: str
    imported_names: list[str] = Field(default_factory=list)
    line: int = Field(..., ge=1)
    is_relative: bool = False

    model_config = {"from_attributes": True}


class DependencyEdge(BaseModel):
    """Edge in the dependency graph."""
    source_symbol_id: str
    target_symbol_id: str
    relation: DependencyRelation
    source_file: str
    target_file: str
    line: int | None = None

    model_config = {"from_attributes": True}


class CodeChunk(BaseModel):
    """A chunk of code for semantic search."""
    id: str
    file_path: str
    content: str
    language: str
    service_name: str | None = None
    symbol_name: str | None = None
    symbol_kind: SymbolKind | None = None
    line_start: int
    line_end: int

    model_config = {"from_attributes": True}


class SemanticSearchResult(BaseModel):
    """Result from a semantic search."""
    chunk_id: str
    file_path: str
    symbol_name: str | None = None
    content: str
    score: float = Field(..., ge=0.0, le=1.0)
    language: str
    service_name: str | None = None
    line_start: int
    line_end: int

    model_config = {"from_attributes": True}


class ServiceInterface(BaseModel):
    """Interface exposed by a service."""
    service_name: str
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    events_published: list[dict[str, Any]] = Field(default_factory=list)
    events_consumed: list[dict[str, Any]] = Field(default_factory=list)
    exported_symbols: list[SymbolDefinition] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DeadCodeEntry(BaseModel):
    """Entry for a piece of dead code."""
    symbol_name: str
    file_path: str
    kind: SymbolKind
    line: int
    service_name: str | None = None
    confidence: str = Field(default="high", pattern=r"^(high|medium|low)$")

    model_config = {"from_attributes": True}


class GraphAnalysis(BaseModel):
    """Analysis of the dependency graph."""
    node_count: int
    edge_count: int
    is_dag: bool
    circular_dependencies: list[list[str]] = Field(default_factory=list)
    top_files_by_pagerank: list[tuple[str, float]] = Field(default_factory=list)
    connected_components: int
    build_order: list[str] | None = None

    model_config = {"from_attributes": True}


class IndexStats(BaseModel):
    """Statistics about the code index."""
    total_files: int
    total_symbols: int
    total_edges: int
    total_chunks: int
    languages: dict[str, int] = Field(default_factory=dict)
    services: dict[str, int] = Field(default_factory=dict)
    last_indexed_at: datetime | None = None

    model_config = {"from_attributes": True}
