"""Integration tests for the nine monitor subsystems (run against real psutil)."""

from __future__ import annotations

from core.base import Severity
from core.battery_monitor import BatteryMonitor
from core.cpu_monitor import CpuMonitor
from core.disk_monitor import DiskMonitor
from core.memory_monitor import MemoryMonitor
from core.network_monitor import NetworkMonitor
from core.process_monitor import ProcessMonitor
from core.service_monitor import ServiceMonitor
from core.temperature_monitor import TemperatureMonitor
from core.uptime_monitor import UptimeMonitor


def test_cpu_monitor_reports_usage() -> None:
    result = CpuMonitor({"usage_percent": {"warning": 80, "critical": 95}}).collect()
    assert result.subsystem == "cpu"
    usage = result.get("usage_percent")
    assert usage is not None and 0 <= usage.value <= 100


def test_memory_monitor_reports_percent() -> None:
    result = MemoryMonitor({"usage_percent": {"warning": 80, "critical": 92}}).collect()
    usage = result.get("usage_percent")
    assert usage is not None and 0 <= usage.value <= 100
    assert result.get("total_bytes").value > 0


def test_disk_monitor_reports_partitions() -> None:
    result = DiskMonitor({"usage_percent": {"warning": 80, "critical": 92}}).collect()
    # At least one usage_percent metric should exist on any real system.
    assert any(m.name == "usage_percent" for m in result.metrics)


def test_network_monitor_reports_counters() -> None:
    result = NetworkMonitor().collect()
    assert result.get("total_sent_bytes") is not None
    assert result.get("active_interfaces") is not None


def test_process_monitor_reports_top() -> None:
    result = ProcessMonitor(top_n=3).collect()
    assert result.get("process_count").value > 0
    # Normalised CPU must be within 0..100 (not per-core > 100).
    tops = [m for m in result.metrics if m.name.startswith("top_cpu_")]
    assert all(0 <= m.value <= 100 for m in tops)


def test_service_monitor_without_watch() -> None:
    result = ServiceMonitor(watch=[]).collect()
    assert result.get("watched_services").value == 0


def test_temperature_monitor_graceful() -> None:
    # May or may not have sensors; must never crash and must return something.
    result = TemperatureMonitor().collect()
    assert result.subsystem == "temperature"
    assert result.metrics  # at least the "available: no" marker


def test_battery_monitor_graceful() -> None:
    result = BatteryMonitor().collect()
    assert result.subsystem == "battery"
    assert result.metrics


def test_uptime_monitor_reports_uptime() -> None:
    result = UptimeMonitor().collect()
    assert result.get("uptime_seconds").value >= 0
    assert result.worst_severity in (Severity.OK, Severity.UNKNOWN)
