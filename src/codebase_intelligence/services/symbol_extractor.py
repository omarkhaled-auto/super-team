"""Symbol extraction from parsed AST trees into SymbolDefinition models."""
from __future__ import annotations

import logging

from src.shared.models.codebase import SymbolDefinition, SymbolKind, Language as LangEnum

logger = logging.getLogger(__name__)


class SymbolExtractor:
    """Converts raw parser output into SymbolDefinition model instances.

    Takes the symbol dicts from language-specific parsers and transforms them
    into proper SymbolDefinition Pydantic model instances with all fields set.
    """

    def extract_symbols(
        self,
        raw_symbols: list[dict],
        file_path: str,
        language: str,
        service_name: str | None = None,
    ) -> list[SymbolDefinition]:
        """Convert raw parser symbol dicts to SymbolDefinition instances.

        Args:
            raw_symbols: List of dicts from language-specific parsers.
                Each dict has: name, kind, line_start, line_end, signature,
                docstring, is_exported, parent_symbol
            file_path: Path to the source file
            language: Language string (python, typescript, csharp, go)
            service_name: Optional service name for the file

        Returns:
            List of SymbolDefinition instances
        """
        # Map language string to Language enum
        lang_enum = self._map_language(language)

        symbols: list[SymbolDefinition] = []
        for raw in raw_symbols:
            try:
                # Map kind to SymbolKind enum
                kind = self._map_kind(raw.get("kind", "function"))

                symbol = SymbolDefinition(
                    file_path=file_path,
                    symbol_name=raw["name"],
                    kind=kind,
                    language=lang_enum,
                    service_name=service_name or raw.get("service_name"),
                    line_start=raw["line_start"],
                    line_end=raw["line_end"],
                    signature=raw.get("signature"),
                    docstring=raw.get("docstring"),
                    is_exported=raw.get("is_exported", True),
                    parent_symbol=raw.get("parent_symbol"),
                )
                symbols.append(symbol)
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                logger.warning(
                    "Failed to create SymbolDefinition for %s in %s: %s",
                    raw.get("name", "?"), file_path, exc,
                )

        return symbols

    @staticmethod
    def _map_language(language: str) -> LangEnum:
        """Map a language string to the Language enum."""
        mapping = {
            "python": LangEnum.PYTHON,
            "typescript": LangEnum.TYPESCRIPT,
            "csharp": LangEnum.CSHARP,
            "go": LangEnum.GO,
        }
        result = mapping.get(language.lower())
        if result is None:
            raise ValueError(f"Unsupported language: {language}")
        return result

    @staticmethod
    def _map_kind(kind) -> SymbolKind:
        """Map a kind string or SymbolKind to the SymbolKind enum."""
        if isinstance(kind, SymbolKind):
            return kind
        mapping = {
            "class": SymbolKind.CLASS,
            "function": SymbolKind.FUNCTION,
            "method": SymbolKind.METHOD,
            "interface": SymbolKind.INTERFACE,
            "type": SymbolKind.TYPE,
            "enum": SymbolKind.ENUM,
            "variable": SymbolKind.VARIABLE,
        }
        result = mapping.get(str(kind).lower())
        if result is None:
            raise ValueError(f"Unknown symbol kind: {kind}")
        return result
