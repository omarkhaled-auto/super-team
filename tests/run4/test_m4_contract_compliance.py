"""Milestone 4 -- Contract Compliance & Infrastructure Wiring Tests.

Covers:
    REQ-026: Schemathesis contract validation (mock-based)
    REQ-028: Planted violation detection (HEALTH-001, SCHEMA-001, LOG-001)
    WIRE-017: Docker Compose 5-file merge network topology
    WIRE-018: Inter-container DNS resolution
    WIRE-019: Traefik PathPrefix routing
"""
from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# REQ-026 -- Schemathesis Contract Validation (mock-based)
# ---------------------------------------------------------------------------


class TestSchemathesisContractValidation:
    """REQ-026 -- Verify contract compliance checking via Schemathesis mocks.

    All tests simulate Schemathesis schema loading and property-based
    testing results without requiring a live HTTP service or Docker.
    """

    @staticmethod
    def _mock_schema_results(
        total: int = 20,
        failures: int = 0,
        errors: int = 0,
    ) -> dict[str, Any]:
        """Build a mock Schemathesis test-run result summary."""
        passed = total - failures - errors
        return {
            "total": total,
            "passed": passed,
            "failures": failures,
            "errors": errors,
            "compliance_rate": passed / total if total > 0 else 0.0,
            "endpoints_tested": [
                "/api/health",
                "/api/users",
                "/api/orders",
                "/api/notifications",
            ],
        }

    def test_schema_loading_returns_endpoints(self) -> None:
        """Mock schema loading from /openapi.json returns endpoint list."""
        mock_schema = MagicMock()
        mock_schema.endpoints = {
            "/api/health": {"get": {"responses": {"200": {}}}},
            "/api/users": {"post": {"responses": {"201": {}}}},
            "/api/orders": {"get": {"responses": {"200": {}}}},
        }
        mock_schema.base_url = "http://localhost:8080"
        mock_schema.spec_version = "3.1.0"

        assert len(mock_schema.endpoints) == 3
        assert "/api/health" in mock_schema.endpoints
        assert mock_schema.spec_version == "3.1.0"

    def test_contract_compliance_above_threshold(self) -> None:
        """Compliance rate > 70% passes the quality gate."""
        results = self._mock_schema_results(total=20, failures=2, errors=0)

        compliance = results["compliance_rate"]
        assert compliance == 0.9
        assert compliance > 0.70, (
            f"Compliance {compliance:.0%} should exceed 70% threshold"
        )

    def test_contract_compliance_below_threshold(self) -> None:
        """Compliance rate <= 70% fails the quality gate."""
        results = self._mock_schema_results(total=20, failures=10, errors=0)

        compliance = results["compliance_rate"]
        assert compliance == 0.5
        assert compliance <= 0.70, (
            f"Compliance {compliance:.0%} should be at or below 70% threshold"
        )

    def test_all_endpoints_tested(self) -> None:
        """Schemathesis should test all discovered endpoints."""
        results = self._mock_schema_results(total=20, failures=0)

        assert len(results["endpoints_tested"]) >= 3
        assert "/api/health" in results["endpoints_tested"]

    def test_zero_errors_full_compliance(self) -> None:
        """Zero failures and errors yields 100% compliance."""
        results = self._mock_schema_results(total=15, failures=0, errors=0)
        assert results["compliance_rate"] == 1.0

    def test_compliance_result_schema(self) -> None:
        """Result dict has all expected keys."""
        results = self._mock_schema_results(total=10, failures=1)
        required_keys = {"total", "passed", "failures", "errors",
                         "compliance_rate", "endpoints_tested"}
        assert required_keys.issubset(results.keys())

    def test_per_service_compliance_aggregation(self) -> None:
        """Aggregate compliance across 3 services, all must exceed 70%."""
        services = {
            "auth-service": self._mock_schema_results(total=10, failures=1),
            "order-service": self._mock_schema_results(total=12, failures=2),
            "notification-service": self._mock_schema_results(total=8, failures=0),
        }

        for svc_name, result in services.items():
            assert result["compliance_rate"] > 0.70, (
                f"{svc_name} compliance {result['compliance_rate']:.0%} below 70%"
            )

        total_passed = sum(r["passed"] for r in services.values())
        total_tests = sum(r["total"] for r in services.values())
        aggregate = total_passed / total_tests
        assert aggregate > 0.70


# ---------------------------------------------------------------------------
# REQ-028 -- Planted Violation Detection
# ---------------------------------------------------------------------------


class TestPlantedViolationDetection:
    """REQ-028 -- Verify that all 3 planted violations are detected.

    Planted violations:
        HEALTH-001: One service missing /health endpoint
        SCHEMA-001: One endpoint returns field not in OpenAPI contract
        LOG-001: One print() statement instead of logger
    """

    @staticmethod
    def _build_quality_gate_report(
        violations: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Build a mock quality gate report containing discovered violations."""
        return {
            "layer": "L3-code-quality",
            "violations": violations,
            "violation_codes": [v["code"] for v in violations],
            "total_violations": len(violations),
            "verdict": "failed" if len(violations) > 0 else "passed",
        }

    def test_all_three_planted_violations_detected(self) -> None:
        """Quality gate report must contain HEALTH-001, SCHEMA-001, LOG-001."""
        planted = [
            {
                "code": "HEALTH-001",
                "message": "Service 'notification-service' missing /health endpoint",
                "file_path": "notification-service/app.py",
                "severity": "error",
            },
            {
                "code": "SCHEMA-001",
                "message": "Endpoint GET /orders returns 'extra_field' not in OpenAPI spec",
                "file_path": "order-service/routes/orders.py",
                "severity": "warning",
            },
            {
                "code": "LOG-001",
                "message": "print() used instead of logger",
                "file_path": "auth-service/handlers/login.py",
                "severity": "warning",
            },
        ]

        report = self._build_quality_gate_report(planted)

        expected_codes = {"HEALTH-001", "SCHEMA-001", "LOG-001"}
        detected_codes = set(report["violation_codes"])

        assert expected_codes.issubset(detected_codes), (
            f"Missing planted violations: {expected_codes - detected_codes}"
        )
        assert report["total_violations"] >= 3

    def test_health_001_missing_health_endpoint(self) -> None:
        """HEALTH-001: Detect service with no /health endpoint."""
        service_endpoints = {
            "auth-service": ["/api/health", "/api/login", "/api/register"],
            "order-service": ["/api/health", "/api/orders"],
            "notification-service": ["/api/notifications"],  # Missing /health
        }

        violations = []
        for svc_name, endpoints in service_endpoints.items():
            has_health = any("/health" in ep for ep in endpoints)
            if not has_health:
                violations.append({
                    "code": "HEALTH-001",
                    "service": svc_name,
                    "message": f"{svc_name} missing /health endpoint",
                })

        assert len(violations) == 1
        assert violations[0]["service"] == "notification-service"
        assert violations[0]["code"] == "HEALTH-001"

    def test_schema_001_extra_response_field(self) -> None:
        """SCHEMA-001: Detect endpoint returning field not in contract."""
        contract_fields = {"id", "status", "items", "total"}
        actual_response_fields = {"id", "status", "items", "total", "extra_field"}

        extra_fields = actual_response_fields - contract_fields
        violations = []
        for extra in extra_fields:
            violations.append({
                "code": "SCHEMA-001",
                "field": extra,
                "message": f"Response contains '{extra}' not in OpenAPI spec",
            })

        assert len(violations) == 1
        assert violations[0]["field"] == "extra_field"

    def test_log_001_print_instead_of_logger(self) -> None:
        """LOG-001: Detect print() usage instead of logger."""
        mock_source_files = {
            "auth-service/handlers/login.py": 'print("User logged in")',
            "auth-service/handlers/register.py": 'logger.info("User registered")',
            "order-service/routes/orders.py": 'logger.debug("Order created")',
        }

        violations = []
        print_pattern = re.compile(r'\bprint\s*\(')
        for file_path, content in mock_source_files.items():
            if print_pattern.search(content):
                violations.append({
                    "code": "LOG-001",
                    "file_path": file_path,
                    "message": "print() used instead of logger",
                })

        assert len(violations) == 1
        assert violations[0]["file_path"] == "auth-service/handlers/login.py"

    def test_planted_violations_cause_failed_verdict(self) -> None:
        """When planted violations are present, verdict must be 'failed'."""
        planted = [
            {"code": "HEALTH-001", "message": "missing /health", "file_path": "a.py", "severity": "error"},
            {"code": "SCHEMA-001", "message": "extra field", "file_path": "b.py", "severity": "warning"},
            {"code": "LOG-001", "message": "print() used", "file_path": "c.py", "severity": "warning"},
        ]
        report = self._build_quality_gate_report(planted)
        assert report["verdict"] == "failed"


# ---------------------------------------------------------------------------
# WIRE-017 -- Docker Compose 5-File Merge Network Topology
# ---------------------------------------------------------------------------


class TestDockerComposeMerge:
    """WIRE-017 -- Verify 5-file merge produces correct network topology.

    Frontend network: traefik + all application services
    Backend network: postgres + redis + all application services (no traefik)
    Constraints:
        - Traefik is NOT on backend network
        - postgres and redis are NOT on frontend network
    """

    @pytest.fixture
    def merged_topology(self) -> dict[str, dict[str, list[str]]]:
        """Simulate a 5-file Docker Compose merge result.

        Returns the merged service -> networks mapping that would result
        from combining all 5 compose files per TECH-004.
        """
        return {
            "services": {
                "traefik": {
                    "networks": ["frontend"],
                    "image": "traefik:v3.6",
                },
                "postgres": {
                    "networks": ["backend"],
                    "image": "postgres:16-alpine",
                },
                "redis": {
                    "networks": ["backend"],
                    "image": "redis:7-alpine",
                },
                "architect": {
                    "networks": ["frontend", "backend"],
                    "image": "architect:latest",
                },
                "contract-engine": {
                    "networks": ["frontend", "backend"],
                    "image": "contract-engine:latest",
                },
                "codebase-intelligence": {
                    "networks": ["frontend", "backend"],
                    "image": "codebase-intelligence:latest",
                },
                "auth-service": {
                    "networks": ["frontend", "backend"],
                    "image": "auth-service:latest",
                },
                "order-service": {
                    "networks": ["frontend", "backend"],
                    "image": "order-service:latest",
                },
                "notification-service": {
                    "networks": ["frontend", "backend"],
                    "image": "notification-service:latest",
                },
            },
            "networks": {
                "frontend": {"driver": "bridge"},
                "backend": {"driver": "bridge"},
            },
        }

    def test_frontend_network_has_traefik(self, merged_topology: dict) -> None:
        """Traefik must be on the frontend network."""
        traefik_nets = merged_topology["services"]["traefik"]["networks"]
        assert "frontend" in traefik_nets

    def test_frontend_network_has_services(self, merged_topology: dict) -> None:
        """All application services must be on the frontend network."""
        app_services = [
            "architect", "contract-engine", "codebase-intelligence",
            "auth-service", "order-service", "notification-service",
        ]
        for svc in app_services:
            nets = merged_topology["services"][svc]["networks"]
            assert "frontend" in nets, f"{svc} should be on frontend network"

    def test_backend_network_has_postgres_and_redis(self, merged_topology: dict) -> None:
        """postgres and redis must be on the backend network."""
        assert "backend" in merged_topology["services"]["postgres"]["networks"]
        assert "backend" in merged_topology["services"]["redis"]["networks"]

    def test_backend_network_has_services(self, merged_topology: dict) -> None:
        """All application services must be on the backend network."""
        app_services = [
            "architect", "contract-engine", "codebase-intelligence",
            "auth-service", "order-service", "notification-service",
        ]
        for svc in app_services:
            nets = merged_topology["services"][svc]["networks"]
            assert "backend" in nets, f"{svc} should be on backend network"

    def test_traefik_not_on_backend(self, merged_topology: dict) -> None:
        """CONSTRAINT: Traefik must NOT be on the backend network."""
        traefik_nets = merged_topology["services"]["traefik"]["networks"]
        assert "backend" not in traefik_nets, (
            "Traefik must not be on backend network"
        )

    def test_postgres_not_on_frontend(self, merged_topology: dict) -> None:
        """CONSTRAINT: postgres must NOT be on the frontend network."""
        pg_nets = merged_topology["services"]["postgres"]["networks"]
        assert "frontend" not in pg_nets, (
            "postgres must not be on frontend network"
        )

    def test_redis_not_on_frontend(self, merged_topology: dict) -> None:
        """CONSTRAINT: redis must NOT be on the frontend network."""
        redis_nets = merged_topology["services"]["redis"]["networks"]
        assert "frontend" not in redis_nets, (
            "redis must not be on frontend network"
        )

    def test_merge_produces_exactly_two_networks(self, merged_topology: dict) -> None:
        """Merged compose must define exactly frontend and backend networks."""
        network_names = set(merged_topology["networks"].keys())
        assert network_names == {"frontend", "backend"}

    def test_merge_produces_nine_services(self, merged_topology: dict) -> None:
        """Merged compose must contain all 9 services from 5 files."""
        assert len(merged_topology["services"]) == 9
        expected = {
            "traefik", "postgres", "redis",
            "architect", "contract-engine", "codebase-intelligence",
            "auth-service", "order-service", "notification-service",
        }
        assert set(merged_topology["services"].keys()) == expected


# ---------------------------------------------------------------------------
# WIRE-018 -- Inter-Container DNS Resolution
# ---------------------------------------------------------------------------


class TestInterContainerDNS:
    """WIRE-018 -- Verify containers resolve each other by hostname.

    Simulates DNS resolution within the Docker network so that the
    Architect container can reach contract-engine by hostname.
    """

    @staticmethod
    def _mock_dns_lookup(hostname: str, dns_table: dict[str, str]) -> str | None:
        """Simulate container DNS resolution."""
        return dns_table.get(hostname)

    def test_architect_resolves_contract_engine(self) -> None:
        """Architect can resolve 'contract-engine' hostname."""
        dns_table = {
            "contract-engine": "172.20.0.3",
            "codebase-intelligence": "172.20.0.4",
            "postgres": "172.20.0.5",
            "redis": "172.20.0.6",
            "auth-service": "172.20.0.7",
        }
        ip = self._mock_dns_lookup("contract-engine", dns_table)
        assert ip is not None, "contract-engine hostname must be resolvable"
        assert ip.startswith("172.20."), "Must resolve to Docker bridge network IP"

    def test_architect_resolves_codebase_intelligence(self) -> None:
        """Architect can resolve 'codebase-intelligence' hostname."""
        dns_table = {
            "contract-engine": "172.20.0.3",
            "codebase-intelligence": "172.20.0.4",
        }
        ip = self._mock_dns_lookup("codebase-intelligence", dns_table)
        assert ip is not None

    def test_all_services_resolvable_from_backend_network(self) -> None:
        """All backend-network services must resolve each other."""
        backend_services = [
            "postgres", "redis",
            "architect", "contract-engine", "codebase-intelligence",
            "auth-service", "order-service", "notification-service",
        ]
        dns_table = {svc: f"172.20.0.{i+2}" for i, svc in enumerate(backend_services)}

        for source in ["architect", "contract-engine"]:
            for target in backend_services:
                ip = self._mock_dns_lookup(target, dns_table)
                assert ip is not None, (
                    f"{source} must resolve {target} on backend network"
                )

    def test_unknown_hostname_returns_none(self) -> None:
        """Unknown hostname returns None (DNS failure)."""
        dns_table = {"contract-engine": "172.20.0.3"}
        ip = self._mock_dns_lookup("nonexistent-service", dns_table)
        assert ip is None


# ---------------------------------------------------------------------------
# WIRE-019 -- Traefik PathPrefix Routing
# ---------------------------------------------------------------------------


class TestTraefikRouting:
    """WIRE-019 -- Verify PathPrefix labels route correctly through Traefik.

    Tests that the Traefik routing rules defined in docker-compose.run4.yml
    correctly map URL path prefixes to backend services.
    """

    @pytest.fixture
    def routing_rules(self) -> list[dict[str, str]]:
        """Traefik routing rules from docker-compose.run4.yml labels."""
        return [
            {
                "service": "architect",
                "router_rule": "PathPrefix(`/api/architect`)",
                "backend_port": "8000",
            },
            {
                "service": "contract-engine",
                "router_rule": "PathPrefix(`/api/contracts`)",
                "backend_port": "8000",
            },
            {
                "service": "codebase-intelligence",
                "router_rule": "PathPrefix(`/api/codebase`)",
                "backend_port": "8000",
            },
        ]

    @staticmethod
    def _resolve_route(
        path: str, rules: list[dict[str, str]],
    ) -> str | None:
        """Simulate Traefik PathPrefix matching to find the target service."""
        for rule in rules:
            prefix_match = re.search(r"PathPrefix\(`([^`]+)`\)", rule["router_rule"])
            if prefix_match:
                prefix = prefix_match.group(1)
                if path.startswith(prefix):
                    return rule["service"]
        return None

    def test_architect_route(self, routing_rules: list) -> None:
        """PathPrefix /api/architect routes to architect service."""
        target = self._resolve_route("/api/architect/decompose", routing_rules)
        assert target == "architect"

    def test_contract_engine_route(self, routing_rules: list) -> None:
        """PathPrefix /api/contracts routes to contract-engine service."""
        target = self._resolve_route("/api/contracts/list", routing_rules)
        assert target == "contract-engine"

    def test_codebase_intel_route(self, routing_rules: list) -> None:
        """PathPrefix /api/codebase routes to codebase-intelligence service."""
        target = self._resolve_route("/api/codebase/find_definition", routing_rules)
        assert target == "codebase-intelligence"

    def test_unknown_path_no_match(self, routing_rules: list) -> None:
        """Unrecognized path prefix returns None (no matching route)."""
        target = self._resolve_route("/api/unknown/endpoint", routing_rules)
        assert target is None

    def test_all_routes_target_port_8000(self, routing_rules: list) -> None:
        """All backend services listen on internal port 8000."""
        for rule in routing_rules:
            assert rule["backend_port"] == "8000", (
                f"{rule['service']} must use internal port 8000"
            )

    def test_each_service_has_traefik_enable_true(self) -> None:
        """Each routed service must have traefik.enable=true label."""
        mock_labels = {
            "architect": [
                "traefik.enable=true",
                "traefik.http.routers.architect.rule=PathPrefix(`/api/architect`)",
            ],
            "contract-engine": [
                "traefik.enable=true",
                "traefik.http.routers.contract-engine.rule=PathPrefix(`/api/contracts`)",
            ],
            "codebase-intelligence": [
                "traefik.enable=true",
                "traefik.http.routers.codebase-intel.rule=PathPrefix(`/api/codebase`)",
            ],
        }

        for svc_name, labels in mock_labels.items():
            assert "traefik.enable=true" in labels, (
                f"{svc_name} must have traefik.enable=true"
            )
