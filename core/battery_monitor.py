"""Battery monitoring for laptops (no-op on desktops without a battery)."""

from __future__ import annotations

import psutil

from core.base import Metric, Monitor, MonitorResult, Severity
from utils.formatting import human_duration


class BatteryMonitor(Monitor):
    name = "battery"

    def _collect(self, result: MonitorResult) -> None:
        getter = getattr(psutil, "sensors_battery", None)
        battery = getter() if getter else None
        if battery is None:
            result.add(Metric(name="present", value="no", unit="",
                              tags={"note": "no battery detected (desktop or unsupported)"}))
            return

        percent = round(battery.percent, 1)
        charging = bool(battery.power_plugged)
        # A low battery is only a concern while discharging.
        severity = self.severity_for("percent", percent) if not charging else Severity.OK

        result.add(
            Metric(
                name="percent",
                value=percent,
                unit="%",
                severity=severity,
                tags={"charging": charging},
            )
        )
        result.add(Metric(name="charging", value="yes" if charging else "no", unit=""))

        secs = battery.secsleft
        if secs is not None and secs >= 0:
            result.add(
                Metric(
                    name="time_left",
                    value=secs,
                    unit="s",
                    tags={"human": human_duration(secs)},
                )
            )
