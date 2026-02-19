"""Tests for ComplianceChecker — contract compliance validation."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import ContractCreate, ContractType
from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.compliance_checker import ComplianceChecker


@pytest.fixture
def pool():
    """Create a ConnectionPool with a temporary SQLite database."""
    tmpdir = tempfile.mkdtemp()
    p = ConnectionPool(os.path.join(tmpdir, "test.db"))
    init_contracts_db(p)
    yield p
    p.close()


@pytest.fixture
def store(pool):
    """Create a ContractStore backed by the temporary database."""
    return ContractStore(pool)


@pytest.fixture
def checker(pool):
    """Create a ComplianceChecker backed by the temporary database."""
    return ComplianceChecker(pool)


def _openapi_spec_with_schemas() -> dict:
    """Return an OpenAPI spec with detailed response schemas."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "User API", "version": "1.0.0"},
        "paths": {
            "/api/users": {
                "get": {
                    "summary": "List users",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "users": {
                                                "type": "array",
                                                "items": {
                                                    "$ref": "#/components/schemas/User",
                                                },
                                            },
                                            "total": {"type": "integer"},
                                        },
                                        "required": ["users", "total"],
                                    }
                                }
                            },
                        },
                    },
                },
                "post": {
                    "summary": "Create user",
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/User",
                                    }
                                }
                            },
                        },
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                        "address": {
                            "type": "object",
                            "properties": {
                                "street": {"type": "string"},
                                "city": {"type": "string"},
                                "location": {
                                    "type": "object",
                                    "properties": {
                                        "lat": {"type": "number"},
                                        "lng": {"type": "number"},
                                    },
                                    "required": ["lat", "lng"],
                                },
                            },
                            "required": ["street", "city"],
                        },
                    },
                    "required": ["id", "name"],
                },
            },
        },
    }


def _create_contract(store, spec, contract_type=ContractType.OPENAPI):
    """Helper to create a contract and return its ID."""
    create = ContractCreate(
        service_name="test-service",
        type=contract_type,
        version="1.0.0",
        spec=spec,
    )
    entry = store.upsert(create)
    return entry.id


# ------------------------------------------------------------------
# 1. test_compliant_response
# ------------------------------------------------------------------
def test_compliant_response(checker, store):
    """A fully compliant response should yield compliant=True and no error violations."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/users": {
            "users": [{"id": "1", "name": "Alice"}],
            "total": 1,
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.endpoint_path == "/api/users"
    assert result.method == "GET"
    assert result.compliant is True
    # May have info violations for extra fields but no errors
    assert all(v.severity != "error" for v in result.violations)


# ------------------------------------------------------------------
# 2. test_missing_required_field
# ------------------------------------------------------------------
def test_missing_required_field(checker, store):
    """Missing a required field should produce an error-severity violation."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/users": {
            "users": [{"id": "1", "name": "Alice"}],
            # "total" is missing — required!
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.compliant is False
    error_violations = [v for v in result.violations if v.severity == "error"]
    assert len(error_violations) >= 1
    assert any("total" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 3. test_wrong_type
# ------------------------------------------------------------------
def test_wrong_type(checker, store):
    """Providing wrong type for a field should produce an error-severity violation."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/users": {
            "users": [{"id": "1", "name": "Alice"}],
            "total": "not_a_number",  # should be integer
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.compliant is False
    error_violations = [v for v in result.violations if v.severity == "error"]
    assert len(error_violations) >= 1
    assert any("total" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 4. test_extra_fields_are_info_severity
# ------------------------------------------------------------------
def test_extra_fields_are_info_severity(checker, store):
    """Extra fields not in schema should be reported as info (not error)."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/users": {
            "users": [{"id": "1", "name": "Alice"}],
            "total": 1,
            "extra_field": "bonus_data",  # Not in schema
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    # Should still be compliant — extra fields are just info
    assert result.compliant is True
    info_violations = [v for v in result.violations if v.severity == "info"]
    assert len(info_violations) >= 1
    assert any("extra_field" in v.field for v in info_violations)


# ------------------------------------------------------------------
# 5. test_nested_object_validation
# ------------------------------------------------------------------
def test_nested_object_validation(checker, store):
    """Nested objects should be validated recursively."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "POST /api/users": {
            "id": "123",
            "name": "Bob",
            "address": {
                # "street" is missing — required at nested level
                "city": "NYC",
            },
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.compliant is False
    error_violations = [v for v in result.violations if v.severity == "error"]
    assert any("street" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 6. test_deeply_nested_validation_3_levels
# ------------------------------------------------------------------
def test_deeply_nested_validation_3_levels(checker, store):
    """Validation should work up to 3 levels deep for nested objects."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "POST /api/users": {
            "id": "123",
            "name": "Bob",
            "address": {
                "street": "123 Main St",
                "city": "NYC",
                "location": {
                    "lat": "not_a_number",  # Should be number
                    "lng": 40.7128,
                },
            },
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.compliant is False
    error_violations = [v for v in result.violations if v.severity == "error"]
    assert any("lat" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 7. test_contract_not_found_raises
# ------------------------------------------------------------------
def test_contract_not_found_raises(checker):
    """Checking compliance against a non-existent contract should raise 404."""
    with pytest.raises(ContractNotFoundError):
        checker.check_compliance("non-existent-id", {})


# ------------------------------------------------------------------
# 8. test_multiple_endpoints
# ------------------------------------------------------------------
def test_multiple_endpoints(checker, store):
    """Compliance check should handle multiple endpoints simultaneously."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/users": {
            "users": [{"id": "1", "name": "Alice"}],
            "total": 1,
        },
        "POST /api/users": {
            "id": "2",
            "name": "Bob",
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 2
    get_result = [r for r in results if r.method == "GET"][0]
    post_result = [r for r in results if r.method == "POST"][0]
    assert get_result.compliant is True
    assert post_result.compliant is True


# ------------------------------------------------------------------
# 9. test_empty_response_data
# ------------------------------------------------------------------
def test_empty_response_data(checker, store):
    """Empty response data should return empty results."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    results = checker.check_compliance(contract_id, {})

    assert results == []


# ------------------------------------------------------------------
# 10. test_unknown_path_violation
# ------------------------------------------------------------------
def test_unknown_path_violation(checker, store):
    """Checking against a path not in the spec should produce an error violation."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {
        "GET /api/nonexistent": {"data": "value"},
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    assert results[0].compliant is False
    assert any(v.severity == "error" for v in results[0].violations)


# ------------------------------------------------------------------
# 11. test_ref_resolution_in_schema
# ------------------------------------------------------------------
def test_ref_resolution_in_schema(checker, store):
    """$ref references in response schemas should be resolved properly."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    # POST /api/users has a $ref to #/components/schemas/User
    response_data = {
        "POST /api/users": {
            "id": "abc",
            "name": "Charlie",
            "email": "charlie@example.com",
        },
    }
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    result = results[0]
    assert result.endpoint_path == "/api/users"
    assert result.method == "POST"
    assert result.compliant is True


# ------------------------------------------------------------------
# 12. test_invalid_endpoint_key_format
# ------------------------------------------------------------------
def test_invalid_endpoint_key_format(checker, store):
    """An endpoint key without 'METHOD /path' format produces an error."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    response_data = {"invalid-key-no-space": {"data": "value"}}
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    assert results[0].compliant is False
    assert results[0].method == "UNKNOWN"


# ------------------------------------------------------------------
# 13. test_unknown_method_for_path
# ------------------------------------------------------------------
def test_unknown_method_for_path(checker, store):
    """A method not defined for a path produces an error violation."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    # DELETE is not defined for /api/users in our spec
    response_data = {"DELETE /api/users": {}}
    results = checker.check_compliance(contract_id, response_data)

    assert len(results) == 1
    assert results[0].compliant is False


# ------------------------------------------------------------------
# 14. test_json_schema_type_returns_empty
# ------------------------------------------------------------------
def test_json_schema_type_returns_empty(checker, store):
    """json_schema contracts return empty results from compliance check."""
    spec = {"type": "object", "properties": {"name": {"type": "string"}}}
    contract_id = _create_contract(store, spec, ContractType.JSON_SCHEMA)
    results = checker.check_compliance(contract_id, {"data": {"name": "test"}})
    assert results == []


# ------------------------------------------------------------------
# 15. test_asyncapi_compliance_basic
# ------------------------------------------------------------------
def test_asyncapi_compliance_basic(checker, store):
    """Basic AsyncAPI compliance check with message schema validation."""
    spec = {
        "asyncapi": "2.6.0",
        "info": {"title": "Events", "version": "1.0.0"},
        "channels": {},
        "components": {
            "schemas": {
                "UserPayload": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "action": {"type": "string"},
                    },
                    "required": ["user_id"],
                }
            },
            "messages": {
                "UserCreated": {
                    "payload": {"$ref": "#/components/schemas/UserPayload"},
                }
            },
        },
    }
    contract_id = _create_contract(store, spec, ContractType.ASYNCAPI)
    response_data = {
        "UserCreated": {"user_id": "abc-123", "action": "create"},
    }
    results = checker.check_compliance(contract_id, response_data)
    assert len(results) == 1
    assert results[0].compliant is True


# ------------------------------------------------------------------
# 16. test_asyncapi_missing_required_field
# ------------------------------------------------------------------
def test_asyncapi_missing_required_field(checker, store):
    """AsyncAPI compliance should flag missing required fields."""
    spec = {
        "asyncapi": "2.6.0",
        "info": {"title": "Events", "version": "1.0.0"},
        "channels": {},
        "components": {
            "schemas": {
                "OrderPayload": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["order_id", "amount"],
                }
            },
            "messages": {
                "OrderPlaced": {
                    "payload": {"$ref": "#/components/schemas/OrderPayload"},
                }
            },
        },
    }
    contract_id = _create_contract(store, spec, ContractType.ASYNCAPI)
    response_data = {
        "OrderPlaced": {"order_id": "ord-1"},  # amount missing
    }
    results = checker.check_compliance(contract_id, response_data)
    assert len(results) == 1
    assert results[0].compliant is False
    error_violations = [v for v in results[0].violations if v.severity == "error"]
    assert any("amount" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 17. test_array_validation
# ------------------------------------------------------------------
def test_array_validation(checker, store):
    """Array items are validated against the items schema."""
    contract_id = _create_contract(store, _openapi_spec_with_schemas())
    # GET /api/users expects users to be an array of User objects
    # Send array with wrong type item
    response_data = {
        "GET /api/users": {
            "users": [{"id": 123, "name": "Alice"}],  # id should be string
            "total": 1,
        },
    }
    results = checker.check_compliance(contract_id, response_data)
    assert len(results) == 1
    result = results[0]
    # Check if violation was detected for the array item
    error_violations = [v for v in result.violations if v.severity == "error"]
    assert any("id" in v.field for v in error_violations)


# ------------------------------------------------------------------
# 18. test_no_response_schema_is_compliant
# ------------------------------------------------------------------
def test_no_response_schema_is_compliant(checker, store):
    """An endpoint with no response schema is considered compliant."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Minimal", "version": "1.0.0"},
        "paths": {
            "/api/ping": {
                "get": {
                    "responses": {
                        "200": {"description": "OK"},
                    },
                },
            },
        },
    }
    contract_id = _create_contract(store, spec)
    response_data = {"GET /api/ping": {"message": "pong"}}
    results = checker.check_compliance(contract_id, response_data)
    assert len(results) == 1
    assert results[0].compliant is True


# ------------------------------------------------------------------
# 19. test_asyncapi_unknown_message_is_compliant
# ------------------------------------------------------------------
def test_asyncapi_unknown_message_is_compliant(checker, store):
    """An AsyncAPI message not in the spec's messages is considered compliant."""
    spec = {
        "asyncapi": "2.6.0",
        "info": {"title": "Events", "version": "1.0.0"},
        "channels": {},
        "components": {"schemas": {}, "messages": {}},
    }
    contract_id = _create_contract(store, spec, ContractType.ASYNCAPI)
    response_data = {"UnknownEvent": {"data": "value"}}
    results = checker.check_compliance(contract_id, response_data)
    assert len(results) == 1
    assert results[0].compliant is True
