"""Dead code detection with confidence-level classification."""
from __future__ import annotations

import logging
import re

import networkx as nx

from src.shared.models.codebase import DeadCodeEntry, SymbolDefinition, SymbolKind

logger = logging.getLogger(__name__)

# Entry point patterns that should never be marked as dead code
_ENTRY_POINT_PATTERNS = [
    re.compile(r"^__main__$"),
    re.compile(r"^main$"),
    re.compile(r"^test_"),
    re.compile(r"^Test"),
    re.compile(r"_test$"),
]

# Lifecycle/framework method names that should not be dead code
_LIFECYCLE_METHODS = {
    # Python
    "__init__", "__new__", "__del__", "__enter__", "__exit__",
    "__str__", "__repr__", "__eq__", "__hash__", "__len__",
    "__getattr__", "__setattr__", "__getitem__", "__setitem__",
    "__iter__", "__next__", "__call__", "__bool__",
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    # FastAPI/Flask route handlers
    "startup", "shutdown", "lifespan",
    # TypeScript/JS
    "constructor", "render", "componentDidMount", "componentWillUnmount",
    "ngOnInit", "ngOnDestroy", "connectedCallback", "disconnectedCallback",
    # Go
    "init", "Init", "ServeHTTP",
    # C#
    "Main", "Dispose", "ConfigureServices", "Configure",
}

# Decorator patterns indicating the symbol is a handler/endpoint
_HANDLER_DECORATORS = {
    "app.get", "app.post", "app.put", "app.delete", "app.patch",
    "router.get", "router.post", "router.put", "router.delete",
    "Get", "Post", "Put", "Delete", "Patch",
    "HttpGet", "HttpPost", "HttpPut", "HttpDelete",
    "route", "Route",
    "property", "staticmethod", "classmethod",
    "abstractmethod", "override",
}


class DeadCodeDetector:
    """Detects potentially unused code using dependency graph analysis.

    Assigns confidence levels:
    - high: Symbol is never referenced and has no special role
    - medium: Symbol is only referenced within its own file
    - low: Symbol appears to be unused but matches a pattern that could be
      dynamically invoked
    """

    def __init__(self, graph: nx.DiGraph) -> None:
        self._graph = graph

    def find_dead_code(
        self,
        symbols: list[SymbolDefinition],
        referenced_symbols: set[str] | None = None,
    ) -> list[DeadCodeEntry]:
        """Find potentially dead code among the given symbols.

        Args:
            symbols: List of all known symbols
            referenced_symbols: Set of symbol IDs that are referenced.
                If None, uses the graph to determine references.

        Returns:
            List of DeadCodeEntry instances for potentially unused symbols.
        """
        if referenced_symbols is None:
            referenced_symbols = self._build_reference_set()

        dead_code: list[DeadCodeEntry] = []

        for symbol in symbols:
            try:
                # Skip symbols that are entry points or lifecycle methods
                if self._is_entry_point(symbol):
                    continue

                # Skip non-exported (private) symbols — they're expected to
                # be used only internally
                if not symbol.is_exported:
                    continue

                # Check if symbol is referenced
                if symbol.id in referenced_symbols:
                    continue

                # Determine confidence level
                confidence = self._assess_confidence(symbol, referenced_symbols)

                dead_code.append(DeadCodeEntry(
                    symbol_name=symbol.symbol_name,
                    file_path=symbol.file_path,
                    kind=symbol.kind,
                    line=symbol.line_start,
                    service_name=symbol.service_name,
                    confidence=confidence,
                ))
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning("Failed to analyze symbol %s: %s", getattr(symbol, 'symbol_name', '?'), exc)

        return dead_code

    def _build_reference_set(self) -> set[str]:
        """Build a set of all referenced symbol IDs from the graph edges."""
        referenced = set()
        for _, _, data in self._graph.edges(data=True):
            try:
                target_sym = data.get("target_symbol")
                source_sym = data.get("source_symbol")
                if target_sym:
                    referenced.add(target_sym)
                if source_sym:
                    referenced.add(source_sym)
            except (AttributeError, TypeError) as exc:
                logger.warning("Failed to read edge data: %s", exc)
        return referenced

    def _is_entry_point(self, symbol: SymbolDefinition) -> bool:
        """Check if a symbol is an entry point or lifecycle method."""
        name = symbol.symbol_name

        # Check lifecycle methods
        if name in _LIFECYCLE_METHODS:
            return True

        # Check entry point patterns
        for pattern in _ENTRY_POINT_PATTERNS:
            if pattern.match(name):
                return True

        # Check if the file is a known entry point
        if symbol.file_path.endswith("__main__.py"):
            return True

        # Methods with dunder names are usually special
        if name.startswith("__") and name.endswith("__"):
            return True

        return False

    def _assess_confidence(
        self, symbol: SymbolDefinition, referenced: set[str]
    ) -> str:
        """Assess the confidence level that a symbol is truly dead code.

        Returns: "high", "medium", or "low"
        """
        name = symbol.symbol_name

        # Low confidence: could be dynamically invoked
        # Names that look like handlers, callbacks, or have common prefixes
        if any(name.startswith(p) for p in ("on_", "handle_", "process_", "do_")):
            return "low"

        # Low confidence: decorated functions might be route handlers
        # (we can't always detect this from the graph alone)
        if symbol.kind == SymbolKind.FUNCTION and symbol.parent_symbol is None:
            # Top-level functions that could be endpoints
            if name.startswith(("get_", "post_", "put_", "delete_", "create_", "update_")):
                return "low"

        # Medium confidence: methods in classes (might be used via polymorphism)
        if symbol.kind == SymbolKind.METHOD:
            return "medium"

        # Medium confidence: interfaces and types might be used for type checking
        if symbol.kind in (SymbolKind.INTERFACE, SymbolKind.TYPE):
            return "medium"

        # High confidence: everything else
        return "high"
