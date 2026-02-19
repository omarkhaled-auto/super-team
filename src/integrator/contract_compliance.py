"""Contract compliance verification facade.

Composes :class:`SchemathesisRunner` and :class:`PactManager` into a
single entry-point (:class:`ContractComplianceVerifier`) for the
integration phase.  Callers MUST NOT instantiate the individual runners
directly; all access goes through the ``verify_all_services`` method of
this facade.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from src.build3_shared.models import ContractViolation, IntegrationReport
from src.integrator.pact_manager import PactManager
from src.integrator.schemathesis_runner import SchemathesisRunner

logger = logging.getLogger(__name__)


class ContractComplianceVerifier:
    """Facade that orchestrates contract compliance verification.

    Internally composes a :class:`SchemathesisRunner` (property-based
    OpenAPI testing) and a :class:`PactManager` (consumer-driven contract
    verification) and runs both in parallel for each service.

    Parameters
    ----------
    contract_registry_path:
        Path to the contract registry directory.
    services:
        Mapping of service_name to base_url.
    """

    def __init__(
        self,
        contract_registry_path: Path,
        services: dict[str, str],
        timeout: float = 30.0,
    ) -> None:
        self._contract_registry_path = Path(contract_registry_path)
        self._services = services
        self._schemathesis = SchemathesisRunner(timeout=timeout)
        pact_dir = self._contract_registry_path / "pacts"
        self._pact = PactManager(pact_dir=pact_dir)
        self._last_violations: list[ContractViolation] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_schemathesis_tests(
        self,
        service_name: str,
    ) -> list[ContractViolation]:
        """Run schemathesis tests against a single service.

        Loads the OpenAPI spec from the contract registry and runs
        SchemathesisRunner against the live service.

        Args:
            service_name: Name of the service to test.

        Returns:
            List of contract violations found.
        """
        base_url = self._services.get(service_name, "")
        if not base_url:
            logger.warning("No URL for service '%s'", service_name)
            return []

        # Look for OpenAPI spec in registry
        spec_path = self._contract_registry_path / f"{service_name}.json"
        if spec_path.exists():
            openapi_url = str(spec_path)
        else:
            openapi_url = f"{base_url}/openapi.json"

        return await self._schemathesis.run_against_service(
            service_name, openapi_url, base_url,
        )

    async def run_pact_verification(
        self,
        provider_name: str,
    ) -> list[ContractViolation]:
        """Run Pact verification for a single provider.

        Args:
            provider_name: Name of the provider to verify.

        Returns:
            List of contract violations found.
        """
        base_url = self._services.get(provider_name, "")
        if not base_url:
            logger.warning("No URL for provider '%s'", provider_name)
            return []

        pacts_by_provider = await self._pact.load_pacts()
        pact_files = pacts_by_provider.get(provider_name, [])
        if not pact_files:
            logger.info("No pact files for provider '%s'", provider_name)
            return []

        return await self._pact.verify_provider(
            provider_name, base_url, pact_files,
        )

    def generate_compliance_report(self) -> str:
        """Generate a markdown compliance report.

        Uses the violations from the last ``verify_all_services`` call
        to produce a per-service and per-endpoint markdown report.

        Returns:
            Markdown string with compliance results.
        """
        lines: list[str] = [
            "# Contract Compliance Report",
            "",
        ]

        if not self._last_violations:
            lines.append("No violations found. All services are compliant.")
            return "\n".join(lines)

        # Group by service
        by_service: dict[str, list[ContractViolation]] = {}
        for v in self._last_violations:
            by_service.setdefault(v.service, []).append(v)

        lines.append(f"**Total violations:** {len(self._last_violations)}")
        lines.append("")

        for svc_name in sorted(by_service.keys()):
            svc_violations = by_service[svc_name]
            lines.append(f"## {svc_name}")
            lines.append("")
            for v in svc_violations:
                lines.append(
                    f"- **{v.code}** `{v.endpoint}`: {v.message} "
                    f"(severity: {v.severity})"
                )
            lines.append("")

        return "\n".join(lines)

    async def verify_all_services(
        self,
        services: list[dict[str, Any]],
        service_urls: dict[str, str],
        contract_registry_path: str | Path,
    ) -> IntegrationReport:
        """Run full contract compliance verification across all services.

        For each service that has an ``openapi_url`` field and a running
        URL in *service_urls*, the facade runs Schemathesis positive tests,
        negative tests, and Pact provider verification **in parallel**.

        Parameters
        ----------
        services:
            List of service dicts.  Each should have at least
            ``service_id``, and optionally ``openapi_url``.
        service_urls:
            Mapping of ``service_id`` → base URL where the service is
            reachable.
        contract_registry_path:
            Path to the directory containing contract / pact files.

        Returns
        -------
        IntegrationReport
            Aggregated report with violation list, test counts, and
            overall health.
        """
        all_violations: list[ContractViolation] = []
        contract_tests_total = 0
        contract_tests_passed = 0

        registry_path = Path(contract_registry_path)

        # ---- Load Pact files grouped by provider -------------------------
        pacts_by_provider: dict[str, list[Path]] = {}
        if self._pact.pact_dir and Path(self._pact.pact_dir).is_dir():
            pacts_by_provider = await self._pact.load_pacts()

        # ---- Per-service verification ------------------------------------
        tasks: list[asyncio.Task[list[ContractViolation]]] = []
        task_labels: list[str] = []

        for svc in services:
            service_id = svc.get("service_id", "")
            if not service_id:
                continue

            base_url = service_urls.get(service_id, "")
            if not base_url:
                logger.warning(
                    "No URL for service '%s'; skipping compliance checks",
                    service_id,
                )
                continue

            openapi_url = svc.get("openapi_url", "")

            # -- Schemathesis positive tests --------------------------------
            if openapi_url:
                tasks.append(
                    asyncio.create_task(
                        self._schemathesis.run_against_service(
                            service_id, openapi_url, base_url,
                        )
                    )
                )
                task_labels.append(f"schemathesis-positive:{service_id}")
                contract_tests_total += 1

            # -- Schemathesis negative tests --------------------------------
            if openapi_url:
                tasks.append(
                    asyncio.create_task(
                        self._schemathesis.run_negative_tests(
                            service_id, openapi_url, base_url,
                        )
                    )
                )
                task_labels.append(f"schemathesis-negative:{service_id}")
                contract_tests_total += 1

            # -- Pact provider verification ---------------------------------
            pact_files = pacts_by_provider.get(service_id, [])
            if pact_files:
                tasks.append(
                    asyncio.create_task(
                        self._pact.verify_provider(
                            service_id, base_url, pact_files,
                        )
                    )
                )
                task_labels.append(f"pact:{service_id}")
                contract_tests_total += 1

        # ---- Run all tasks in parallel -----------------------------------
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for label, result in zip(task_labels, results):
                if isinstance(result, BaseException):
                    logger.error(
                        "Task '%s' raised an exception: %s", label, result,
                    )
                    all_violations.append(
                        ContractViolation(
                            code="INTERNAL-001",
                            severity="error",
                            service=label.split(":")[-1] if ":" in label else "",
                            endpoint="*",
                            message=f"Verification task failed: {result}",
                        )
                    )
                elif isinstance(result, list):
                    if not result:
                        # No violations -- the test passed
                        contract_tests_passed += 1
                    all_violations.extend(result)
                else:
                    # Unexpected result type
                    contract_tests_passed += 1

        # ---- Build IntegrationReport -------------------------------------
        services_deployed = len(service_urls)
        services_healthy = len(
            [s for s in services if s.get("service_id") in service_urls]
        )

        overall_health = self._determine_health(
            all_violations, contract_tests_passed, contract_tests_total,
        )

        report = IntegrationReport(
            services_deployed=services_deployed,
            services_healthy=services_healthy,
            contract_tests_passed=contract_tests_passed,
            contract_tests_total=contract_tests_total,
            violations=all_violations,
            overall_health=overall_health,
        )

        # Store violations for generate_compliance_report()
        self._last_violations = all_violations

        logger.info(
            "Contract compliance complete: %d violations, health=%s",
            len(all_violations),
            overall_health,
        )

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_health(
        violations: list[ContractViolation],
        passed: int,
        total: int,
    ) -> str:
        """Compute overall health string based on results.

        Returns one of: ``"passed"``, ``"partial"``, ``"failed"``,
        ``"unknown"``.
        """
        if total == 0:
            return "unknown"

        has_errors = any(
            v.severity in ("error", "critical") for v in violations
        )

        if not violations:
            return "passed"
        if has_errors and passed == 0:
            return "failed"
        if has_errors:
            return "partial"
        # Only warnings / info
        return "passed"
