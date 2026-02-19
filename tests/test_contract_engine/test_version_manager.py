"""Tests for VersionManager service."""
import os
import tempfile

import pytest

from src.contract_engine.services.version_manager import VersionManager
from src.shared.db.connection import ConnectionPool
from src.shared.db.schema import init_contracts_db
from src.shared.errors import ImmutabilityViolationError
from src.shared.models.contracts import BreakingChange


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


def _insert_dummy_build_cycle(pool, cycle_id="cycle-1"):
    """Insert a minimal build_cycle row so FK constraints are satisfied."""
    conn = pool.get()
    conn.execute(
        "INSERT INTO build_cycles (id, project_name, status) VALUES (?, ?, ?)",
        (cycle_id, "test-project", "running"),
    )
    conn.commit()


class TestVersionManager:
    """Tests for the VersionManager class."""

    def test_create_version_basic(self, pool):
        """Creating a version record succeeds and returns a ContractVersion."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        result = vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-abc",
        )

        assert result.contract_id == "test-id"
        assert result.version == "1.0.0"
        assert result.spec_hash == "hash-abc"
        assert result.is_breaking is False
        assert result.breaking_changes == []
        assert result.created_at is not None

    def test_check_immutability_allows_no_build_cycle(self, pool):
        """A None build_cycle_id should always be allowed (no immutability check)."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        # Create a version without build_cycle_id
        vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
            build_cycle_id=None,
        )

        # Creating another with None build_cycle_id should not raise
        vm.create_version(
            contract_id="test-id",
            version="2.0.0",
            spec_hash="hash-2",
            build_cycle_id=None,
        )

    def test_check_immutability_allows_first_version(self, pool):
        """The first version in a build cycle should always be allowed."""
        _insert_dummy_contract(pool)
        _insert_dummy_build_cycle(pool, "cycle-1")
        vm = VersionManager(pool)

        # Should not raise - first version in this build cycle
        result = vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
            build_cycle_id="cycle-1",
        )

        assert result.build_cycle_id == "cycle-1"

    def test_check_immutability_blocks_duplicate(self, pool):
        """A second version in the same build cycle raises ImmutabilityViolationError."""
        _insert_dummy_contract(pool)
        _insert_dummy_build_cycle(pool, "cycle-1")
        vm = VersionManager(pool)

        # First version in cycle is OK
        vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
            build_cycle_id="cycle-1",
        )

        # Second version in the same cycle should raise
        with pytest.raises(ImmutabilityViolationError) as exc_info:
            vm.create_version(
                contract_id="test-id",
                version="2.0.0",
                spec_hash="hash-2",
                build_cycle_id="cycle-1",
            )

        assert "cycle-1" in str(exc_info.value)
        assert "immutable" in str(exc_info.value).lower()

    def test_get_version_history(self, pool):
        """Version history is returned ordered by created_at DESC."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
        )
        vm.create_version(
            contract_id="test-id",
            version="2.0.0",
            spec_hash="hash-2",
        )
        vm.create_version(
            contract_id="test-id",
            version="3.0.0",
            spec_hash="hash-3",
        )

        history = vm.get_version_history("test-id")

        assert len(history) == 3
        # Newest first (DESC)
        assert history[0].version == "3.0.0"
        assert history[1].version == "2.0.0"
        assert history[2].version == "1.0.0"

    def test_create_version_with_breaking_changes(self, pool):
        """Creating a version with breaking changes persists them."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        changes = [
            BreakingChange(
                change_type="path_removed",
                path="/api/users",
                old_value="/api/users",
                new_value=None,
                severity="error",
                affected_consumers=["frontend", "mobile"],
            ),
            BreakingChange(
                change_type="type_changed",
                path="/api/orders.POST.requestBody.schema",
                old_value="string",
                new_value="integer",
                severity="error",
                affected_consumers=["checkout-svc"],
            ),
        ]

        result = vm.create_version(
            contract_id="test-id",
            version="2.0.0",
            spec_hash="hash-breaking",
            is_breaking=True,
            breaking_changes=changes,
            change_summary="Removed users endpoint and changed order type",
        )

        assert result.is_breaking is True
        assert len(result.breaking_changes) == 2
        assert result.breaking_changes[0].change_type == "path_removed"
        assert result.breaking_changes[1].change_type == "type_changed"
        assert result.breaking_changes[0].affected_consumers == ["frontend", "mobile"]

    def test_get_version_history_includes_breaking_changes(self, pool):
        """Version history loads breaking changes from the breaking_changes table."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        changes = [
            BreakingChange(
                change_type="method_removed",
                path="/api/items.DELETE",
                old_value="DELETE",
                new_value=None,
                severity="error",
                affected_consumers=["admin-panel"],
            ),
        ]

        vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-safe",
        )
        vm.create_version(
            contract_id="test-id",
            version="2.0.0",
            spec_hash="hash-breaking",
            is_breaking=True,
            breaking_changes=changes,
        )

        history = vm.get_version_history("test-id")

        assert len(history) == 2

        # Newest first (v2 has breaking changes)
        v2 = history[0]
        assert v2.version == "2.0.0"
        assert v2.is_breaking is True
        assert len(v2.breaking_changes) == 1
        assert v2.breaking_changes[0].change_type == "method_removed"
        assert v2.breaking_changes[0].affected_consumers == ["admin-panel"]

        # Older version has no breaking changes
        v1 = history[1]
        assert v1.version == "1.0.0"
        assert v1.is_breaking is False
        assert len(v1.breaking_changes) == 0


class TestVersionManagerEdgeCases:
    """Additional edge-case tests for VersionManager."""

    def test_get_version_history_empty(self, pool):
        """Getting history for a contract with no versions returns an empty list."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)
        history = vm.get_version_history("test-id")
        assert history == []

    def test_get_version_history_nonexistent_contract(self, pool):
        """Getting history for a contract that does not exist returns empty list."""
        vm = VersionManager(pool)
        history = vm.get_version_history("nonexistent-id")
        assert history == []

    def test_check_immutability_different_contracts_same_build(self, pool):
        """Different contracts in the same build cycle should not conflict."""
        _insert_dummy_contract(pool, contract_id="c1", service_name="svc-a")
        _insert_dummy_contract(pool, contract_id="c2", service_name="svc-b")
        _insert_dummy_build_cycle(pool, "shared-cycle")
        vm = VersionManager(pool)

        vm.create_version(
            contract_id="c1", version="1.0.0", spec_hash="h1",
            build_cycle_id="shared-cycle",
        )
        # Different contract in same build cycle is fine
        vm.create_version(
            contract_id="c2", version="1.0.0", spec_hash="h2",
            build_cycle_id="shared-cycle",
        )

    def test_check_immutability_same_contract_different_build(self, pool):
        """Same contract in different build cycles is allowed."""
        _insert_dummy_contract(pool)
        _insert_dummy_build_cycle(pool, "cycle-1")
        _insert_dummy_build_cycle(pool, "cycle-2")
        vm = VersionManager(pool)

        vm.create_version(
            contract_id="test-id", version="1.0.0", spec_hash="h1",
            build_cycle_id="cycle-1",
        )
        # Same contract in different build cycle is fine
        vm.create_version(
            contract_id="test-id", version="2.0.0", spec_hash="h2",
            build_cycle_id="cycle-2",
        )

    def test_create_version_change_summary(self, pool):
        """Change summary is persisted with the version."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        result = vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
            change_summary="Added new users endpoint",
        )
        assert result.contract_id == "test-id"

    def test_create_version_with_empty_breaking_changes(self, pool):
        """Creating a version with an empty breaking_changes list works fine."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        result = vm.create_version(
            contract_id="test-id",
            version="1.0.0",
            spec_hash="hash-1",
            breaking_changes=[],
        )
        assert result.breaking_changes == []
        assert result.is_breaking is False

    def test_version_created_at_populated(self, pool):
        """created_at field is populated by the database."""
        _insert_dummy_contract(pool)
        vm = VersionManager(pool)

        result = vm.create_version(
            contract_id="test-id", version="1.0.0", spec_hash="hash-1",
        )
        assert result.created_at is not None
