"""AsyncAPI 2.x / 3.x specification parser.

Parses AsyncAPI 2.x and 3.x specification dicts (or YAML strings) into structured
Python dataclasses for use within the Contract Engine service.

Handles $ref resolution across four patterns:
    1. ``#/components/messages/MessageName``
    2. ``#/components/schemas/SchemaName``
    3. ``#/channels/ChannelName``
    4. ``#/components/operations/OperationName``

Supports nested refs (one level deep) and detects circular references
gracefully without raising exceptions.

Example usage::

    >>> import yaml
    >>> from src.contract_engine.services.asyncapi_parser import parse_asyncapi
    >>> with open("spec.yaml") as f:
    ...     raw = yaml.safe_load(f)
    >>> spec = parse_asyncapi(raw)
    >>> spec.title, spec.version  # doctest: +SKIP
    ('My API', '1.0.0')
    >>> [(ch.name, ch.address) for ch in spec.channels]  # doctest: +SKIP
    [('user-events', 'user/events')]

Dependencies:
    - pyyaml >= 6.0
    - jsonschema >= 4.20.0 (used externally for validation, not inside parser)
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel / constants
# ---------------------------------------------------------------------------

_CIRCULAR_REF_PLACEHOLDER: dict[str, Any] = {
    "_circular_ref": True,
    "_warning": "Circular $ref detected; resolution stopped to prevent infinite loop.",
}

_SUPPORTED_ASYNCAPI_MAJORS = {"2", "3"}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AsyncAPIMessage:
    """Represents a single message defined in an AsyncAPI spec.

    Attributes:
        name:           Logical name of the message (key under components/messages).
        content_type:   MIME type for the message payload.
        payload_schema: JSON Schema dict describing the message payload.
        headers_schema: Optional JSON Schema dict describing message headers.
        description:    Human-readable description of the message.
    """

    name: str
    content_type: str = "application/json"
    payload_schema: dict[str, Any] = field(default_factory=dict)
    headers_schema: dict[str, Any] | None = None
    description: str = ""


@dataclass
class AsyncAPIChannel:
    """Represents a channel (topic / queue) in the AsyncAPI spec.

    Attributes:
        name:        Logical name of the channel (key under ``channels``).
        address:     The address string (e.g. ``user/signedup``).
        description: Human-readable description of the channel.
        messages:    List of messages associated with this channel.
    """

    name: str
    address: str
    description: str = ""
    messages: list[AsyncAPIMessage] = field(default_factory=list)


@dataclass
class AsyncAPIOperation:
    """Represents an operation (publish / subscribe action) in the spec.

    Attributes:
        name:          Logical name of the operation.
        action:        Either ``"send"`` or ``"receive"``.
        channel_name:  Name of the channel this operation is bound to.
        summary:       Short human-readable summary.
        message_names: List of message names this operation may use.
    """

    name: str
    action: str  # "send" or "receive"
    channel_name: str
    summary: str = ""
    message_names: list[str] = field(default_factory=list)


@dataclass
class AsyncAPISpec:
    """Top-level container for a fully-parsed AsyncAPI 3.0 specification.

    Attributes:
        title:            The API title from ``info.title``.
        version:          The API version from ``info.version``.
        asyncapi_version: The AsyncAPI specification version string.
        channels:         Parsed channel objects.
        operations:       Parsed operation objects.
        messages:         All known messages keyed by their logical name.
        schemas:          All component schemas keyed by name.
        raw_spec:         The original unmodified spec dict for reference.
    """

    title: str
    version: str
    asyncapi_version: str = "3.0.0"
    channels: list[AsyncAPIChannel] = field(default_factory=list)
    operations: list[AsyncAPIOperation] = field(default_factory=list)
    messages: dict[str, AsyncAPIMessage] = field(default_factory=dict)
    schemas: dict[str, Any] = field(default_factory=dict)
    raw_spec: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# $ref resolution helpers
# ---------------------------------------------------------------------------


def _resolve_ref(
    spec: dict[str, Any],
    ref_string: str,
    visited: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve a JSON ``$ref`` pointer against *spec*.

    Supports the following four pointer prefixes:

    * ``#/components/messages/…``
    * ``#/components/schemas/…``
    * ``#/channels/…``
    * ``#/components/operations/…``

    After resolving the immediate target, the function checks whether the
    resolved object *itself* contains a ``$ref`` key.  If so, it resolves
    **one more level** (nested ref).  Deeper nesting is not followed in
    order to keep the parser predictable and safe.

    Circular references are detected via a *visited* set.  If the same
    ``$ref`` string is encountered twice within a single resolution chain
    the function returns a placeholder dict with a ``_circular_ref`` flag
    instead of recursing infinitely.

    Args:
        spec:       The full AsyncAPI specification dict (root document).
        ref_string: The ``$ref`` value, e.g. ``"#/components/messages/Foo"``.
        visited:    Accumulator for already-visited ref strings.  Callers
                    should normally leave this as ``None``; the function
                    manages it internally.

    Returns:
        The resolved dict fragment from *spec*, a shallow copy so that
        callers can safely mutate it without affecting the original spec.
        If resolution fails, an empty dict is returned and a warning is
        logged.

    Raises:
        This function does **not** raise; it returns gracefully on failure.
    """

    if visited is None:
        visited = set()

    # --- Circular reference guard -------------------------------------------
    if ref_string in visited:
        logger.warning("Circular $ref detected: %s", ref_string)
        return copy.deepcopy(_CIRCULAR_REF_PLACEHOLDER)

    visited.add(ref_string)

    # --- Parse the JSON Pointer ---------------------------------------------
    # Expected format: "#/path/to/object"
    if not ref_string.startswith("#/"):
        logger.warning("Unsupported $ref format (not a local pointer): %s", ref_string)
        return {}

    pointer_parts = ref_string[2:].split("/")  # strip leading "#/"

    # --- Walk the spec dict --------------------------------------------------
    current: Any = spec
    for part in pointer_parts:
        # JSON Pointer escaping: ~1 -> /, ~0 -> ~
        decoded_part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current.get(decoded_part)
        elif isinstance(current, list):
            # Rarely used but technically valid in JSON Pointer
            try:
                current = current[int(decoded_part)]
            except (ValueError, IndexError):
                logger.warning(
                    "Failed to resolve $ref list index '%s' in %s",
                    decoded_part,
                    ref_string,
                )
                return {}
        else:
            logger.warning(
                "Cannot traverse non-container at '%s' in $ref %s",
                decoded_part,
                ref_string,
            )
            return {}

        if current is None:
            logger.warning("Unresolvable $ref (key not found): %s", ref_string)
            return {}

    if not isinstance(current, dict):
        # Scalars and lists can be valid targets, wrap them for consistency
        logger.debug("Resolved $ref %s to a non-dict value; wrapping.", ref_string)
        return {"_resolved_value": current}

    # Shallow-copy so mutations downstream don't corrupt the original spec
    resolved = dict(current)

    # --- Nested ref resolution (one level deep) -----------------------------
    if "$ref" in resolved:
        nested_ref = resolved["$ref"]
        logger.debug("Following nested $ref: %s -> %s", ref_string, nested_ref)
        resolved = _resolve_ref(spec, nested_ref, visited)

    return resolved


def _resolve_if_ref(
    spec: dict[str, Any],
    value: Any,
    visited: set[str] | None = None,
) -> Any:
    """Return the resolved object if *value* is a ``$ref`` dict, else *value*.

    This is a convenience wrapper around :func:`_resolve_ref` that transparently
    handles the common pattern of "this might be a reference or an inline
    definition".

    Args:
        spec:    The root AsyncAPI spec dict.
        value:   Either a dict potentially containing ``$ref``, or any other
                 value that should be returned as-is.
        visited: Optional visited-set forwarded to :func:`_resolve_ref`.

    Returns:
        The resolved dict when *value* contains ``$ref``, otherwise *value*
        unchanged.
    """

    if isinstance(value, dict) and "$ref" in value:
        return _resolve_ref(spec, value["$ref"], visited)
    return value


def _deep_resolve_refs(
    spec: dict[str, Any],
    obj: Any,
    *,
    max_depth: int = 10,
    _depth: int = 0,
    _visited: set[str] | None = None,
) -> Any:
    """Recursively resolve all ``$ref`` occurrences inside *obj*.

    Walks dicts and lists, replacing every ``{"$ref": "..."}`` with the
    resolved content.  Recursion is bounded by *max_depth* to avoid stack
    overflow on extremely deeply nested specs.

    Args:
        spec:      Root AsyncAPI spec dict.
        obj:       The object tree to walk (usually a dict or list).
        max_depth: Maximum recursion depth for the walk.

    Returns:
        A new object tree with ``$ref`` dicts replaced by their resolved
        values.
    """

    if _depth > max_depth:
        logger.warning("_deep_resolve_refs hit max_depth=%d; stopping.", max_depth)
        return obj

    if _visited is None:
        _visited = set()

    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_str = obj["$ref"]
            if ref_str in _visited:
                return copy.deepcopy(_CIRCULAR_REF_PLACEHOLDER)
            # Let _resolve_ref handle adding ref_str to the visited set.
            # We pass a copy so that sibling branches don't share state.
            _visited_copy = set(_visited)
            resolved = _resolve_ref(spec, ref_str, _visited_copy)
            # After _resolve_ref returns, _visited_copy now contains ref_str
            # (and any nested refs it followed).  Continue resolving within
            # the resolved object.
            return _deep_resolve_refs(
                spec,
                resolved,
                max_depth=max_depth,
                _depth=_depth + 1,
                _visited=_visited_copy,
            )
        return {
            k: _deep_resolve_refs(
                spec, v, max_depth=max_depth, _depth=_depth + 1, _visited=set(_visited)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            _deep_resolve_refs(
                spec, item, max_depth=max_depth, _depth=_depth + 1, _visited=set(_visited)
            )
            for item in obj
        ]
    return obj


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _extract_info(spec: dict[str, Any]) -> tuple[str, str]:
    """Extract ``info.title`` and ``info.version`` from the spec.

    Both fields are required by the AsyncAPI 3.0 specification.  If either
    is missing the function raises :class:`ValueError`.

    Args:
        spec: Root AsyncAPI spec dict.

    Returns:
        A ``(title, version)`` tuple.

    Raises:
        ValueError: If ``info``, ``info.title``, or ``info.version`` is
            missing.
    """

    info = spec.get("info")
    if not isinstance(info, dict):
        raise ValueError(
            "AsyncAPI spec is missing the required 'info' object."
        )

    title = info.get("title")
    if not title:
        raise ValueError(
            "AsyncAPI spec is missing the required 'info.title' field."
        )

    version = info.get("version")
    if not version:
        raise ValueError(
            "AsyncAPI spec is missing the required 'info.version' field."
        )

    return str(title), str(version)


def _extract_asyncapi_version(spec: dict[str, Any]) -> str:
    """Extract and validate the ``asyncapi`` version string.

    The parser targets AsyncAPI 2.x and 3.x.  If the version field is
    missing or the major version is not ``2`` or ``3``, a
    :class:`ValueError` is raised.

    Args:
        spec: Root AsyncAPI spec dict.

    Returns:
        The asyncapi version string (e.g. ``"3.0.0"`` or ``"2.6.0"``).

    Raises:
        ValueError: If the ``asyncapi`` field is missing or the major
            version is not ``2`` or ``3``.
    """

    asyncapi_version = spec.get("asyncapi")
    if not asyncapi_version:
        raise ValueError(
            "AsyncAPI spec is missing the required 'asyncapi' version field."
        )

    version_str = str(asyncapi_version)
    major = version_str.split(".")[0]
    if major not in _SUPPORTED_ASYNCAPI_MAJORS:
        supported = ", ".join(sorted(_SUPPORTED_ASYNCAPI_MAJORS))
        raise ValueError(
            f"Unsupported AsyncAPI version '{version_str}'. "
            f"This parser supports major versions: {supported}."
        )

    return version_str


def _parse_schemas(spec: dict[str, Any]) -> dict[str, Any]:
    """Parse ``components.schemas`` into a flat dict of schema dicts.

    Each schema value has its ``$ref`` entries resolved so that downstream
    consumers receive self-contained JSON-Schema-like dicts.

    Args:
        spec: Root AsyncAPI spec dict.

    Returns:
        Dict mapping schema name to its (resolved) JSON Schema dict.
    """

    components = spec.get("components", {})
    if not isinstance(components, dict):
        logger.warning("'components' is not a dict; skipping schema parsing.")
        return {}

    raw_schemas = components.get("schemas", {})
    if not isinstance(raw_schemas, dict):
        logger.warning("'components.schemas' is not a dict; skipping.")
        return {}

    schemas: dict[str, Any] = {}
    for name, schema_def in raw_schemas.items():
        if not isinstance(schema_def, dict):
            logger.warning(
                "Schema '%s' is not a dict (%s); skipping.",
                name,
                type(schema_def).__name__,
            )
            continue

        # Seed the visited set with this schema's own canonical ref path so
        # that self-referencing schemas (e.g. recursive tree nodes) are
        # detected as circular rather than causing infinite recursion.
        own_ref = f"#/components/schemas/{name}"
        resolved = _deep_resolve_refs(spec, schema_def, _visited={own_ref})
        schemas[str(name)] = resolved

    logger.debug("Parsed %d component schemas.", len(schemas))
    return schemas


def _parse_single_message(
    spec: dict[str, Any],
    name: str,
    msg_def: dict[str, Any],
) -> AsyncAPIMessage:
    """Parse a single message definition dict into an :class:`AsyncAPIMessage`.

    The *msg_def* may itself be a ``$ref`` (already resolved by the caller)
    or an inline definition.

    Args:
        spec:    Root AsyncAPI spec dict (used for nested ref resolution).
        name:    Logical name of the message.
        msg_def: The message definition dict.

    Returns:
        A populated :class:`AsyncAPIMessage` instance.
    """

    # The message body may contain a $ref for the payload; resolve it.
    payload_raw = msg_def.get("payload", {})
    if isinstance(payload_raw, dict):
        payload_schema = _deep_resolve_refs(spec, payload_raw)
    else:
        payload_schema = {}
        logger.warning(
            "Message '%s' has non-dict payload (%s); defaulting to empty schema.",
            name,
            type(payload_raw).__name__,
        )

    # Headers may also use $ref
    headers_raw = msg_def.get("headers")
    headers_schema: dict[str, Any] | None = None
    if isinstance(headers_raw, dict):
        headers_schema = _deep_resolve_refs(spec, headers_raw)
    elif headers_raw is not None:
        logger.warning(
            "Message '%s' has non-dict headers (%s); ignoring.",
            name,
            type(headers_raw).__name__,
        )

    content_type = msg_def.get("contentType", "application/json")
    description = msg_def.get("description", "")

    # AsyncAPI 3.0 may also have a "name" field inside the message def
    # that overrides the component key.
    display_name = msg_def.get("name", name)

    return AsyncAPIMessage(
        name=str(display_name),
        content_type=str(content_type),
        payload_schema=payload_schema if isinstance(payload_schema, dict) else {},
        headers_schema=headers_schema,
        description=str(description),
    )


def _parse_messages(spec: dict[str, Any]) -> dict[str, AsyncAPIMessage]:
    """Parse ``components.messages`` into a dict of :class:`AsyncAPIMessage`.

    Each message definition is resolved (if it contains ``$ref`` values)
    and converted into a dataclass.

    Args:
        spec: Root AsyncAPI spec dict.

    Returns:
        Dict mapping message name to :class:`AsyncAPIMessage`.
    """

    components = spec.get("components", {})
    if not isinstance(components, dict):
        return {}

    raw_messages = components.get("messages", {})
    if not isinstance(raw_messages, dict):
        logger.warning("'components.messages' is not a dict; skipping.")
        return {}

    messages: dict[str, AsyncAPIMessage] = {}
    for name, msg_def in raw_messages.items():
        name_str = str(name)
        try:
            # The message definition itself might be a $ref
            resolved_def = _resolve_if_ref(spec, msg_def)
            if not isinstance(resolved_def, dict):
                logger.warning(
                    "Message '%s' resolved to non-dict; skipping.", name_str
                )
                continue

            messages[name_str] = _parse_single_message(spec, name_str, resolved_def)
        except (KeyError, ValueError, TypeError):
            logger.exception("Failed to parse message '%s'; skipping.", name_str)

    logger.debug("Parsed %d component messages.", len(messages))
    return messages


def _resolve_channel_messages(
    spec: dict[str, Any],
    channel_messages_raw: dict[str, Any] | list[Any] | Any,
    all_messages: dict[str, AsyncAPIMessage],
) -> list[AsyncAPIMessage]:
    """Resolve the ``messages`` block inside a channel definition.

    In AsyncAPI 3.0 a channel's ``messages`` field is a *map* of
    ``{messageKey: messageObject | $ref}``.  Each entry is resolved and
    returned as a flat list.

    If a message referenced by the channel has already been parsed into
    *all_messages*, the existing dataclass is reused.  Otherwise a new
    :class:`AsyncAPIMessage` is created from the inline/resolved definition.

    Args:
        spec:                 Root AsyncAPI spec dict.
        channel_messages_raw: The raw ``messages`` value from the channel def.
        all_messages:         Previously parsed component-level messages.

    Returns:
        List of :class:`AsyncAPIMessage` objects for the channel.
    """

    result: list[AsyncAPIMessage] = []

    if isinstance(channel_messages_raw, dict):
        for msg_key, msg_value in channel_messages_raw.items():
            msg_key_str = str(msg_key)
            try:
                resolved = _resolve_if_ref(spec, msg_value)

                # Try to match against already-parsed component messages
                # by checking the $ref target name or the resolved name.
                ref_name = _extract_ref_name(msg_value)
                if ref_name and ref_name in all_messages:
                    result.append(all_messages[ref_name])
                    continue

                if not isinstance(resolved, dict):
                    logger.warning(
                        "Channel message '%s' resolved to non-dict; skipping.",
                        msg_key_str,
                    )
                    continue

                # Check if resolved dict has a 'name' matching a known message
                resolved_name = resolved.get("name", msg_key_str)
                if resolved_name in all_messages:
                    result.append(all_messages[resolved_name])
                    continue

                # Build a new message from the inline definition
                result.append(
                    _parse_single_message(spec, msg_key_str, resolved)
                )
            except (KeyError, ValueError, TypeError):
                logger.exception(
                    "Failed to resolve channel message '%s'; skipping.",
                    msg_key_str,
                )

    elif isinstance(channel_messages_raw, list):
        # Some specs may use a list of $ref objects (non-standard but common)
        for idx, msg_value in enumerate(channel_messages_raw):
            try:
                resolved = _resolve_if_ref(spec, msg_value)
                ref_name = _extract_ref_name(msg_value)
                if ref_name and ref_name in all_messages:
                    result.append(all_messages[ref_name])
                    continue

                if isinstance(resolved, dict):
                    msg_name = resolved.get("name", f"message_{idx}")
                    if msg_name in all_messages:
                        result.append(all_messages[msg_name])
                    else:
                        result.append(
                            _parse_single_message(spec, str(msg_name), resolved)
                        )
                else:
                    logger.warning(
                        "Channel message at index %d is not a dict; skipping.", idx
                    )
            except (KeyError, ValueError, TypeError):
                logger.exception(
                    "Failed to resolve channel message at index %d; skipping.", idx
                )
    else:
        if channel_messages_raw is not None:
            logger.warning(
                "Channel 'messages' field is neither a dict nor list (%s); ignoring.",
                type(channel_messages_raw).__name__,
            )

    return result


def _extract_ref_name(value: Any) -> str | None:
    """Extract the trailing name component from a ``$ref`` value.

    For example ``{"$ref": "#/components/messages/UserSignedUp"}`` yields
    ``"UserSignedUp"``.

    Args:
        value: A potentially ``$ref``-containing dict.

    Returns:
        The last segment of the ``$ref`` pointer, or ``None`` if *value*
        is not a ``$ref`` dict.
    """

    if isinstance(value, dict) and "$ref" in value:
        ref_str = value["$ref"]
        if isinstance(ref_str, str) and "/" in ref_str:
            return ref_str.rsplit("/", 1)[-1]
    return None


def _parse_channels_v2(
    spec: dict[str, Any],
    all_messages: dict[str, AsyncAPIMessage],
) -> list[AsyncAPIChannel]:
    """Parse channels from an AsyncAPI 2.x specification.

    In AsyncAPI 2.x, the channel key *is* the address and operations
    (``subscribe`` / ``publish``) are nested directly inside each channel.

    Args:
        spec:         Root AsyncAPI spec dict.
        all_messages: Previously parsed component-level messages.

    Returns:
        List of :class:`AsyncAPIChannel`.
    """
    raw_channels = spec.get("channels", {})
    if not isinstance(raw_channels, dict):
        logger.warning("'channels' is not a dict; skipping channel parsing.")
        return []

    channels: list[AsyncAPIChannel] = []
    for address, ch_def in raw_channels.items():
        address_str = str(address)
        try:
            resolved_def = _resolve_if_ref(spec, ch_def)
            if not isinstance(resolved_def, dict):
                logger.warning(
                    "Channel '%s' resolved to non-dict; skipping.", address_str
                )
                continue

            description = str(resolved_def.get("description", ""))

            # In 2.x the channel key is the address itself.
            # Derive a logical name from the address (last segment or full).
            name = address_str.rsplit("/", 1)[-1] if "/" in address_str else address_str

            # Collect messages from subscribe / publish operations.
            channel_messages: list[AsyncAPIMessage] = []
            for op_key in ("subscribe", "publish"):
                op_def = resolved_def.get(op_key)
                if not isinstance(op_def, dict):
                    continue
                msg_def = op_def.get("message")
                if msg_def is None:
                    continue
                resolved_msg = _resolve_if_ref(spec, msg_def)
                if not isinstance(resolved_msg, dict):
                    continue

                # Handle oneOf messages (multiple message types on one channel).
                one_of = resolved_msg.get("oneOf")
                if isinstance(one_of, list):
                    for idx, sub_msg in enumerate(one_of):
                        sub_resolved = _resolve_if_ref(spec, sub_msg)
                        if isinstance(sub_resolved, dict):
                            ref_name = _extract_ref_name(sub_msg)
                            if ref_name and ref_name in all_messages:
                                channel_messages.append(all_messages[ref_name])
                            else:
                                msg_name = sub_resolved.get("name", f"{name}_{op_key}_msg_{idx}")
                                channel_messages.append(
                                    _parse_single_message(spec, str(msg_name), sub_resolved)
                                )
                else:
                    # Single message.
                    ref_name = _extract_ref_name(msg_def)
                    if ref_name and ref_name in all_messages:
                        channel_messages.append(all_messages[ref_name])
                    else:
                        msg_name = resolved_msg.get("name", f"{name}_{op_key}_msg")
                        channel_messages.append(
                            _parse_single_message(spec, str(msg_name), resolved_msg)
                        )

            channels.append(
                AsyncAPIChannel(
                    name=name,
                    address=address_str,
                    description=description,
                    messages=channel_messages,
                )
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Failed to parse 2.x channel '%s'; skipping.", address_str)

    logger.debug("Parsed %d channels (v2.x).", len(channels))
    return channels


def _parse_operations_v2(
    spec: dict[str, Any],
    channels: list[AsyncAPIChannel],
) -> list[AsyncAPIOperation]:
    """Derive operations from AsyncAPI 2.x channel definitions.

    In 2.x, operations are embedded inside channels as ``subscribe`` and
    ``publish`` blocks.  This function extracts them into the same
    :class:`AsyncAPIOperation` dataclass used for 3.x.

    Args:
        spec:     Root AsyncAPI spec dict.
        channels: Already-parsed channels.

    Returns:
        List of :class:`AsyncAPIOperation`.
    """
    raw_channels = spec.get("channels", {})
    if not isinstance(raw_channels, dict):
        return []

    operations: list[AsyncAPIOperation] = []
    for address, ch_def in raw_channels.items():
        resolved_def = _resolve_if_ref(spec, ch_def)
        if not isinstance(resolved_def, dict):
            continue

        channel_name = str(address).rsplit("/", 1)[-1] if "/" in str(address) else str(address)

        for op_key in ("subscribe", "publish"):
            op_def = resolved_def.get(op_key)
            if not isinstance(op_def, dict):
                continue

            # Map 2.x subscribe/publish to 3.x send/receive semantics.
            # In 2.x: "publish" = app sends, "subscribe" = app receives.
            action = "send" if op_key == "publish" else "receive"
            op_id = op_def.get("operationId", f"{channel_name}_{op_key}")
            summary = str(op_def.get("summary", op_def.get("description", "")))

            message_names: list[str] = []
            msg_def = op_def.get("message")
            if isinstance(msg_def, dict):
                ref_name = _extract_ref_name(msg_def)
                if ref_name:
                    message_names.append(ref_name)
                elif "name" in msg_def:
                    message_names.append(str(msg_def["name"]))

            operations.append(
                AsyncAPIOperation(
                    name=str(op_id),
                    action=action,
                    channel_name=channel_name,
                    summary=summary,
                    message_names=message_names,
                )
            )

    logger.debug("Derived %d operations from 2.x channels.", len(operations))
    return operations


def _parse_channels(
    spec: dict[str, Any],
    all_messages: dict[str, AsyncAPIMessage],
) -> list[AsyncAPIChannel]:
    """Parse top-level ``channels`` into a list of :class:`AsyncAPIChannel`.

    Each channel definition is resolved (handling ``$ref``) and its nested
    ``messages`` block is linked to the component-level message catalogue.

    Args:
        spec:         Root AsyncAPI spec dict.
        all_messages: Previously parsed component-level messages.

    Returns:
        List of :class:`AsyncAPIChannel`.
    """

    raw_channels = spec.get("channels", {})
    if not isinstance(raw_channels, dict):
        logger.warning("'channels' is not a dict; skipping channel parsing.")
        return []

    channels: list[AsyncAPIChannel] = []
    for name, ch_def in raw_channels.items():
        name_str = str(name)
        try:
            resolved_def = _resolve_if_ref(spec, ch_def)
            if not isinstance(resolved_def, dict):
                logger.warning(
                    "Channel '%s' resolved to non-dict; skipping.", name_str
                )
                continue

            address = str(resolved_def.get("address", ""))
            description = str(resolved_def.get("description", ""))

            # Resolve messages attached to this channel
            channel_messages_raw = resolved_def.get("messages", {})
            channel_messages = _resolve_channel_messages(
                spec, channel_messages_raw, all_messages
            )

            channels.append(
                AsyncAPIChannel(
                    name=name_str,
                    address=address,
                    description=description,
                    messages=channel_messages,
                )
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Failed to parse channel '%s'; skipping.", name_str)

    logger.debug("Parsed %d channels.", len(channels))
    return channels


def _resolve_operation_channel_name(
    spec: dict[str, Any],
    channel_value: Any,
) -> str:
    """Derive the channel name from an operation's ``channel`` field.

    The ``channel`` field in an AsyncAPI 3.0 operation is typically a
    ``$ref`` pointer like ``"#/channels/userSignedup"``.  This function
    extracts the trailing segment as the channel name.  If the channel
    value is an inline dict it looks for a ``name`` or ``address`` key.

    Args:
        spec:          Root AsyncAPI spec dict.
        channel_value: The raw ``channel`` field value from the operation def.

    Returns:
        The resolved channel name string, or an empty string on failure.
    """

    if isinstance(channel_value, dict) and "$ref" in channel_value:
        ref_name = _extract_ref_name(channel_value)
        return ref_name or ""

    if isinstance(channel_value, str):
        # Might be a bare channel name or a ref string without wrapping
        if channel_value.startswith("#/"):
            parts = channel_value.split("/")
            return parts[-1] if parts else ""
        return channel_value

    if isinstance(channel_value, dict):
        return str(channel_value.get("name", channel_value.get("address", "")))

    return ""


def _resolve_operation_messages(
    spec: dict[str, Any],
    messages_value: Any,
    all_messages: dict[str, AsyncAPIMessage],
) -> list[str]:
    """Extract message names from an operation's ``messages`` field.

    In AsyncAPI 3.0 the operation ``messages`` field is a list of
    ``$ref`` pointers to channel-level message entries.  Each entry looks
    like ``{"$ref": "#/channels/chName/messages/msgKey"}``.

    Args:
        spec:           Root AsyncAPI spec dict.
        messages_value: Raw ``messages`` field from the operation def.
        all_messages:   Component-level message catalogue.

    Returns:
        List of message name strings.
    """

    names: list[str] = []

    if isinstance(messages_value, list):
        for entry in messages_value:
            ref_name = _extract_ref_name(entry)
            if ref_name:
                names.append(ref_name)
                continue
            if isinstance(entry, dict):
                name = entry.get("name", "")
                if name:
                    names.append(str(name))
            elif isinstance(entry, str):
                names.append(entry)

    elif isinstance(messages_value, dict):
        # Could be a single message ref or a map of messages
        if "$ref" in messages_value:
            ref_name = _extract_ref_name(messages_value)
            if ref_name:
                names.append(ref_name)
        else:
            # Treat keys as message names
            names.extend(str(k) for k in messages_value)

    return names


def _parse_operations(
    spec: dict[str, Any],
    all_messages: dict[str, AsyncAPIMessage],
    channels: list[AsyncAPIChannel],
) -> list[AsyncAPIOperation]:
    """Parse ``operations`` into a list of :class:`AsyncAPIOperation`.

    Also checks ``components.operations`` for any shared operation
    definitions referenced via ``$ref``.

    Args:
        spec:         Root AsyncAPI spec dict.
        all_messages: Component-level message catalogue.
        channels:     Already-parsed channels (for cross-referencing).

    Returns:
        List of :class:`AsyncAPIOperation`.
    """

    raw_operations = spec.get("operations", {})
    if not isinstance(raw_operations, dict):
        logger.warning("'operations' is not a dict; skipping.")
        return []

    # Build a channel name set for validation
    channel_names = {ch.name for ch in channels}

    operations: list[AsyncAPIOperation] = []
    for name, op_def in raw_operations.items():
        name_str = str(name)
        try:
            resolved_def = _resolve_if_ref(spec, op_def)
            if not isinstance(resolved_def, dict):
                logger.warning(
                    "Operation '%s' resolved to non-dict; skipping.", name_str
                )
                continue

            action = str(resolved_def.get("action", "")).lower()
            if action not in ("send", "receive"):
                logger.warning(
                    "Operation '%s' has unrecognised action '%s'; "
                    "defaulting to 'send'.",
                    name_str,
                    action,
                )
                action = action if action else "send"

            # Resolve channel reference
            channel_ref = resolved_def.get("channel", {})
            channel_name = _resolve_operation_channel_name(spec, channel_ref)

            if channel_name and channel_name not in channel_names:
                logger.debug(
                    "Operation '%s' references channel '%s' which was not "
                    "parsed as a top-level channel.",
                    name_str,
                    channel_name,
                )

            summary = str(resolved_def.get("summary", ""))

            # Resolve messages
            op_messages_raw = resolved_def.get("messages", [])
            message_names = _resolve_operation_messages(
                spec, op_messages_raw, all_messages
            )

            operations.append(
                AsyncAPIOperation(
                    name=name_str,
                    action=action,
                    channel_name=channel_name,
                    summary=summary,
                    message_names=message_names,
                )
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Failed to parse operation '%s'; skipping.", name_str)

    logger.debug("Parsed %d operations.", len(operations))
    return operations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_asyncapi_yaml(yaml_string: str) -> AsyncAPISpec:
    """Parse an AsyncAPI 3.0 YAML string into an :class:`AsyncAPISpec`.

    This is a convenience wrapper around :func:`parse_asyncapi` for callers
    that have a raw YAML string rather than an already-deserialised dict.

    Args:
        yaml_string: A YAML-encoded AsyncAPI 3.0 specification.

    Returns:
        A fully parsed :class:`AsyncAPISpec`.

    Raises:
        ValueError: If the YAML cannot be parsed or the resulting object
            is not a dict.
        yaml.YAMLError: On malformed YAML.
    """

    parsed = yaml.safe_load(yaml_string)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Expected a YAML mapping at the root, got {type(parsed).__name__}."
        )
    return parse_asyncapi(parsed)


def parse_asyncapi(spec: dict[str, Any]) -> AsyncAPISpec:
    """Parse an AsyncAPI 2.x or 3.x specification dict into an :class:`AsyncAPISpec`.

    This is the main entry point for the parser.  It accepts a Python dict
    that has already been deserialised from JSON or YAML and returns a
    fully-populated :class:`AsyncAPISpec` dataclass with all ``$ref``
    pointers resolved.

    Handles ``$ref`` resolution with these four patterns:

    1. ``#/components/messages/MessageName``
    2. ``#/components/schemas/SchemaName``
    3. ``#/channels/ChannelName``
    4. ``#/components/operations/OperationName`` (if present)

    Supports nested refs (one level deep) and circular reference detection.

    The parser is designed to be *robust*: unexpected structures are logged
    as warnings and skipped rather than causing the entire parse to fail.

    Args:
        spec: A dict representing a complete AsyncAPI 2.x or 3.x document.
              This is typically obtained via ``yaml.safe_load()`` or
              ``json.load()``.

    Returns:
        An :class:`AsyncAPISpec` populated with channels, operations,
        messages, and schemas extracted from *spec*.

    Raises:
        ValueError: If the spec is missing required fields such as
            ``asyncapi``, ``info.title``, or ``info.version``.
        TypeError: If *spec* is not a dict.
    """

    # --- Input validation ----------------------------------------------------
    if not isinstance(spec, dict):
        raise TypeError(
            f"Expected a dict for the AsyncAPI spec, got {type(spec).__name__}."
        )

    # Keep an unmodified copy for raw_spec
    raw_spec = copy.deepcopy(spec)

    # --- Required top-level fields -------------------------------------------
    asyncapi_version = _extract_asyncapi_version(spec)
    title, version = _extract_info(spec)
    major = asyncapi_version.split(".")[0]

    logger.info(
        "Parsing AsyncAPI %s spec: '%s' v%s",
        asyncapi_version,
        title,
        version,
    )

    # --- Components: schemas -------------------------------------------------
    schemas = _parse_schemas(spec)

    # --- Components: messages ------------------------------------------------
    messages = _parse_messages(spec)

    # --- Version-specific parsing --------------------------------------------
    if major == "2":
        channels = _parse_channels_v2(spec, messages)
        operations = _parse_operations_v2(spec, channels)
    else:
        channels = _parse_channels(spec, messages)
        operations = _parse_operations(spec, messages, channels)

    # --- Assemble result -----------------------------------------------------
    result = AsyncAPISpec(
        title=title,
        version=version,
        asyncapi_version=asyncapi_version,
        channels=channels,
        operations=operations,
        messages=messages,
        schemas=schemas,
        raw_spec=raw_spec,
    )

    logger.info(
        "Parsed spec '%s' v%s: %d channels, %d operations, "
        "%d messages, %d schemas.",
        title,
        version,
        len(channels),
        len(operations),
        len(messages),
        len(schemas),
    )

    return result
