"""Temperature monitoring via hardware sensors (where exposed by the OS)."""

from __future__ import annotations

import psutil

from core.base import Metric, Monitor, MonitorResult


class TemperatureMonitor(Monitor):
    name = "temperature"

    def _collect(self, result: MonitorResult) -> None:
        getter = getattr(psutil, "sensors_temperatures", None)
        if getter is None:
            result.add(Metric(name="available", value="no", unit="",
                              tags={"note": "temperature sensors unsupported on this platform"}))
            return
        try:
            readings = getter()
        except (OSError, NotImplementedError):
            readings = {}

        if not readings:
            result.add(Metric(name="available", value="no", unit="",
                              tags={"note": "no temperature sensors detected"}))
            return

        hottest = 0.0
        for chip, entries in readings.items():
            for entry in entries:
                if entry.current is None:
                    continue
                hottest = max(hottest, entry.current)
                label = entry.label or chip
                result.add(
                    Metric(
                        name="sensor_celsius",
                        value=round(entry.current, 1),
                        unit="°C",
                        severity=self.severity_for("celsius", entry.current),
                        tags={"chip": chip, "label": label, "high": entry.high, "critical": entry.critical},
                    )
                )
        result.add(
            Metric(
                name="celsius",
                value=round(hottest, 1),
                unit="°C",
                severity=self.severity_for("celsius", hottest),
                tags={"note": "hottest sensor"},
            )
        )
