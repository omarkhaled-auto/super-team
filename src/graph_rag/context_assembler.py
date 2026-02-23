"""Context window assembly for Graph RAG service context blocks.

Produces structured markdown context blocks suitable for injection into builder
prompts.  Implements the truncation strategy described in GRAPH_RAG_DESIGN.md
Section 7.2 to stay within a configurable token budget.
"""
from __future__ import annotations


class ContextAssembler:
    """Assembles structured markdown context from graph traversal data.

    Parameters
    ----------
    max_tokens:
        Approximate token budget for assembled context.  Token count is
        estimated as ``len(text) // 4``.
    """

    def __init__(self, max_tokens: int = 2000) -> None:
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble_service_context(
        self,
        service_name: str,
        provided_endpoints: list[dict[str, str]],
        consumed_endpoints: list[dict[str, str]],
        events_published: list[dict[str, str]],
        events_consumed: list[dict[str, str]],
        owned_entities: list[dict[str, str | list]],
        referenced_entities: list[dict[str, str | list]],
        depends_on: list[str],
        depended_on_by: list[str],
    ) -> str:
        """Produce a markdown context block for *service_name*.

        Empty sections are omitted entirely.  When the total exceeds the
        token budget, lower-priority sections are truncated according to
        the priority scheme defined in GRAPH_RAG_DESIGN.md Section 7.2.
        """
        sections: list[tuple[str, str, int]] = []

        # -- Header (always included, priority 0) -------------------------
        header = f"## Graph RAG Context: {service_name}"
        sections.append(("header", header, 0))

        # -- Service Dependencies (priority 1) ----------------------------
        if depends_on or depended_on_by:
            lines = ["### Service Dependencies"]
            lines.append(
                f"- **Depends on:** {', '.join(depends_on) if depends_on else 'none'}"
            )
            lines.append(
                f"- **Depended on by:** {', '.join(depended_on_by) if depended_on_by else 'none'}"
            )
            sections.append(("dependencies", "\n".join(lines), 1))

        # -- APIs This Service Must Consume (priority 2) ------------------
        if consumed_endpoints:
            lines = [
                "### APIs This Service Must Consume",
                "| Method | Path | Provider Service |",
                "|--------|------|-----------------|",
            ]
            for ep in consumed_endpoints:
                method = ep.get("method", "")
                path = ep.get("path", "")
                provider = ep.get("provider_service", "")
                lines.append(f"| {method} | {path} | {provider} |")
            sections.append(("consumed_apis", "\n".join(lines), 2))

        # -- Domain Entities Referenced (priority 3) ----------------------
        if referenced_entities:
            lines = ["### Domain Entities Referenced (from other services)"]
            for ent in referenced_entities:
                name = ent.get("name", "Unknown")
                owning = ent.get("owning_service", "")
                if owning:
                    lines.append(f"#### {name} (owned by {owning})")
                else:
                    lines.append(f"#### {name}")
                fields = ent.get("fields", [])
                if isinstance(fields, list):
                    for field in fields:
                        if isinstance(field, dict):
                            fname = field.get("name", "")
                            ftype = field.get("type", "")
                            fdesc = field.get("description", "")
                            entry = f"- {fname}: {ftype}"
                            if fdesc:
                                entry += f" ({fdesc})"
                            lines.append(entry)
                        else:
                            lines.append(f"- {field}")
            sections.append(("referenced_entities", "\n".join(lines), 3))

        # -- APIs This Service Provides (priority 4) ----------------------
        if provided_endpoints:
            lines = [
                "### APIs This Service Provides",
                "| Method | Path | Handler |",
                "|--------|------|---------|",
            ]
            for ep in provided_endpoints:
                method = ep.get("method", "")
                path = ep.get("path", "")
                handler = ep.get("handler", "")
                lines.append(f"| {method} | {path} | {handler} |")
            sections.append(("provided_apis", "\n".join(lines), 4))

        # -- Events Published (priority 5) --------------------------------
        if events_published:
            lines = [
                "### Events Published",
                "| Event Name | Channel |",
                "|------------|---------|",
            ]
            for ev in events_published:
                name = ev.get("event_name", "")
                channel = ev.get("channel", "")
                lines.append(f"| {name} | {channel} |")
            sections.append(("events_published", "\n".join(lines), 5))

        # -- Events Consumed (priority 5) ---------------------------------
        if events_consumed:
            lines = [
                "### Events Consumed",
                "| Event Name | Publisher |",
                "|------------|----------|",
            ]
            for ev in events_consumed:
                name = ev.get("event_name", "")
                publisher = ev.get("publisher_service", "")
                lines.append(f"| {name} | {publisher} |")
            sections.append(("events_consumed", "\n".join(lines), 5))

        # -- Domain Entities Owned (priority 6) ---------------------------
        if owned_entities:
            lines = ["### Domain Entities Owned"]
            for ent in owned_entities:
                name = ent.get("name", "Unknown")
                lines.append(f"#### {name}")
                fields = ent.get("fields", [])
                if isinstance(fields, list):
                    for field in fields:
                        if isinstance(field, dict):
                            fname = field.get("name", "")
                            ftype = field.get("type", "")
                            fdesc = field.get("description", "")
                            entry = f"- {fname}: {ftype}"
                            if fdesc:
                                entry += f" ({fdesc})"
                            lines.append(entry)
                        else:
                            lines.append(f"- {field}")
            sections.append(("owned_entities", "\n".join(lines), 6))

        # -- Cross-Service Integration Notes (priority 7) -----------------
        notes = self._generate_integration_notes(
            service_name,
            consumed_endpoints,
            events_published,
            events_consumed,
            depended_on_by,
        )
        if notes:
            lines = ["### Cross-Service Integration Notes"]
            lines.extend(f"- {n}" for n in notes)
            sections.append(("integration_notes", "\n".join(lines), 7))

        return self.truncate_to_budget(sections, self._max_tokens)

    def assemble_community_summary(
        self,
        community_id: int,
        members: list[dict[str, str]],
        edges: list[dict[str, str]],
    ) -> str:
        """Produce a short markdown summary for a detected community.

        Parameters
        ----------
        community_id:
            Numeric community identifier.
        members:
            List of node dicts with at least ``id`` and ``node_type`` keys.
        edges:
            List of edge dicts with at least ``source``, ``target``, and
            ``relation`` keys.
        """
        member_ids = [m.get("id", "") for m in members]
        services = sorted(
            {m.get("service_name", "") for m in members if m.get("service_name")}
        )

        relationships: list[str] = []
        for edge in edges[:20]:  # Cap to avoid huge summaries
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relation", "")
            relationships.append(f"{src} --[{rel}]--> {tgt}")

        lines = [
            f"## Community {community_id}",
            f"**Members:** {', '.join(member_ids[:30])}{'...' if len(member_ids) > 30 else ''}",
            f"**Key relationships:** {'; '.join(relationships) if relationships else 'none'}",
            f"**Services:** {', '.join(services) if services else 'none'}",
        ]
        return "\n".join(lines)

    def truncate_to_budget(
        self,
        sections: list[tuple[str, str, int]],
        max_tokens: int,
    ) -> str:
        """Assemble sections within a token budget.

        Parameters
        ----------
        sections:
            List of ``(section_name, section_text, priority)`` tuples.
            Lower priority number means higher retention priority.
        max_tokens:
            Maximum approximate token count.  Estimated as
            ``len(text) // 4``.

        Returns
        -------
        str
            Concatenated sections fitting within budget, with the last
            partial section truncated and marked if necessary.
        """
        sorted_sections = sorted(sections, key=lambda s: s[2])
        result: list[str] = []
        tokens_used = 0

        for _name, text, _priority in sorted_sections:
            section_tokens = len(text) // 4
            if tokens_used + section_tokens <= max_tokens:
                result.append(text)
                tokens_used += section_tokens
            else:
                remaining = max_tokens - tokens_used
                if remaining > 0:
                    truncated_chars = remaining * 4
                    result.append(text[:truncated_chars] + "\n[... truncated ...]")
                break

        return "\n\n".join(result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_integration_notes(
        service_name: str,
        consumed_endpoints: list[dict[str, str]],
        events_published: list[dict[str, str]],
        events_consumed: list[dict[str, str]],
        depended_on_by: list[str],
    ) -> list[str]:
        """Auto-generate integration notes from relationship data."""
        notes: list[str] = []

        for ep in consumed_endpoints:
            provider = ep.get("provider_service", "")
            method = ep.get("method", "")
            path = ep.get("path", "")
            if provider and method and path:
                notes.append(
                    f"When calling {provider} {method} {path}, ensure the "
                    f"request matches the provider's contract schema."
                )

        for ev in events_published:
            event_name = ev.get("event_name", "")
            if event_name:
                consumers_str = ""
                # Check if any downstream services depend on this event
                if depended_on_by:
                    consumers_str = (
                        f" Downstream services ({', '.join(depended_on_by)}) "
                        f"may consume this event -- ensure payload schema is stable."
                    )
                notes.append(
                    f"When publishing {event_name}, include all required "
                    f"fields in the payload.{consumers_str}"
                )

        for ev in events_consumed:
            event_name = ev.get("event_name", "")
            publisher = ev.get("publisher_service", "")
            if event_name and publisher:
                notes.append(
                    f"Event {event_name} is published by {publisher}. "
                    f"Implement idempotent handling for this event."
                )

        return notes
