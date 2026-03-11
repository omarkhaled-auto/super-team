#!/usr/bin/env python3
"""Pre-flight validation script for Super-Team pipeline.

Run before launching the pipeline to detect common environment issues
early, saving time and budget.

Usage:
    python scripts/preflight.py [--prd PATH] [--output-dir PATH] [--skip-docker]

Exit codes:
    0 = All checks passed
    1 = One or more FAIL checks (pipeline will likely crash)
    2 = Only WARN checks (pipeline can proceed with reduced functionality)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


class CheckResult:
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


def _print_check(name: str, status: str, detail: str = "") -> None:
    symbol = {"OK": "+", "WARN": "!", "FAIL": "X"}[status]
    color = {"OK": "\033[92m", "WARN": "\033[93m", "FAIL": "\033[91m"}[status]
    reset = "\033[0m"
    msg = f"  [{symbol}] {name}: {status}"
    if detail:
        msg += f" -- {detail}"
    print(f"{color}{msg}{reset}")


def check_python_version() -> str:
    v = sys.version_info
    if v >= (3, 12):
        _print_check("Python version", CheckResult.OK, f"{v.major}.{v.minor}.{v.micro}")
        return CheckResult.OK
    if v >= (3, 10):
        _print_check("Python version", CheckResult.WARN, f"{v.major}.{v.minor} (3.12+ recommended)")
        return CheckResult.WARN
    _print_check("Python version", CheckResult.FAIL, f"{v.major}.{v.minor} (3.12+ required)")
    return CheckResult.FAIL


def check_claude_cli() -> str:
    cli_path = shutil.which("claude")
    if not cli_path:
        _print_check("Claude CLI", CheckResult.FAIL, "Not found on PATH")
        return CheckResult.FAIL
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True, timeout=10,
        )
        version = result.stdout.decode("utf-8", errors="replace").strip()[:60]
        _print_check("Claude CLI", CheckResult.OK, f"{cli_path} ({version})")
        return CheckResult.OK
    except Exception as exc:
        _print_check("Claude CLI", CheckResult.WARN, f"Found at {cli_path} but version check failed: {exc}")
        return CheckResult.WARN


def check_docker(skip: bool = False) -> str:
    if skip:
        _print_check("Docker", CheckResult.WARN, "Skipped (--skip-docker)")
        return CheckResult.WARN

    docker_path = shutil.which("docker")
    if not docker_path:
        _print_check("Docker CLI", CheckResult.WARN, "Not on PATH (integration phase will be skipped)")
        return CheckResult.WARN

    try:
        result = subprocess.run(
            [docker_path, "info"],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:100]
            _print_check("Docker daemon", CheckResult.WARN, f"Not running: {stderr}")
            return CheckResult.WARN
        _print_check("Docker daemon", CheckResult.OK, "Running")
    except subprocess.TimeoutExpired:
        _print_check("Docker daemon", CheckResult.WARN, "Timed out")
        return CheckResult.WARN
    except Exception as exc:
        _print_check("Docker daemon", CheckResult.WARN, str(exc))
        return CheckResult.WARN

    # Check docker compose
    try:
        result = subprocess.run(
            [docker_path, "compose", "version"],
            capture_output=True, timeout=10,
        )
        version = result.stdout.decode("utf-8", errors="replace").strip()[:60]
        _print_check("Docker Compose", CheckResult.OK, version)
    except Exception:
        _print_check("Docker Compose", CheckResult.WARN, "Not available")
        return CheckResult.WARN

    return CheckResult.OK


def check_env_vars() -> str:
    status = CheckResult.OK

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        _print_check("ANTHROPIC_API_KEY", CheckResult.OK, f"Set ({masked})")
    else:
        # Fix 17: Check if Claude CLI is available as fallback auth
        claude_cli = shutil.which("claude")
        if claude_cli:
            _print_check("ANTHROPIC_API_KEY", CheckResult.OK,
                          f"Not set (using Claude CLI at {claude_cli})")
        else:
            _print_check("ANTHROPIC_API_KEY", CheckResult.FAIL,
                          "Not set and no Claude CLI found")
            status = CheckResult.FAIL

    # Check for potentially harmful env vars
    if os.environ.get("CLAUDECODE"):
        _print_check("CLAUDECODE env var", CheckResult.WARN,
                      "Set (will be filtered by pipeline, but may cause nesting issues)")
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        _print_check("CLAUDE_CODE_ENTRYPOINT", CheckResult.WARN,
                      "Set (will be filtered by pipeline)")

    return status


def check_prd_file(prd_path: str | None) -> str:
    if not prd_path:
        _print_check("PRD file", CheckResult.WARN, "No --prd specified, skipping check")
        return CheckResult.WARN

    p = Path(prd_path)
    if not p.exists():
        _print_check("PRD file", CheckResult.FAIL, f"Not found: {prd_path}")
        return CheckResult.FAIL

    size = p.stat().st_size
    if size < 1000:
        _print_check("PRD file", CheckResult.WARN, f"Very small ({size} bytes) -- possibly incomplete")
        return CheckResult.WARN

    text = p.read_text(encoding="utf-8", errors="replace")
    if "## " not in text:
        _print_check("PRD file", CheckResult.WARN, "No markdown headings found")
        return CheckResult.WARN

    _print_check("PRD file", CheckResult.OK, f"{size:,} bytes, {len(text.splitlines())} lines")
    return CheckResult.OK


def check_output_dir(output_dir: str | None) -> str:
    if not output_dir:
        _print_check("Output directory", CheckResult.WARN, "No --output-dir specified")
        return CheckResult.WARN

    p = Path(output_dir)
    if p.exists():
        state_file = p / ".super-orchestrator" / "pipeline_state.json"
        if state_file.exists():
            _print_check("Existing state", CheckResult.WARN,
                          f"Found {state_file} -- pipeline will attempt resume")
        else:
            _print_check("Output directory", CheckResult.OK, f"Exists: {p}")
    else:
        _print_check("Output directory", CheckResult.OK, f"Will be created: {p}")

    return CheckResult.OK


def check_pycache() -> str:
    """Check for stale __pycache__ in patched packages."""
    stale_dirs = []
    for pkg_name in ("claude_agent_sdk", "agent_team", "agent_team_v15"):
        for site_dir in (Path(sys.prefix) / "Lib" / "site-packages",
                         Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"):
            cache_dir = site_dir / pkg_name
            if cache_dir.exists():
                for pycache in cache_dir.rglob("__pycache__"):
                    stale_dirs.append(str(pycache))

    # Also check super-team source
    src_dir = Path(__file__).parent.parent / "src"
    for pycache in src_dir.rglob("__pycache__"):
        stale_dirs.append(str(pycache))

    if stale_dirs:
        _print_check("__pycache__", CheckResult.WARN,
                      f"Found {len(stale_dirs)} cache dirs (run with --clear-cache to remove)")
        return CheckResult.WARN

    _print_check("__pycache__", CheckResult.OK, "No stale caches found")
    return CheckResult.OK


def check_imports() -> str:
    """Verify key pipeline imports work."""
    failures = []
    for module in (
        "src.super_orchestrator.pipeline",
        "src.architect.services.prd_parser",
        "src.architect.services.service_boundary",
        "src.architect.services.domain_modeler",
        "src.shared.models.architect",
    ):
        try:
            __import__(module)
        except Exception as exc:
            failures.append(f"{module}: {exc}")

    if failures:
        _print_check("Pipeline imports", CheckResult.FAIL,
                      f"{len(failures)} failed: {failures[0]}")
        return CheckResult.FAIL

    _print_check("Pipeline imports", CheckResult.OK, "All core modules importable")
    return CheckResult.OK


def clear_pycache() -> None:
    """Remove __pycache__ directories from source."""
    src_dir = Path(__file__).parent.parent / "src"
    count = 0
    for pycache in src_dir.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
        count += 1
    print(f"  Cleared {count} __pycache__ directories from src/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Super-Team pipeline pre-flight checks")
    parser.add_argument("--prd", help="Path to PRD file")
    parser.add_argument("--output-dir", help="Pipeline output directory")
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker checks")
    parser.add_argument("--clear-cache", action="store_true", help="Clear __pycache__ directories")
    args = parser.parse_args()

    print("\n=== Super-Team Pre-Flight Checks ===\n")

    if args.clear_cache:
        clear_pycache()
        print()

    results: list[str] = []

    results.append(check_python_version())
    results.append(check_claude_cli())
    results.append(check_docker(skip=args.skip_docker))
    results.append(check_env_vars())
    results.append(check_prd_file(args.prd))
    results.append(check_output_dir(args.output_dir))
    results.append(check_pycache())
    results.append(check_imports())

    print()

    fails = results.count(CheckResult.FAIL)
    warns = results.count(CheckResult.WARN)
    oks = results.count(CheckResult.OK)

    print(f"Results: {oks} OK, {warns} WARN, {fails} FAIL")

    if fails > 0:
        print("\nFAILED: Fix the FAIL items above before launching the pipeline.")
        return 1
    elif warns > 0:
        print("\nWARNINGS: Pipeline can proceed but some features may be limited.")
        return 2
    else:
        print("\nALL CHECKS PASSED: Ready to launch!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
