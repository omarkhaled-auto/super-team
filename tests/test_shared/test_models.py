"""Comprehensive tests for all Pydantic data models — minimum 50 test cases."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.shared.models.architect import (
    DecomposeRequest,
    DecompositionResult,
    DecompositionRun,
    DomainEntity,
    DomainModel,
    DomainRelationship,
    EntityField,
    RelationshipType,
    ServiceDefinition,
    ServiceMap,
    ServiceStack,
    StateMachine,
    StateTransition,
)
from src.shared.models.codebase import (
    CodeChunk,
    DeadCodeEntry,
    DependencyEdge,
    DependencyRelation,
    GraphAnalysis,
    ImportReference,
    IndexStats,
    Language,
    SemanticSearchResult,
    ServiceInterface,
    SymbolDefinition,
    SymbolKind,
)
from src.shared.models.common import ArtifactRegistration, BuildCycle, HealthStatus
from src.shared.models.contracts import (
    AsyncAPIContract,
    BreakingChange,
    ChannelSpec,
    ComplianceResult,
    ComplianceViolation,
    ContractCreate,
    ContractEntry,
    ContractListResponse,
    ContractStatus,
    ContractTestSuite,
    ContractType,
    ContractVersion,
    EndpointSpec,
    ImplementationRecord,
    ImplementationStatus,
    MarkRequest,
    MarkResponse,
    MessageSpec,
    OpenAPIContract,
    OperationSpec,
    SharedSchema,
    UnimplementedContract,
    ValidateRequest,
    ValidationResult,
)


# ---- Architect Models ----


class TestServiceStack:
    def test_valid_construction(self):
        stack = ServiceStack(language="python", framework="fastapi")
        assert stack.language == "python"
        assert stack.framework == "fastapi"
        assert stack.database is None
        assert stack.message_broker is None

    def test_serialization_roundtrip(self):
        stack = ServiceStack(language="go", database="postgres")
        data = stack.model_dump()
        restored = ServiceStack(**data)
        assert restored == stack


class TestServiceDefinition:
    def test_valid_construction(self):
        sd = ServiceDefinition(
            name="user-service",
            domain="identity",
            description="Users",
            stack=ServiceStack(language="python"),
            estimated_loc=5000,
        )
        assert sd.name == "user-service"
        assert sd.owns_entities == []

    def test_name_pattern_invalid_uppercase(self):
        with pytest.raises(ValidationError):
            ServiceDefinition(
                name="UserService",
                domain="identity",
                description="Users",
                stack=ServiceStack(language="python"),
                estimated_loc=5000,
            )

    def test_name_pattern_invalid_starts_with_number(self):
        with pytest.raises(ValidationError):
            ServiceDefinition(
                name="1service",
                domain="identity",
                description="Users",
                stack=ServiceStack(language="python"),
                estimated_loc=5000,
            )

    def test_estimated_loc_too_low(self):
        with pytest.raises(ValidationError):
            ServiceDefinition(
                name="svc",
                domain="d",
                description="d",
                stack=ServiceStack(language="python"),
                estimated_loc=50,
            )

    def test_estimated_loc_too_high(self):
        with pytest.raises(ValidationError):
            ServiceDefinition(
                name="svc",
                domain="d",
                description="d",
                stack=ServiceStack(language="python"),
                estimated_loc=300000,
            )

    def test_serialization_roundtrip(self):
        sd = ServiceDefinition(
            name="order-svc",
            domain="commerce",
            description="Orders",
            stack=ServiceStack(language="typescript"),
            estimated_loc=10000,
            owns_entities=["Order"],
        )
        data = sd.model_dump()
        restored = ServiceDefinition(**data)
        assert restored.name == sd.name
        assert restored.owns_entities == ["Order"]


class TestStateMachine:
    def test_valid_construction(self):
        sm = StateMachine(
            states=["draft", "published"],
            initial_state="draft",
            transitions=[
                StateTransition(from_state="draft", to_state="published", trigger="publish")
            ],
        )
        assert len(sm.states) == 2

    def test_states_min_length(self):
        with pytest.raises(ValidationError):
            StateMachine(states=["only_one"], initial_state="only_one", transitions=[])


class TestDomainRelationship:
    def test_valid_cardinality(self):
        dr = DomainRelationship(
            source_entity="A",
            target_entity="B",
            relationship_type=RelationshipType.OWNS,
            cardinality="1:N",
        )
        assert dr.cardinality == "1:N"

    def test_invalid_cardinality(self):
        with pytest.raises(ValidationError):
            DomainRelationship(
                source_entity="A",
                target_entity="B",
                relationship_type=RelationshipType.OWNS,
                cardinality="many-to-many",
            )

    def test_all_cardinality_patterns(self):
        for card in ["1:1", "1:N", "N:1", "N:N"]:
            dr = DomainRelationship(
                source_entity="X",
                target_entity="Y",
                relationship_type=RelationshipType.REFERENCES,
                cardinality=card,
            )
            assert dr.cardinality == card


class TestServiceMap:
    def test_valid_construction(self):
        sm = ServiceMap(
            project_name="test",
            services=[
                ServiceDefinition(
                    name="svc-a",
                    domain="core",
                    description="A",
                    stack=ServiceStack(language="python"),
                    estimated_loc=1000,
                )
            ],
            prd_hash="abc123",
        )
        assert sm.project_name == "test"

    def test_services_min_length(self):
        with pytest.raises(ValidationError):
            ServiceMap(project_name="test", services=[], prd_hash="abc")

    def test_optional_build_cycle_id(self):
        sm = ServiceMap(
            project_name="p",
            services=[
                ServiceDefinition(
                    name="s",
                    domain="d",
                    description="d",
                    stack=ServiceStack(language="go"),
                    estimated_loc=500,
                )
            ],
            prd_hash="hash",
        )
        assert sm.build_cycle_id is None


class TestDecomposeRequest:
    def test_valid_construction(self):
        req = DecomposeRequest(prd_text="A" * 100)
        assert len(req.prd_text) == 100

    def test_prd_text_too_short(self):
        with pytest.raises(ValidationError):
            DecomposeRequest(prd_text="short")

    def test_prd_text_max_length(self):
        with pytest.raises(ValidationError):
            DecomposeRequest(prd_text="A" * 1_048_577)

    def test_serialization_roundtrip(self):
        req = DecomposeRequest(prd_text="Build a microservice system with users and orders")
        data = req.model_dump()
        restored = DecomposeRequest(**data)
        assert restored.prd_text == req.prd_text


class TestDecompositionRun:
    def test_valid_construction(self):
        run = DecompositionRun(prd_content_hash="abc123")
        assert run.status == "pending"
        assert run.service_map_id is None
        assert run.validation_issues == []
        assert run.id  # UUID should be generated

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            DecompositionRun(prd_content_hash="abc", status="invalid_status")

    def test_valid_statuses(self):
        for status in ["pending", "running", "completed", "failed", "review"]:
            run = DecompositionRun(prd_content_hash="hash", status=status)
            assert run.status == status

    def test_serialization_roundtrip(self):
        run = DecompositionRun(prd_content_hash="test_hash", status="running")
        data = run.model_dump()
        restored = DecompositionRun(**data)
        assert restored.status == "running"
        assert restored.id == run.id


# ---- Contract Models ----


class TestContractEntry:
    def test_valid_construction(self):
        entry = ContractEntry(
            type=ContractType.OPENAPI,
            version="1.0.0",
            service_name="user-service",
            spec={"openapi": "3.1.0"},
        )
        assert entry.spec_hash  # auto-computed
        assert entry.status == ContractStatus.DRAFT
        assert entry.id  # UUID generated

    def test_spec_hash_auto_computed(self):
        spec = {"openapi": "3.1.0", "info": {"title": "Test"}}
        entry = ContractEntry(
            type=ContractType.OPENAPI,
            version="1.0.0",
            service_name="svc",
            spec=spec,
        )
        import hashlib
        expected_hash = hashlib.sha256(
            json.dumps(spec, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert entry.spec_hash == expected_hash

    def test_invalid_version_pattern(self):
        with pytest.raises(ValidationError):
            ContractEntry(
                type=ContractType.OPENAPI,
                version="v1",
                service_name="svc",
                spec={},
            )

    def test_valid_semver_versions(self):
        for v in ["0.0.1", "1.0.0", "2.3.4", "10.20.30"]:
            entry = ContractEntry(
                type=ContractType.OPENAPI,
                version=v,
                service_name="svc",
                spec={"test": True},
            )
            assert entry.version == v

    def test_serialization_roundtrip(self):
        entry = ContractEntry(
            type=ContractType.ASYNCAPI,
            version="2.0.0",
            service_name="events",
            spec={"asyncapi": "3.0.0"},
        )
        data = entry.model_dump()
        restored = ContractEntry(**data)
        assert restored.service_name == entry.service_name
        assert restored.spec_hash == entry.spec_hash


class TestContractCreate:
    def test_valid_construction(self):
        cc = ContractCreate(
            service_name="svc",
            type=ContractType.OPENAPI,
            version="1.0.0",
            spec={"test": True},
        )
        assert cc.build_cycle_id is None

    def test_service_name_max_length(self):
        with pytest.raises(ValidationError):
            ContractCreate(
                service_name="x" * 101,
                type=ContractType.OPENAPI,
                version="1.0.0",
                spec={},
            )


class TestEndpointSpec:
    def test_valid_methods(self):
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            ep = EndpointSpec(path="/api/test", method=method)
            assert ep.method == method

    def test_invalid_method(self):
        with pytest.raises(ValidationError):
            EndpointSpec(path="/api/test", method="INVALID")


class TestOperationSpec:
    def test_valid_actions(self):
        for action in ["send", "receive"]:
            op = OperationSpec(name="op", action=action, channel_name="ch")
            assert op.action == action

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            OperationSpec(name="op", action="invalid", channel_name="ch")


class TestBreakingChange:
    def test_valid_severities(self):
        for severity in ["error", "warning", "info"]:
            bc = BreakingChange(
                change_type="removed", path="/users", severity=severity
            )
            assert bc.severity == severity

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            BreakingChange(change_type="removed", path="/users", severity="critical")

    def test_default_severity(self):
        bc = BreakingChange(change_type="removed", path="/users")
        assert bc.severity == "error"


class TestValidateRequest:
    def test_valid_construction(self):
        vr = ValidateRequest(spec={"openapi": "3.1.0"}, type=ContractType.OPENAPI)
        assert vr.type == ContractType.OPENAPI

    def test_serialization_roundtrip(self):
        vr = ValidateRequest(spec={"test": True}, type=ContractType.ASYNCAPI)
        data = vr.model_dump()
        restored = ValidateRequest(**data)
        assert restored.type == vr.type


class TestMarkRequest:
    def test_valid_construction(self):
        mr = MarkRequest(
            contract_id="abc-123",
            service_name="user-service",
            evidence_path="src/user/handler.py",
        )
        assert mr.contract_id == "abc-123"

    def test_serialization_roundtrip(self):
        mr = MarkRequest(
            contract_id="id1", service_name="svc", evidence_path="/path"
        )
        data = mr.model_dump()
        restored = MarkRequest(**data)
        assert restored == mr


class TestMarkResponse:
    def test_valid_construction(self):
        resp = MarkResponse(marked=True, total_implementations=3, all_implemented=False)
        assert resp.marked is True
        assert resp.total_implementations == 3


class TestUnimplementedContract:
    def test_valid_construction(self):
        uc = UnimplementedContract(
            id="c1", type="openapi", version="1.0.0",
            expected_service="user-svc", status="pending"
        )
        assert uc.expected_service == "user-svc"


class TestContractTestSuite:
    def test_valid_construction(self):
        cts = ContractTestSuite(
            contract_id="c1",
            test_code="def test_example(): pass",
            test_count=1,
        )
        assert cts.framework == "pytest"

    def test_valid_frameworks(self):
        for fw in ["pytest", "jest"]:
            cts = ContractTestSuite(
                contract_id="c1", framework=fw, test_code="code", test_count=0
            )
            assert cts.framework == fw

    def test_invalid_framework(self):
        with pytest.raises(ValidationError):
            ContractTestSuite(
                contract_id="c1", framework="mocha", test_code="code", test_count=0
            )

    def test_test_count_negative(self):
        with pytest.raises(ValidationError):
            ContractTestSuite(
                contract_id="c1", test_code="code", test_count=-1
            )


class TestValidationResult:
    def test_valid_defaults(self):
        vr = ValidationResult(valid=True)
        assert vr.errors == []
        assert vr.warnings == []


class TestContractListResponse:
    def test_valid_construction(self):
        clr = ContractListResponse(items=[], total=0, page=1, page_size=20)
        assert clr.total == 0


class TestComplianceResult:
    def test_valid_construction(self):
        cr = ComplianceResult(
            endpoint_path="/api/users",
            method="GET",
            compliant=True,
            violations=[],
        )
        assert cr.compliant is True

    def test_with_violations(self):
        cr = ComplianceResult(
            endpoint_path="/api/users",
            method="POST",
            compliant=False,
            violations=[
                ComplianceViolation(
                    field="name", expected="string", actual="integer"
                )
            ],
        )
        assert len(cr.violations) == 1


# ---- Codebase Models ----


class TestSymbolDefinition:
    def test_id_auto_generated(self):
        sd = SymbolDefinition(
            file_path="src/main.py",
            symbol_name="MyClass",
            kind=SymbolKind.CLASS,
            language=Language.PYTHON,
            line_start=1,
            line_end=10,
        )
        assert sd.id == "src/main.py::MyClass"

    def test_explicit_id_preserved(self):
        sd = SymbolDefinition(
            id="custom-id",
            file_path="src/main.py",
            symbol_name="MyClass",
            kind=SymbolKind.CLASS,
            language=Language.PYTHON,
            line_start=1,
            line_end=10,
        )
        assert sd.id == "custom-id"

    def test_line_start_minimum(self):
        with pytest.raises(ValidationError):
            SymbolDefinition(
                file_path="f.py",
                symbol_name="f",
                kind=SymbolKind.FUNCTION,
                language=Language.PYTHON,
                line_start=0,
                line_end=1,
            )

    def test_optional_defaults(self):
        sd = SymbolDefinition(
            file_path="f.py",
            symbol_name="f",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=1,
            line_end=1,
        )
        assert sd.service_name is None
        assert sd.signature is None
        assert sd.docstring is None
        assert sd.is_exported is True
        assert sd.parent_symbol is None

    def test_serialization_roundtrip(self):
        sd = SymbolDefinition(
            file_path="src/auth.py",
            symbol_name="login",
            kind=SymbolKind.FUNCTION,
            language=Language.PYTHON,
            line_start=5,
            line_end=15,
        )
        data = sd.model_dump()
        restored = SymbolDefinition(**data)
        assert restored.id == sd.id


class TestImportReference:
    def test_valid_construction(self):
        ir = ImportReference(
            source_file="a.py", target_file="b.py", line=1
        )
        assert ir.imported_names == []
        assert ir.is_relative is False

    def test_line_minimum(self):
        with pytest.raises(ValidationError):
            ImportReference(source_file="a.py", target_file="b.py", line=0)


class TestDependencyEdge:
    def test_valid_construction(self):
        de = DependencyEdge(
            source_symbol_id="a::X",
            target_symbol_id="b::Y",
            relation=DependencyRelation.IMPORTS,
            source_file="a.py",
            target_file="b.py",
        )
        assert de.line is None


class TestSemanticSearchResult:
    def test_score_bounds(self):
        ssr = SemanticSearchResult(
            chunk_id="c1",
            file_path="f.py",
            content="code",
            score=0.95,
            language="python",
            line_start=1,
            line_end=10,
        )
        assert ssr.score == 0.95

    def test_score_too_high(self):
        with pytest.raises(ValidationError):
            SemanticSearchResult(
                chunk_id="c1",
                file_path="f.py",
                content="code",
                score=1.5,
                language="python",
                line_start=1,
                line_end=10,
            )

    def test_score_too_low(self):
        with pytest.raises(ValidationError):
            SemanticSearchResult(
                chunk_id="c1",
                file_path="f.py",
                content="code",
                score=-0.1,
                language="python",
                line_start=1,
                line_end=10,
            )


class TestDeadCodeEntry:
    def test_valid_confidence_levels(self):
        for conf in ["high", "medium", "low"]:
            dce = DeadCodeEntry(
                symbol_name="unused",
                file_path="f.py",
                kind=SymbolKind.FUNCTION,
                line=10,
                confidence=conf,
            )
            assert dce.confidence == conf

    def test_invalid_confidence(self):
        with pytest.raises(ValidationError):
            DeadCodeEntry(
                symbol_name="unused",
                file_path="f.py",
                kind=SymbolKind.FUNCTION,
                line=10,
                confidence="uncertain",
            )

    def test_default_confidence(self):
        dce = DeadCodeEntry(
            symbol_name="unused",
            file_path="f.py",
            kind=SymbolKind.FUNCTION,
            line=10,
        )
        assert dce.confidence == "high"


class TestGraphAnalysis:
    def test_valid_construction(self):
        ga = GraphAnalysis(
            node_count=10,
            edge_count=20,
            is_dag=True,
            connected_components=2,
        )
        assert ga.circular_dependencies == []
        assert ga.top_files_by_pagerank == []
        assert ga.build_order is None

    def test_serialization_roundtrip(self):
        ga = GraphAnalysis(
            node_count=5,
            edge_count=8,
            is_dag=False,
            circular_dependencies=[["a", "b", "a"]],
            connected_components=1,
        )
        data = ga.model_dump()
        restored = GraphAnalysis(**data)
        assert restored.is_dag is False


class TestIndexStats:
    def test_valid_defaults(self):
        stats = IndexStats(
            total_files=0,
            total_symbols=0,
            total_edges=0,
            total_chunks=0,
        )
        assert stats.languages == {}
        assert stats.services == {}
        assert stats.last_indexed_at is None


class TestServiceInterface:
    def test_valid_defaults(self):
        si = ServiceInterface(service_name="auth")
        assert si.endpoints == []
        assert si.events_published == []
        assert si.exported_symbols == []


# ---- Common Models ----


class TestBuildCycle:
    def test_valid_construction(self):
        bc = BuildCycle(project_name="test-project")
        assert bc.status == "running"
        assert bc.services_planned == 0
        assert bc.total_cost_usd == 0.0
        assert bc.id  # UUID generated

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            BuildCycle(project_name="test", status="unknown")

    def test_valid_statuses(self):
        for status in ["running", "completed", "failed", "paused"]:
            bc = BuildCycle(project_name="test", status=status)
            assert bc.status == status

    def test_serialization_roundtrip(self):
        bc = BuildCycle(project_name="p", status="completed")
        data = bc.model_dump()
        restored = BuildCycle(**data)
        assert restored.status == "completed"
        assert restored.id == bc.id


class TestHealthStatus:
    def test_valid_construction(self):
        hs = HealthStatus(
            service_name="test",
            version="1.0.0",
            uptime_seconds=100.0,
        )
        assert hs.status == "healthy"
        assert hs.database == "connected"
        assert hs.details == {}

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            HealthStatus(
                status="broken",
                service_name="test",
                version="1.0.0",
                uptime_seconds=0.0,
            )

    def test_valid_statuses(self):
        for status in ["healthy", "degraded", "unhealthy"]:
            hs = HealthStatus(
                status=status,
                service_name="test",
                version="1.0.0",
                uptime_seconds=0.0,
            )
            assert hs.status == status

    def test_database_states(self):
        for db in ["connected", "disconnected"]:
            hs = HealthStatus(
                service_name="test",
                version="1.0.0",
                database=db,
                uptime_seconds=0.0,
            )
            assert hs.database == db


class TestArtifactRegistration:
    def test_valid_construction(self):
        ar = ArtifactRegistration(
            file_path="src/main.py",
            service_name="auth",
        )
        assert ar.build_cycle_id is None
        assert ar.registered_at is not None


# ---- Enum Tests ----


class TestEnums:
    def test_relationship_types(self):
        assert RelationshipType.OWNS.value == "OWNS"
        assert RelationshipType.REFERENCES.value == "REFERENCES"
        assert RelationshipType.TRIGGERS.value == "TRIGGERS"
        assert RelationshipType.EXTENDS.value == "EXTENDS"
        assert RelationshipType.DEPENDS_ON.value == "DEPENDS_ON"

    def test_contract_types(self):
        assert ContractType.OPENAPI.value == "openapi"
        assert ContractType.ASYNCAPI.value == "asyncapi"
        assert ContractType.JSON_SCHEMA.value == "json_schema"

    def test_contract_statuses(self):
        assert ContractStatus.ACTIVE.value == "active"
        assert ContractStatus.DEPRECATED.value == "deprecated"
        assert ContractStatus.DRAFT.value == "draft"

    def test_implementation_statuses(self):
        assert ImplementationStatus.VERIFIED.value == "verified"
        assert ImplementationStatus.PENDING.value == "pending"
        assert ImplementationStatus.FAILED.value == "failed"

    def test_symbol_kinds(self):
        kinds = [sk.value for sk in SymbolKind]
        assert "class" in kinds
        assert "function" in kinds
        assert "interface" in kinds
        assert "method" in kinds

    def test_languages(self):
        langs = [lang.value for lang in Language]
        assert set(langs) == {"python", "typescript", "csharp", "go"}

    def test_dependency_relations(self):
        rels = [r.value for r in DependencyRelation]
        assert set(rels) == {"imports", "calls", "inherits", "implements", "uses"}


# ---- Model re-export tests ----


class TestModelReExports:
    def test_import_from_shared_models(self):
        """Verify WIRE-001: all models importable from src.shared.models."""
        from src.shared.models import (
            ArtifactRegistration,
            BuildCycle,
            ContractEntry,
            DecomposeRequest,
            HealthStatus,
            ServiceDefinition,
            SymbolDefinition,
        )
        assert ServiceDefinition is not None
        assert ContractEntry is not None
        assert SymbolDefinition is not None
        assert HealthStatus is not None
        assert BuildCycle is not None
        assert DecomposeRequest is not None
        assert ArtifactRegistration is not None


# ---- now_iso() shared utility tests ----


class TestNowIso:
    """Tests for the now_iso() shared utility function."""

    def test_now_iso_returns_utc_iso_string(self):
        """now_iso() should return a valid UTC ISO-8601 string."""
        from src.shared.utils import now_iso
        result = now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None  # must be timezone-aware

    def test_now_iso_is_recent(self):
        """now_iso() should return a timestamp within the last few seconds."""
        from datetime import timezone
        from src.shared.utils import now_iso
        result = now_iso()
        parsed = datetime.fromisoformat(result)
        now = datetime.now(timezone.utc)
        delta = abs((now - parsed).total_seconds())
        assert delta < 5, f"now_iso() returned a timestamp {delta}s away from now"

    def test_now_iso_format(self):
        """now_iso() should return a string parseable by datetime.fromisoformat."""
        from src.shared.utils import now_iso
        result = now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO-8601 has 'T' separator
        # Should not raise
        datetime.fromisoformat(result)

    def test_now_iso_successive_calls_ordered(self):
        """Two successive calls to now_iso() should be chronologically ordered."""
        from src.shared.utils import now_iso
        t1 = now_iso()
        t2 = now_iso()
        assert t1 <= t2


# ---- BreakingChange.is_breaking model tests ----


class TestBreakingChangeIsBreaking:
    """Tests for the BreakingChange.is_breaking computed field."""

    def test_error_severity_computes_is_breaking_true(self):
        """Error severity should compute is_breaking=True."""
        bc = BreakingChange(change_type="removed", path="/users", severity="error")
        assert bc.is_breaking is True

    def test_warning_severity_computes_is_breaking_true(self):
        """Warning severity should compute is_breaking=True."""
        bc = BreakingChange(change_type="required_added", path="/users", severity="warning")
        assert bc.is_breaking is True

    def test_info_severity_computes_is_breaking_false(self):
        """Info severity should compute is_breaking=False."""
        bc = BreakingChange(change_type="added", path="/users", severity="info")
        assert bc.is_breaking is False

    def test_explicit_is_breaking_override(self):
        """Explicitly setting is_breaking should be respected."""
        bc = BreakingChange(
            change_type="custom", path="/test", severity="info", is_breaking=True
        )
        assert bc.is_breaking is True

    def test_is_breaking_default_without_severity(self):
        """Default severity is error, so is_breaking defaults to True."""
        bc = BreakingChange(change_type="removed", path="/users")
        assert bc.is_breaking is True


# ---- ContractTestSuite.id field tests ----


class TestContractTestSuiteId:
    """Tests for the ContractTestSuite.id auto-generated UUID field."""

    def test_suite_has_auto_id(self):
        """ContractTestSuite should have an auto-generated id."""
        suite = ContractTestSuite(
            contract_id="c1",
            test_code="def test_foo(): pass",
            test_count=1,
        )
        assert suite.id is not None
        assert len(suite.id) > 0

    def test_suite_id_is_uuid(self):
        """ContractTestSuite.id should be a valid UUID."""
        import uuid
        suite = ContractTestSuite(
            contract_id="c1",
            test_code="def test_foo(): pass",
            test_count=1,
        )
        parsed = uuid.UUID(suite.id)
        assert str(parsed) == suite.id

    def test_suite_ids_are_unique(self):
        """Two ContractTestSuites should have different IDs."""
        suite1 = ContractTestSuite(
            contract_id="c1", test_code="code1", test_count=1,
        )
        suite2 = ContractTestSuite(
            contract_id="c1", test_code="code2", test_count=1,
        )
        assert suite1.id != suite2.id

    def test_suite_include_negative_field(self):
        """ContractTestSuite should have include_negative field."""
        suite = ContractTestSuite(
            contract_id="c1", test_code="code", test_count=1, include_negative=True,
        )
        assert suite.include_negative is True
