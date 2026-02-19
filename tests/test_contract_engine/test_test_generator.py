"""Tests for ContractTestGenerator — contract test suite generation and caching."""
from __future__ import annotations

import ast
import os
import tempfile

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import ContractCreate, ContractType
from src.contract_engine.services.contract_store import ContractStore
from src.contract_engine.services.test_generator import ContractTestGenerator


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
def generator(pool):
    """Create a ContractTestGenerator backed by the temporary database."""
    return ContractTestGenerator(pool)


def _valid_openapi_spec() -> dict:
    """Return a minimal valid OpenAPI 3.0.0 specification."""
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
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                }
                            },
                        },
                    },
                },
                "post": {
                    "summary": "Create user",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                    "required": ["name", "email"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {"description": "Created"},
                        "400": {"description": "Bad request"},
                    },
                },
            },
        },
    }


def _valid_asyncapi_spec() -> dict:
    """Return a minimal valid AsyncAPI 3.0.0 specification."""
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "User Events", "version": "1.0.0"},
        "channels": {
            "user-created": {
                "address": "users/created",
                "messages": {
                    "UserCreated": {"$ref": "#/components/messages/UserCreated"},
                },
            },
        },
        "operations": {
            "publishUserCreated": {
                "action": "send",
                "channel": {"$ref": "#/channels/user-created"},
                "summary": "Publish user created event",
            },
        },
        "components": {
            "messages": {
                "UserCreated": {
                    "payload": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                        },
                        "required": ["id", "name"],
                    },
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
# 1. test_generate_openapi_tests_valid_python
# ------------------------------------------------------------------
def test_generate_openapi_tests_valid_python(generator, store):
    """Generated OpenAPI test code should be syntactically valid Python."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)

    assert suite.test_code
    assert suite.framework == "pytest"
    # Verify code is valid Python
    ast.parse(suite.test_code)


# ------------------------------------------------------------------
# 2. test_generate_openapi_tests_has_schemathesis
# ------------------------------------------------------------------
def test_generate_openapi_tests_has_schemathesis(generator, store):
    """Generated OpenAPI tests should contain schemathesis imports and @schema.parametrize()."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)

    assert "import schemathesis" in suite.test_code
    assert "@schema.parametrize()" in suite.test_code


# ------------------------------------------------------------------
# 3. test_generate_openapi_tests_count_accurate
# ------------------------------------------------------------------
def test_generate_openapi_tests_count_accurate(generator, store):
    """test_count should match the number of test_ functions."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)

    import re
    actual_count = len(re.findall(r"^def test_\w+", suite.test_code, re.MULTILINE))
    assert suite.test_count == actual_count
    assert suite.test_count > 0


# ------------------------------------------------------------------
# 4. test_generate_asyncapi_tests_valid_python
# ------------------------------------------------------------------
def test_generate_asyncapi_tests_valid_python(generator, store):
    """Generated AsyncAPI test code should be syntactically valid Python."""
    contract_id = _create_contract(
        store, _valid_asyncapi_spec(), ContractType.ASYNCAPI
    )
    suite = generator.generate_tests(contract_id)

    assert suite.test_code
    ast.parse(suite.test_code)


# ------------------------------------------------------------------
# 5. test_generate_asyncapi_tests_has_jsonschema
# ------------------------------------------------------------------
def test_generate_asyncapi_tests_has_jsonschema(generator, store):
    """Generated AsyncAPI tests should contain jsonschema validation."""
    contract_id = _create_contract(
        store, _valid_asyncapi_spec(), ContractType.ASYNCAPI
    )
    suite = generator.generate_tests(contract_id)

    assert "jsonschema" in suite.test_code


# ------------------------------------------------------------------
# 6. test_caching_returns_same_suite
# ------------------------------------------------------------------
def test_caching_returns_same_suite(generator, store):
    """Second call with same spec_hash should return cached suite."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite1 = generator.generate_tests(contract_id)
    suite2 = generator.generate_tests(contract_id)

    assert suite1.test_code == suite2.test_code
    assert suite1.test_count == suite2.test_count


# ------------------------------------------------------------------
# 7. test_cache_invalidation_on_spec_change
# ------------------------------------------------------------------
def test_cache_invalidation_on_spec_change(generator, store, pool):
    """Changing the spec should regenerate tests (cache miss)."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite1 = generator.generate_tests(contract_id)

    # Update the contract spec (new path added)
    updated_spec = _valid_openapi_spec()
    updated_spec["paths"]["/api/users/{id}"] = {
        "get": {
            "summary": "Get user",
            "responses": {"200": {"description": "OK"}},
        }
    }
    # Directly update spec in DB to simulate a contract update
    import hashlib, json
    new_spec_json = json.dumps(updated_spec, sort_keys=True)
    new_hash = hashlib.sha256(new_spec_json.encode("utf-8")).hexdigest()
    conn = pool.get()
    conn.execute(
        "UPDATE contracts SET spec_json = ?, spec_hash = ? WHERE id = ?",
        (new_spec_json, new_hash, contract_id),
    )
    conn.commit()

    suite2 = generator.generate_tests(contract_id)

    # suite2 should have more tests due to additional endpoint
    assert suite2.test_count >= suite1.test_count


# ------------------------------------------------------------------
# 8. test_include_negative_generates_more_tests
# ------------------------------------------------------------------
def test_include_negative_generates_more_tests(generator, store):
    """include_negative=True should produce additional 4xx test cases."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite_normal = generator.generate_tests(contract_id, include_negative=False)

    # With include_negative in the cache key, positive and negative suites
    # are stored separately -- no manual cache clearing needed.
    suite_negative = generator.generate_tests(contract_id, include_negative=True)

    # Negative tests should have more test functions
    assert suite_negative.test_count > suite_normal.test_count


# ------------------------------------------------------------------
# 9. test_contract_not_found_raises
# ------------------------------------------------------------------
def test_contract_not_found_raises(generator):
    """Requesting tests for a non-existent contract should raise 404."""
    with pytest.raises(ContractNotFoundError):
        generator.generate_tests("non-existent-id")


# ------------------------------------------------------------------
# 10. test_get_suite_returns_none_when_missing
# ------------------------------------------------------------------
def test_get_suite_returns_none_when_missing(generator):
    """get_suite() for an unknown contract should return None."""
    result = generator.get_suite("non-existent-id")
    assert result is None


# ------------------------------------------------------------------
# 11. test_generated_code_has_docstring
# ------------------------------------------------------------------
def test_generated_code_has_docstring(generator, store):
    """Generated test code should include a module docstring."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)

    assert '"""Auto-generated contract tests' in suite.test_code


# ------------------------------------------------------------------
# 12. test_include_negative_produces_different_suite (cache key fix)
# ------------------------------------------------------------------
def test_include_negative_produces_different_suite(generator, store):
    """generate_tests with include_negative=True must NOT return cached non-negative suite."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite1 = generator.generate_tests(contract_id, include_negative=False)
    suite2 = generator.generate_tests(contract_id, include_negative=True)
    # They must differ -- negative suite has extra tests
    assert suite1.test_code != suite2.test_code or suite1.test_count != suite2.test_count


# ------------------------------------------------------------------
# 13. test_cached_suite_has_id
# ------------------------------------------------------------------
def test_cached_suite_has_id(generator, store):
    """ContractTestSuite must have an id field after generation."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)
    assert hasattr(suite, "id")
    assert suite.id is not None
    assert len(suite.id) > 0


# ------------------------------------------------------------------
# 14. test_suite_id_is_uuid_format
# ------------------------------------------------------------------
def test_suite_id_is_uuid_format(generator, store):
    """ContractTestSuite.id should be a valid UUID string."""
    import uuid
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite = generator.generate_tests(contract_id)
    # Validate it's a parseable UUID
    parsed_uuid = uuid.UUID(suite.id)
    assert str(parsed_uuid) == suite.id


# ------------------------------------------------------------------
# 15. test_different_include_negative_different_cache_entries
# ------------------------------------------------------------------
def test_different_include_negative_different_cache_entries(generator, store):
    """Calling generate_tests with include_negative=True then False should
    each return their own cached version on second call."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite_neg = generator.generate_tests(contract_id, include_negative=True)
    suite_pos = generator.generate_tests(contract_id, include_negative=False)
    # Call again -- should get cached versions
    suite_neg2 = generator.generate_tests(contract_id, include_negative=True)
    suite_pos2 = generator.generate_tests(contract_id, include_negative=False)
    assert suite_neg.test_code == suite_neg2.test_code
    assert suite_pos.test_code == suite_pos2.test_code
    assert suite_neg.test_code != suite_pos.test_code


# ------------------------------------------------------------------
# 16. test_suite_include_negative_field
# ------------------------------------------------------------------
def test_suite_include_negative_field(generator, store):
    """ContractTestSuite should carry the include_negative flag."""
    contract_id = _create_contract(store, _valid_openapi_spec())
    suite_no = generator.generate_tests(contract_id, include_negative=False)
    suite_yes = generator.generate_tests(contract_id, include_negative=True)
    assert suite_no.include_negative is False
    assert suite_yes.include_negative is True


# ------------------------------------------------------------------
# 17. test_asyncapi_2x_spec_generates_tests
# ------------------------------------------------------------------
def test_asyncapi_2x_spec_generates_tests(generator, store):
    """An AsyncAPI 2.x spec should also produce valid test code."""
    spec_2x = {
        "asyncapi": "2.6.0",
        "info": {"title": "Events 2.x", "version": "1.0.0"},
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
    contract_id = _create_contract(store, spec_2x, ContractType.ASYNCAPI)
    suite = generator.generate_tests(contract_id)
    assert suite.test_code
    ast.parse(suite.test_code)
