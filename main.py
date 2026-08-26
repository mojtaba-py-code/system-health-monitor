#!/usr/bin/env python3
"""System Health Monitor — command-line entry point.

A professional CLI to monitor system health in real time: live dashboard,
periodic monitoring with alerts, on-demand reports, history queries and safe
process/service inspection.

Run ``python main.py --help`` or ``python main.py <command> --help``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import dashboard as dashboard_mod
from core import filesystem_monitor, report_generator, scheduler
from core.alert_manager import AlertManager
from core.collector import Collector, HealthSnapshot
from core.process_monitor import (
    ProcessAccessDeniedError,
    ProcessMonitor,
    ProcessNotFoundError,
)
from core.service_monitor import ServiceMonitor
from database.metrics_db import MetricsDB
from utils.config import Config
from utils.exceptions import MonitorError
from utils.logging_config import setup_logging
from utils.security import validate_interval, validate_pid

PROJECT_ROOT = Path(__file__).resolve().parent

try:
    from rich.console import Console

    _console: Console | None = Console()
except ImportError:  # pragma: no cover
    _console = None


def _out(message: str) -> None:
    (_console.print if _console else print)(message)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="FILE", help="Path to settings.yaml.")
    common.add_argument("--thresholds", metavar="FILE", help="Path to thresholds.yaml.")
    common.add_argument("--verbose", "-v", action="store_true", help="DEBUG logging.")
    common.add_argument("--quiet", "-q", action="store_true", help="Suppress snapshot output.")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="shm", description="System Health Monitor")
    parser.add_argument("--version", action="version", version="System Health Monitor 1.0.0")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("monitor", parents=[common], help="Run periodic monitoring with alerts.")
    p.add_argument("--interval", type=float, help="Seconds between samples.")
    p.add_argument("--cycles", type=int, help="Number of cycles (default: run until Ctrl-C).")
    p.add_argument("--no-store", action="store_true", help="Do not write metrics to the database.")
    p.add_argument("--no-alerts", action="store_true", help="Do not dispatch alerts.")

    p = sub.add_parser("dashboard", parents=[common], help="Live auto-refreshing dashboard.")
    p.add_argument("--interval", type=float, help="Refresh interval in seconds.")
    p.add_argument("--duration", type=float, help="Seconds to run (default: until Ctrl-C).")

    p = sub.add_parser("report", parents=[common], help="Generate a health report.")
    p.add_argument("--format", choices=list(report_generator.SUPPORTED_FORMATS))
    p.add_argument("--json", action="store_true")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--html", action="store_true")
    p.add_argument("--pdf", action="store_true")
    p.add_argument("--output", "-o", metavar="DIR", help="Output directory.")

    p = sub.add_parser("history", parents=[common], help="Query stored metric/alert history.")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--subsystem")
    p.add_argument("--metric")
    p.add_argument("--summary", action="store_true")

    p = sub.add_parser("alerts", parents=[common], help="Show alerts (recent or current).")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--now", action="store_true", help="Evaluate the current snapshot instead of history.")

    p = sub.add_parser("processes", parents=[common], help="Show top processes or control one.")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--details", type=int, metavar="PID", help="Show details for a PID.")
    p.add_argument("--kill", type=int, metavar="PID")
    p.add_argument("--suspend", type=int, metavar="PID")
    p.add_argument("--resume", type=int, metavar="PID")
    p.add_argument("--force", action="store_true", help="Skip confirmation for control actions.")

    p = sub.add_parser("services", parents=[common], help="Show status of watched services.")
    p.add_argument("--watch", nargs="*", help="Override the services to check.")

    p = sub.add_parser("watch", parents=[common], help="Watch folders for filesystem changes in real time.")
    p.add_argument("paths", nargs="*", help="Directories to watch (defaults to config).")
    p.add_argument("--duration", type=float, help="Seconds to watch (default: until Ctrl-C).")
    p.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None)

    sub.add_parser("config", parents=[common], help="Print the effective configuration.")

    return parser


# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------
def _load(args) -> Config:
    return Config.load(getattr(args, "config", None), getattr(args, "thresholds", None))


def _open_db(cfg: Config) -> MetricsDB | None:
    try:
        db = MetricsDB(PROJECT_ROOT / cfg.get("database.path", "database/metrics.db"))
        retention = int(cfg.get("database.retention_days", 30))
        db.prune(retention)
        return db
    except MonitorError as exc:
        _out(f"[yellow]History disabled: {exc}[/yellow]" if _console else f"History disabled: {exc}")
        return None


def _print_snapshot(snapshot: HealthSnapshot) -> None:
    if _console:
        _console.print(dashboard_mod.render_snapshot(snapshot))
    else:
        print(dashboard_mod._plain(snapshot))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def cmd_monitor(args, cfg, db) -> int:
    interval = validate_interval(args.interval if args.interval is not None else cfg.get("general.interval", 2.0))
    collector = Collector(cfg)
    alerts = None if args.no_alerts else AlertManager(cfg, db)
    store_db = None if args.no_store else db

    def show(snapshot: HealthSnapshot) -> None:
        if not args.quiet:
            _print_snapshot(snapshot)

    cycles = scheduler.run_periodic(
        collector, interval=interval, cycles=args.cycles,
        db=store_db, alert_manager=alerts, on_snapshot=show,
    )
    _out(f"Completed {cycles} monitoring cycle(s).")
    return 0


def cmd_dashboard(args, cfg, db) -> int:
    interval = validate_interval(args.interval if args.interval is not None else cfg.get("general.interval", 2.0))
    collector = Collector(cfg)
    alerts = AlertManager(cfg, db)
    count = dashboard_mod.run_dashboard(
        collector, interval=interval, duration=args.duration, alert_manager=alerts, db=db
    )
    _out(f"Rendered {count} snapshot(s).")
    return 0


def cmd_report(args, cfg, db) -> int:
    collector = Collector(cfg)
    snapshot = collector.collect()
    if db is not None:
        db.store_results(snapshot.results)
    if not args.quiet:
        _print_snapshot(snapshot)

    fmt = args.format
    for shortcut in ("json", "csv", "html", "pdf"):
        if getattr(args, shortcut):
            fmt = shortcut
    fmt = fmt or cfg.get("reporting.default_format", "json")

    output_dir = args.output or (PROJECT_ROOT / cfg.get("reporting.directory", "reports"))
    roots = cfg.get("security.allowed_output_roots", []) or None
    path = report_generator.generate_report(snapshot, fmt=fmt, output_dir=output_dir, allowed_roots=roots)
    _out(f"[green]Report written: {path}[/green]" if _console else f"Report written: {path}")
    return 0


def cmd_history(args, cfg, db) -> int:
    if db is None:
        _out("History unavailable.")
        return 1
    if args.summary:
        _out(json.dumps(db.summary(), indent=2))
        return 0
    rows = db.recent_metrics(subsystem=args.subsystem, name=args.metric, limit=args.limit)
    if not rows:
        _out("No history yet.")
        return 0
    for row in rows:
        _out(f"  {row['timestamp']}  {row['subsystem']:>11}.{row['name']:<18} "
             f"{row['value']}{row['unit'] or ''}  [{row['severity']}]")
    return 0


def cmd_alerts(args, cfg, db) -> int:
    if args.now:
        collector = Collector(cfg)
        snapshot = collector.collect()
        alerts = AlertManager(cfg, db).evaluate(snapshot)
        if not alerts:
            _out("[green]No active alerts — all systems nominal.[/green]" if _console else "No active alerts.")
            return 0
        for alert in alerts:
            _out(f"  [{alert.severity.label}] {alert.message}")
        return 0
    if db is None:
        _out("Alert history unavailable.")
        return 1
    rows = db.recent_alerts(limit=args.limit)
    if not rows:
        _out("No alerts recorded.")
        return 0
    for row in rows:
        _out(f"  {row['timestamp']}  [{row['severity']}] {row['message']}")
    return 0


def cmd_processes(args, cfg, db) -> int:
    monitor = ProcessMonitor(cfg.thresholds_for("process"), top_n=args.top)

    # Control actions (mutually exclusive with the listing).
    for verb, pid in (("kill", args.kill), ("suspend", args.suspend), ("resume", args.resume)):
        if pid is not None:
            return _process_action(monitor, verb, pid, force=args.force)

    if args.details is not None:
        try:
            details = monitor.details(validate_pid(args.details))
        except (ProcessNotFoundError, ProcessAccessDeniedError) as exc:
            _out(f"[red]{exc}[/red]" if _console else str(exc))
            return 1
        _out(json.dumps(details, indent=2, default=str))
        return 0

    result = monitor.collect()
    _out(f"Processes: {result.get('process_count').value}  Zombies: {result.get('zombie_count').value}")
    for metric in result.metrics:
        if metric.name.startswith("top_cpu_"):
            t = metric.tags
            _out(f"  PID {t.get('pid'):>6}  {metric.value:>5}% CPU  {t.get('name')}")
    return 0


def _process_action(monitor: ProcessMonitor, verb: str, pid: int, *, force: bool) -> int:
    if not force:
        answer = input(f"Really {verb} PID {pid}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            _out("Cancelled.")
            return 1
    try:
        getattr(monitor, verb)(pid, force=True)
        _out(f"[green]{verb} sent to PID {pid}.[/green]" if _console else f"{verb} sent to PID {pid}.")
        return 0
    except (ProcessNotFoundError, ProcessAccessDeniedError, ValueError) as exc:
        _out(f"[red]{exc}[/red]" if _console else str(exc))
        return 1


def cmd_services(args, cfg, db) -> int:
    watch = args.watch if args.watch is not None else list(cfg.get("services.watch", []) or [])
    monitor = ServiceMonitor(cfg.thresholds_for("service"), watch=watch)
    result = monitor.collect()
    if not watch:
        _out("No services configured to watch (set services.watch in settings.yaml or use --watch).")
        return 0
    for metric in result.metrics:
        if metric.name == "service_state":
            _out(f"  {metric.tags.get('service'):<20} {metric.value:<12} [{metric.severity.label}]")
    return 0


def cmd_watch(args, cfg, db) -> int:
    paths = args.paths or list(cfg.get("filesystem.watch", []) or [])
    if not paths:
        _out("No folders to watch. Pass paths or set filesystem.watch in settings.yaml.")
        return 1
    recursive = args.recursive if args.recursive is not None else bool(cfg.get("filesystem.recursive", True))
    counts = filesystem_monitor.watch(paths, recursive=recursive, duration=args.duration)
    total = sum(counts.values())
    _out(f"Observed {total} event(s): {counts}")
    return 0


def cmd_config(args, cfg, db) -> int:
    _out(json.dumps({"settings": cfg.settings, "thresholds": cfg.thresholds}, indent=2))
    return 0


_HANDLERS = {
    "monitor": cmd_monitor,
    "dashboard": cmd_dashboard,
    "report": cmd_report,
    "history": cmd_history,
    "alerts": cmd_alerts,
    "processes": cmd_processes,
    "services": cmd_services,
    "watch": cmd_watch,
    "config": cmd_config,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    cfg = _load(args)
    log_cfg = dict(cfg.settings.get("logging", {}))
    if args.verbose:
        log_cfg["level"] = "DEBUG"
    setup_logging(log_cfg, root=PROJECT_ROOT)

    db = _open_db(cfg)
    try:
        return _HANDLERS[args.command](args, cfg, db)
    except MonitorError as exc:
        _out(f"[red]Error: {exc}[/red]" if _console else f"Error: {exc}")
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
