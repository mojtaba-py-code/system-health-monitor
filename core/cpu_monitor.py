"""CPU monitoring: overall/per-core usage, frequency, load and context switches."""

from __future__ import annotations

import os

import psutil

from core.base import Metric, Monitor, MonitorResult


class CpuMonitor(Monitor):
    name = "cpu"

    def __init__(self, thresholds=None) -> None:
        super().__init__(thresholds)
        # cpu_percent needs a baseline; the first read primes it.
        self._primed = False

    def _collect(self, result: MonitorResult) -> None:
        interval = None if self._primed else 0.1
        overall = psutil.cpu_percent(interval=interval)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        self._primed = True

        result.add(
            Metric(
                name="usage_percent",
                value=round(overall, 1),
                unit="%",
                severity=self.severity_for("usage_percent", overall),
            )
        )

        if per_core:
            for index, value in enumerate(per_core):
                result.add(
                    Metric(
                        name=f"core_{index}_percent",
                        value=round(value, 1),
                        unit="%",
                        severity=self.severity_for("usage_percent", value),
                        tags={"core": index},
                    )
                )
            result.add(Metric(name="core_count", value=len(per_core), unit="cores"))

        # Frequency (may be unavailable in some virtualised environments).
        try:
            freq = psutil.cpu_freq()
            if freq:
                result.add(Metric(name="frequency_mhz", value=round(freq.current, 1), unit="MHz"))
        except (OSError, AttributeError, NotImplementedError):
            pass

        # Load average → normalise per core so the threshold is portable.
        try:
            load1, load5, load15 = os.getloadavg()
            cores = psutil.cpu_count() or 1
            per_core_load = load1 / cores
            result.add(
                Metric(
                    name="load_per_core",
                    value=round(per_core_load, 2),
                    unit="",
                    severity=self.severity_for("load_per_core", per_core_load),
                    tags={"load1": round(load1, 2), "load5": round(load5, 2), "load15": round(load15, 2)},
                )
            )
        except (OSError, AttributeError):
            # os.getloadavg() is unavailable on Windows — that is expected.
            pass

        try:
            stats = psutil.cpu_stats()
            result.add(Metric(name="context_switches", value=stats.ctx_switches, unit="count"))
            result.add(Metric(name="interrupts", value=stats.interrupts, unit="count"))
        except (OSError, NotImplementedError):
            pass
