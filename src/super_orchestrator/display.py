"""Rich-based terminal display layer for pipeline progress.

Provides formatted output for pipeline headers, phase tables, builder
status, quality summaries, error panels, progress bars, and final
summaries.  Uses a module-level :class:`~rich.console.Console` singleton
for consistent output.

.. rubric:: Design decisions

* **Module-level Console singleton** -- all display functions share
  ``_console`` so that Rich formatting is consistent across the session.
* **Functions, not a class** -- each display function is standalone and
  stateless, making them easy to test and compose.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Module-level Console singleton
# ---------------------------------------------------------------------------

_console = Console()


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------


def print_pipeline_header(state: Any, tracker: Any = None, pipeline_id: str | None = None, prd_path: str | None = None) -> None:
    """Print a Rich panel header with pipeline identification.

    Parameters
    ----------
    state:
        A ``PipelineState`` instance (or duck-typed object with
        ``pipeline_id``, ``prd_path``).
    tracker:
        A ``PipelineCostTracker`` instance (optional).
    pipeline_id:
        Legacy: explicit pipeline ID override.
    prd_path:
        Legacy: explicit PRD path override.
    """
    pid = pipeline_id or _get_attr(state, "pipeline_id", "unknown")
    prd = prd_path or _get_attr(state, "prd_path", "unknown")
    total_cost = _get_attr(tracker, "total_cost", 0.0) if tracker else 0.0

    header = Text()
    header.append("Super Orchestrator", style="bold white")
    header.append(" v3.0.0\n", style="dim")
    header.append(f"Pipeline: ", style="bold")
    header.append(f"{pid}\n", style="cyan")
    header.append(f"PRD: ", style="bold")
    header.append(f"{prd}\n", style="green")
    if total_cost > 0:
        header.append(f"Cost: ", style="bold")
        header.append(f"${total_cost:.4f}", style="yellow")

    _console.print(
        Panel(
            header,
            title="[bold]Pipeline Overview[/bold]",
            border_style="blue",
            expand=False,
        )
    )


def print_phase_table(state: Any, tracker: Any = None) -> None:
    """Print a Rich table showing the status of each pipeline phase.

    Parameters
    ----------
    state:
        A ``PipelineState`` instance (or duck-typed dict/object with
        ``current_state``, ``completed_phases``, ``phase_costs``).
    tracker:
        A ``PipelineCostTracker`` instance (optional).
    """
    table = Table(title="Phase Status", show_header=True, header_style="bold magenta")
    table.add_column("Phase", style="cyan", min_width=25)
    table.add_column("Status", justify="center", min_width=12)
    table.add_column("Cost ($)", justify="right", min_width=10)
    table.add_column("Duration", justify="right", min_width=10)

    # Import phase names
    from src.build3_shared.constants import ALL_PHASES

    current_state = _get_attr(state, "current_state", "init")
    completed = _get_attr(state, "completed_phases", [])
    phase_costs = _get_attr(state, "phase_costs", {})
    tracker_costs = _get_attr(tracker, "phase_costs", {}) if tracker else {}

    # Map phases to human-readable names
    phase_display = {
        "architect": "Architect",
        "contract_registration": "Contract Registration",
        "builders": "Builders",
        "integration": "Integration",
        "quality_gate": "Quality Gate",
        "fix_pass": "Fix Pass",
    }

    for phase in ALL_PHASES:
        name = phase_display.get(phase, phase)
        cost = phase_costs.get(phase, 0.0) or tracker_costs.get(phase, 0.0)
        cost_str = f"${cost:.4f}" if cost > 0 else "\u2014"

        if phase in completed:
            status = "[green]COMPLETE[/green]"
        elif _is_phase_active(phase, current_state):
            status = "[yellow]RUNNING[/yellow]"
        else:
            status = "[dim]PENDING[/dim]"

        duration_str = "\u2014"
        table.add_row(name, status, cost_str, duration_str)

    _console.print(table)


def print_builder_table(state: Any) -> None:
    """Print a Rich table showing builder results per service.

    Parameters
    ----------
    state:
        A ``PipelineState`` instance with ``builder_results``,
        ``builder_statuses``, ``builder_costs``.
    """
    table = Table(title="Builder Results", show_header=True, header_style="bold magenta")
    table.add_column("Service", style="cyan", min_width=20)
    table.add_column("Status", justify="center", min_width=12)
    table.add_column("Tests", justify="center", min_width=12)
    table.add_column("Convergence", justify="center", min_width=12)
    table.add_column("Cost ($)", justify="right", min_width=10)

    builder_results = _get_attr(state, "builder_results", {})
    builder_statuses = _get_attr(state, "builder_statuses", {})
    builder_costs = _get_attr(state, "builder_costs", {})

    if not builder_results and not builder_statuses:
        _console.print("[dim]No builder results available.[/dim]")
        return

    for service_id in sorted(set(list(builder_results.keys()) + list(builder_statuses.keys()))):
        result = builder_results.get(service_id, {})
        status_str = builder_statuses.get(service_id, "pending")
        cost = builder_costs.get(service_id, 0.0)

        if status_str == "healthy":
            status = "[green]HEALTHY[/green]"
        elif status_str in ("failed", "unhealthy"):
            status = "[red]FAILED[/red]"
        else:
            status = f"[dim]{status_str.upper()}[/dim]"

        test_passed = result.get("test_passed", 0)
        test_total = result.get("test_total", 0)
        tests = f"{test_passed}/{test_total}" if test_total > 0 else "—"

        convergence = result.get("convergence_ratio", 0.0)
        conv_str = f"{convergence:.0%}" if convergence > 0 else "—"

        cost_str = f"${cost:.4f}" if cost > 0 else "—"

        table.add_row(service_id, status, tests, conv_str, cost_str)

    _console.print(table)


def print_quality_summary(report: Any) -> None:
    """Print a Rich panel summarising the quality gate results.

    Parameters
    ----------
    report:
        A ``QualityGateReport`` instance or dict with ``overall_verdict``,
        ``total_violations``, ``blocking_violations``, ``layers``.
    """
    verdict = _get_attr(report, "overall_verdict", "skipped")
    if hasattr(verdict, "value"):
        verdict = verdict.value

    total_violations = _get_attr(report, "total_violations", 0)
    blocking = _get_attr(report, "blocking_violations", 0)
    fix_attempts = _get_attr(report, "fix_attempts", 0)
    max_fix = _get_attr(report, "max_fix_attempts", 3)

    # Determine style from verdict
    if verdict == "passed":
        style = "green"
        icon = ":white_check_mark:"
    elif verdict == "failed":
        style = "red"
        icon = ":x:"
    elif verdict == "partial":
        style = "yellow"
        icon = ":warning:"
    else:
        style = "dim"
        icon = ":grey_question:"

    content = Text()
    content.append(f"Verdict: {verdict.upper()}\n", style=f"bold {style}")
    content.append(f"Total Violations: {total_violations}\n")
    content.append(f"Blocking Violations: {blocking}\n")
    content.append(f"Fix Attempts: {fix_attempts}/{max_fix}\n")

    # Layer breakdown as a table
    layers = _get_attr(report, "layers", {})
    layer_table = Table(show_header=True, header_style="bold")
    layer_table.add_column("Layer", style="cyan", min_width=20)
    layer_table.add_column("Verdict", justify="center", min_width=10)
    layer_table.add_column("Violations", justify="right", min_width=10)

    if layers:
        for layer_name, layer_data in layers.items():
            layer_verdict = layer_data.get("verdict", "skipped") if isinstance(layer_data, dict) else _get_attr(layer_data, "verdict", "skipped")
            if hasattr(layer_verdict, "value"):
                layer_verdict = layer_verdict.value
            layer_display = layer_name.replace("_", " ").title()
            layer_violations = layer_data.get("violations", []) if isinstance(layer_data, dict) else _get_attr(layer_data, "violations", [])
            violation_count = len(layer_violations) if isinstance(layer_violations, list) else 0
            layer_table.add_row(layer_display, layer_verdict, str(violation_count))

    _console.print(
        Panel(
            Group(content, layer_table),
            title="[bold]Quality Gate Summary[/bold]",
            border_style=style,
            expand=False,
        )
    )


def print_error_panel(error: str | Exception) -> None:
    """Print an error message in a red Rich panel.

    Parameters
    ----------
    error:
        Error message string or Exception instance.
    """
    error_text = str(error)
    _console.print(
        Panel(
            Text(error_text, style="bold white"),
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
        )
    )


def create_progress_bar(description: str = "") -> Progress:
    """Create a Rich Progress instance with the standard column layout.

    Parameters
    ----------
    description:
        Default description text for the progress bar.

    Returns
    -------
    Progress
        Configured Rich Progress with SpinnerColumn, TextColumn,
        BarColumn, and TimeElapsedColumn.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=_console,
    )


def print_final_summary(state: Any, tracker: Any = None, cost_tracker: Any = None) -> None:
    """Print the final pipeline summary with costs and results.

    Parameters
    ----------
    state:
        A ``PipelineState`` instance.
    tracker:
        A ``PipelineCostTracker`` instance (preferred parameter name).
    cost_tracker:
        Legacy alias for *tracker*.
    """
    cost_tracker = tracker or cost_tracker
    current_state = _get_attr(state, "current_state", "unknown")

    if current_state == "complete":
        style = "green"
        title = "Pipeline Complete"
    elif current_state == "failed":
        style = "red"
        title = "Pipeline Failed"
    else:
        style = "yellow"
        title = "Pipeline Status"

    content = Text()
    content.append(f"Pipeline ID: ", style="bold")
    content.append(f"{_get_attr(state, 'pipeline_id', 'unknown')}\n", style="cyan")
    content.append(f"Final State: ", style="bold")
    content.append(f"{current_state}\n", style=style)

    # Phases completed
    completed = _get_attr(state, "completed_phases", [])
    content.append(f"Phases Completed: {len(completed)}\n")

    # Builder stats
    total_builders = _get_attr(state, "total_builders", 0)
    successful = _get_attr(state, "successful_builders", 0)
    if total_builders > 0:
        content.append(f"Builders: {successful}/{total_builders} passed\n")

    # Cost info
    total_cost = _get_attr(state, "total_cost", 0.0)
    budget = _get_attr(state, "budget_limit", None)
    content.append(f"\nTotal Cost: ", style="bold")
    content.append(f"${total_cost:.4f}", style="cyan")
    if budget is not None:
        content.append(f" / ${budget:.2f}\n")
    else:
        content.append(" / no limit\n")

    if cost_tracker is not None:
        phase_costs = getattr(cost_tracker, "phase_costs", {})
        if phase_costs:
            content.append("\nPhase Costs:\n", style="bold")
            for phase, cost in phase_costs.items():
                content.append(f"  {phase}: ${cost:.4f}\n")

    # Interrupted?
    interrupted = _get_attr(state, "interrupted", False)
    if interrupted:
        reason = _get_attr(state, "interrupt_reason", "")
        content.append(f"\n[yellow]Interrupted: {reason}[/yellow]\n")

    _console.print(
        Panel(
            content,
            title=f"[bold]{title}[/bold]",
            border_style=style,
            expand=False,
        )
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Get attribute from object or dict, with fallback to default."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_phase_active(phase: str, current_state: str) -> bool:
    """Determine if a phase is currently active based on state."""
    state_to_phase = {
        "architect_running": "architect",
        "architect_review": "architect",
        "contracts_registering": "contract_registration",
        "builders_running": "builders",
        "builders_complete": "builders",
        "integrating": "integration",
        "quality_gate": "quality_gate",
        "fix_pass": "fix_pass",
    }
    return state_to_phase.get(current_state) == phase
