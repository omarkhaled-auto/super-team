"""Tests for ImplementationTracker service."""
import os
import tempfile

import pytest

from src.contract_engine.services.implementation_tracker import ImplementationTracker
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import ContractNotFoundError
from src.shared.models.contracts import ImplementationStatus


@pytest.fixture
def pool():
    tmpdir = tempfile.mkdtemp()
    p = ConnectionPool(os.path.join(tmpdir, "test.db"))
    init_contracts_db(p)
    yield p
    p.close()


def _insert_dummy_contract(pool, contract_id="test-id", service_name="test-svc"):
    """Insert a minimal contract row so FK constraints are satisfied."""
    conn = pool.get()
    conn.execute(
        "INSERT INTO contracts "
        "(id, type, version, service_name, spec_json, spec_hash, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (contract_id, "openapi", "1.0.0", service_name, "{}", "abc", "draft"),
    )
    conn.commit()


class TestImplementationTracker:
    """Tests for the ImplementationTracker class."""

    def test_mark_implemented_success(self, pool):
        """Marking a contract as implemented succeeds and returns a MarkResponse."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        result = tracker.mark_implemented(
            contract_id="test-id",
            service_name="consumer-svc",
            evidence_path="/path/to/tests.py",
        )

        assert result.marked is True
        assert result.total_implementations == 1
        # Not all_implemented because the implementation is still 'pending'
        assert result.all_implemented is False

    def test_mark_implemented_contract_not_found(self, pool):
        """Marking a non-existent contract raises ContractNotFoundError."""
        tracker = ImplementationTracker(pool)

        with pytest.raises(ContractNotFoundError) as exc_info:
            tracker.mark_implemented(
                contract_id="nonexistent-id",
                service_name="consumer-svc",
                evidence_path="/path/to/tests.py",
            )

        assert "nonexistent-id" in str(exc_info.value)

    def test_mark_implemented_idempotent(self, pool):
        """Marking the same contract+service twice is idempotent (upsert)."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        result1 = tracker.mark_implemented(
            contract_id="test-id",
            service_name="consumer-svc",
            evidence_path="/path/v1/tests.py",
        )

        # Mark again with a different evidence_path - should upsert, not fail
        result2 = tracker.mark_implemented(
            contract_id="test-id",
            service_name="consumer-svc",
            evidence_path="/path/v2/tests.py",
        )

        assert result1.marked is True
        assert result2.marked is True
        # Still just one implementation record
        assert result2.total_implementations == 1

    def test_verify_implementation(self, pool):
        """Verifying an implementation sets status to 'verified'."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        # First mark it
        tracker.mark_implemented(
            contract_id="test-id",
            service_name="consumer-svc",
            evidence_path="/path/to/tests.py",
        )

        # Then verify it
        record = tracker.verify_implementation(
            contract_id="test-id",
            service_name="consumer-svc",
        )

        assert record.status == ImplementationStatus.VERIFIED
        assert record.verified_at is not None
        assert record.contract_id == "test-id"
        assert record.service_name == "consumer-svc"
        assert record.evidence_path == "/path/to/tests.py"

    def test_get_unimplemented_returns_contracts(self, pool):
        """Contracts without implementations appear in get_unimplemented()."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="svc-a")
        _insert_dummy_contract(pool, contract_id="c2", service_name="svc-b")
        tracker = ImplementationTracker(pool)

        unimplemented = tracker.get_unimplemented()

        assert len(unimplemented) == 2
        ids = {u.id for u in unimplemented}
        assert "c1" in ids
        assert "c2" in ids

    def test_get_unimplemented_filter_by_service(self, pool):
        """Filtering by service_name returns only that service's contracts."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="svc-a")
        _insert_dummy_contract(pool, contract_id="c2", service_name="svc-b")
        tracker = ImplementationTracker(pool)

        unimplemented = tracker.get_unimplemented(service_name="svc-a")

        assert len(unimplemented) == 1
        assert unimplemented[0].id == "c1"
        assert unimplemented[0].expected_service == "svc-a"

    def test_get_unimplemented_empty_when_all_verified(self, pool):
        """When all contracts have verified implementations, the list is empty."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="svc-a")
        tracker = ImplementationTracker(pool)

        # Mark and verify the implementation
        tracker.mark_implemented(
            contract_id="c1",
            service_name="svc-a",
            evidence_path="/evidence.py",
        )
        tracker.verify_implementation(
            contract_id="c1",
            service_name="svc-a",
        )

        unimplemented = tracker.get_unimplemented()

        assert len(unimplemented) == 0


class TestImplementationTrackerEdgeCases:
    """Additional edge-case tests for ImplementationTracker."""

    def test_verify_nonexistent_implementation_raises(self, pool):
        """Verifying an implementation that does not exist raises error."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        with pytest.raises(ContractNotFoundError):
            tracker.verify_implementation(
                contract_id="test-id",
                service_name="no-such-service",
            )

    def test_mark_multiple_services_same_contract(self, pool):
        """Multiple services can implement the same contract."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        r1 = tracker.mark_implemented("test-id", "svc-a", "/path/a.py")
        r2 = tracker.mark_implemented("test-id", "svc-b", "/path/b.py")

        assert r1.total_implementations == 1
        assert r2.total_implementations == 2

    def test_all_implemented_only_when_all_verified(self, pool):
        """all_implemented is only True when all implementations are verified."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        # Mark implemented (status = pending)
        result = tracker.mark_implemented("test-id", "svc-a", "/path.py")
        assert result.all_implemented is False

        # Verify the implementation
        tracker.verify_implementation("test-id", "svc-a")

        # Mark again to re-check (or just query)
        result2 = tracker.mark_implemented("test-id", "svc-a", "/path.py")
        # After re-mark, it goes back to pending
        assert result2.all_implemented is False

    def test_get_unimplemented_with_pending_implementation(self, pool):
        """Contracts with pending implementations still show as unimplemented."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="svc-a")
        tracker = ImplementationTracker(pool)

        # Mark as implemented but don't verify
        tracker.mark_implemented("c1", "svc-a", "/evidence.py")

        unimplemented = tracker.get_unimplemented()
        # Should still show up because implementation is pending, not verified
        assert len(unimplemented) == 1
        assert unimplemented[0].id == "c1"

    def test_verify_sets_verified_at_timestamp(self, pool):
        """Verifying an implementation sets the verified_at timestamp."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        tracker.mark_implemented("test-id", "svc-a", "/path.py")
        record = tracker.verify_implementation("test-id", "svc-a")

        assert record.verified_at is not None
        assert record.status == ImplementationStatus.VERIFIED

    def test_get_unimplemented_no_contracts(self, pool):
        """get_unimplemented on an empty database returns an empty list."""
        tracker = ImplementationTracker(pool)
        result = tracker.get_unimplemented()
        assert result == []

    def test_get_unimplemented_filter_returns_empty_for_nonexistent_service(self, pool):
        """Filtering by a nonexistent service returns an empty list."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="real-svc")
        tracker = ImplementationTracker(pool)

        result = tracker.get_unimplemented(service_name="fake-svc")
        assert result == []

    def test_mark_updates_evidence_path_on_remark(self, pool):
        """Re-marking an implementation updates the evidence_path."""
        _insert_dummy_contract(pool)
        tracker = ImplementationTracker(pool)

        tracker.mark_implemented("test-id", "svc-a", "/old/path.py")
        tracker.mark_implemented("test-id", "svc-a", "/new/path.py")

        # Verify to get the full record back and check
        record = tracker.verify_implementation("test-id", "svc-a")
        assert record.evidence_path == "/new/path.py"
