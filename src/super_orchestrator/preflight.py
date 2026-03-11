"""Pre-flight checks run before every pipeline execution.

Verifies that known library incompatibilities are patched and that the
environment is ready.  Each check auto-fixes when possible and raises
``PipelineError`` only if the issue cannot be resolved automatically.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import textwrap

from src.super_orchestrator.exceptions import PipelineError

logger = logging.getLogger(__name__)


def run_preflight_checks() -> None:
    """Run all pre-flight checks.  Call before ``execute_pipeline``."""
    _check_mcp_pydantic_compat()
    logger.info("Pre-flight checks passed")


# ---------------------------------------------------------------------------
# Check: MCP FastMCP + Pydantic v2 create_model compatibility
# ---------------------------------------------------------------------------
#
# Root cause:  FastMCP's ``_create_wrapped_model`` calls
#   ``create_model(name, result=annotation)``
# which Pydantic v2 interprets as a *default value*, not a *type*.
# The correct Pydantic v2 syntax is:
#   ``create_model(name, result=(annotation, ...))``
#
# This causes crashes for MCP tool functions whose return type is
# ``list[...]``, ``str``, ``int``, ``tuple[...]``, or any other type
# that Pydantic cannot implicitly recognize as a field type annotation.
#
# The fix: patch the one-liner in ``_create_wrapped_model`` at import
# time, so it works regardless of MCP library version upgrades.
# ---------------------------------------------------------------------------

_BUGGY_LINE = "return create_model(model_name, result=annotation)"
_FIXED_LINE = "return create_model(model_name, result=(annotation, ...))"


def _check_mcp_pydantic_compat() -> None:
    """Ensure FastMCP's _create_wrapped_model uses Pydantic v2 syntax."""
    try:
        mod = importlib.import_module(
            "mcp.server.fastmcp.utilities.func_metadata"
        )
    except ImportError:
        # MCP not installed — nothing to patch
        return

    fn = getattr(mod, "_create_wrapped_model", None)
    if fn is None:
        return

    source = inspect.getsource(fn)

    if _BUGGY_LINE in source and _FIXED_LINE not in source:
        # Need to patch
        source_file = inspect.getfile(mod)
        logger.warning(
            "Detected MCP/Pydantic v2 incompatibility in %s — auto-patching",
            source_file,
        )
        try:
            with open(source_file, "r", encoding="utf-8") as f:
                content = f.read()

            if _BUGGY_LINE not in content:
                # Source on disk already patched, but cached bytecode is stale
                _clear_bytecode(source_file)
                importlib.reload(mod)
                return

            content = content.replace(_BUGGY_LINE, _FIXED_LINE, 1)

            with open(source_file, "w", encoding="utf-8") as f:
                f.write(content)

            _clear_bytecode(source_file)
            importlib.reload(mod)
            logger.info("MCP func_metadata.py patched successfully")

        except (OSError, PermissionError) as exc:
            raise PipelineError(
                f"Cannot auto-patch MCP library ({exc}). "
                f"Manually replace in {source_file}:\n"
                f"  OLD: {_BUGGY_LINE}\n"
                f"  NEW: {_FIXED_LINE}"
            ) from exc

    elif _FIXED_LINE.replace("return ", "") in source:
        # Already patched (either by us or upstream fix)
        logger.debug("MCP/Pydantic compat: already patched")
    else:
        # Function signature changed entirely — unknown version
        logger.debug(
            "MCP _create_wrapped_model has unknown implementation — skipping patch"
        )


def _clear_bytecode(source_file: str) -> None:
    """Remove __pycache__ .pyc for the given source file."""
    import pathlib

    source_path = pathlib.Path(source_file)
    cache_dir = source_path.parent / "__pycache__"
    if cache_dir.exists():
        stem = source_path.stem
        for pyc in cache_dir.glob(f"{stem}*.pyc"):
            try:
                pyc.unlink()
                logger.debug("Removed stale bytecode: %s", pyc)
            except OSError:
                pass
