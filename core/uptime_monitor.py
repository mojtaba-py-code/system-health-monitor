"""Uptime monitoring: boot time and elapsed uptime."""

from __future__ import annotations

import time
from datetime import datetime

import psutil

from core.base import Metric, Monitor, MonitorResult
from utils.formatting import human_duration


class UptimeMonitor(Monitor):
    name = "uptime"

    def _collect(self, result: MonitorResult) -> None:
        boot = psutil.boot_time()
        uptime_seconds = max(time.time() - boot, 0)
        result.add(
            Metric(
                name="uptime_seconds",
                value=int(uptime_seconds),
                unit="s",
                tags={"human": human_duration(uptime_seconds)},
            )
        )
        result.add(
            Metric(
                name="boot_time",
                value=datetime.fromtimestamp(boot).isoformat(timespec="seconds"),
                unit="",
            )
        )
