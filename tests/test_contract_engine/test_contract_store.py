"""Tests for ContractStore CRUD operations against a real SQLite database."""
from __future__ import annotations

import os
import tempfile

import pytest

from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.contract_engine.services.contract_store import ContractStore
from src.shared.models.contracts import (
    ContractCreate,
    ContractType,
    ContractStatus,
)
from src.shared.errors import ContractNotFoundError


@pytest.fixture
def store():
    """Create a ContractStore backed by a temporary SQLite database."""
    tmpdir = tempfile.mkdtemp()
    pool = ConnectionPool(os.path.join(tmpdir, "test.db"))
    init_contracts_db(pool)
    yield ContractStore(pool)
    pool.close()


def _make_create(
    service_name: str = "user-service",
    contract_type: ContractType = ContractType.OPENAPI,
    version: str = "1.0.0",
    spec: dict | None = None,
    build_cycle_id: str | None = None,
) -> ContractCreate:
    """Helper to build a ContractCreate with sensible defaults."""
    if spec is None:
        spec = {"openapi": "3.1.0", "info": {"title": service_name, "version": version}}
    return ContractCreate(
        service_name=service_name,
        type=contract_type,
        version=version,
        spec=spec,
        build_cycle_id=build_cycle_id,
    )


# ------------------------------------------------------------------
# 1. test_upsert_creates_contract
# ------------------------------------------------------------------
def test_upsert_creates_contract(store: ContractStore):
    """Upserting a new contract should persist it and return all fields."""
    create = _make_create(
        service_name="orders-service",
        version="2.0.0",
        spec={"openapi": "3.1.0", "info": {"title": "Orders", "version": "2.0.0"}},
    )
    entry = store.upsert(create)

    assert entry.service_name == "orders-service"
    assert entry.type == ContractType.OPENAPI
    assert entry.version == "2.0.0"
    assert entry.spec == create.spec
    assert entry.build_cycle_id is None
    assert entry.id is not None
    assert entry.spec_hash != ""
    assert entry.created_at is not None
    assert entry.updated_at is not None


# ------------------------------------------------------------------
# 2. test_upsert_updates_on_conflict
# ------------------------------------------------------------------
def test_upsert_updates_on_conflict(store: ContractStore):
    """Upserting with the same (service_name, type, version) should update the row."""
    create_v1 = _make_create(spec={"openapi": "3.1.0", "info": {"title": "v1"}})
    entry_v1 = store.upsert(create_v1)

    create_v2 = _make_create(spec={"openapi": "3.1.0", "info": {"title": "v2"}})
    entry_v2 = store.upsert(create_v2)

    # The ID should remain the same because the unique constraint matched.
    assert entry_v2.id == entry_v1.id
    # The spec should have been updated.
    assert entry_v2.spec == {"openapi": "3.1.0", "info": {"title": "v2"}}


# ------------------------------------------------------------------
# 3. test_upsert_sets_draft_status
# ------------------------------------------------------------------
def test_upsert_sets_draft_status(store: ContractStore):
    """A freshly upserted contract should always have 'draft' status."""
    entry = store.upsert(_make_create())
    assert entry.status == ContractStatus.DRAFT


# ------------------------------------------------------------------
# 4. test_get_returns_contract
# ------------------------------------------------------------------
def test_get_returns_contract(store: ContractStore):
    """Getting a contract by ID should return the correct entry."""
    created = store.upsert(_make_create(service_name="auth-service"))
    fetched = store.get(created.id)

    assert fetched.id == created.id
    assert fetched.service_name == "auth-service"
    assert fetched.type == created.type
    assert fetched.version == created.version
    assert fetched.spec == created.spec
    assert fetched.spec_hash == created.spec_hash


# ------------------------------------------------------------------
# 5. test_get_not_found_raises
# ------------------------------------------------------------------
def test_get_not_found_raises(store: ContractStore):
    """Getting a nonexistent contract should raise ContractNotFoundError."""
    with pytest.raises(ContractNotFoundError):
        store.get("nonexistent-id-12345")


# ------------------------------------------------------------------
# 6. test_list_default_pagination
# ------------------------------------------------------------------
def test_list_default_pagination(store: ContractStore):
    """Listing with no arguments should use default page=1, page_size=20."""
    # Insert 3 contracts with distinct unique keys.
    for i in range(3):
        store.upsert(_make_create(service_name=f"svc-{i}"))

    result = store.list()

    assert result.page == 1
    assert result.page_size == 20
    assert result.total == 3
    assert len(result.items) == 3


# ------------------------------------------------------------------
# 7. test_list_filter_by_service_name
# ------------------------------------------------------------------
def test_list_filter_by_service_name(store: ContractStore):
    """Filtering by service_name should return only matching contracts."""
    store.upsert(_make_create(service_name="alpha"))
    store.upsert(_make_create(service_name="beta"))
    store.upsert(_make_create(service_name="alpha", version="2.0.0"))

    result = store.list(service_name="alpha")

    assert result.total == 2
    assert all(item.service_name == "alpha" for item in result.items)


# ------------------------------------------------------------------
# 8. test_list_filter_by_type
# ------------------------------------------------------------------
def test_list_filter_by_type(store: ContractStore):
    """Filtering by contract type should return only matching contracts."""
    store.upsert(_make_create(service_name="svc-a", contract_type=ContractType.OPENAPI))
    store.upsert(
        _make_create(service_name="svc-b", contract_type=ContractType.ASYNCAPI)
    )
    store.upsert(
        _make_create(service_name="svc-c", contract_type=ContractType.JSON_SCHEMA)
    )

    result = store.list(contract_type=ContractType.ASYNCAPI.value)

    assert result.total == 1
    assert result.items[0].type == ContractType.ASYNCAPI


# ------------------------------------------------------------------
# 9. test_list_filter_by_status
# ------------------------------------------------------------------
def test_list_filter_by_status(store: ContractStore):
    """Filtering by status should return only matching contracts."""
    store.upsert(_make_create(service_name="svc-x"))
    store.upsert(_make_create(service_name="svc-y"))

    # All freshly created contracts are 'draft', so filtering for 'draft' should
    # return both while filtering for 'active' should return none.
    drafts = store.list(status=ContractStatus.DRAFT.value)
    assert drafts.total == 2

    actives = store.list(status=ContractStatus.ACTIVE.value)
    assert actives.total == 0


# ------------------------------------------------------------------
# 10. test_list_pagination
# ------------------------------------------------------------------
def test_list_pagination(store: ContractStore):
    """Pagination parameters should slice the result set correctly."""
    for i in range(5):
        store.upsert(_make_create(service_name=f"paginated-{i}"))

    page1 = store.list(page=1, page_size=2)
    assert page1.total == 5
    assert page1.page == 1
    assert page1.page_size == 2
    assert len(page1.items) == 2

    page2 = store.list(page=2, page_size=2)
    assert page2.total == 5
    assert page2.page == 2
    assert len(page2.items) == 2

    page3 = store.list(page=3, page_size=2)
    assert page3.total == 5
    assert page3.page == 3
    assert len(page3.items) == 1  # only 1 remaining item

    # No overlap between pages.
    page1_ids = {item.id for item in page1.items}
    page2_ids = {item.id for item in page2.items}
    page3_ids = {item.id for item in page3.items}
    assert page1_ids.isdisjoint(page2_ids)
    assert page2_ids.isdisjoint(page3_ids)


# ------------------------------------------------------------------
# 11. test_delete_removes_contract
# ------------------------------------------------------------------
def test_delete_removes_contract(store: ContractStore):
    """Deleting a contract should remove it from the store."""
    entry = store.upsert(_make_create(service_name="to-delete"))
    store.delete(entry.id)

    with pytest.raises(ContractNotFoundError):
        store.get(entry.id)


# ------------------------------------------------------------------
# 12. test_delete_not_found_raises
# ------------------------------------------------------------------
def test_delete_not_found_raises(store: ContractStore):
    """Deleting a nonexistent contract should raise ContractNotFoundError."""
    with pytest.raises(ContractNotFoundError):
        store.delete("nonexistent-id-99999")


# ------------------------------------------------------------------
# 13. test_has_changed_same_spec_returns_false
# ------------------------------------------------------------------
def test_has_changed_same_spec_returns_false(store: ContractStore):
    """has_changed should return False when the spec matches what is stored."""
    spec = {"openapi": "3.1.0", "info": {"title": "Same", "version": "1.0.0"}}
    store.upsert(
        _make_create(service_name="check-svc", version="1.0.0", spec=spec)
    )

    result = store.has_changed(
        service_name="check-svc",
        contract_type=ContractType.OPENAPI.value,
        version="1.0.0",
        spec=spec,
    )
    assert result is False


# ------------------------------------------------------------------
# 14. test_has_changed_different_spec_returns_true
# ------------------------------------------------------------------
def test_has_changed_different_spec_returns_true(store: ContractStore):
    """has_changed should return True when the spec differs from what is stored."""
    original_spec = {"openapi": "3.1.0", "info": {"title": "Original"}}
    store.upsert(
        _make_create(service_name="change-svc", version="1.0.0", spec=original_spec)
    )

    modified_spec = {"openapi": "3.1.0", "info": {"title": "Modified"}}
    result = store.has_changed(
        service_name="change-svc",
        contract_type=ContractType.OPENAPI.value,
        version="1.0.0",
        spec=modified_spec,
    )
    assert result is True


# ------------------------------------------------------------------
# 15. test_has_changed_nonexistent_returns_true
# ------------------------------------------------------------------
def test_has_changed_nonexistent_returns_true(store: ContractStore):
    """has_changed should return True when no matching contract exists."""
    result = store.has_changed(
        service_name="ghost-service",
        contract_type=ContractType.OPENAPI.value,
        version="1.0.0",
        spec={"openapi": "3.1.0"},
    )
    assert result is True


# ------------------------------------------------------------------
# Additional edge case tests
# ------------------------------------------------------------------


class TestContractStoreEdgeCases:
    """Additional edge-case tests for ContractStore."""

    def test_list_page_size_clamped_to_max(self, store: ContractStore):
        """Requesting a page_size > 100 is clamped to 100."""
        store.upsert(_make_create(service_name="svc-1"))
        result = store.list(page=1, page_size=500)
        assert result.page_size == 100

    def test_list_page_size_clamped_to_min(self, store: ContractStore):
        """Requesting a page_size < 1 is clamped to 1."""
        store.upsert(_make_create(service_name="svc-1"))
        result = store.list(page=1, page_size=0)
        assert result.page_size == 1

    def test_list_page_clamped_to_min(self, store: ContractStore):
        """Requesting page < 1 is clamped to 1."""
        store.upsert(_make_create(service_name="svc-1"))
        result = store.list(page=-1)
        assert result.page == 1

    def test_upsert_with_build_cycle_id(self, store: ContractStore):
        """Upserting with a build_cycle_id persists it."""
        # First insert a build cycle
        conn = store._pool.get()
        conn.execute(
            "INSERT INTO build_cycles (id, project_name, status) VALUES (?, ?, ?)",
            ("bc-1", "test-project", "running"),
        )
        conn.commit()

        entry = store.upsert(
            _make_create(service_name="bc-svc", build_cycle_id="bc-1")
        )
        assert entry.build_cycle_id == "bc-1"

    def test_list_combines_multiple_filters(self, store: ContractStore):
        """Multiple filters (service_name AND type) can be combined."""
        store.upsert(_make_create(
            service_name="multi-a", contract_type=ContractType.OPENAPI,
        ))
        store.upsert(_make_create(
            service_name="multi-a", contract_type=ContractType.ASYNCAPI,
        ))
        store.upsert(_make_create(
            service_name="multi-b", contract_type=ContractType.OPENAPI,
        ))

        result = store.list(
            service_name="multi-a",
            contract_type=ContractType.OPENAPI.value,
        )
        assert result.total == 1
        assert result.items[0].service_name == "multi-a"
        assert result.items[0].type == ContractType.OPENAPI

    def test_compute_hash_deterministic(self):
        """_compute_hash is deterministic: same spec produces same hash."""
        spec = {"a": 1, "b": [2, 3]}
        h1 = ContractStore._compute_hash(spec)
        h2 = ContractStore._compute_hash(spec)
        assert h1 == h2

    def test_compute_hash_key_order_independent(self):
        """_compute_hash is key-order independent (uses sort_keys)."""
        spec1 = {"z": 1, "a": 2}
        spec2 = {"a": 2, "z": 1}
        assert ContractStore._compute_hash(spec1) == ContractStore._compute_hash(spec2)

    def test_compute_hash_different_specs_differ(self):
        """Different specs produce different hashes."""
        h1 = ContractStore._compute_hash({"a": 1})
        h2 = ContractStore._compute_hash({"a": 2})
        assert h1 != h2

    def test_list_empty_database(self, store: ContractStore):
        """Listing an empty database returns empty items with total=0."""
        result = store.list()
        assert result.total == 0
        assert result.items == []
        assert result.page == 1

    def test_delete_then_list_shows_fewer(self, store: ContractStore):
        """After deleting a contract, the list shows fewer items."""
        e1 = store.upsert(_make_create(service_name="del-a"))
        store.upsert(_make_create(service_name="del-b"))

        assert store.list().total == 2
        store.delete(e1.id)
        assert store.list().total == 1
