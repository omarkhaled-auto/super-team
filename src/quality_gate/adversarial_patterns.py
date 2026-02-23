"""Adversarial pattern scanner for Build 3 quality gate (Layer 4).

Purely static analyser -- reads source files only. No network calls,
no subprocess invocations, no MCP interaction.  Satisfies the
``QualityScanner`` protocol.

Scan codes
----------
ADV-001  Dead event handlers
ADV-002  Dead contracts
ADV-003  Orphan services
ADV-004  Naming inconsistency
ADV-005  Missing error handling patterns
ADV-006  Potential race conditions
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from src.build3_shared.constants import ADVERSARIAL_SCAN_CODES
from src.build3_shared.models import ScanViolation

# ---------------------------------------------------------------------------
# Excluded directories (never walked)
# ---------------------------------------------------------------------------
EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"}
)

# ---------------------------------------------------------------------------
# Module-level compiled regex patterns
# ---------------------------------------------------------------------------

# ADV-001: event-handler decorator patterns
_RE_EVENT_HANDLER_DECORATOR: Final[re.Pattern[str]] = re.compile(
    r"@(?:event_handler|on_event|subscriber)\s*\(.*?\)\s*\n"
    r"(?:(?:async\s+)?def\s+(\w+))",
    re.MULTILINE,
)

# ADV-002: OpenAPI / contract file indicators inside YAML / JSON
_RE_OPENAPI_INDICATOR: Final[re.Pattern[str]] = re.compile(
    r"""(?:["']?openapi["']?\s*:\s*["']?\d|"""
    r"""["']?swagger["']?\s*:\s*["']?\d|"""
    r"""["']?asyncapi["']?\s*:\s*["']?\d)""",
    re.IGNORECASE,
)

# ADV-003: service entry-point filenames
_SERVICE_ENTRY_POINTS: Final[frozenset[str]] = frozenset(
    {"main.py", "app.py", "server.py", "service.py"}
)

# ADV-004: camelCase names (functions / variables) in Python source
_RE_CAMEL_CASE_DEF: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:async\s+)?def\s+([a-z]+[A-Z]\w*)\s*\(",
    re.MULTILINE,
)
_RE_CAMEL_CASE_ASSIGN: Final[re.Pattern[str]] = re.compile(
    r"^\s*([a-z]+[A-Z]\w*)\s*=\s*",
    re.MULTILINE,
)

# ADV-005: bare except / overly broad exception handling
_RE_BARE_EXCEPT: Final[re.Pattern[str]] = re.compile(
    r"^\s*except\s*:",
    re.MULTILINE,
)
_RE_BROAD_EXCEPT: Final[re.Pattern[str]] = re.compile(
    r"^\s*except\s+(Exception|BaseException)\s*(?:as\s+\w+)?\s*:",
    re.MULTILINE,
)
_RE_RERAISE: Final[re.Pattern[str]] = re.compile(
    r"^\s*raise\b",
    re.MULTILINE,
)

# ADV-006: module-level mutable state
_RE_MODULE_LEVEL_MUTABLE: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z_]\w*)\s*:\s*(?:list|dict|set|List|Dict|Set)\b.*=\s*"
    r"(?:\[|\{|dict\(|list\(|set\()",
    re.MULTILINE,
)
_RE_MODULE_LEVEL_MUTABLE_UNTYPED: Final[re.Pattern[str]] = re.compile(
    r"^([A-Z_][A-Z0-9_]*)\s*=\s*(?:\[\]|\{\}|dict\(\)|list\(\)|set\(\))",
    re.MULTILINE,
)
_RE_LOCK_USAGE: Final[re.Pattern[str]] = re.compile(
    r"(?:threading\.Lock|Lock\(\)|RLock\(\)|asyncio\.Lock)",
)
_RE_GLOBAL_KEYWORD: Final[re.Pattern[str]] = re.compile(
    r"^\s*global\s+(\w+)",
    re.MULTILINE,
)

# Generic helpers
_RE_IMPORT_OR_FROM: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:from|import)\s+",
    re.MULTILINE,
)
_PYTHON_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".pyi"})
_CONTRACT_SUFFIXES: Final[frozenset[str]] = frozenset({".yaml", ".yml", ".json"})


# ---------------------------------------------------------------------------
# AdversarialScanner
# ---------------------------------------------------------------------------
class AdversarialScanner:
    """Purely static adversarial-pattern scanner.

    Implements the ``QualityScanner`` protocol::

        async def scan(self, target_dir: Path) -> list[ScanViolation]

    Every finding is advisory (``severity="warning"`` or ``"info"``).
    """

    def __init__(self, graph_rag_client: Any | None = None) -> None:
        self._graph_rag_client = graph_rag_client

    # -- public interface ---------------------------------------------------

    async def scan(self, target_dir: Path) -> list[ScanViolation]:
        """Scan *target_dir* for adversarial patterns.

        Returns a list of :class:`ScanViolation` instances, one per finding.
        """
        target_dir = Path(target_dir).resolve()
        violations: list[ScanViolation] = []
        violations.extend(self._check_dead_event_handlers(target_dir))
        violations.extend(self._check_dead_contracts(target_dir))
        violations.extend(self._check_orphan_services(target_dir))
        violations.extend(self._check_naming_inconsistency(target_dir))
        violations.extend(self._check_error_handling(target_dir))
        violations.extend(self._check_race_conditions(target_dir))
        if self._graph_rag_client is not None:
            violations = await self._filter_dead_events_with_graph_rag(violations)
        return violations

    async def _filter_dead_events_with_graph_rag(
        self, violations: list[ScanViolation]
    ) -> list[ScanViolation]:
        """Remove false positive ADV-001/ADV-002 using Graph RAG cross-service data."""
        try:
            result = await self._graph_rag_client.check_cross_service_events()
            matched_names = {
                e.get("event_name", "") for e in result.get("matched_events", [])
            }
            return [
                v for v in violations
                if not (
                    v.code in (ADVERSARIAL_SCAN_CODES[0], ADVERSARIAL_SCAN_CODES[1])
                    and any(name in v.message for name in matched_names if name)
                )
            ]
        except Exception:
            return violations

    # -- helpers ------------------------------------------------------------

    def _should_skip_file(self, file_path: Path) -> bool:
        """Return ``True`` if the file resides under an excluded directory."""
        parts = file_path.parts
        return any(part in EXCLUDED_DIRS for part in parts)

    def _iter_python_files(self, target_dir: Path) -> list[Path]:
        """Collect all Python files under *target_dir*, skipping exclusions."""
        results: list[Path] = []
        for suffix in sorted(_PYTHON_SUFFIXES):
            for path in target_dir.rglob(f"*{suffix}"):
                if path.is_file() and not self._should_skip_file(path):
                    results.append(path)
        return results

    def _iter_contract_files(self, target_dir: Path) -> list[Path]:
        """Collect YAML / JSON files that look like OpenAPI or AsyncAPI specs."""
        results: list[Path] = []
        for suffix in sorted(_CONTRACT_SUFFIXES):
            for path in target_dir.rglob(f"*{suffix}"):
                if path.is_file() and not self._should_skip_file(path):
                    results.append(path)
        return results

    @staticmethod
    def _safe_read(path: Path) -> str:
        """Read file contents, returning empty string on any I/O error."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _relative(path: Path, base: Path) -> str:
        """Return a POSIX-style relative path string for display."""
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            return path.as_posix()

    # -- ADV-001: Dead event handlers ---------------------------------------

    def _check_dead_event_handlers(self, target_dir: Path) -> list[ScanViolation]:
        """Detect functions decorated as event handlers that are never referenced."""
        violations: list[ScanViolation] = []
        python_files = self._iter_python_files(target_dir)

        # Phase 1 -- collect handler names and their locations
        handlers: list[tuple[str, Path, int]] = []
        for path in python_files:
            content = self._safe_read(path)
            if not content:
                continue
            for match in _RE_EVENT_HANDLER_DECORATOR.finditer(content):
                func_name = match.group(1)
                line_no = content[: match.start()].count("\n") + 1
                handlers.append((func_name, path, line_no))

        if not handlers:
            return violations

        # Phase 2 -- build a corpus of all Python source for reference checks
        corpus_by_file: dict[Path, str] = {}
        for path in python_files:
            content = self._safe_read(path)
            if content:
                corpus_by_file[path] = content

        # Phase 3 -- check whether each handler name appears anywhere else
        for func_name, handler_path, line_no in handlers:
            # Build a pattern that matches the name as a whole word but NOT
            # at its own definition site (the decorator + def line).
            ref_pattern = re.compile(r"(?<!\bdef\s)" + re.escape(func_name) + r"\b")
            found_elsewhere = False
            for other_path, other_content in corpus_by_file.items():
                if other_path == handler_path:
                    # Remove the handler's own def block from the search
                    # so we only find *other* references in the same file.
                    lines = other_content.splitlines(keepends=True)
                    stripped = "".join(
                        ln for idx, ln in enumerate(lines, start=1)
                        if idx != line_no
                    )
                    if ref_pattern.search(stripped):
                        found_elsewhere = True
                        break
                else:
                    if ref_pattern.search(other_content):
                        found_elsewhere = True
                        break

            if not found_elsewhere:
                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[0],  # ADV-001
                        severity="warning",
                        category="adversarial",
                        file_path=self._relative(handler_path, target_dir),
                        line=line_no,
                        message=(
                            f"Event handler '{func_name}' is decorated but "
                            f"never referenced elsewhere in the codebase. "
                            f"Suggestion: Verify the handler is wired to an event bus at "
                            f"runtime, or remove the dead handler."
                        ),
                    )
                )

        return violations

    # -- ADV-002: Dead contracts --------------------------------------------

    def _check_dead_contracts(self, target_dir: Path) -> list[ScanViolation]:
        """Detect OpenAPI / AsyncAPI spec files not referenced by any code."""
        violations: list[ScanViolation] = []
        contract_files: list[Path] = []

        # Identify contract files
        for candidate in self._iter_contract_files(target_dir):
            content = self._safe_read(candidate)
            if content and _RE_OPENAPI_INDICATOR.search(content):
                contract_files.append(candidate)

        if not contract_files:
            return violations

        # Build search corpus from all Python files
        python_sources: list[str] = []
        for py_path in self._iter_python_files(target_dir):
            content = self._safe_read(py_path)
            if content:
                python_sources.append(content)

        all_python_text = "\n".join(python_sources)

        for contract_path in contract_files:
            filename = contract_path.name
            stem = contract_path.stem

            # Check whether the filename or stem is mentioned in any Python source
            referenced = (
                filename in all_python_text
                or stem in all_python_text
            )

            if not referenced:
                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[1],  # ADV-002
                        severity="warning",
                        category="adversarial",
                        file_path=self._relative(contract_path, target_dir),
                        line=1,
                        message=(
                            f"Contract file '{filename}' is not referenced "
                            f"by any Python source in the codebase. "
                            f"Suggestion: Ensure the contract is loaded by a service or "
                            f"remove the orphaned specification file."
                        ),
                    )
                )

        return violations

    # -- ADV-003: Orphan services -------------------------------------------

    def _check_orphan_services(self, target_dir: Path) -> list[ScanViolation]:
        """Detect service directories that have no imports from/to other services."""
        violations: list[ScanViolation] = []

        # Discover service directories (dirs containing a known entry point)
        service_dirs: list[Path] = []
        for entry_name in sorted(_SERVICE_ENTRY_POINTS):
            for entry_file in target_dir.rglob(entry_name):
                if entry_file.is_file() and not self._should_skip_file(entry_file):
                    svc_dir = entry_file.parent
                    if svc_dir not in service_dirs:
                        service_dirs.append(svc_dir)

        if len(service_dirs) < 2:
            # Need at least two services to detect orphans
            return violations

        # For each service, collect its Python file contents
        service_contents: dict[Path, str] = {}
        for svc_dir in service_dirs:
            parts: list[str] = []
            for py_file in svc_dir.rglob("*.py"):
                if py_file.is_file() and not self._should_skip_file(py_file):
                    content = self._safe_read(py_file)
                    if content:
                        parts.append(content)
            service_contents[svc_dir] = "\n".join(parts)

        # Determine the "module name" for each service directory
        service_names: dict[Path, str] = {}
        for svc_dir in service_dirs:
            try:
                rel = svc_dir.relative_to(target_dir)
                # Convert path parts to dotted module path
                service_names[svc_dir] = ".".join(rel.parts)
            except ValueError:
                service_names[svc_dir] = svc_dir.name

        # Check each service for references from other services
        for svc_dir in service_dirs:
            svc_name = service_names[svc_dir]
            dir_name = svc_dir.name

            referenced_by_other = False
            for other_dir in service_dirs:
                if other_dir == svc_dir:
                    continue
                other_text = service_contents.get(other_dir, "")
                # Check for imports like "from <svc_name>" or "import <svc_name>"
                # or plain references to the directory name
                if (
                    svc_name in other_text
                    or dir_name in other_text
                ):
                    referenced_by_other = True
                    break

            if not referenced_by_other:
                # Also check that the service doesn't reference any other service
                own_text = service_contents.get(svc_dir, "")
                references_other = False
                for other_dir in service_dirs:
                    if other_dir == svc_dir:
                        continue
                    other_name = service_names[other_dir]
                    other_dir_name = other_dir.name
                    if other_name in own_text or other_dir_name in own_text:
                        references_other = True
                        break

                if not references_other:
                    # Find the entry-point file for reporting
                    entry_file = svc_dir / "main.py"
                    if not entry_file.exists():
                        for ep in _SERVICE_ENTRY_POINTS:
                            candidate = svc_dir / ep
                            if candidate.exists():
                                entry_file = candidate
                                break

                    violations.append(
                        ScanViolation(
                            code=ADVERSARIAL_SCAN_CODES[2],  # ADV-003
                            severity="info",
                            category="adversarial",
                            file_path=self._relative(entry_file, target_dir),
                            line=1,
                            message=(
                                f"Service directory '{dir_name}' appears orphaned -- "
                                f"no imports or references connect it to other services. "
                                f"Suggestion: Integrate the service via shared contracts or "
                                f"imports, or remove it if no longer needed."
                            ),
                        )
                    )

        return violations

    # -- ADV-004: Naming inconsistency --------------------------------------

    def _check_naming_inconsistency(self, target_dir: Path) -> list[ScanViolation]:
        """Detect camelCase function/variable names in Python files."""
        violations: list[ScanViolation] = []

        # Well-known camelCase names that are conventional in Python
        # (e.g., unittest's setUp / tearDown, pydantic model config, etc.)
        allowed_camel: frozenset[str] = frozenset(
            {
                "setUp",
                "tearDown",
                "setUpClass",
                "tearDownClass",
                "setUpModule",
                "tearDownModule",
                "maxDiff",
                "addCleanup",
            }
        )

        for py_path in self._iter_python_files(target_dir):
            content = self._safe_read(py_path)
            if not content:
                continue

            seen_names: set[str] = set()

            # Check function definitions
            for match in _RE_CAMEL_CASE_DEF.finditer(content):
                name = match.group(1)
                if name in allowed_camel or name in seen_names:
                    continue
                seen_names.add(name)
                line_no = content[: match.start()].count("\n") + 1
                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[3],  # ADV-004
                        severity="info",
                        category="adversarial",
                        file_path=self._relative(py_path, target_dir),
                        line=line_no,
                        message=(
                            f"Function '{name}' uses camelCase instead of "
                            f"snake_case (PEP 8 violation). "
                            f"Suggestion: Rename to '{_to_snake_case(name)}' for "
                            f"consistency with Python conventions."
                        ),
                    )
                )

            # Check variable assignments (top-level in functions / module)
            for match in _RE_CAMEL_CASE_ASSIGN.finditer(content):
                name = match.group(1)
                if name in allowed_camel or name in seen_names:
                    continue
                seen_names.add(name)
                line_no = content[: match.start()].count("\n") + 1
                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[3],  # ADV-004
                        severity="info",
                        category="adversarial",
                        file_path=self._relative(py_path, target_dir),
                        line=line_no,
                        message=(
                            f"Variable '{name}' uses camelCase instead of "
                            f"snake_case (PEP 8 violation). "
                            f"Suggestion: Rename to '{_to_snake_case(name)}' for "
                            f"consistency with Python conventions."
                        ),
                    )
                )

        return violations

    # -- ADV-005: Missing error handling patterns ---------------------------

    def _check_error_handling(self, target_dir: Path) -> list[ScanViolation]:
        """Detect bare ``except:`` and overly broad exception handling."""
        violations: list[ScanViolation] = []

        for py_path in self._iter_python_files(target_dir):
            content = self._safe_read(py_path)
            if not content:
                continue
            lines = content.splitlines()

            # Bare except
            for match in _RE_BARE_EXCEPT.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[4],  # ADV-005
                        severity="warning",
                        category="adversarial",
                        file_path=self._relative(py_path, target_dir),
                        line=line_no,
                        message="Bare 'except:' catches all exceptions including KeyboardInterrupt and SystemExit. Suggestion: Catch specific exception types, or use 'except Exception:' with a re-raise.",
                    )
                )

            # Broad except (Exception / BaseException) without re-raise
            for match in _RE_BROAD_EXCEPT.finditer(content):
                exc_type = match.group(1)
                line_no = content[: match.start()].count("\n") + 1

                # Look ahead in the except block for a raise statement.
                # We scan from the except line forward until dedent or EOF.
                except_indent = len(match.group(0)) - len(match.group(0).lstrip())
                block_lines = lines[line_no:]  # lines after the except
                has_reraise = False
                for block_line in block_lines:
                    stripped = block_line.lstrip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    current_indent = len(block_line) - len(stripped)
                    if current_indent <= except_indent and stripped:
                        # Dedented -- left the except block
                        break
                    if _RE_RERAISE.match(block_line):
                        has_reraise = True
                        break

                if not has_reraise:
                    violations.append(
                        ScanViolation(
                            code=ADVERSARIAL_SCAN_CODES[4],  # ADV-005
                            severity="warning",
                            category="adversarial",
                            file_path=self._relative(py_path, target_dir),
                            line=line_no,
                            message=(
                                f"Broad 'except {exc_type}' without re-raise "
                                f"may silently swallow errors. "
                                f"Suggestion: Catch more specific exception types, or add "
                                f"'raise' to propagate the exception after handling."
                            ),
                        )
                    )

        return violations

    # -- ADV-006: Potential race conditions ----------------------------------

    def _check_race_conditions(self, target_dir: Path) -> list[ScanViolation]:
        """Detect shared mutable state modified inside functions without locking."""
        violations: list[ScanViolation] = []

        for py_path in self._iter_python_files(target_dir):
            content = self._safe_read(py_path)
            if not content:
                continue

            # Skip files that already use locks
            if _RE_LOCK_USAGE.search(content):
                continue

            # Find module-level mutable state names
            mutable_names: set[str] = set()
            for match in _RE_MODULE_LEVEL_MUTABLE.finditer(content):
                mutable_names.add(match.group(1))
            for match in _RE_MODULE_LEVEL_MUTABLE_UNTYPED.finditer(content):
                mutable_names.add(match.group(1))

            if not mutable_names:
                continue

            # Find function bodies that use 'global <name>' for these variables
            global_refs: set[str] = set()
            for match in _RE_GLOBAL_KEYWORD.finditer(content):
                var_name = match.group(1)
                if var_name in mutable_names:
                    global_refs.add(var_name)

            # Also check for direct mutation patterns: <name>.append / .update / .extend / [key] =
            mutation_pattern = re.compile(
                r"^\s+("
                + "|".join(re.escape(n) for n in sorted(mutable_names))
                + r")\s*(?:\.\s*(?:append|extend|update|pop|remove|clear|insert|add|discard)"
                  r"|\[.+\]\s*=)",
                re.MULTILINE,
            )
            mutated_names: set[str] = set()
            for match in mutation_pattern.finditer(content):
                mutated_names.add(match.group(1))

            flagged = global_refs | mutated_names
            if not flagged:
                continue

            # Report each flagged variable once
            for var_name in sorted(flagged):
                # Find the line where the variable is defined
                defn_pattern = re.compile(
                    r"^" + re.escape(var_name) + r"\s*[:=]",
                    re.MULTILINE,
                )
                defn_match = defn_pattern.search(content)
                line_no = 1
                if defn_match:
                    line_no = content[: defn_match.start()].count("\n") + 1

                violations.append(
                    ScanViolation(
                        code=ADVERSARIAL_SCAN_CODES[5],  # ADV-006
                        severity="warning",
                        category="adversarial",
                        file_path=self._relative(py_path, target_dir),
                        line=line_no,
                        message=(
                            f"Module-level mutable '{var_name}' is modified "
                            f"inside a function without any threading lock. "
                            f"Suggestion: Protect shared mutable state with "
                            f"threading.Lock / asyncio.Lock, or make the "
                            f"state local to the function."
                        ),
                    )
                )

        return violations


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# Pattern for splitting camelCase into words
_RE_CAMEL_SPLIT: Final[re.Pattern[str]] = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def _to_snake_case(name: str) -> str:
    """Convert a camelCase name to snake_case."""
    return _RE_CAMEL_SPLIT.sub("_", name).lower()
