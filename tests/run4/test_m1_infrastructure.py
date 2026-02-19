"""Milestone 1 — Test Infrastructure verification tests.

TEST-001 through TEST-007 validating Run4State, Run4Config, fixture
validity, mock MCP sessions, health polling, and regression detection.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from src.run4.config import Run4Config
from src.run4.fix_pass import detect_regressions, take_violation_snapshot
from src.run4.mcp_health import poll_until_healthy
from src.run4.state import Finding, Run4State
from tests.run4.conftest import MockTextContent, MockToolResult, make_mcp_result

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ===================================================================
# TEST-001: State save/load round-trip
# ===================================================================


class TestStateSaveLoadRoundtrip:
    """TEST-001 — Save Run4State, load it back, verify ALL fields."""

    def test_basic_roundtrip(self, tmp_path: Path) -> None:
        """All scalar, list, and dict fields survive save/load."""
        state = Run4State(
            run_id="test-run-001",
            current_phase="health_check",
            completed_phases=["init", "setup"],
            mcp_health={
                "architect": {"status": "healthy", "tools_count": 5},
                "contract-engine": {"status": "healthy", "tools_count": 3},
            },
            builder_results={
                "auth-service": {"success": True, "test_passed": 10, "test_total": 10},
            },
            fix_passes=[
                {"pass_number": 1, "fixed": 3, "remaining": 2},
            ],
            scores={"contracts": 0.95, "code_quality": 0.88},
            aggregate_score=0.91,
            traffic_light="GREEN",
            total_cost=12.50,
            phase_costs={"health_check": 1.20, "builders": 11.30},
        )

        # Add findings with nested data
        finding = Finding(
            finding_id="FINDING-001",
            priority="P0",
            system="Build 1",
            component="auth-service/login",
            evidence="POST /login returns 500 on valid credentials",
            recommendation="Fix database connection in login handler",
            resolution="OPEN",
            fix_pass_number=0,
            fix_verification="",
        )
        state.add_finding(finding)

        state_path = tmp_path / "run4_state.json"
        state.save(state_path)

        loaded = Run4State.load(state_path)
        assert loaded is not None

        # Verify all fields
        assert loaded.schema_version == 1
        assert loaded.run_id == "test-run-001"
        assert loaded.current_phase == "health_check"
        assert loaded.completed_phases == ["init", "setup"]
        assert loaded.mcp_health["architect"]["status"] == "healthy"
        assert loaded.mcp_health["architect"]["tools_count"] == 5
        assert loaded.mcp_health["contract-engine"]["status"] == "healthy"
        assert loaded.builder_results["auth-service"]["success"] is True
        assert loaded.builder_results["auth-service"]["test_passed"] == 10
        assert loaded.fix_passes[0]["fixed"] == 3
        assert loaded.scores["contracts"] == 0.95
        assert loaded.scores["code_quality"] == 0.88
        assert loaded.aggregate_score == 0.91
        assert loaded.traffic_light == "GREEN"
        assert loaded.total_cost == 12.50
        assert loaded.phase_costs["health_check"] == 1.20

        # Verify nested findings
        assert len(loaded.findings) == 1
        f = loaded.findings[0]
        assert f.finding_id == "FINDING-001"
        assert f.priority == "P0"
        assert f.system == "Build 1"
        assert f.component == "auth-service/login"
        assert f.evidence == "POST /login returns 500 on valid credentials"
        assert f.recommendation == "Fix database connection in login handler"
        assert f.resolution == "OPEN"
        assert f.fix_pass_number == 0
        assert f.fix_verification == ""
        assert f.created_at  # non-empty ISO timestamp

        # Verify timestamps survived round-trip
        assert loaded.started_at  # non-empty
        assert loaded.updated_at  # non-empty

    def test_finding_id_auto_increment(self, tmp_path: Path) -> None:
        """next_finding_id() auto-increments correctly."""
        state = Run4State()

        assert state.next_finding_id() == "FINDING-001"

        state.add_finding(Finding(priority="P1", system="Build 1", component="svc"))
        assert state.findings[0].finding_id == "FINDING-001"

        assert state.next_finding_id() == "FINDING-002"

        state.add_finding(Finding(finding_id="FINDING-005", priority="P2", system="Build 2", component="x"))
        assert state.next_finding_id() == "FINDING-006"


# ===================================================================
# TEST-002a: State load missing file
# ===================================================================


class TestStateLoadMissingFile:
    """TEST-002a — Run4State.load() returns None for missing file."""

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = Run4State.load(tmp_path / "nonexistent.json")
        assert result is None


# ===================================================================
# TEST-002b: State load corrupted JSON
# ===================================================================


class TestStateLoadCorruptedJson:
    """TEST-002b — Run4State.load() returns None for corrupted JSON."""

    def test_corrupted_json_returns_none(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupted.json"
        bad_file.write_text("{this is not valid json!!!", encoding="utf-8")
        result = Run4State.load(bad_file)
        assert result is None

    def test_non_object_json_returns_none(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "array.json"
        bad_file.write_text("[1, 2, 3]", encoding="utf-8")
        result = Run4State.load(bad_file)
        assert result is None

    def test_wrong_schema_version_returns_none(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "wrong_version.json"
        bad_file.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        result = Run4State.load(bad_file)
        assert result is None


# ===================================================================
# TEST-003: Config validates paths
# ===================================================================


class TestConfigValidatesPaths:
    """TEST-003 — Run4Config raises ValueError when build root missing."""

    def test_missing_build1_root(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="build1_project_root"):
            Run4Config(
                build1_project_root=tmp_path / "nonexistent",
                build2_project_root=tmp_path,
                build3_project_root=tmp_path,
            )

    def test_missing_build2_root(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="build2_project_root"):
            Run4Config(
                build1_project_root=tmp_path,
                build2_project_root=tmp_path / "nonexistent",
                build3_project_root=tmp_path,
            )

    def test_missing_build3_root(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="build3_project_root"):
            Run4Config(
                build1_project_root=tmp_path,
                build2_project_root=tmp_path,
                build3_project_root=tmp_path / "nonexistent",
            )

    def test_valid_paths_succeed(self, tmp_path: Path) -> None:
        b1 = tmp_path / "b1"
        b2 = tmp_path / "b2"
        b3 = tmp_path / "b3"
        b1.mkdir()
        b2.mkdir()
        b3.mkdir()
        config = Run4Config(
            build1_project_root=b1,
            build2_project_root=b2,
            build3_project_root=b3,
        )
        assert config.build1_project_root == b1
        assert config.build2_project_root == b2
        assert config.build3_project_root == b3

    def test_string_paths_converted_to_path(self, tmp_path: Path) -> None:
        b1 = tmp_path / "s1"
        b2 = tmp_path / "s2"
        b3 = tmp_path / "s3"
        b1.mkdir()
        b2.mkdir()
        b3.mkdir()
        config = Run4Config(
            build1_project_root=str(b1),
            build2_project_root=str(b2),
            build3_project_root=str(b3),
        )
        assert isinstance(config.build1_project_root, Path)
        assert isinstance(config.build2_project_root, Path)
        assert isinstance(config.build3_project_root, Path)

    def test_from_yaml_success(self, tmp_path: Path) -> None:
        """from_yaml() parses the run4: section correctly."""
        b1 = tmp_path / "y1"
        b2 = tmp_path / "y2"
        b3 = tmp_path / "y3"
        b1.mkdir()
        b2.mkdir()
        b3.mkdir()
        # Use PurePosixPath-style strings to avoid YAML backslash escaping
        run4_data = {
            "run4": {
                "build1_project_root": str(b1),
                "build2_project_root": str(b2),
                "build3_project_root": str(b3),
                "max_fix_passes": 10,
                "max_budget_usd": 50.0,
                "builder_depth": "quick",
            }
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(run4_data), encoding="utf-8")
        config = Run4Config.from_yaml(str(config_file))
        assert config.max_fix_passes == 10
        assert config.max_budget_usd == 50.0
        assert config.builder_depth == "quick"

    def test_from_yaml_missing_file(self, tmp_path: Path) -> None:
        """from_yaml() raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            Run4Config.from_yaml(str(tmp_path / "nope.yaml"))

    def test_from_yaml_no_run4_section(self, tmp_path: Path) -> None:
        """from_yaml() raises ValueError when run4: section is missing."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("other_section:\n  key: value\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No 'run4:' section"):
            Run4Config.from_yaml(str(config_file))


# ===================================================================
# TEST-004: Fixture YAML / JSON validity
# ===================================================================


class TestFixtureValidity:
    """TEST-004 — Validate OpenAPI, AsyncAPI, and Pact fixtures."""

    def test_openapi_auth_validates(self) -> None:
        """OpenAPI auth spec passes openapi-spec-validator."""
        from openapi_spec_validator import validate

        spec_path = _FIXTURES_DIR / "sample_openapi_auth.yaml"
        with open(spec_path, "r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        # validate() raises on failure, returns None on success
        validate(spec)

    def test_openapi_order_validates(self) -> None:
        """OpenAPI order spec passes openapi-spec-validator."""
        from openapi_spec_validator import validate

        spec_path = _FIXTURES_DIR / "sample_openapi_order.yaml"
        with open(spec_path, "r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
        validate(spec)

    def test_asyncapi_order_structure(self) -> None:
        """AsyncAPI order spec validates structurally against 3.0 schema."""
        spec_path = _FIXTURES_DIR / "sample_asyncapi_order.yaml"
        with open(spec_path, "r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)

        # Structural validation for AsyncAPI 3.0
        assert spec.get("asyncapi") == "3.0.0", "asyncapi version must be 3.0.0"
        assert "info" in spec, "info section required"
        assert "title" in spec["info"], "info.title required"
        assert "version" in spec["info"], "info.version required"
        assert "channels" in spec, "channels section required"
        assert "order/created" in spec["channels"], "order/created channel required"
        assert "order/shipped" in spec["channels"], "order/shipped channel required"
        assert "servers" in spec, "servers section required"
        assert "development" in spec["servers"], "development server required"

        # Validate message payloads have required fields
        messages = spec.get("components", {}).get("messages", {})
        assert "OrderCreated" in messages, "OrderCreated message required"
        assert "OrderShipped" in messages, "OrderShipped message required"

        created_payload = messages["OrderCreated"]["payload"]
        assert "order_id" in created_payload["properties"]
        assert "user_id" in created_payload["properties"]
        assert "items" in created_payload["properties"]
        assert "total" in created_payload["properties"]
        assert "created_at" in created_payload["properties"]

        shipped_payload = messages["OrderShipped"]["payload"]
        assert "order_id" in shipped_payload["properties"]
        assert "user_id" in shipped_payload["properties"]
        assert "shipped_at" in shipped_payload["properties"]
        assert "tracking_number" in shipped_payload["properties"]

    def test_pact_auth_validates(self) -> None:
        """Pact contract is valid JSON with required V4 structure."""
        pact_path = _FIXTURES_DIR / "sample_pact_auth.json"
        with open(pact_path, "r", encoding="utf-8") as fh:
            pact = json.load(fh)

        assert pact["consumer"]["name"] == "order-service"
        assert pact["provider"]["name"] == "auth-service"
        assert pact["metadata"]["pactSpecification"]["version"] == "4.0"
        assert len(pact["interactions"]) >= 1

        # Verify the login interaction
        login_interaction = pact["interactions"][0]
        assert login_interaction["request"]["method"] == "POST"
        assert login_interaction["request"]["path"] == "/login"
        assert login_interaction["response"]["status"] == 200

        body_content = login_interaction["response"]["body"]["content"]
        assert "access_token" in body_content
        assert "refresh_token" in body_content

    def test_sample_prd_content(self) -> None:
        """Sample PRD contains required service descriptions."""
        prd_path = _FIXTURES_DIR / "sample_prd.md"
        content = prd_path.read_text(encoding="utf-8")

        # Check all 3 services are described
        assert "auth-service" in content
        assert "order-service" in content
        assert "notification-service" in content

        # Check required endpoints
        assert "POST /register" in content
        assert "POST /login" in content
        assert "GET /users/me" in content
        assert "GET /health" in content
        assert "POST /orders" in content
        assert "GET /orders" in content
        assert "PUT /orders" in content
        assert "POST /notify" in content
        assert "GET /notifications" in content

        # Check data models
        assert "User" in content
        assert "Order" in content
        assert "Notification" in content

        # Check tech stack
        assert "FastAPI" in content
        assert "PostgreSQL" in content


# ===================================================================
# TEST-005: Mock MCP session usable
# ===================================================================


class TestMockMcpSession:
    """TEST-005 — mock_mcp_session fixture returns usable AsyncMock."""

    @pytest.mark.asyncio
    async def test_mock_session_has_methods(self, mock_mcp_session: AsyncMock) -> None:
        """The mock session has callable initialize, list_tools, call_tool."""
        assert hasattr(mock_mcp_session, "initialize")
        assert hasattr(mock_mcp_session, "list_tools")
        assert hasattr(mock_mcp_session, "call_tool")

    @pytest.mark.asyncio
    async def test_mock_initialize(self, mock_mcp_session: AsyncMock) -> None:
        """initialize() is callable and returns None."""
        result = await mock_mcp_session.initialize()
        assert result is None

    @pytest.mark.asyncio
    async def test_mock_list_tools(self, mock_mcp_session: AsyncMock) -> None:
        """list_tools() returns an object with a .tools list."""
        result = await mock_mcp_session.list_tools()
        assert hasattr(result, "tools")
        assert len(result.tools) == 2
        assert result.tools[0].name == "tool_a"
        assert result.tools[1].name == "tool_b"

    @pytest.mark.asyncio
    async def test_mock_call_tool(self, mock_mcp_session: AsyncMock) -> None:
        """call_tool() returns a MockToolResult."""
        result = await mock_mcp_session.call_tool("test_tool", {"arg": "value"})
        assert hasattr(result, "content")
        assert not result.isError

    def test_make_mcp_result_success(self) -> None:
        """make_mcp_result creates a valid success result."""
        result = make_mcp_result({"status": "ok", "data": [1, 2, 3]})
        assert isinstance(result, MockToolResult)
        assert not result.isError
        assert len(result.content) == 1
        parsed = json.loads(result.content[0].text)
        assert parsed["status"] == "ok"
        assert parsed["data"] == [1, 2, 3]

    def test_make_mcp_result_error(self) -> None:
        """make_mcp_result creates a valid error result."""
        result = make_mcp_result({"error": "not found"}, is_error=True)
        assert result.isError
        parsed = json.loads(result.content[0].text)
        assert parsed["error"] == "not found"


# ===================================================================
# TEST-006: poll_until_healthy success
# ===================================================================


class TestPollUntilHealthy:
    """TEST-006 — poll_until_healthy returns results for healthy mocks."""

    @pytest.mark.asyncio
    async def test_all_healthy(self) -> None:
        """poll_until_healthy succeeds when all services return 200."""
        import httpx
        from unittest.mock import patch, MagicMock

        # Create a mock async client that always returns 200
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            results = await poll_until_healthy(
                service_urls={
                    "auth": "http://localhost:8001/health",
                    "order": "http://localhost:8002/health",
                },
                timeout_s=10,
                interval_s=0.01,
                required_consecutive=2,
            )

        assert "auth" in results
        assert "order" in results
        assert results["auth"]["status"] == "healthy"
        assert results["order"]["status"] == "healthy"
        assert results["auth"]["consecutive_ok"] >= 2
        assert results["order"]["consecutive_ok"] >= 2

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        """poll_until_healthy raises TimeoutError when services stay down."""
        import httpx
        from unittest.mock import patch, MagicMock

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.run4.mcp_health.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(TimeoutError, match="not healthy"):
                await poll_until_healthy(
                    service_urls={"broken": "http://localhost:9999/health"},
                    timeout_s=0.05,
                    interval_s=0.01,
                    required_consecutive=2,
                )


# ===================================================================
# TEST-007: detect_regressions finds new violations
# ===================================================================


class TestDetectRegressions:
    """TEST-007 — detect_regressions correctly finds new violations."""

    def test_new_violation_detected(self) -> None:
        """New violations in 'after' that are not in 'before' are regressions."""
        before = {
            "SEC": ["src/auth.py", "src/login.py"],
            "CORS": ["src/api.py"],
        }
        after = {
            "SEC": ["src/auth.py", "src/login.py", "src/admin.py"],
            "CORS": ["src/api.py", "src/gateway.py"],
            "LOG": ["src/service.py"],
        }
        regressions = detect_regressions(before, after)

        # Should find src/admin.py (reappeared in SEC), src/gateway.py
        # (reappeared in CORS), and src/service.py (new in LOG)
        assert len(regressions) == 3
        scan_codes = [r["scan_code"] for r in regressions]
        file_paths = [r["file_path"] for r in regressions]
        types = [r["type"] for r in regressions]
        assert "SEC" in scan_codes
        assert "CORS" in scan_codes
        assert "LOG" in scan_codes
        assert "src/admin.py" in file_paths
        assert "src/gateway.py" in file_paths
        assert "src/service.py" in file_paths
        # SEC and CORS existed in before -> reappeared; LOG is brand new
        for r in regressions:
            if r["scan_code"] == "LOG":
                assert r["type"] == "new"
            else:
                assert r["type"] == "reappeared"

    def test_no_regressions(self) -> None:
        """No regressions when 'after' is a subset of 'before'."""
        before = {"SEC": ["src/auth.py", "src/login.py"]}
        after = {"SEC": ["src/auth.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 0

    def test_empty_before(self) -> None:
        """All violations in 'after' are regressions if 'before' is empty."""
        before: dict[str, list[str]] = {}
        after = {"SEC": ["src/auth.py"]}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 1
        assert regressions[0]["scan_code"] == "SEC"
        assert regressions[0]["file_path"] == "src/auth.py"
        assert regressions[0]["type"] == "new"

    def test_empty_after(self) -> None:
        """No regressions when 'after' is empty."""
        before = {"SEC": ["src/auth.py"]}
        after: dict[str, list[str]] = {}
        regressions = detect_regressions(before, after)
        assert len(regressions) == 0


class TestTakeViolationSnapshot:
    """TECH-008 — take_violation_snapshot creates {scan_code: [file_path, ...]}."""

    def test_flat_list_of_dicts(self) -> None:
        """Flat list of violation dicts is grouped by scan_code."""
        scan_results = [
            {"scan_code": "SEC-001", "file_path": "src/a.py"},
            {"scan_code": "SEC-001", "file_path": "src/b.py"},
            {"scan_code": "CORS-002", "file_path": "src/c.py"},
        ]
        snapshot = take_violation_snapshot(scan_results)
        assert "SEC-001" in snapshot
        assert "CORS-002" in snapshot
        assert snapshot["SEC-001"] == ["src/a.py", "src/b.py"]
        assert snapshot["CORS-002"] == ["src/c.py"]

    def test_pre_grouped_dict(self) -> None:
        """Already-grouped dict passes through as a snapshot."""
        scan_results = {
            "SEC-001": ["src/a.py", "src/b.py"],
            "CORS-002": ["src/c.py"],
        }
        snapshot = take_violation_snapshot(scan_results)
        assert snapshot["SEC-001"] == ["src/a.py", "src/b.py"]
        assert snapshot["CORS-002"] == ["src/c.py"]

    def test_dict_with_violations_key(self) -> None:
        """Dict with a 'violations' key wrapping a list."""
        scan_results = {
            "violations": [
                {"scan_code": "LOG-001", "file_path": "src/log.py"},
            ]
        }
        snapshot = take_violation_snapshot(scan_results)
        assert snapshot == {"LOG-001": ["src/log.py"]}

    def test_empty_input(self) -> None:
        """Empty input returns empty snapshot."""
        assert take_violation_snapshot({}) == {}
        assert take_violation_snapshot([]) == {}

    def test_snapshot_is_defensive_copy(self) -> None:
        """Pre-grouped dict values are copied, not aliased."""
        original_paths = ["src/a.py"]
        scan_results = {"SEC-001": original_paths}
        snapshot = take_violation_snapshot(scan_results)
        snapshot["SEC-001"].append("src/b.py")
        assert len(original_paths) == 1  # original not mutated
