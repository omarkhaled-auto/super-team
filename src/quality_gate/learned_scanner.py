"""Learned scanner -- applies violation patterns from prior runs.

Loads patterns from a ``PatternStore`` (ChromaDB) and scans project
files for matches.  Violations are reported with ``LEARNED`` severity,
which is treated as ``WARNING`` (never blocks the pipeline).

Follows the ``QualityScanner`` protocol::

    async def scan(self, target_dir: Path) -> list[ScanViolation]
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.build3_shared.models import ScanViolation
from src.quality_gate.security_scanner import EXCLUDED_DIRS, SCANNABLE_EXTENSIONS

if TYPE_CHECKING:
    from src.persistence.pattern_store import PatternStore

logger = logging.getLogger(__name__)


class LearnedScanner:
    """Scans source files for violation patterns learned from prior runs.

    Loads top patterns for a given tech stack from ChromaDB on init and
    applies them via file walking.  LEARNED severity is treated as
    WARNING by the gate engine (never blocks the pipeline).

    Args:
        pattern_store: ChromaDB-backed pattern store.
        tech_stack: Technology stack to filter patterns.
        config: Pipeline config (for max_patterns_per_injection).
    """

    def __init__(
        self,
        pattern_store: "PatternStore",
        tech_stack: str,
        config: Any = None,
    ) -> None:
        self._pattern_store = pattern_store
        self._tech_stack = tech_stack
        self._patterns: list[dict] = []

        max_patterns = 20
        if config is not None:
            persistence_cfg = getattr(config, "persistence", None)
            if persistence_cfg is not None:
                max_patterns = getattr(persistence_cfg, "max_patterns_per_injection", 20)

        # Load top patterns from ChromaDB
        try:
            self._patterns = pattern_store.find_similar_patterns(
                message=f"Common violations for {tech_stack}",
                tech_stack=tech_stack,
                limit=max_patterns,
            )
            logger.info(
                "LearnedScanner loaded %d patterns for tech_stack=%s",
                len(self._patterns),
                tech_stack,
            )
        except Exception as exc:
            logger.warning("LearnedScanner failed to load patterns: %s", exc)

    @property
    def scan_codes(self) -> list[str]:
        """Return dynamically generated scan codes for loaded patterns."""
        return [
            f"LEARNED-{i + 1:03d}" for i in range(len(self._patterns))
        ]

    async def scan(self, target_dir: Path) -> list[ScanViolation]:
        """Scan *target_dir* for matches against learned patterns.

        Returns violations with severity ``LEARNED``, which is treated
        as ``info`` by the gate engine (bucketed under "info" for
        unknown severities -- see ``classify_violations``).
        """
        if not self._patterns:
            return []

        target_dir = Path(target_dir)
        if not target_dir.is_dir():
            return []

        violations: list[ScanViolation] = []

        try:
            files = [
                p for p in target_dir.rglob("*")
                if p.is_file()
                and p.suffix in SCANNABLE_EXTENSIONS
                and not (EXCLUDED_DIRS & set(p.parts))
            ]

            for fp in files:
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                except (OSError, PermissionError):
                    continue

                for i, pattern in enumerate(self._patterns):
                    doc = pattern.get("document", "")
                    meta = pattern.get("metadata", {})
                    scan_code_orig = meta.get("scan_code", "")

                    # Simple keyword-based matching from the pattern document
                    # Extract key terms from the pattern for matching
                    if doc and len(doc) > 10:
                        # Use the first significant keyword from the pattern
                        keywords = _extract_keywords(doc)
                        for keyword in keywords:
                            if keyword.lower() in content.lower():
                                violations.append(ScanViolation(
                                    code=f"LEARNED-{i + 1:03d}",
                                    severity="info",
                                    category="learned",
                                    file_path=str(fp),
                                    line=0,
                                    service="",
                                    message=(
                                        f"Learned pattern match (originally {scan_code_orig}): "
                                        f"{doc[:200]}"
                                    ),
                                ))
                                break  # One match per pattern per file

                    if len(violations) >= 200:
                        break
                if len(violations) >= 200:
                    break

        except Exception as exc:
            logger.warning("LearnedScanner.scan failed (non-blocking): %s", exc)

        return violations


def _extract_keywords(doc: str) -> list[str]:
    """Extract significant keywords from a pattern document for matching."""
    # Split on common delimiters and filter short/common words
    words = re.split(r"[\s|,.:;()\[\]{}]+", doc)
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "as", "or", "and", "but", "not", "no", "if", "then", "else",
        "this", "that", "it", "its", "suggestion", "found", "missing",
    }
    keywords = [
        w for w in words
        if len(w) >= 4
        and w.lower() not in stop_words
        and not w.isdigit()
    ]
    return keywords[:3]  # Use at most 3 keywords
