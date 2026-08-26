"""Concurrent metric collector.

Builds the set of enabled monitors from configuration and runs their
``collect()`` calls **in parallel** with a :class:`ThreadPoolExecutor`. Metric
collection is I/O- and syscall-bound, so threading gives a real wall-clock win
while keeping CPU overhead low. A per-monitor timeout prevents one slow
subsystem (e.g. a stalled sensor) from blocking the whole snapshot.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.base import Monitor, MonitorResult, Severity
from core.battery_monitor import BatteryMonitor
from core.cpu_monitor import CpuMonitor
from core.disk_monitor import DiskMonitor
from core.memory_monitor import MemoryMonitor
from core.network_monitor import NetworkMonitor
from core.process_monitor import ProcessMonitor
from core.service_monitor import ServiceMonitor
from core.temperature_monitor import TemperatureMonitor
from core.uptime_monitor import UptimeMonitor
from utils.config import Config
from utils.logging_config import get_logger

logger = get_logger("collector")


@dataclass
class HealthSnapshot:
    """A single point-in-time view across all enabled subsystems."""

    results: list[MonitorResult] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    @property
    def worst_severity(self) -> Severity:
        severities = [r.worst_severity for r in self.results if r.worst_severity != Severity.UNKNOWN]
        return max(severities) if severities else Severity.UNKNOWN

    def by_subsystem(self, name: str) -> MonitorResult | None:
        for result in self.results:
            if result.subsystem == name:
                return result
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.worst_severity.label,
            "subsystems": {r.subsystem: r.as_dict() for r in self.results},
        }


class Collector:
    """Owns the monitor instances and collects snapshots concurrently."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.workers = max(1, int(config.get("general.workers", 6)))
        self.monitors: list[Monitor] = self._build_monitors(config)

    def _build_monitors(self, config: Config) -> list[Monitor]:
        # Factories receive the subsystem's thresholds and any extra params.
        factories: dict[str, Callable[[], Monitor]] = {
            "cpu": lambda: CpuMonitor(config.thresholds_for("cpu")),
            "memory": lambda: MemoryMonitor(config.thresholds_for("memory")),
            "disk": lambda: DiskMonitor(config.thresholds_for("disk")),
            "network": lambda: NetworkMonitor(config.thresholds_for("network")),
            "process": lambda: ProcessMonitor(
                config.thresholds_for("process"),
                top_n=int(config.get("general.top_processes", 5)),
            ),
            "service": lambda: ServiceMonitor(
                config.thresholds_for("service"),
                watch=list(config.get("services.watch", []) or []),
            ),
            "temperature": lambda: TemperatureMonitor(config.thresholds_for("temperature")),
            "battery": lambda: BatteryMonitor(config.thresholds_for("battery")),
            "uptime": lambda: UptimeMonitor(config.thresholds_for("uptime")),
        }
        monitors: list[Monitor] = []
        for name, factory in factories.items():
            if config.monitor_enabled(name):
                monitors.append(factory())
        logger.debug("Built %d monitor(s): %s", len(monitors), [m.name for m in monitors])
        return monitors

    def collect(self, *, timeout: float = 15.0) -> HealthSnapshot:
        """Run every monitor concurrently and return a snapshot."""
        snapshot = HealthSnapshot()
        if not self.monitors:
            return snapshot

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="shm") as pool:
            future_to_monitor = {pool.submit(m.collect): m for m in self.monitors}
            for future in as_completed(future_to_monitor, timeout=timeout):
                monitor = future_to_monitor[future]
                try:
                    snapshot.results.append(future.result())
                except Exception as exc:  # noqa: BLE001 - never let one monitor abort the run
                    failed = MonitorResult(subsystem=monitor.name)
                    failed.error(f"collector: {type(exc).__name__}: {exc}")
                    snapshot.results.append(failed)
                    logger.error("Monitor %s failed: %s", monitor.name, exc)

        # Keep a stable, human-friendly ordering regardless of completion order.
        order = {m.name: i for i, m in enumerate(self.monitors)}
        snapshot.results.sort(key=lambda r: order.get(r.subsystem, 99))
        return snapshot
