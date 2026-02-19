"""Shared test fixtures for the Run 4 test suite.

Provides session-scoped configuration fixtures, mock MCP session
utilities, and helper functions for constructing MCP tool results.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.run4.config import Run4Config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Mock MCP result helper (INT-003)
# ---------------------------------------------------------------------------

@dataclass
class MockToolResult:
    """Lightweight stand-in for an MCP ``CallToolResult``."""

    content: list[Any]
    isError: bool = False


@dataclass
class MockTextContent:
    """Lightweight stand-in for MCP ``TextContent``."""

    type: str = "text"
    text: str = ""


def make_mcp_result(data: dict, is_error: bool = False) -> MockToolResult:
    """Build a mock MCP tool result with TextContent containing JSON.

    Args:
        data: Dictionary to serialise into the result's text content.
        is_error: Whether the result represents an error.

    Returns:
        A ``MockToolResult`` whose first content item is a
        ``MockTextContent`` with the JSON-encoded *data*.
    """
    import json

    text_content = MockTextContent(text=json.dumps(data))
    return MockToolResult(content=[text_content], isError=is_error)


# ---------------------------------------------------------------------------
# Session-scoped fixtures (INT-001)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run4_config(tmp_path_factory: pytest.TempPathFactory) -> Run4Config:
    """Provide a Run4Config with temporary build-root directories.

    Creates three temporary directories to satisfy path validation.
    """
    base = tmp_path_factory.mktemp("run4_roots")
    b1 = base / "build1"
    b2 = base / "build2"
    b3 = base / "build3"
    b1.mkdir()
    b2.mkdir()
    b3.mkdir()
    return Run4Config(
        build1_project_root=b1,
        build2_project_root=b2,
        build3_project_root=b3,
    )


@pytest.fixture(scope="session")
def sample_prd_text() -> str:
    """Load the sample PRD fixture as a string."""
    prd_path = _FIXTURES_DIR / "sample_prd.md"
    return prd_path.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def build1_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a temporary Build 1 project root."""
    return tmp_path_factory.mktemp("build1_root")


@pytest.fixture(scope="session")
def contract_engine_params() -> dict:
    """Provide StdioServerParameters-compatible dict for contract-engine MCP.

    Returns a dict rather than a real ``StdioServerParameters`` so the
    test suite runs without the MCP server actually being available.
    """
    return {
        "command": "python",
        "args": ["-m", "src.contract_engine.mcp_server"],
        "env": {
            "DATABASE_PATH": "./data/contracts.db",
        },
    }


@pytest.fixture(scope="session")
def architect_params() -> dict:
    """Provide StdioServerParameters-compatible dict for architect MCP."""
    return {
        "command": "python",
        "args": ["-m", "src.architect.mcp_server"],
        "env": {
            "DATABASE_PATH": "./data/architect.db",
            "CONTRACT_ENGINE_URL": "http://localhost:8002",
        },
    }


@pytest.fixture(scope="session")
def codebase_intel_params() -> dict:
    """Provide StdioServerParameters-compatible dict for codebase-intelligence MCP."""
    return {
        "command": "python",
        "args": ["-m", "src.codebase_intelligence.mcp_server"],
        "env": {
            "DATABASE_PATH": "./data/symbols.db",
            "CHROMA_PATH": "./data/chroma",
            "GRAPH_PATH": "./data/graph.json",
        },
    }


# ---------------------------------------------------------------------------
# Mock MCP session fixture (INT-002)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mcp_session() -> AsyncMock:
    """Provide an ``AsyncMock`` simulating an MCP ``ClientSession``.

    The mock has callable ``initialize``, ``list_tools``, and
    ``call_tool`` methods pre-configured with sensible defaults.
    """
    session = AsyncMock()

    # initialize() returns None
    session.initialize = AsyncMock(return_value=None)

    # list_tools() returns an object with a .tools list
    tool_a = MagicMock()
    tool_a.name = "tool_a"
    tool_a.description = "First test tool"

    tool_b = MagicMock()
    tool_b.name = "tool_b"
    tool_b.description = "Second test tool"

    tools_response = MagicMock()
    tools_response.tools = [tool_a, tool_b]
    session.list_tools = AsyncMock(return_value=tools_response)

    # call_tool() returns a default success result
    session.call_tool = AsyncMock(
        return_value=make_mcp_result({"status": "ok"})
    )

    return session
