"""Tests for AdversarialScanner and Layer4Scanner (TEST-026).

Covers:
    - ADV-001: Dead event handlers (2 tests)
    - ADV-002: Dead contracts (2 tests)
    - ADV-003: Orphan services (1 test)
    - ADV-004: Naming inconsistency / camelCase (2 tests)
    - ADV-005: Missing error handling / bare except (2 tests)
    - ADV-006: Potential race conditions (2 tests)
    - Empty directory (1 test)
    - Layer4Scanner verdict always PASSED (2 tests)
    - Severity constraints (1 test)

Total: 15 test cases.

Run with:
    pytest tests/build3/test_adversarial.py -v
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from src.build3_shared.models import GateVerdict
from src.quality_gate.adversarial_patterns import AdversarialScanner
from src.quality_gate.layer4_adversarial import Layer4Scanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _write_openapi_yaml(path: Path) -> None:
    """Write a minimal OpenAPI 3.0 YAML spec to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent("""\
            openapi: "3.0.0"
            info:
              title: Test API
              version: "1.0.0"
            paths:
              /api/items:
                get:
                  summary: List items
                  responses:
                    "200":
                      description: OK
        """),
        encoding="utf-8",
    )


def _write_openapi_json(path: Path) -> None:
    """Write a minimal OpenAPI 3.0 JSON spec to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/api/items": {
                "get": {
                    "summary": "List items",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    path.write_text(json.dumps(spec), encoding="utf-8")


# ===========================================================================
# ADV-001: Dead event handlers
# ===========================================================================


class TestADV001DeadEventHandlers:
    """ADV-001: Detect event handlers decorated but never referenced."""

    async def test_dead_handler_detected(self, tmp_path: Path) -> None:
        """A decorated event handler that is never referenced elsewhere
        should produce an ADV-001 violation."""
        _write(
            tmp_path / "handlers.py",
            """\
            from events import event_handler

            @event_handler("user.created")
            def on_user_created(event):
                print("User created:", event)
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv001 = [v for v in violations if v.code == "ADV-001"]
        assert len(adv001) >= 1
        assert "on_user_created" in adv001[0].message

    async def test_referenced_handler_not_flagged(self, tmp_path: Path) -> None:
        """An event handler that IS referenced elsewhere should NOT be
        flagged as dead."""
        _write(
            tmp_path / "handlers.py",
            """\
            from events import event_handler

            @event_handler("order.placed")
            def on_order_placed(event):
                print("Order placed:", event)
            """,
        )
        # Another file references the handler by name
        _write(
            tmp_path / "wiring.py",
            """\
            from handlers import on_order_placed

            bus.register(on_order_placed)
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv001 = [v for v in violations if v.code == "ADV-001"]
        assert len(adv001) == 0


# ===========================================================================
# ADV-002: Dead contracts
# ===========================================================================


class TestADV002DeadContracts:
    """ADV-002: Detect OpenAPI/AsyncAPI specs not referenced by code."""

    async def test_unreferenced_contract_detected(self, tmp_path: Path) -> None:
        """An OpenAPI YAML file that is never mentioned in any Python
        source should produce an ADV-002 violation."""
        _write_openapi_yaml(tmp_path / "specs" / "orphan_api.yaml")

        # A Python file that does NOT reference the contract
        _write(
            tmp_path / "app.py",
            """\
            def main():
                print("Hello, world!")
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv002 = [v for v in violations if v.code == "ADV-002"]
        assert len(adv002) >= 1
        assert "orphan_api.yaml" in adv002[0].message

    async def test_referenced_contract_not_flagged(self, tmp_path: Path) -> None:
        """An OpenAPI spec whose filename appears in Python source
        should NOT be flagged."""
        _write_openapi_json(tmp_path / "contracts" / "user_api.json")

        _write(
            tmp_path / "loader.py",
            """\
            import json
            from pathlib import Path

            spec = json.loads(Path("contracts/user_api.json").read_text())
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv002 = [v for v in violations if v.code == "ADV-002"]
        assert len(adv002) == 0


# ===========================================================================
# ADV-003: Orphan services
# ===========================================================================


class TestADV003OrphanServices:
    """ADV-003: Detect service directories with no cross-service references."""

    async def test_orphan_service_detected(self, tmp_path: Path) -> None:
        """A service directory that neither imports from nor is imported
        by any other service should produce an ADV-003 violation."""
        # Service A -- standalone, no references to service_b
        svc_a = tmp_path / "service_a"
        _write(
            svc_a / "main.py",
            """\
            def run():
                print("Service A running")
            """,
        )

        # Service B -- standalone, no references to service_a
        svc_b = tmp_path / "service_b"
        _write(
            svc_b / "main.py",
            """\
            def run():
                print("Service B running")
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv003 = [v for v in violations if v.code == "ADV-003"]
        # Both services are orphans -- at least 2 violations
        assert len(adv003) >= 2
        flagged_dirs = {v.message for v in adv003}
        assert any("service_a" in m for m in flagged_dirs)
        assert any("service_b" in m for m in flagged_dirs)


# ===========================================================================
# ADV-004: Naming inconsistency (camelCase in Python)
# ===========================================================================


class TestADV004NamingInconsistency:
    """ADV-004: Detect camelCase function/variable names in Python files."""

    async def test_camel_case_function_detected(self, tmp_path: Path) -> None:
        """A Python function using camelCase should produce an ADV-004
        violation."""
        _write(
            tmp_path / "utils.py",
            """\
            def getUserName(user_id):
                return f"user_{user_id}"

            def processData(raw):
                return raw.strip()
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv004 = [v for v in violations if v.code == "ADV-004"]
        assert len(adv004) >= 1
        names_flagged = [v.message for v in adv004]
        assert any("getUserName" in m for m in names_flagged)

    async def test_snake_case_not_flagged(self, tmp_path: Path) -> None:
        """Standard snake_case names should NOT trigger ADV-004."""
        _write(
            tmp_path / "clean.py",
            """\
            def get_user_name(user_id):
                return f"user_{user_id}"

            def process_data(raw):
                return raw.strip()

            total_count = 0
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv004 = [v for v in violations if v.code == "ADV-004"]
        assert len(adv004) == 0


# ===========================================================================
# ADV-005: Missing error handling (bare except)
# ===========================================================================


class TestADV005MissingErrorHandling:
    """ADV-005: Detect bare except: and overly broad exception handling."""

    async def test_bare_except_detected(self, tmp_path: Path) -> None:
        """A bare ``except:`` clause should produce an ADV-005 violation."""
        _write(
            tmp_path / "risky.py",
            """\
            def do_work():
                try:
                    result = 1 / 0
                except:
                    pass
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv005 = [v for v in violations if v.code == "ADV-005"]
        assert len(adv005) >= 1
        assert any("Bare" in v.message or "bare" in v.message.lower() for v in adv005)

    async def test_specific_exception_not_flagged(self, tmp_path: Path) -> None:
        """Catching a specific exception (e.g. ValueError) should NOT
        trigger ADV-005."""
        _write(
            tmp_path / "safe.py",
            """\
            def parse_int(value):
                try:
                    return int(value)
                except ValueError:
                    return None

            def read_file(path):
                try:
                    with open(path) as f:
                        return f.read()
                except FileNotFoundError:
                    return ""
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv005 = [v for v in violations if v.code == "ADV-005"]
        assert len(adv005) == 0


# ===========================================================================
# ADV-006: Potential race conditions
# ===========================================================================


class TestADV006PotentialRaceConditions:
    """ADV-006: Detect global mutable state modified without locking."""

    async def test_global_mutable_without_lock_detected(self, tmp_path: Path) -> None:
        """Module-level mutable state mutated inside a function without
        any lock should produce an ADV-006 violation."""
        _write(
            tmp_path / "shared_state.py",
            """\
            CACHE: dict = {}

            def update_cache(key, value):
                global CACHE
                CACHE[key] = value

            def clear_cache():
                global CACHE
                CACHE.clear()
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv006 = [v for v in violations if v.code == "ADV-006"]
        assert len(adv006) >= 1
        assert any("CACHE" in v.message for v in adv006)

    async def test_locked_mutable_not_flagged(self, tmp_path: Path) -> None:
        """Module-level mutable state protected by a threading.Lock
        should NOT trigger ADV-006."""
        _write(
            tmp_path / "safe_state.py",
            """\
            import threading

            _lock = threading.Lock()
            REGISTRY: dict = {}

            def register(name, handler):
                with _lock:
                    REGISTRY[name] = handler
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        adv006 = [v for v in violations if v.code == "ADV-006"]
        assert len(adv006) == 0


# ===========================================================================
# Empty directory
# ===========================================================================


class TestEmptyDirectory:
    """Scanning an empty directory should return zero violations."""

    async def test_empty_directory_no_violations(self, tmp_path: Path) -> None:
        """An empty target directory produces no violations."""
        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        assert violations == []


# ===========================================================================
# Layer4Scanner -- verdict always PASSED
# ===========================================================================


class TestLayer4ScannerVerdict:
    """Layer4Scanner verdict must always be GateVerdict.PASSED."""

    async def test_verdict_passed_with_violations(self, tmp_path: Path) -> None:
        """Even when the underlying scanner finds violations, the
        Layer4Scanner verdict must be PASSED."""
        # Plant a file that triggers ADV-005 (bare except)
        _write(
            tmp_path / "bad_code.py",
            """\
            def broken():
                try:
                    x = 1 / 0
                except:
                    pass
            """,
        )

        layer4 = Layer4Scanner()
        result = await layer4.evaluate(tmp_path)

        # Must have found at least one violation
        assert len(result.violations) >= 1
        # Verdict must still be PASSED
        assert result.verdict == GateVerdict.PASSED

    async def test_verdict_passed_with_no_violations(self, tmp_path: Path) -> None:
        """A clean directory still results in PASSED."""
        layer4 = Layer4Scanner()
        result = await layer4.evaluate(tmp_path)

        assert result.violations == []
        assert result.verdict == GateVerdict.PASSED


# ===========================================================================
# Severity constraints
# ===========================================================================


class TestSeverityConstraints:
    """All adversarial violations must have severity 'warning' or 'info'."""

    async def test_all_violations_advisory_severity(self, tmp_path: Path) -> None:
        """Every violation produced by AdversarialScanner must carry a
        severity of 'warning' or 'info' -- never 'error'."""
        # Plant code that triggers multiple violation types at once:
        #   ADV-004 (camelCase), ADV-005 (bare except), ADV-006 (global mutable)
        _write(
            tmp_path / "multi_issue.py",
            """\
            ITEMS: list = []

            def processItem(item):
                global ITEMS
                try:
                    ITEMS.append(item)
                except:
                    pass
            """,
        )

        scanner = AdversarialScanner()
        violations = await scanner.scan(tmp_path)

        # Must have found at least one violation to make this test meaningful
        assert len(violations) >= 1, "Expected at least one violation for severity check"

        allowed_severities = {"warning", "info"}
        for v in violations:
            assert v.severity in allowed_severities, (
                f"Violation {v.code} has severity '{v.severity}' "
                f"but only {allowed_severities} are allowed"
            )
