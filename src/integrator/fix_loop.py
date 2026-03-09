"""Contract fix loop -- feeds violations back to builder subprocesses."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from src.build3_shared.models import ContractViolation
from src.build3_shared.utils import load_json
from src.run4.builder import BuilderResult, write_fix_instructions

# Keys to filter from subprocess environments to avoid leaking secrets.
_FILTERED_ENV_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = ("critical", "error", "warning", "info")


class ContractFixLoop:
    """Launches builder subprocesses to fix contract violations."""

    def __init__(self, config: Any = None, timeout: int = 1800) -> None:
        if config is not None:
            self.timeout = getattr(
                getattr(config, "builder", None), "timeout", timeout,
            )
        else:
            self.timeout = timeout
        self._config = config
        self._fix_context: str = ""  # Injected by caller when persistence is enabled

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_violations(
        self, violations: list[ContractViolation]
    ) -> dict[str, list[ContractViolation]]:
        """Group violations by severity: critical, error, warning, info.

        Returns a dict whose keys are the four severity levels.  Each key
        maps to the list of :class:`ContractViolation` objects that carry
        that severity.  Severities with no matching violations still appear
        as empty lists.
        """
        classified: dict[str, list[ContractViolation]] = {
            sev: [] for sev in _SEVERITY_ORDER
        }
        for v in violations:
            bucket = v.severity.lower() if v.severity else "error"
            if bucket in classified:
                classified[bucket].append(v)
            else:
                # Fall back to "error" for unknown severity values.
                classified["error"].append(v)
        return classified

    # ------------------------------------------------------------------
    # Builder integration
    # ------------------------------------------------------------------

    async def feed_violations_to_builder(
        self,
        service_id: str,
        violations: list[ContractViolation],
        builder_dir: str | Path,
    ) -> BuilderResult:
        """Write *FIX_INSTRUCTIONS.md* and launch a builder subprocess.

        Parameters
        ----------
        service_id:
            Identifier of the service that needs fixing.
        violations:
            Contract violations to address.
        builder_dir:
            Working directory for the builder subprocess.

        Returns
        -------
        BuilderResult
            Result parsed from the builder's STATE.json, including cost,
            success status, and test metrics.
        """
        builder_dir = Path(builder_dir)
        builder_dir.mkdir(parents=True, exist_ok=True)

        # ---- Write FIX_INSTRUCTIONS.md using priority-based format ----
        violation_dicts = [
            {
                "code": v.code,
                "component": f"{v.service}/{v.file_path}" if v.file_path else v.service,
                "evidence": f"{v.endpoint}: {v.actual}" if v.actual else v.endpoint,
                "action": v.message,
                "message": v.message,
                "priority": "P0" if v.severity.lower() == "critical" else
                            "P1" if v.severity.lower() == "error" else "P2",
            }
            for v in violations
        ]
        write_fix_instructions(builder_dir, violation_dicts, fix_context=self._fix_context)

        # ---- Launch builder subprocess --------------------------------
        proc: asyncio.subprocess.Process | None = None
        filtered_env = {k: v for k, v in os.environ.items() if k not in _FILTERED_ENV_KEYS}
        exit_code = -1
        start = time.monotonic()

        # Redirect stdout/stderr to log files instead of PIPE.
        # Using PIPE without reading causes deadlock when the 4KB buffer fills on Windows.
        log_dir = builder_dir / ".agent-team"
        log_dir.mkdir(parents=True, exist_ok=True)
        _stdout_log = open(log_dir / "fix_stdout.log", "w", encoding="utf-8")
        _stderr_log = open(log_dir / "fix_stderr.log", "w", encoding="utf-8")

        # Prefer agent_team_v15 (MCP-enhanced), fall back to agent_team (base).
        builder_module = "agent_team"
        for _mod in ("agent_team_v15", "agent_team"):
            try:
                __import__(_mod)
                builder_module = _mod
                break
            except ImportError:
                continue

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                builder_module,
                "--cwd",
                str(builder_dir),
                "--depth",
                "quick",
                stdout=_stdout_log,
                stderr=_stderr_log,
                env=filtered_env,
            )
            await asyncio.wait_for(
                proc.wait(), timeout=self.timeout
            )
            exit_code = proc.returncode or 0
        except asyncio.TimeoutError:
            logger.warning(
                "Builder subprocess for %s timed out after %ds",
                service_id,
                self.timeout,
            )
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            # Close log file handles
            for _fh in (_stdout_log, _stderr_log):
                try:
                    _fh.close()
                except Exception:
                    pass

        duration = time.monotonic() - start
        # Read stdout/stderr from log files instead of pipe buffers
        stdout_path = log_dir / "fix_stdout.log"
        stderr_path = log_dir / "fix_stderr.log"
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""

        # ---- Parse result from STATE.json ----------------------------
        from src.run4.builder import _state_to_builder_result

        return _state_to_builder_result(
            service_name=service_id,
            output_dir=builder_dir,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_s=duration,
        )
