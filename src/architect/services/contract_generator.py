"""Contract generator for the Architect Service.

Generates OpenAPI 3.1 contract stubs from a ServiceMap and DomainModel.
Every function in this module is a pure function with no global state.
"""
from __future__ import annotations

import re
from typing import Any

from src.shared.models.architect import DomainEntity, DomainModel, ServiceMap


# ---------------------------------------------------------------------------
# Field-type mapping: source type string -> JSON Schema fragment
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, dict[str, str]] = {
    "string": {"type": "string"},
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "number": {"type": "number"},
    "decimal": {"type": "number"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "uuid": {"type": "string", "format": "uuid"},
    "email": {"type": "string", "format": "email"},
    "array": {"type": "array", "items": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _camel_to_kebab(name: str) -> str:
    """Convert a CamelCase or PascalCase name to kebab-case.

    Examples:
        "User"      -> "user"
        "OrderItem" -> "order-item"
        "HTMLParser" -> "html-parser"
    """
    # Insert a hyphen before each uppercase letter that follows a lowercase
    # letter or digit, or before an uppercase letter followed by a lowercase.
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", s)
    return s.lower()


def _pluralize(name: str) -> str:
    """Naive English pluralization: append 's' unless already ends in 's'."""
    if name.endswith("s"):
        return name
    return name + "s"


def _entity_path_segment(entity_name: str) -> str:
    """Derive the URL path segment for an entity name.

    "User" -> "users", "OrderItem" -> "order-items"
    """
    return _pluralize(_camel_to_kebab(entity_name))


def _map_field_type(type_str: str) -> dict[str, Any]:
    """Map a domain field type string to a JSON Schema type fragment."""
    normalized = type_str.strip().lower()

    # Handle parameterised list types like "list[int]", "List[string]"
    if normalized.startswith("list[") and normalized.endswith("]"):
        return {"type": "array", "items": {"type": "string"}}

    return dict(_TYPE_MAP.get(normalized, {"type": "string"}))


def _find_entity(domain_model: DomainModel, entity_name: str) -> DomainEntity | None:
    """Look up a DomainEntity by name (case-insensitive)."""
    for entity in domain_model.entities:
        if entity.name.lower() == entity_name.lower():
            return entity
    return None


def _build_schema(entity: DomainEntity | None, entity_name: str) -> dict[str, Any]:
    """Build a JSON Schema object definition for an entity.

    If *entity* is ``None`` (not found in domain model) a minimal schema
    containing only an ``id`` field is returned.
    """
    properties: dict[str, Any] = {
        "id": {"type": "string", "format": "uuid"},
    }
    required: list[str] = ["id"]

    if entity is not None:
        for field in entity.fields:
            properties[field.name] = _map_field_type(field.type)
            if field.required:
                required.append(field.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _build_ref(entity_name: str) -> dict[str, str]:
    """Return a ``$ref`` pointer to a component schema."""
    return {"$ref": f"#/components/schemas/{entity_name}"}


def _build_crud_paths(
    entity_name: str,
    path_segment: str,
) -> dict[str, Any]:
    """Generate the five standard CRUD path items for a single entity.

    Returns a dict keyed by path string (e.g. ``/api/users``) whose values
    are OpenAPI path-item objects.
    """
    ref = _build_ref(entity_name)
    collection_path = f"/api/{path_segment}"
    item_path = f"/api/{path_segment}/{{id}}"

    paths: dict[str, Any] = {}

    # -- Collection endpoints -----------------------------------------------
    paths[collection_path] = {
        "get": {
            "summary": f"List all {path_segment}",
            "operationId": f"list_{path_segment.replace('-', '_')}",
            "responses": {
                "200": {
                    "description": f"A list of {path_segment}.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": ref,
                            }
                        }
                    },
                }
            },
        },
        "post": {
            "summary": f"Create a new {entity_name}",
            "operationId": f"create_{path_segment.replace('-', '_')}",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ref,
                    }
                },
            },
            "responses": {
                "201": {
                    "description": f"The created {entity_name}.",
                    "content": {
                        "application/json": {
                            "schema": ref,
                        }
                    },
                }
            },
        },
    }

    # -- Item endpoints -----------------------------------------------------
    id_param: dict[str, Any] = {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }

    paths[item_path] = {
        "get": {
            "summary": f"Get a {entity_name} by ID",
            "operationId": f"get_{path_segment.replace('-', '_')}_by_id",
            "parameters": [id_param],
            "responses": {
                "200": {
                    "description": f"The requested {entity_name}.",
                    "content": {
                        "application/json": {
                            "schema": ref,
                        }
                    },
                }
            },
        },
        "put": {
            "summary": f"Update a {entity_name}",
            "operationId": f"update_{path_segment.replace('-', '_')}",
            "parameters": [id_param],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": ref,
                    }
                },
            },
            "responses": {
                "200": {
                    "description": f"The updated {entity_name}.",
                    "content": {
                        "application/json": {
                            "schema": ref,
                        }
                    },
                }
            },
        },
        "delete": {
            "summary": f"Delete a {entity_name}",
            "operationId": f"delete_{path_segment.replace('-', '_')}",
            "parameters": [id_param],
            "responses": {
                "204": {
                    "description": "No content.",
                }
            },
        },
    }

    return paths


def _build_health_path() -> dict[str, Any]:
    """Return a minimal ``/health`` endpoint definition."""
    return {
        "/health": {
            "get": {
                "summary": "Health check",
                "operationId": "health_check",
                "responses": {
                    "200": {
                        "description": "Service is healthy.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_contract_stubs(
    service_map: ServiceMap,
    domain_model: DomainModel,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate OpenAPI 3.1 and AsyncAPI 3.0 contract stubs for each service.

    For each service in the service map:
    1. Create an OpenAPI 3.1 spec with info, paths, and components/schemas.
    2. Generate CRUD endpoints for each owned entity.
    3. Generate schema definitions from entity fields.

    When *events* is provided (non-empty list), also generates AsyncAPI 3.0
    specs for services that publish domain events.

    Args:
        service_map: The decomposed service map.
        domain_model: The domain model with entity details.
        events: Optional list of event dicts extracted from the PRD.

    Returns:
        List of spec dicts (OpenAPI 3.1 and AsyncAPI 3.0), one per service
        per type.  Each dict includes a ``"type"`` key (``"openapi"`` or
        ``"asyncapi"``) and a ``"service_id"`` key.
    """
    specs: list[dict[str, Any]] = []

    for service in service_map.services:
        description = service.description if service.description else service.name

        spec: dict[str, Any] = {
            "type": "openapi",
            "service_id": service.name,
            "openapi": "3.1.0",
            "info": {
                "title": f"{service.name} API",
                "version": "1.0.0",
                "description": description,
            },
            "paths": {},
            "components": {
                "schemas": {},
            },
        }

        # If the service owns no entities, produce a minimal spec with a
        # health endpoint only.
        if not service.owns_entities:
            spec["paths"].update(_build_health_path())
            specs.append(spec)
            continue

        # Generate CRUD paths and schemas for each owned entity.
        for entity_name in service.owns_entities:
            entity = _find_entity(domain_model, entity_name)
            path_segment = _entity_path_segment(entity_name)

            # Schema
            spec["components"]["schemas"][entity_name] = _build_schema(
                entity, entity_name
            )

            # CRUD paths
            crud_paths = _build_crud_paths(entity_name, path_segment)
            spec["paths"].update(crud_paths)

        specs.append(spec)

    # Generate AsyncAPI stubs when events are provided
    if events:
        asyncapi_stubs = _generate_asyncapi_stubs(service_map, events)
        specs.extend(asyncapi_stubs)

    return specs


# ---------------------------------------------------------------------------
# AsyncAPI 3.0 stub generation
# ---------------------------------------------------------------------------


def _generate_asyncapi_stubs(
    service_map: ServiceMap,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate AsyncAPI 3.0 specs for services that publish domain events.

    Groups events by their publisher service, then produces one AsyncAPI
    spec per publishing service containing channels and operations for
    each published event.

    Args:
        service_map: The decomposed service map.
        events: List of event dicts with ``name``, ``publisher_service``,
                ``subscriber_services``, ``payload_fields``, ``channel``.

    Returns:
        List of AsyncAPI 3.0 spec dicts, one per publishing service.
    """
    # Build a lookup of service names (lowercase) to ServiceDefinition
    service_lookup: dict[str, Any] = {}
    for svc in service_map.services:
        service_lookup[svc.name.lower()] = svc
        # Also index by domain/description keywords for fuzzy matching
        if svc.domain:
            service_lookup[svc.domain.lower()] = svc

    # Group events by publisher
    publisher_events: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        pub = event.get("publisher_service", "")
        if not pub:
            continue
        pub_key = pub.lower()
        publisher_events.setdefault(pub_key, []).append(event)

    specs: list[dict[str, Any]] = []
    for pub_key, pub_events in publisher_events.items():
        # Resolve the service name
        svc = service_lookup.get(pub_key)
        service_id = svc.name if svc else pub_key
        service_title = service_id.replace("-", " ").title()

        channels: dict[str, Any] = {}
        operations: dict[str, Any] = {}

        for event in pub_events:
            event_name = event.get("name", "")
            channel_name = event.get("channel", event_name)
            payload_fields = event.get("payload_fields", [])

            # Build payload schema properties
            properties: dict[str, Any] = {}
            for field_name in payload_fields:
                properties[field_name] = {"type": "string"}

            # PascalCase message name: "invoice.posted" -> "InvoicePosted"
            message_name = "".join(
                word.capitalize() for word in re.split(r"[._\-]", event_name) if word
            )

            channels[channel_name] = {
                "address": channel_name,
                "messages": {
                    message_name: {
                        "payload": {
                            "type": "object",
                            "properties": properties,
                        }
                    }
                },
            }

            # Operation name: "publishInvoicePosted"
            op_name = f"publish{message_name}"
            operations[op_name] = {
                "action": "send",
                "channel": {"$ref": f"#/channels/{channel_name}"},
            }

            # Add subscribe operations for subscriber services
            for sub_service in event.get("subscriber_services", []):
                sub_op_name = f"subscribe{message_name}"
                operations[sub_op_name] = {
                    "action": "receive",
                    "channel": {"$ref": f"#/channels/{channel_name}"},
                }

        spec: dict[str, Any] = {
            "type": "asyncapi",
            "service_id": service_id,
            "spec": {
                "asyncapi": "3.0.0",
                "info": {
                    "title": f"{service_title} Events",
                    "version": "1.0.0",
                },
                "channels": channels,
                "operations": operations,
            },
        }
        specs.append(spec)

    return specs
