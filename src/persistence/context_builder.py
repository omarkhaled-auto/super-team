"""Context builder -- assembles failure memory and fix context for prompt injection."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.build3_shared.models import ScanViolation

if TYPE_CHECKING:
    from src.persistence.pattern_store import PatternStore
    from src.persistence.run_tracker import RunTracker

logger = logging.getLogger(__name__)


def build_failure_context(
    service_name: str,
    tech_stack: str,
    config: object,
    pattern_store: "PatternStore | None",
    run_tracker: "RunTracker | None",
) -> str:
    """Build a failure-memory context section for builder prompt injection.

    Queries ``RunTracker`` for top violations by tech stack and
    ``PatternStore`` for semantically similar past patterns.  Returns
    a formatted prompt section using the same delimiter pattern as the
    contract engine context injection.

    Returns ``""`` if persistence is disabled, unavailable, or on any failure.

    Args:
        service_name: Name of the service being built.
        tech_stack: Technology stack (e.g. ``"python/fastapi"``).
        config: Pipeline config -- checked for ``persistence.enabled``.
        pattern_store: ChromaDB-backed pattern store instance.
        run_tracker: SQLite-backed run tracker instance.
    """
    try:
        persistence_cfg = getattr(config, "persistence", None)
        if persistence_cfg is None or not getattr(persistence_cfg, "enabled", False):
            return ""
        if run_tracker is None and pattern_store is None:
            return ""

        max_patterns = getattr(persistence_cfg, "max_patterns_per_injection", 5)
        sections: list[str] = []

        # Top violations from SQLite stats
        if run_tracker is not None:
            stats = run_tracker.get_stats_for_stack(tech_stack)
            if stats:
                top_stats = stats[:max_patterns]
                lines = [
                    f"- {s['scan_code']}: {s['occurrence_count']} occurrences, "
                    f"fix rate {s['fix_success_rate']:.0%}"
                    for s in top_stats
                ]
                sections.append(
                    "Top recurring violations for this tech stack:\n"
                    + "\n".join(lines)
                )

        # Semantic pattern matches from ChromaDB
        if pattern_store is not None:
            patterns = pattern_store.find_similar_patterns(
                message=f"Common violations for {service_name} {tech_stack}",
                tech_stack=tech_stack,
                limit=max_patterns,
            )
            if patterns:
                lines = []
                for p in patterns:
                    meta = p.get("metadata", {})
                    lines.append(
                        f"- [{meta.get('scan_code', '?')}] "
                        f"{p.get('document', '')[:200]}"
                    )
                sections.append(
                    "Similar violation patterns from prior runs:\n"
                    + "\n".join(lines)
                )

        if not sections:
            return ""

        body = "\n\n".join(sections)
        return (
            "\n\n"
            "================================================\n"
            "FAILURE MEMORY FROM PRIOR RUNS\n"
            "================================================\n"
            f"Service: {service_name} | Stack: {tech_stack}\n\n"
            f"{body}\n\n"
            "Use this information to proactively avoid these violations.\n"
            "================================================\n"
        )

    except Exception as exc:
        logger.warning("build_failure_context failed (non-blocking): %s", exc)
        return ""


def build_fix_context(
    violations: list[ScanViolation],
    tech_stack: str,
    config: object,
    pattern_store: "PatternStore | None",
) -> str:
    """Build a fix-example context section for FIX_INSTRUCTIONS.md injection.

    For each violation, queries ``PatternStore`` for prior fix examples
    and formats them as a prompt section.

    Returns ``""`` if persistence is disabled, unavailable, or on any failure.

    Args:
        violations: Current violations that need fixing.
        tech_stack: Technology stack for filtering.
        config: Pipeline config -- checked for ``persistence.enabled``.
        pattern_store: ChromaDB-backed pattern store instance.
    """
    try:
        persistence_cfg = getattr(config, "persistence", None)
        if persistence_cfg is None or not getattr(persistence_cfg, "enabled", False):
            return ""
        if pattern_store is None:
            return ""

        max_patterns = getattr(persistence_cfg, "max_patterns_per_injection", 5)
        all_examples: list[str] = []
        seen_codes: set[str] = set()

        for violation in violations:
            if violation.code in seen_codes:
                continue
            seen_codes.add(violation.code)

            examples = pattern_store.find_fix_examples(
                scan_code=violation.code,
                tech_stack=tech_stack,
                limit=min(3, max_patterns),
            )
            if examples:
                for ex in examples:
                    doc = ex.get("document", "")
                    if doc:
                        all_examples.append(
                            f"[{violation.code}] Prior fix:\n{doc[:500]}"
                        )

            if len(all_examples) >= max_patterns:
                break

        if not all_examples:
            return ""

        body = "\n\n".join(all_examples)
        return (
            "\n\n"
            "================================================\n"
            "FIX EXAMPLES FROM PRIOR RUNS\n"
            "================================================\n"
            f"{body}\n\n"
            "Apply similar fix patterns where applicable.\n"
            "================================================\n"
        )

    except Exception as exc:
        logger.warning("build_fix_context failed (non-blocking): %s", exc)
        return ""
