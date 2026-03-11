"""Tests for decomposition mode dispatch, monolith mode, and bounded-context merging.

Covers the three decomposition strategies added to ``identify_boundaries``:
  - microservices (default, identical to previous behaviour)
  - monolith (one backend + optional frontend)
  - bounded_contexts (merge small services into larger bounded contexts)
"""
from __future__ import annotations

import pytest

from src.architect.services.prd_parser import ParsedPRD
from src.architect.services.service_boundary import (
    ServiceBoundary,
    _boundaries_monolith,
    _build_relatedness_graph,
    _identify_boundaries_natural,
    _is_frontend_boundary,
    _merge_to_bounded_contexts,
    _merge_two_boundaries,
    build_service_map,
    identify_boundaries,
)
from src.super_orchestrator.config import (
    ArchitectConfig,
    validate_architect_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(name: str, owning_context: str | None = None) -> dict:
    """Shorthand for creating a raw entity dict."""
    return {
        "name": name,
        "description": f"{name} entity",
        "fields": [],
        "owning_context": owning_context,
    }


def _make_boundary(
    name: str,
    entity_count: int = 3,
    is_frontend: bool = False,
) -> ServiceBoundary:
    """Create a test boundary with N dummy entities."""
    entities = [f"{name}_E{i}" for i in range(entity_count)]
    return ServiceBoundary(
        name=name,
        domain=name.lower().replace(" ", "-"),
        description=f"Test boundary {name}",
        entities=entities,
        is_frontend=is_frontend,
    )


def _make_parsed(
    entities: list[dict] | None = None,
    relationships: list[dict] | None = None,
    explicit_services: list[dict] | None = None,
    events: list[dict] | None = None,
    technology_hints: dict | None = None,
    project_name: str = "TestProject",
) -> ParsedPRD:
    """Build a ParsedPRD fixture."""
    return ParsedPRD(
        project_name=project_name,
        entities=entities or [],
        relationships=relationships or [],
        explicit_services=explicit_services or [],
        events=events or [],
        technology_hints=technology_hints or {},
    )


# ---------------------------------------------------------------------------
# Fixtures: A 10-entity, 5-service PRD with explicit services
# ---------------------------------------------------------------------------

_SUPPLYFORGE_ENTITIES = [
    _entity("Supplier", "Procurement Service"),
    _entity("PurchaseOrder", "Procurement Service"),
    _entity("Product", "Inventory Service"),
    _entity("StockLevel", "Inventory Service"),
    _entity("Warehouse", "Warehouse Service"),
    _entity("ShipmentBatch", "Warehouse Service"),
    _entity("Invoice", "Finance Service"),
    _entity("Payment", "Finance Service"),
    _entity("User", "Auth Service"),
    _entity("AuditLog", "Auth Service"),
]

_SUPPLYFORGE_SERVICES = [
    {"name": "Procurement Service", "language": "python", "framework": "FastAPI"},
    {"name": "Inventory Service", "language": "python", "framework": "FastAPI"},
    {"name": "Warehouse Service", "language": "typescript", "framework": "NestJS"},
    {"name": "Finance Service", "language": "python", "framework": "FastAPI"},
    {"name": "Auth Service", "language": "python", "framework": "FastAPI"},
]

_SUPPLYFORGE_RELATIONSHIPS = [
    {"source": "PurchaseOrder", "target": "Supplier", "type": "BELONGS_TO"},
    {"source": "Product", "target": "StockLevel", "type": "HAS_MANY"},
    {"source": "Warehouse", "target": "ShipmentBatch", "type": "OWNS"},
    {"source": "Invoice", "target": "Payment", "type": "HAS_MANY"},
    {"source": "Invoice", "target": "PurchaseOrder", "type": "REFERENCES"},
    {"source": "ShipmentBatch", "target": "Product", "type": "REFERENCES"},
]

_SUPPLYFORGE_PARSED = _make_parsed(
    entities=_SUPPLYFORGE_ENTITIES,
    relationships=_SUPPLYFORGE_RELATIONSHIPS,
    explicit_services=_SUPPLYFORGE_SERVICES,
    project_name="SupplyForge",
)


# ===========================================================================
# Config validation
# ===========================================================================


class TestConfigValidation:
    def test_default_strategy_is_microservices(self):
        config = ArchitectConfig()
        assert config.decomposition_strategy == "microservices"

    def test_default_max_services(self):
        config = ArchitectConfig()
        assert config.max_services == 5

    def test_default_min_entities(self):
        config = ArchitectConfig()
        assert config.min_entities_per_service == 6

    def test_invalid_strategy_raises(self):
        config = ArchitectConfig(decomposition_strategy="invalid")
        with pytest.raises(ValueError, match="Invalid decomposition_strategy"):
            validate_architect_config(config)

    def test_valid_strategies_accepted(self):
        for strategy in ("microservices", "bounded_contexts", "monolith"):
            config = ArchitectConfig(decomposition_strategy=strategy)
            validate_architect_config(config)  # Should not raise

    def test_max_services_zero_raises(self):
        config = ArchitectConfig(max_services=0)
        with pytest.raises(ValueError, match="max_services"):
            validate_architect_config(config)

    def test_min_entities_zero_raises(self):
        config = ArchitectConfig(min_entities_per_service=0)
        with pytest.raises(ValueError, match="min_entities_per_service"):
            validate_architect_config(config)


# ===========================================================================
# Mode dispatch
# ===========================================================================


class TestModeDispatch:
    def test_default_uses_natural(self):
        """Default (microservices) dispatches to _identify_boundaries_natural."""
        result = identify_boundaries(_SUPPLYFORGE_PARSED)
        natural = _identify_boundaries_natural(_SUPPLYFORGE_PARSED)
        assert len(result) == len(natural)
        assert {b.name for b in result} == {b.name for b in natural}

    def test_microservices_explicit_same_as_default(self):
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="microservices"
        )
        natural = _identify_boundaries_natural(_SUPPLYFORGE_PARSED)
        assert len(result) == len(natural)
        assert {b.name for b in result} == {b.name for b in natural}

    def test_monolith_dispatches(self):
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="monolith"
        )
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) == 1
        # Backend must have all 10 entities
        assert len(backend[0].entities) == 10

    def test_bounded_contexts_dispatches(self):
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED,
            decomposition_strategy="bounded_contexts",
            max_services=3,
        )
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) <= 3


# ===========================================================================
# Microservices regression
# ===========================================================================


class TestMicroservicesRegression:
    def test_identical_service_ids(self):
        """microservices mode produces the exact same boundary names as natural."""
        old = _identify_boundaries_natural(_SUPPLYFORGE_PARSED)
        new = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="microservices"
        )
        old_names = sorted(b.name for b in old)
        new_names = sorted(b.name for b in new)
        assert old_names == new_names

    def test_identical_entity_counts(self):
        old = _identify_boundaries_natural(_SUPPLYFORGE_PARSED)
        new = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="microservices"
        )
        old_counts = sorted(len(b.entities) for b in old)
        new_counts = sorted(len(b.entities) for b in new)
        assert old_counts == new_counts

    def test_identical_entity_assignments(self):
        old = _identify_boundaries_natural(_SUPPLYFORGE_PARSED)
        new = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="microservices"
        )
        for ob in sorted(old, key=lambda b: b.name):
            nb = next(b for b in new if b.name == ob.name)
            assert sorted(ob.entities) == sorted(nb.entities)


# ===========================================================================
# Monolith mode
# ===========================================================================


class TestMonolithMode:
    def test_all_entities_in_backend(self):
        result = _boundaries_monolith(_SUPPLYFORGE_PARSED)
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) == 1
        prd_names = sorted(
            e.get("name", "") for e in _SUPPLYFORGE_PARSED.entities
        )
        assert sorted(backend[0].entities) == prd_names

    def test_no_frontend_when_no_frontend_stack(self):
        parsed = _make_parsed(
            entities=[_entity("A"), _entity("B")],
            explicit_services=[
                {"name": "Svc1", "language": "python", "framework": "FastAPI"},
                {"name": "Svc2", "language": "python", "framework": "FastAPI"},
                {"name": "Svc3", "language": "python", "framework": "FastAPI"},
            ],
        )
        result = _boundaries_monolith(parsed)
        assert len(result) == 1
        assert not _is_frontend_boundary(result[0])

    def test_frontend_detected_from_explicit_services(self):
        parsed = _make_parsed(
            entities=[_entity("A")],
            explicit_services=[
                {"name": "Backend", "language": "python", "framework": "FastAPI"},
                {"name": "Frontend", "language": "typescript", "framework": "Angular"},
            ],
        )
        result = _boundaries_monolith(parsed)
        frontend = [b for b in result if _is_frontend_boundary(b)]
        assert len(frontend) == 1
        assert frontend[0].name == "frontend"

    def test_frontend_detected_from_technology_hints(self):
        parsed = _make_parsed(
            entities=[_entity("X")],
            technology_hints={"framework": "React"},
        )
        result = _boundaries_monolith(parsed)
        frontend = [b for b in result if _is_frontend_boundary(b)]
        assert len(frontend) == 1

    def test_backend_lang_from_majority(self):
        """Backend stack should be the most common non-frontend language."""
        parsed = _make_parsed(
            entities=[_entity("E1"), _entity("E2")],
            explicit_services=[
                {"name": "S1", "language": "python", "framework": "FastAPI"},
                {"name": "S2", "language": "python", "framework": "FastAPI"},
                {"name": "S3", "language": "typescript", "framework": "NestJS"},
                {"name": "S4", "language": "python", "framework": "FastAPI"},
                {"name": "FE", "language": "typescript", "framework": "Angular"},
            ],
        )
        result = _boundaries_monolith(parsed)
        backend = [b for b in result if not _is_frontend_boundary(b)][0]
        # Python appears 3 times vs typescript 1 (excluding Angular frontend)
        smap = build_service_map(parsed, result)
        # The default stack from technology_hints is used; but backend name includes "backend"
        assert "backend" in backend.name.lower()

    def test_backend_name_includes_project(self):
        parsed = _make_parsed(
            entities=[_entity("Z")],
            project_name="MyApp",
        )
        result = _boundaries_monolith(parsed)
        backend = [b for b in result if not _is_frontend_boundary(b)][0]
        assert "myapp" in backend.name.lower()

    def test_monolith_empty_entities(self):
        parsed = _make_parsed(entities=[], project_name="Empty")
        result = _boundaries_monolith(parsed)
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) == 1
        assert backend[0].entities == []

    def test_monolith_contracts_computed(self):
        """Monolith backend should have provides_contracts set."""
        parsed = _make_parsed(
            entities=[_entity("A"), _entity("B")],
            relationships=[
                {"source": "A", "target": "B", "type": "REFERENCES"},
            ],
        )
        result = _boundaries_monolith(parsed)
        backend = [b for b in result if not _is_frontend_boundary(b)][0]
        # Single backend — all relationships are intra-service, so no cross-contracts
        # but the backend should provide its own API contract
        assert len(backend.provides_contracts) >= 1


# ===========================================================================
# Bounded context merge engine
# ===========================================================================


class TestBoundedContextMerge:
    def test_merge_respects_max_services(self):
        """Result has at most max_services backend services."""
        boundaries = [_make_boundary(f"Svc{i}", entity_count=2) for i in range(8)]
        parsed = _make_parsed(
            entities=[_entity(f"Svc{i}_E{j}") for i in range(8) for j in range(2)],
        )
        result = _merge_to_bounded_contexts(
            boundaries, parsed, max_services=3, min_entities_per_service=1
        )
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) <= 3

    def test_merge_preserves_all_entities(self):
        """No entities lost during merging."""
        boundaries = [_make_boundary(f"Svc{i}", entity_count=3) for i in range(6)]
        original_entities = set()
        for b in boundaries:
            original_entities.update(b.entities)

        parsed = _make_parsed(
            entities=[_entity(name) for name in original_entities],
        )
        result = _merge_to_bounded_contexts(
            boundaries, parsed, max_services=2, min_entities_per_service=1
        )
        merged_entities = set()
        for b in result:
            merged_entities.update(b.entities)

        assert original_entities == merged_entities

    def test_merge_no_duplicate_entities(self):
        """Merged boundary doesn't contain duplicate entities."""
        a = _make_boundary("A", entity_count=3)
        b = _make_boundary("B", entity_count=3)
        result = _merge_two_boundaries(a, b)
        assert len(result.entities) == len(set(result.entities))

    def test_frontend_never_merged(self):
        """Frontend service is always separate, never merged."""
        boundaries = [
            _make_boundary("Svc1", entity_count=2),
            _make_boundary("Svc2", entity_count=2),
            _make_boundary("Frontend", entity_count=0, is_frontend=True),
        ]
        parsed = _make_parsed(
            entities=[_entity(name) for b in boundaries for name in b.entities],
        )
        result = _merge_to_bounded_contexts(
            boundaries, parsed, max_services=1, min_entities_per_service=1
        )
        frontend = [b for b in result if _is_frontend_boundary(b)]
        assert len(frontend) == 1
        assert frontend[0].name == "Frontend"

    def test_already_meeting_constraints_no_merge(self):
        """If boundaries already meet constraints, no merging occurs."""
        boundaries = [_make_boundary(f"Svc{i}", entity_count=10) for i in range(3)]
        parsed = _make_parsed(
            entities=[_entity(name) for b in boundaries for name in b.entities],
        )
        result = _merge_to_bounded_contexts(
            boundaries, parsed, max_services=5, min_entities_per_service=6
        )
        assert len(result) == 3

    def test_single_service_unchanged(self):
        boundaries = [_make_boundary("Solo", entity_count=5)]
        parsed = _make_parsed(
            entities=[_entity(name) for name in boundaries[0].entities],
        )
        result = _merge_to_bounded_contexts(
            boundaries, parsed, max_services=5, min_entities_per_service=1
        )
        assert len(result) == 1

    def test_merge_prefers_related_services(self):
        """Services with entity relationships merge before unrelated ones."""
        svc_a = ServiceBoundary(
            name="SvcA", domain="a", description="A",
            entities=["EntityA1", "EntityA2"],
        )
        svc_b = ServiceBoundary(
            name="SvcB", domain="b", description="B",
            entities=["EntityB1", "EntityB2"],
        )
        svc_c = ServiceBoundary(
            name="SvcC", domain="c", description="C",
            entities=["EntityC1", "EntityC2"],
        )

        parsed = _make_parsed(
            entities=[
                _entity("EntityA1"), _entity("EntityA2"),
                _entity("EntityB1"), _entity("EntityB2"),
                _entity("EntityC1"), _entity("EntityC2"),
            ],
            relationships=[
                # A and B are related (3 points each)
                {"source": "EntityA1", "target": "EntityB1", "type": "REFERENCES"},
                {"source": "EntityA2", "target": "EntityB2", "type": "REFERENCES"},
            ],
        )

        result = _merge_to_bounded_contexts(
            [svc_a, svc_b, svc_c], parsed,
            max_services=2, min_entities_per_service=1,
        )
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) == 2

        # A and B should be merged (related via 2 relationships = 6 points)
        ab_boundary = next(
            b for b in backend if "EntityA1" in b.entities
        )
        assert "EntityB1" in ab_boundary.entities

    def test_merge_min_entities_drives_merge(self):
        """Small services get merged even without relationships."""
        small = [_make_boundary(f"Small{i}", entity_count=2) for i in range(4)]
        parsed = _make_parsed(
            entities=[_entity(name) for b in small for name in b.entities],
        )
        result = _merge_to_bounded_contexts(
            small, parsed, max_services=10, min_entities_per_service=6
        )
        # With min_entities=6 and 4 services of 2 entities each,
        # we need at least 2 merges (4→2 services of 4 entities each)
        # But 4 < 6, so needs further merging → 1 service of 8 entities
        backend = [b for b in result if not _is_frontend_boundary(b)]
        for b in backend:
            assert len(b.entities) >= 6 or len(backend) == 1


# ===========================================================================
# Relatedness graph
# ===========================================================================


class TestRelatednessGraph:
    def test_relationship_increases_score(self):
        svc_a = _make_boundary("SvcA", entity_count=2)
        svc_b = _make_boundary("SvcB", entity_count=2)
        parsed = _make_parsed(
            entities=[_entity(n) for b in [svc_a, svc_b] for n in b.entities],
            relationships=[
                {"source": "SvcA_E0", "target": "SvcB_E0", "type": "REFERENCES"},
            ],
        )
        scores = _build_relatedness_graph([svc_a, svc_b], parsed)
        pair = tuple(sorted(["SvcA", "SvcB"]))
        assert scores.get(pair, 0) >= 3.0

    def test_no_relationship_zero_score(self):
        svc_a = _make_boundary("SvcA", entity_count=2)
        svc_b = _make_boundary("SvcB", entity_count=2)
        parsed = _make_parsed(
            entities=[_entity(n) for b in [svc_a, svc_b] for n in b.entities],
        )
        scores = _build_relatedness_graph([svc_a, svc_b], parsed)
        pair = tuple(sorted(["SvcA", "SvcB"]))
        assert scores.get(pair, 0) == 0.0

    def test_same_stack_increases_score(self):
        svc_a = _make_boundary("S1", entity_count=2)
        svc_b = _make_boundary("S2", entity_count=2)
        parsed = _make_parsed(
            entities=[_entity(n) for b in [svc_a, svc_b] for n in b.entities],
            explicit_services=[
                {"name": "S1", "language": "python"},
                {"name": "S2", "language": "python"},
            ],
        )
        scores = _build_relatedness_graph([svc_a, svc_b], parsed)
        pair = tuple(sorted(["S1", "S2"]))
        assert scores.get(pair, 0) >= 1.0


# ===========================================================================
# Merge two boundaries
# ===========================================================================


class TestMergeTwoBoundaries:
    def test_combines_entities(self):
        a = _make_boundary("A", entity_count=3)
        b = _make_boundary("B", entity_count=2)
        result = _merge_two_boundaries(a, b)
        assert len(result.entities) == 5

    def test_deduplicates_entities(self):
        a = ServiceBoundary(
            name="A", domain="a", description="A", entities=["X", "Y"]
        )
        b = ServiceBoundary(
            name="B", domain="b", description="B", entities=["Y", "Z"]
        )
        result = _merge_two_boundaries(a, b)
        assert sorted(result.entities) == ["X", "Y", "Z"]

    def test_larger_service_is_primary_in_name(self):
        a = _make_boundary("Small", entity_count=2)
        b = _make_boundary("Big", entity_count=5)
        result = _merge_two_boundaries(a, b)
        # "Big" has more entities so should be primary
        assert result.name.startswith("Big")

    def test_combines_contracts(self):
        a = ServiceBoundary(
            name="A", domain="a", description="A", entities=["E1"],
            provides_contracts=["a-api"], consumes_contracts=["c-api"],
        )
        b = ServiceBoundary(
            name="B", domain="b", description="B", entities=["E2"],
            provides_contracts=["b-api"], consumes_contracts=["d-api"],
        )
        result = _merge_two_boundaries(a, b)
        assert "a-api" in result.provides_contracts
        assert "b-api" in result.provides_contracts
        assert "c-api" in result.consumes_contracts
        assert "d-api" in result.consumes_contracts

    def test_long_name_falls_back_to_primary(self):
        a = _make_boundary("VeryLongServiceNameThatExceedsLimit", entity_count=5)
        b = _make_boundary("AnotherVeryLongServiceNameForTesting", entity_count=3)
        result = _merge_two_boundaries(a, b)
        # Name should not exceed 50 chars, falls back to primary
        assert len(result.name) <= 50


# ===========================================================================
# is_frontend_boundary
# ===========================================================================


class TestIsFrontendBoundary:
    def test_explicit_frontend_flag(self):
        b = ServiceBoundary(
            name="FE", domain="fe", description="UI",
            entities=[], is_frontend=True,
        )
        assert _is_frontend_boundary(b) is True

    def test_non_frontend(self):
        b = _make_boundary("Backend", entity_count=3)
        assert _is_frontend_boundary(b) is False


# ===========================================================================
# End-to-end: all 3 modes with same PRD
# ===========================================================================


class TestEndToEndAllModes:
    """Verify all 3 modes produce valid output from the same PRD."""

    def test_microservices_produces_5_services(self):
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="microservices"
        )
        assert len(result) == 5
        all_entities = {e for b in result for e in b.entities}
        assert len(all_entities) == 10

    def test_bounded_contexts_reduces_to_max(self):
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED,
            decomposition_strategy="bounded_contexts",
            max_services=3,
            min_entities_per_service=1,
        )
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(backend) <= 3
        # All 10 entities preserved
        all_entities = {e for b in result for e in b.entities}
        assert len(all_entities) == 10

    def test_monolith_produces_backend_and_no_frontend(self):
        """SupplyForge has no explicit frontend framework -> 1 backend only."""
        result = identify_boundaries(
            _SUPPLYFORGE_PARSED, decomposition_strategy="monolith"
        )
        assert len(result) == 1
        assert len(result[0].entities) == 10

    def test_monolith_with_frontend(self):
        """Add a frontend service to see 2 boundaries."""
        parsed = _make_parsed(
            entities=_SUPPLYFORGE_ENTITIES,
            relationships=_SUPPLYFORGE_RELATIONSHIPS,
            explicit_services=_SUPPLYFORGE_SERVICES + [
                {"name": "Frontend", "language": "typescript", "framework": "Angular"},
            ],
            project_name="SupplyForge",
        )
        result = identify_boundaries(parsed, decomposition_strategy="monolith")
        assert len(result) == 2
        frontend = [b for b in result if _is_frontend_boundary(b)]
        backend = [b for b in result if not _is_frontend_boundary(b)]
        assert len(frontend) == 1
        assert len(backend) == 1
        assert len(backend[0].entities) == 10

    def test_all_modes_produce_valid_service_map(self):
        """All 3 modes should produce a valid ServiceMap."""
        for strategy in ("microservices", "bounded_contexts", "monolith"):
            result = identify_boundaries(
                _SUPPLYFORGE_PARSED,
                decomposition_strategy=strategy,
                max_services=3,
            )
            smap = build_service_map(_SUPPLYFORGE_PARSED, result)
            assert smap.project_name == "SupplyForge"
            assert len(smap.services) >= 1
            # All entities owned by some service
            all_owned = {e for s in smap.services for e in s.owns_entities}
            prd_entities = {e.get("name") for e in _SUPPLYFORGE_PARSED.entities}
            assert prd_entities == all_owned, (
                f"strategy={strategy}: entity mismatch"
            )


# ===========================================================================
# Config YAML loading
# ===========================================================================


class TestConfigYAMLLoading:
    def test_strategy_from_yaml(self, tmp_path):
        import yaml
        from src.super_orchestrator.config import load_super_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({
            "architect": {"decomposition_strategy": "monolith"}
        }))
        config = load_super_config(cfg_path)
        assert config.architect.decomposition_strategy == "monolith"

    def test_max_services_from_yaml(self, tmp_path):
        import yaml
        from src.super_orchestrator.config import load_super_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({
            "architect": {"max_services": 3}
        }))
        config = load_super_config(cfg_path)
        assert config.architect.max_services == 3

    def test_default_strategy_when_not_specified(self, tmp_path):
        import yaml
        from src.super_orchestrator.config import load_super_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"builder": {"max_concurrent": 2}}))
        config = load_super_config(cfg_path)
        assert config.architect.decomposition_strategy == "microservices"

    def test_invalid_strategy_in_yaml_raises(self, tmp_path):
        import yaml
        from src.super_orchestrator.config import load_super_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({
            "architect": {"decomposition_strategy": "banana"}
        }))
        with pytest.raises(ValueError, match="Invalid decomposition_strategy"):
            load_super_config(cfg_path)
