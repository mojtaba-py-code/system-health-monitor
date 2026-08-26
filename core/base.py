"""Core data model shared by every monitor.

Everything the application collects is expressed as a :class:`Metric` with a
:class:`Severity` derived from configurable :class:`Threshold` rules. A monitor
returns a :class:`MonitorResult` bundling its metrics, so the collector, alert
manager, database and reporting layers all speak the same language.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any


class Severity(IntEnum):
    """Ordered severity levels (higher = worse) for easy comparison."""

    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = -1

    @property
    def label(self) -> str:
        return {
            Severity.OK: "OK",
            Severity.WARNING: "WARNING",
            Severity.CRITICAL: "CRITICAL",
            Severity.UNKNOWN: "UNKNOWN",
        }[self]


@dataclass(frozen=True)
class Threshold:
    """A warning/critical threshold with an explicit "worse" direction.

    ``higher_is_worse=True`` (default) means the value crossing *above* the
    thresholds is bad (e.g. CPU usage). ``False`` means crossing *below* is bad
    (e.g. free disk space or battery percentage).
    """

    warning: float | None = None
    critical: float | None = None
    higher_is_worse: bool = True

    def evaluate(self, value: float) -> Severity:
        if value is None:
            return Severity.UNKNOWN
        if self.higher_is_worse:
            if self.critical is not None and value >= self.critical:
                return Severity.CRITICAL
            if self.warning is not None and value >= self.warning:
                return Severity.WARNING
        else:
            if self.critical is not None and value <= self.critical:
                return Severity.CRITICAL
            if self.warning is not None and value <= self.warning:
                return Severity.WARNING
        return Severity.OK

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Threshold:
        return cls(
            warning=data.get("warning"),
            critical=data.get("critical"),
            higher_is_worse=bool(data.get("higher_is_worse", True)),
        )


@dataclass
class Metric:
    """A single measured value with its severity and metadata."""

    name: str
    value: float | int | str | None
    unit: str = ""
    severity: Severity = Severity.OK
    subsystem: str = ""
    tags: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "severity": self.severity.label,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }


@dataclass
class MonitorResult:
    """The output of a single monitor's :meth:`Monitor.collect` call."""

    subsystem: str
    metrics: list[Metric] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    collected_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    duration_ms: int = 0

    def add(self, metric: Metric) -> Metric:
        metric.subsystem = metric.subsystem or self.subsystem
        self.metrics.append(metric)
        return metric

    def error(self, message: str) -> None:
        self.errors.append(message)

    @property
    def worst_severity(self) -> Severity:
        real = [m.severity for m in self.metrics if m.severity != Severity.UNKNOWN]
        return max(real) if real else Severity.UNKNOWN

    def get(self, name: str) -> Metric | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "collected_at": self.collected_at,
            "duration_ms": self.duration_ms,
            "worst_severity": self.worst_severity.label,
            "metrics": [m.as_dict() for m in self.metrics],
            "errors": self.errors,
        }


class Monitor(ABC):
    """Abstract base class for all monitors.

    Subclasses implement :meth:`_collect`, adding metrics to the provided
    result. The public :meth:`collect` wraps that with timing and top-level
    error handling so a single failing monitor never crashes the collector.
    """

    #: Short subsystem identifier, e.g. "cpu".
    name: str = "base"

    def __init__(self, thresholds: Mapping[str, Any] | None = None) -> None:
        self._thresholds: dict[str, Threshold] = {}
        for key, spec in (thresholds or {}).items():
            if isinstance(spec, Mapping):
                self._thresholds[key] = Threshold.from_mapping(spec)

    def threshold_for(self, key: str) -> Threshold | None:
        return self._thresholds.get(key)

    def severity_for(self, key: str, value: float | None) -> Severity:
        threshold = self._thresholds.get(key)
        if threshold is None or value is None:
            return Severity.OK if value is not None else Severity.UNKNOWN
        return threshold.evaluate(value)

    @abstractmethod
    def _collect(self, result: MonitorResult) -> None:
        """Populate *result* with metrics. Implemented by subclasses."""

    def collect(self) -> MonitorResult:
        result = MonitorResult(subsystem=self.name)
        start = time.perf_counter()
        try:
            self._collect(result)
        except Exception as exc:  # noqa: BLE001 - isolate monitor failures
            result.error(f"{type(exc).__name__}: {exc}")
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        return result
