"""Pact-based contract compliance verification.

Uses pact-python (v3 API) to verify that provider services conform to
consumer-driven contracts (pact files).  All pact-python imports are
lazy so the rest of the system works even when pact-python is not
installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from src.build3_shared.models import ContractViolation

logger = logging.getLogger(__name__)


class PactManager:
    """Manages loading, grouping, and verifying Pact contract files."""

    def __init__(self, pact_dir: Path) -> None:
        self.pact_dir = pact_dir
        self._pact_available: bool | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_pact_available(self) -> bool:
        """Return *True* if pact-python v3 is importable."""
        if self._pact_available is not None:
            return self._pact_available
        try:
            from pact.v3.verifier import Verifier  # noqa: F401

            self._pact_available = True
        except Exception:
            self._pact_available = False
            logger.warning(
                "pact-python is not installed or not importable; "
                "Pact verification will be unavailable"
            )
        return self._pact_available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load_pacts(self) -> dict[str, list[Path]]:
        """Load pact files from *self.pact_dir* and group them by provider name.

        Each JSON file is expected to contain a top-level ``provider``
        object with a ``name`` field.  Files that cannot be parsed or
        lack the expected structure are logged and skipped.

        Returns:
            Mapping of provider name to the list of pact file paths for
            that provider.
        """
        pact_path = Path(self.pact_dir)
        if not pact_path.is_dir():
            logger.warning("Pact directory does not exist: %s", pact_path)
            return {}

        grouped: dict[str, list[Path]] = {}

        for json_file in sorted(pact_path.glob("*.json")):
            try:
                raw = await asyncio.to_thread(json_file.read_text, encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable pact file %s: %s", json_file, exc)
                continue

            provider = data.get("provider", {})
            provider_name: str = provider.get("name", "") if isinstance(provider, dict) else ""
            if not provider_name:
                logger.warning(
                    "Pact file %s missing provider.name; skipping", json_file
                )
                continue

            grouped.setdefault(provider_name, []).append(json_file)
            logger.debug(
                "Loaded pact file %s for provider '%s'", json_file.name, provider_name
            )

        logger.info(
            "Loaded %d pact file(s) across %d provider(s) from %s",
            sum(len(v) for v in grouped.values()),
            len(grouped),
            pact_path,
        )
        return grouped

    async def verify_provider(
        self,
        provider_name: str,
        provider_url: str,
        pact_files: list[str | Path],
    ) -> list[ContractViolation]:
        """Verify a provider against one or more consumer pact files.

        Uses ``pact.v3.verifier.Verifier`` with the lazy-import pattern
        so that pact-python need not be installed at import time.  The
        blocking ``verify()`` call is offloaded via
        :func:`asyncio.to_thread`.

        Args:
            provider_name: Name of the provider service being verified.
            provider_url: Base URL where the provider is running.
            pact_files: Paths to the pact JSON files for this provider.

        Returns:
            A (possibly empty) list of :class:`ContractViolation` instances.
        """
        if not pact_files:
            return []

        # ---- Lazy import ------------------------------------------------
        if not self._check_pact_available():
            return [
                ContractViolation(
                    code="PACT-001",
                    severity="error",
                    service=provider_name,
                    endpoint="*",
                    message=(
                        "pact-python is not installed; "
                        "cannot verify provider contracts"
                    ),
                )
            ]

        try:
            from pact.v3.verifier import Verifier
        except Exception as exc:
            return [
                ContractViolation(
                    code="PACT-001",
                    severity="error",
                    service=provider_name,
                    endpoint="*",
                    message=f"Failed to import pact-python verifier: {exc}",
                )
            ]

        # ---- Build verifier ---------------------------------------------
        violations: list[ContractViolation] = []
        try:
            verifier = Verifier(provider_name)
            verifier.add_transport(url=provider_url)

            for pact_file in pact_files:
                verifier.add_source(str(pact_file))

            # Register a default state handler for provider state setup/teardown.
            def _default_state_handler(state_name: str, action: str = "setup", **kwargs: Any) -> None:
                logger.info(
                    "Pact state handler: provider=%s state=%r action=%s",
                    provider_name, state_name, action,
                )

            verifier.state_handler(_default_state_handler, teardown=True)

            logger.info(
                "Verifying provider '%s' at %s against %d pact file(s)",
                provider_name,
                provider_url,
                len(pact_files),
            )

            # The blocking verify() call is offloaded to a thread so
            # we never block the async event loop.
            await asyncio.to_thread(verifier.verify)

            logger.info("Provider '%s' passed all pact verifications", provider_name)

        except Exception as exc:
            error_text = str(exc)
            logger.error(
                "Pact verification failed for provider '%s': %s",
                provider_name,
                error_text,
            )

            # Attempt to produce one violation per interaction from the
            # error message.  If we cannot parse it, emit a single
            # catch-all violation.
            interaction_violations = self._parse_verification_error(
                provider_name, error_text
            )
            if interaction_violations:
                violations.extend(interaction_violations)
            else:
                violations.append(
                    ContractViolation(
                        code="PACT-001",
                        severity="error",
                        service=provider_name,
                        endpoint="*",
                        message=f"Pact verification failed: {error_text}",
                    )
                )

        return violations

    def generate_pact_state_handler(self, provider_name: str = "") -> str:
        """Return Python source code for a FastAPI ``POST /_pact/state`` endpoint.

        The generated handler accepts provider-state change requests from
        the Pact verifier and logs them.  It can be pasted or exec'd
        into a FastAPI application.

        Returns:
            Python source code as a string.
        """
        return '''\
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

_logger = logging.getLogger("pact_state_handler")

app: FastAPI  # assumed to be defined by the host application


@app.post("/_pact/state")
async def pact_state_handler(request: Request) -> JSONResponse:
    """Handle Pact provider state setup / teardown requests.

    The Pact verifier POSTs JSON with ``consumer``, ``state``, and
    ``action`` (``setup`` or ``teardown``) fields.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body"},
        )

    consumer = body.get("consumer", "unknown")
    state = body.get("state", "")
    action = body.get("action", "setup")

    _logger.info(
        "Pact state request: consumer=%s state=%r action=%s",
        consumer,
        state,
        action,
    )

    # Add custom state setup / teardown logic here.
    # For example, seed or clean up test data based on the state
    # description.

    return JSONResponse(
        status_code=200,
        content={"result": state},
    )
'''

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_verification_error(
        provider_name: str,
        error_text: str,
    ) -> list[ContractViolation]:
        """Best-effort extraction of per-interaction failures.

        The pact-python verifier raises a generic exception whose string
        representation may contain details about which interactions
        failed.  This method attempts to split those into individual
        :class:`ContractViolation` items.

        If the error text mentions state-related keywords it uses
        ``PACT-002``; otherwise ``PACT-001``.
        """
        violations: list[ContractViolation] = []

        # Split on common delimiters that pact-python uses
        lines = error_text.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("Traceback") or line.startswith("File "):
                continue

            # Determine violation code
            state_keywords = {"state", "setup", "setUp", "provider state"}
            code = "PACT-002" if any(kw in line.lower() for kw in state_keywords) else "PACT-001"

            violations.append(
                ContractViolation(
                    code=code,
                    severity="error",
                    service=provider_name,
                    endpoint="*",
                    message=line,
                )
            )

        return violations
