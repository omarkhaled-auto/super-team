"""Tests for the AsyncAPI 3.0 specification parser.

Covers basic parsing, field extraction, channel/operation/message/schema
parsing, $ref resolution (including nested and circular refs), and error
handling for invalid input.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.contract_engine.services.asyncapi_parser import (
    AsyncAPIChannel,
    AsyncAPIMessage,
    AsyncAPIOperation,
    AsyncAPISpec,
    parse_asyncapi,
)


# ======================================================================
# Helpers – reusable spec fragments
# ======================================================================


def _minimal_spec(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid AsyncAPI 3.0 spec dict, with optional overrides."""
    base: dict[str, Any] = {
        "asyncapi": "3.0.0",
        "info": {"title": "Test Service", "version": "1.0.0"},
    }
    base.update(overrides)
    return base


def _spec_with_channel_and_message() -> dict[str, Any]:
    """Return a spec that has one channel with one message and one operation."""
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "Events API", "version": "2.0.0"},
        "channels": {
            "userSignedup": {
                "address": "user/signedup",
                "description": "Channel for user signup events",
                "messages": {
                    "UserSignedUp": {
                        "$ref": "#/components/messages/UserSignedUp",
                    }
                },
            }
        },
        "operations": {
            "publishUserSignedup": {
                "action": "send",
                "channel": {"$ref": "#/channels/userSignedup"},
                "summary": "Publish a user-signed-up event",
                "messages": [
                    {"$ref": "#/channels/userSignedup/messages/UserSignedUp"}
                ],
            }
        },
        "components": {
            "messages": {
                "UserSignedUp": {
                    "name": "UserSignedUp",
                    "contentType": "application/json",
                    "description": "A user signed up.",
                    "payload": {
                        "$ref": "#/components/schemas/UserSignedUpPayload",
                    },
                }
            },
            "schemas": {
                "UserSignedUpPayload": {
                    "type": "object",
                    "properties": {
                        "userId": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                    "required": ["userId", "email"],
                }
            },
        },
    }


# ======================================================================
# 1. Basic parsing
# ======================================================================


def test_parse_basic_spec():
    """A minimal valid spec should parse without error and return an AsyncAPISpec."""
    spec = _minimal_spec()
    result = parse_asyncapi(spec)
    assert isinstance(result, AsyncAPISpec)


def test_parse_extracts_title_version():
    """The parser should extract info.title and info.version."""
    spec = _minimal_spec()
    result = parse_asyncapi(spec)
    assert result.title == "Test Service"
    assert result.version == "1.0.0"
    assert result.asyncapi_version == "3.0.0"


# ======================================================================
# 2. Channels, operations, messages, schemas
# ======================================================================


def test_parse_channels():
    """Channels defined in the spec should be parsed into AsyncAPIChannel objects."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    assert len(result.channels) == 1
    ch = result.channels[0]
    assert isinstance(ch, AsyncAPIChannel)
    assert ch.name == "userSignedup"
    assert ch.address == "user/signedup"
    assert ch.description == "Channel for user signup events"


def test_parse_operations():
    """Operations should be parsed into AsyncAPIOperation objects."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    assert len(result.operations) == 1
    op = result.operations[0]
    assert isinstance(op, AsyncAPIOperation)
    assert op.name == "publishUserSignedup"
    assert op.action == "send"
    assert op.channel_name == "userSignedup"
    assert op.summary == "Publish a user-signed-up event"


def test_parse_messages():
    """Component-level messages should be extracted into the messages dict."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    assert "UserSignedUp" in result.messages
    msg = result.messages["UserSignedUp"]
    assert isinstance(msg, AsyncAPIMessage)
    assert msg.name == "UserSignedUp"
    assert msg.content_type == "application/json"
    assert msg.description == "A user signed up."


def test_parse_schemas():
    """Component schemas should be parsed and returned with refs resolved."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    assert "UserSignedUpPayload" in result.schemas
    schema = result.schemas["UserSignedUpPayload"]
    assert schema.get("type") == "object"
    assert "userId" in schema.get("properties", {})


# ======================================================================
# 3. $ref resolution
# ======================================================================


def test_ref_resolution_messages():
    """A channel message that uses $ref to components/messages should resolve."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    # The channel's message list should contain the resolved message object.
    ch = result.channels[0]
    assert len(ch.messages) >= 1
    msg = ch.messages[0]
    assert msg.name == "UserSignedUp"


def test_ref_resolution_schemas():
    """A message payload that uses $ref to components/schemas should resolve."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    msg = result.messages["UserSignedUp"]
    # After ref resolution the payload_schema should contain the actual schema,
    # not a $ref pointer.
    assert "$ref" not in msg.payload_schema
    assert msg.payload_schema.get("type") == "object"


def test_circular_ref_detection():
    """Circular $ref chains should not crash the parser.

    The parser should detect the cycle and replace it with a circular-ref
    placeholder rather than recursing infinitely.
    """
    spec: dict[str, Any] = {
        "asyncapi": "3.0.0",
        "info": {"title": "Circular Test", "version": "0.1.0"},
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Node"},
                        },
                    },
                }
            }
        },
    }

    # Should NOT raise; the parser handles circular refs gracefully.
    result = parse_asyncapi(spec)
    assert isinstance(result, AsyncAPISpec)
    assert "Node" in result.schemas


# ======================================================================
# 4. Error handling
# ======================================================================


def test_invalid_spec_raises():
    """A spec missing required fields (e.g. asyncapi key) should raise ValueError."""
    with pytest.raises((ValueError, TypeError)):
        parse_asyncapi({"info": {"title": "No version key"}})


def test_empty_spec_raises():
    """An empty dict should raise ValueError because required fields are absent."""
    with pytest.raises((ValueError, TypeError)):
        parse_asyncapi({})


def test_non_dict_spec_raises():
    """Passing a non-dict (e.g. a list) should raise TypeError."""
    with pytest.raises(TypeError):
        parse_asyncapi([1, 2, 3])  # type: ignore[arg-type]


# ======================================================================
# 5. raw_spec preservation
# ======================================================================


def test_raw_spec_preserved():
    """The raw_spec field should contain a deep copy of the original input."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)

    assert result.raw_spec == spec
    # Mutating the original should NOT affect the stored copy.
    spec["info"]["title"] = "MUTATED"
    assert result.raw_spec["info"]["title"] != "MUTATED"


# ======================================================================
# 6. AsyncAPI 2.x support
# ======================================================================


def _asyncapi_2x_basic_spec() -> dict[str, Any]:
    """Return a minimal valid AsyncAPI 2.6.0 spec."""
    return {
        "asyncapi": "2.6.0",
        "info": {"title": "Test 2.x", "version": "1.0.0"},
        "channels": {
            "user/created": {
                "subscribe": {
                    "message": {
                        "payload": {
                            "type": "object",
                            "properties": {
                                "userId": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    }


def _asyncapi_2x_with_components() -> dict[str, Any]:
    """Return an AsyncAPI 2.x spec with component messages and schemas."""
    return {
        "asyncapi": "2.4.0",
        "info": {"title": "Events 2.x", "version": "2.0.0"},
        "channels": {
            "order/placed": {
                "publish": {
                    "operationId": "publishOrderPlaced",
                    "summary": "Order was placed",
                    "message": {
                        "$ref": "#/components/messages/OrderPlaced",
                    },
                },
            },
            "order/cancelled": {
                "subscribe": {
                    "operationId": "onOrderCancelled",
                    "message": {
                        "$ref": "#/components/messages/OrderCancelled",
                    },
                },
            },
        },
        "components": {
            "messages": {
                "OrderPlaced": {
                    "name": "OrderPlaced",
                    "contentType": "application/json",
                    "payload": {
                        "$ref": "#/components/schemas/OrderEvent",
                    },
                },
                "OrderCancelled": {
                    "name": "OrderCancelled",
                    "contentType": "application/json",
                    "payload": {
                        "type": "object",
                        "properties": {
                            "orderId": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
            "schemas": {
                "OrderEvent": {
                    "type": "object",
                    "properties": {
                        "orderId": {"type": "string"},
                        "totalCents": {"type": "integer"},
                    },
                    "required": ["orderId"],
                },
            },
        },
    }


def test_parse_asyncapi_2x_basic():
    """AsyncAPI 2.x specs should parse successfully with title and version."""
    spec = _asyncapi_2x_basic_spec()
    result = parse_asyncapi(spec)
    assert isinstance(result, AsyncAPISpec)
    assert result.title == "Test 2.x"
    assert result.version == "1.0.0"
    assert result.asyncapi_version == "2.6.0"


def test_parse_asyncapi_2x_channels():
    """AsyncAPI 2.x channels should be parsed into AsyncAPIChannel objects."""
    spec = _asyncapi_2x_basic_spec()
    result = parse_asyncapi(spec)
    assert len(result.channels) >= 1
    ch = result.channels[0]
    assert isinstance(ch, AsyncAPIChannel)
    assert ch.address == "user/created"


def test_parse_asyncapi_2x_operations_derived():
    """AsyncAPI 2.x should derive operations from subscribe/publish blocks."""
    spec = _asyncapi_2x_basic_spec()
    result = parse_asyncapi(spec)
    assert len(result.operations) >= 1
    op = result.operations[0]
    assert isinstance(op, AsyncAPIOperation)
    # 2.x subscribe maps to "receive"
    assert op.action == "receive"


def test_parse_asyncapi_2x_with_components():
    """AsyncAPI 2.x specs with components should resolve messages and schemas."""
    spec = _asyncapi_2x_with_components()
    result = parse_asyncapi(spec)
    assert result.title == "Events 2.x"
    assert len(result.channels) == 2
    assert len(result.operations) == 2
    assert "OrderPlaced" in result.messages
    assert "OrderCancelled" in result.messages
    assert "OrderEvent" in result.schemas


def test_parse_asyncapi_2x_publish_is_send():
    """In 2.x, 'publish' should map to action='send'."""
    spec = _asyncapi_2x_with_components()
    result = parse_asyncapi(spec)
    send_ops = [op for op in result.operations if op.action == "send"]
    assert len(send_ops) >= 1
    assert send_ops[0].name == "publishOrderPlaced"


def test_parse_asyncapi_2x_subscribe_is_receive():
    """In 2.x, 'subscribe' should map to action='receive'."""
    spec = _asyncapi_2x_with_components()
    result = parse_asyncapi(spec)
    receive_ops = [op for op in result.operations if op.action == "receive"]
    assert len(receive_ops) >= 1
    assert receive_ops[0].name == "onOrderCancelled"


def test_parse_asyncapi_2x_ref_resolution():
    """AsyncAPI 2.x $ref to component messages should resolve correctly."""
    spec = _asyncapi_2x_with_components()
    result = parse_asyncapi(spec)
    msg = result.messages["OrderPlaced"]
    assert msg.payload_schema.get("type") == "object"
    assert "orderId" in msg.payload_schema.get("properties", {})


def test_parse_asyncapi_3x_still_works():
    """Existing 3.x parsing must not regress."""
    spec = _spec_with_channel_and_message()
    result = parse_asyncapi(spec)
    assert result.title == "Events API"
    assert result.asyncapi_version == "3.0.0"
    assert len(result.channels) == 1
    assert len(result.operations) == 1
    assert "UserSignedUp" in result.messages


def test_parse_asyncapi_2x_channel_messages_linked():
    """Channel messages should be populated from subscribe/publish blocks in 2.x."""
    spec = _asyncapi_2x_with_components()
    result = parse_asyncapi(spec)
    # Find channel for order/placed
    placed_ch = [ch for ch in result.channels if "placed" in ch.address]
    assert len(placed_ch) == 1
    assert len(placed_ch[0].messages) >= 1
