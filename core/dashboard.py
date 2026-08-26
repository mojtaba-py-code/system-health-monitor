"""Rich live CLI dashboard.

Renders a colour-coded, auto-refreshing view of every subsystem. Falls back to
plain text if ``rich`` is unavailable so the command never hard-fails.
"""

from __future__ import annotations

import time

from core.base import MonitorResult
from core.collector import Collector, HealthSnapshot
from utils.logging_config import get_logger

logger = get_logger("dashboard")

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH = True
    _console: Console | None = Console()
except ImportError:  # pragma: no cover
    _RICH = False
    _console = None

_STYLE = {
    "OK": "bold green",
    "WARNING": "bold yellow",
    "CRITICAL": "bold red",
    "UNKNOWN": "dim",
}


def _severity_text(label: str) -> Text:
    return Text(label, style=_STYLE.get(label, "white"))


def _subsystem_table(result: MonitorResult) -> Table:
    table = Table(title=None, expand=True, show_edge=False, pad_edge=False)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_column("Status", justify="center")
    # Show the most relevant metrics (skip verbose per-core / raw byte counters).
    shown = 0
    for metric in result.metrics:
        if metric.name.startswith(("core_", "total_", "packets_")) or metric.name.endswith("_bytes"):
            continue
        table.add_row(metric.name, f"{metric.value}{metric.unit}", _severity_text(metric.severity.label))
        shown += 1
        if shown >= 8:
            break
    for err in result.errors[:2]:
        table.add_row("error", Text(err[:40], style="red"), _severity_text("UNKNOWN"))
    return table


def render_snapshot(snapshot: HealthSnapshot):
    """Return a rich renderable for the snapshot (or a string when rich absent)."""
    if not _RICH:
        return _plain(snapshot)

    panels = []
    for result in snapshot.results:
        border = _STYLE.get(result.worst_severity.label, "white")
        panels.append(
            Panel(
                _subsystem_table(result),
                title=f"{result.subsystem.upper()} — {result.worst_severity.label}",
                border_style=border,
            )
        )
    header = Text.assemble(
        ("System Health Monitor  ", "bold cyan"),
        (f"overall: {snapshot.worst_severity.label}", _STYLE.get(snapshot.worst_severity.label, "white")),
        (f"   {snapshot.timestamp}", "dim"),
    )
    return Group(header, *panels)


def _plain(snapshot: HealthSnapshot) -> str:
    lines = [f"System Health — overall {snapshot.worst_severity.label} — {snapshot.timestamp}"]
    for result in snapshot.results:
        lines.append(f"[{result.subsystem}] {result.worst_severity.label}")
        for metric in result.metrics[:6]:
            lines.append(f"   {metric.name}: {metric.value}{metric.unit} ({metric.severity.label})")
    return "\n".join(lines)


def run_dashboard(
    collector: Collector,
    *,
    interval: float = 2.0,
    duration: float | None = None,
    alert_manager=None,
    db=None,
) -> int:
    """Run the live dashboard until *duration* elapses or Ctrl-C.

    Returns the number of snapshots rendered.
    """
    count = 0
    start = time.monotonic()

    def _step() -> HealthSnapshot:
        nonlocal count
        snapshot = collector.collect()
        count += 1
        if db is not None:
            try:
                db.store_results(snapshot.results)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to store snapshot: %s", exc)
        if alert_manager is not None:
            alert_manager.process(snapshot)
        return snapshot

    if not _RICH:  # pragma: no cover - depends on environment
        try:
            while True:
                print(_plain(_step()))
                if duration is not None and (time.monotonic() - start) >= duration:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        return count

    try:
        with Live(render_snapshot(_step()), console=_console, refresh_per_second=4, screen=False) as live:
            while True:
                if duration is not None and (time.monotonic() - start) >= duration:
                    break
                time.sleep(interval)
                live.update(render_snapshot(_step()))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        if _console:
            _console.print("[dim]Dashboard stopped.[/dim]")
    return count
