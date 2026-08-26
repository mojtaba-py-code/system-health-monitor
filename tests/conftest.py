"""Shared fixtures and helpers for the test-suite."""

from __future__ import annotations

import pytest

from core.base import Metric, Monitor, MonitorResult, Severity
from core.collector import HealthSnapshot
from utils.config import Config


class FakeMonitor(Monitor):
    """A deterministic monitor for testing orchestration without hardware."""

    def __init__(self, name: str, metrics: list[Metric]):
        super().__init__({})
        self.name = name
        self._metrics = metrics

    def _collect(self, result: MonitorResult) -> None:
        for metric in self._metrics:
            result.add(metric)


def make_metric(name: str, value, severity: Severity = Severity.OK, subsystem: str = "test") -> Metric:
    return Metric(name=name, value=value, unit="%", severity=severity, subsystem=subsystem)


def make_snapshot(*results: MonitorResult) -> HealthSnapshot:
    snap = HealthSnapshot()
    snap.results.extend(results)
    return snap


@pytest.fixture
def critical_snapshot() -> HealthSnapshot:
    """A snapshot containing OK, WARNING and CRITICAL metrics."""
    cpu = MonitorResult(subsystem="cpu")
    cpu.add(make_metric("usage_percent", 97, Severity.CRITICAL, "cpu"))
    mem = MonitorResult(subsystem="memory")
    mem.add(make_metric("usage_percent", 85, Severity.WARNING, "memory"))
    disk = MonitorResult(subsystem="disk")
    disk.add(make_metric("usage_percent", 40, Severity.OK, "disk"))
    return make_snapshot(cpu, mem, disk)


@pytest.fixture
def default_config() -> Config:
    return Config.load(None, None)
