"""Shared data models for Build 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ServiceStatus(str, Enum):
    """Status of a service during the build pipeline."""
    PENDING = "pending"
    BUILDING = "building"
    BUILT = "built"
    DEPLOYING = "deploying"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    FAILED = "failed"


class QualityLevel(str, Enum):
    """Quality gate layer identifiers."""
    LAYER1_SERVICE = "layer1_service"
    LAYER2_CONTRACT = "layer2_contract"
    LAYER3_SYSTEM = "layer3_system"
    LAYER4_ADVERSARIAL = "layer4_adversarial"


class GateVerdict(str, Enum):
    """Verdict from a quality gate layer or overall."""
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


@dataclass
class ServiceInfo:
    """Metadata for a service managed by the pipeline."""
    service_id: str
    domain: str
    stack: dict[str, str] = field(default_factory=dict)
    estimated_loc: int = 0
    docker_image: str = ""
    health_endpoint: str = "/health"
    port: int = 8080
    status: ServiceStatus = ServiceStatus.PENDING
    build_cost: float = 0.0
    build_dir: str = ""


@dataclass
class BuilderResult:
    """Result from a single builder execution."""
    system_id: str
    service_id: str
    success: bool = False
    cost: float = 0.0
    error: str = ""
    output_dir: str = ""
    test_passed: int = 0
    test_total: int = 0
    convergence_ratio: float = 0.0
    artifacts: list[str] = field(default_factory=list)


@dataclass
class ContractViolation:
    """A violation found during contract compliance verification."""
    code: str
    severity: str
    service: str
    endpoint: str
    message: str
    expected: str = ""
    actual: str = ""
    file_path: str = ""


@dataclass
class ScanViolation:
    """A violation found during quality gate scanning."""
    code: str
    severity: str
    category: str
    file_path: str = ""
    line: int = 0
    service: str = ""
    message: str = ""


@dataclass
class LayerResult:
    """Result from a single quality gate layer."""
    layer: QualityLevel
    verdict: GateVerdict = GateVerdict.SKIPPED
    violations: list[ScanViolation] = field(default_factory=list)
    contract_violations: list[ContractViolation] = field(default_factory=list)
    total_checks: int = 0
    passed_checks: int = 0
    duration_seconds: float = 0.0


@dataclass
class QualityGateReport:
    """Full quality gate report across all layers."""
    layers: dict[str, LayerResult] = field(default_factory=dict)
    overall_verdict: GateVerdict = GateVerdict.SKIPPED
    fix_attempts: int = 0
    max_fix_attempts: int = 3
    total_violations: int = 0
    blocking_violations: int = 0


@dataclass
class IntegrationReport:
    """Report from integration testing phase."""
    services_deployed: int = 0
    services_healthy: int = 0
    contract_tests_passed: int = 0
    contract_tests_total: int = 0
    integration_tests_passed: int = 0
    integration_tests_total: int = 0
    data_flow_tests_passed: int = 0
    data_flow_tests_total: int = 0
    boundary_tests_passed: int = 0
    boundary_tests_total: int = 0
    violations: list[ContractViolation] = field(default_factory=list)
    overall_health: str = "unknown"
