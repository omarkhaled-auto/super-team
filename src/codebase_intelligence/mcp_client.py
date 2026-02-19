"""MCP client wrappers for Build 1 Codebase Intelligence service.

Provides ``CodebaseIntelligenceClient`` — a high-level async wrapper around
the 7 Codebase Intelligence MCP tools (SVC-011 through SVC-017).  Each method
opens a fresh stdio transport session, calls the appropriate tool, and returns
a typed Python object.  On any MCP/transport error the methods return safe
defaults (empty dicts/lists) rather than raising, so Build 2 callers can
always proceed to fallback logic without exception handling.

All methods support a retry-with-exponential-backoff pattern (3 retries,
base delay 1 s) to handle transient MCP transport failures.

Also provides ``generate_codebase_map()`` — a filesystem-based fallback that
produces a basic codebase map without requiring the CI MCP server, and
``get_codebase_map_with_fallback()`` which tries CI MCP first and falls back
to ``generate_codebase_map()`` when the server is unavailable (WIRE-010).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("codebase_intelligence.mcp_client")


# ---------------------------------------------------------------------------
# WIRE-010 — Filesystem fallback: generate_codebase_map()
# ---------------------------------------------------------------------------

# File extensions mapped to language names for the fallback scanner.
_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".cs": "csharp",
    ".java": "java",
    ".rs": "rust",
    ".rb": "ruby",
}


def generate_codebase_map(
    project_root: str | Path,
    *,
    extensions: set[str] | None = None,
) -> dict[str, Any]:
    """Generate a basic codebase map by scanning the filesystem directly.

    This is the **fallback** used by Build 2 when the Codebase Intelligence
    MCP server is unavailable (WIRE-010).  It walks *project_root*, collects
    source files, and returns a lightweight map with file paths grouped by
    detected language.

    Args:
        project_root: Root directory of the project to scan.
        extensions: Optional set of file extensions to include (e.g.
            ``{".py", ".ts"}``).  Defaults to all known extensions in
            ``_EXTENSION_TO_LANGUAGE``.

    Returns:
        A dict with keys ``project_root``, ``files`` (list of file info
        dicts), ``languages`` (set of detected languages), and
        ``fallback`` flag set to ``True``.
    """
    root = Path(project_root)
    if extensions is None:
        extensions = set(_EXTENSION_TO_LANGUAGE.keys())

    files: list[dict[str, Any]] = []
    languages: set[str] = set()

    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs & common non-source dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".venv", "venv"}
            ]
            for fname in filenames:
                ext = Path(fname).suffix
                if ext in extensions:
                    fpath = Path(dirpath) / fname
                    lang = _EXTENSION_TO_LANGUAGE.get(ext, "unknown")
                    languages.add(lang)
                    files.append({
                        "file_path": str(fpath),
                        "language": lang,
                        "size_bytes": fpath.stat().st_size,
                    })

    return {
        "project_root": str(root),
        "files": files,
        "languages": sorted(languages),
        "total_files": len(files),
        "fallback": True,
    }


async def get_codebase_map_with_fallback(
    project_root: str | Path,
    client: "CodebaseIntelligenceClient | None" = None,
) -> dict[str, Any]:
    """Obtain a codebase map, trying CI MCP first with filesystem fallback.

    Implements the WIRE-010 requirement: when the Codebase Intelligence MCP
    server is unavailable, Build 2 falls back to ``generate_codebase_map()``.

    Args:
        project_root: Root directory of the project.
        client: Optional ``CodebaseIntelligenceClient`` instance.  When
            *None*, the function skips MCP and goes straight to fallback.

    Returns:
        A codebase map dict.  When produced by MCP the dict follows the
        CI server's schema; when produced by fallback it contains a
        ``"fallback": True`` marker.
    """
    if client is not None:
        try:
            # Try to get service interface as a proxy for "CI is alive"
            result = await client.get_service_interface("__healthcheck__")
            if result and "error" not in result:
                # CI MCP is available — gather full map via MCP
                logger.info("CI MCP available; using MCP-based codebase map")
                return {"project_root": str(project_root), "fallback": False, **result}
        except (ConnectionError, ImportError, OSError, Exception) as exc:
            logger.warning(
                "CI MCP unavailable (%s); falling back to generate_codebase_map()",
                exc,
            )

    # Fallback: filesystem-based codebase map
    logger.info("Using filesystem fallback: generate_codebase_map()")
    return generate_codebase_map(project_root)


class CodebaseIntelligenceClient:
    """Async client wrapper for the Codebase Intelligence MCP server.

    Each public method corresponds to one MCP tool registered in
    ``src.codebase_intelligence.mcp_server``.

    Parameters
    ----------
    session:
        An already-initialised MCP ``ClientSession`` (or compatible mock).
        When *None*, methods will create a new stdio session on each call.
    max_retries:
        Maximum number of retry attempts on transient failures (default 3).
    backoff_base:
        Base delay in seconds for exponential backoff (default 1).
    """

    def __init__(
        self,
        session: Any | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self._session = session
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_session(self) -> Any:
        """Return the pre-injected session or create a new stdio one."""
        if self._session is not None:
            return self._session

        # Lazy import to avoid hard dep when session is injected
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.session import ClientSession

        server_params = StdioServerParameters(
            command="python",
            args=["-m", "src.codebase_intelligence.mcp_server"],
        )
        read, write = await stdio_client(server_params).__aenter__()
        session = await ClientSession(read, write).__aenter__()
        await session.initialize()
        return session

    async def _call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> Any:
        """Call an MCP tool with retry + exponential backoff.

        Returns the parsed JSON result on success, or *None* on exhausted
        retries.
        """
        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                result = await session.call_tool(tool_name, params)
                return result
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = self._backoff_base * (2 ** attempt)
                    logger.debug(
                        "Retry %d/%d for %s after %.1fs: %s",
                        attempt + 1,
                        self._max_retries,
                        tool_name,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.warning(
            "All %d retries exhausted for %s: %s",
            self._max_retries,
            tool_name,
            last_error,
        )
        return None

    def _parse_result(self, result: Any, safe_default: Any) -> Any:
        """Parse an MCP tool result into a Python object.

        Returns *safe_default* when the result is ``None``, flagged as an
        error, or not parseable.
        """
        if result is None:
            return safe_default
        if getattr(result, "isError", False):
            return safe_default
        try:
            return json.loads(result.content[0].text)
        except Exception:
            return safe_default

    # ------------------------------------------------------------------
    # SVC-011 — find_definition
    # ------------------------------------------------------------------

    async def find_definition(
        self,
        symbol: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Find the definition location of a symbol.

        Returns a dict with file, line, kind, signature — or an empty dict
        on failure.
        """
        params: dict[str, Any] = {"symbol": symbol}
        if language is not None:
            params["language"] = language
        result = await self._call_tool("find_definition", params)
        return self._parse_result(result, {})

    # ------------------------------------------------------------------
    # SVC-012 — find_callers
    # ------------------------------------------------------------------

    async def find_callers(
        self,
        symbol: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Find all callers of a symbol.

        Returns a list of caller dicts — or an empty list on failure.
        """
        result = await self._call_tool(
            "find_callers", {"symbol": symbol, "max_results": max_results},
        )
        return self._parse_result(result, [])

    # ------------------------------------------------------------------
    # SVC-013 — find_dependencies
    # ------------------------------------------------------------------

    async def find_dependencies(
        self,
        file_path: str,
        depth: int = 1,
        direction: str = "both",
    ) -> dict[str, Any]:
        """Retrieve dependency relationships for a file.

        Returns a dict with imports, imported_by, transitive_deps,
        circular_deps — or an empty dict on failure.
        """
        result = await self._call_tool(
            "find_dependencies",
            {"file_path": file_path, "depth": depth, "direction": direction},
        )
        return self._parse_result(result, {})

    # ------------------------------------------------------------------
    # SVC-014 — search_semantic
    # ------------------------------------------------------------------

    async def search_semantic(
        self,
        query: str,
        language: str | None = None,
        service_name: str | None = None,
        n_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic code search.

        Returns a list of search-result dicts — or an empty list on failure.
        """
        params: dict[str, Any] = {"query": query, "n_results": n_results}
        if language is not None:
            params["language"] = language
        if service_name is not None:
            params["service_name"] = service_name
        result = await self._call_tool("search_semantic", params)
        return self._parse_result(result, [])

    # ------------------------------------------------------------------
    # SVC-015 — get_service_interface
    # ------------------------------------------------------------------

    async def get_service_interface(
        self,
        service_name: str,
    ) -> dict[str, Any]:
        """Extract the public interface of a service.

        Returns a ServiceInterface dict — or an empty dict on failure.
        """
        result = await self._call_tool(
            "get_service_interface", {"service_name": service_name},
        )
        return self._parse_result(result, {})

    # ------------------------------------------------------------------
    # SVC-016 — check_dead_code
    # ------------------------------------------------------------------

    async def check_dead_code(
        self,
        service_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect potentially dead code.

        Returns a list of dead-code entry dicts — or an empty list on failure.
        """
        params: dict[str, Any] = {}
        if service_name is not None:
            params["service_name"] = service_name
        result = await self._call_tool("check_dead_code", params)
        return self._parse_result(result, [])

    # ------------------------------------------------------------------
    # SVC-017 — register_artifact
    # ------------------------------------------------------------------

    async def register_artifact(
        self,
        file_path: str,
        service_name: str | None = None,
        source_base64: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        """Index a source file through the codebase-intelligence pipeline.

        Returns an ArtifactResult dict with indexed, symbols_found,
        dependencies_found, errors — or an empty dict on failure.
        """
        params: dict[str, Any] = {"file_path": file_path}
        if service_name is not None:
            params["service_name"] = service_name
        if source_base64 is not None:
            params["source_base64"] = source_base64
        if project_root is not None:
            params["project_root"] = project_root
        result = await self._call_tool("register_artifact", params)
        return self._parse_result(result, {})
