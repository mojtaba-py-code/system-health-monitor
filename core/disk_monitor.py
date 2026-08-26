"""Disk monitoring: per-partition usage plus aggregate I/O throughput."""

from __future__ import annotations

import time

import psutil

from core.base import Metric, Monitor, MonitorResult
from utils.formatting import human_bytes


class DiskMonitor(Monitor):
    name = "disk"

    def __init__(self, thresholds=None) -> None:
        super().__init__(thresholds)
        self._prev_io: tuple[float, int, int] | None = None

    def _collect(self, result: MonitorResult) -> None:
        self._collect_usage(result)
        self._collect_io(result)

    def _collect_usage(self, result: MonitorResult) -> None:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (OSError, PermissionError):
                # Empty CD-ROM drives etc. raise — skip them quietly.
                continue
            free_percent = 100.0 - usage.percent
            tag = {"mount": part.mountpoint, "fstype": part.fstype, "total": human_bytes(usage.total)}
            result.add(
                Metric(
                    name="usage_percent",
                    value=round(usage.percent, 1),
                    unit="%",
                    severity=self.severity_for("usage_percent", usage.percent),
                    tags={**tag, "device": part.device},
                )
            )
            result.add(
                Metric(
                    name="free_percent",
                    value=round(free_percent, 1),
                    unit="%",
                    severity=self.severity_for("free_percent", free_percent),
                    tags={**tag, "free": human_bytes(usage.free)},
                )
            )

    def _collect_io(self, result: MonitorResult) -> None:
        io = psutil.disk_io_counters()
        if io is None:
            return
        now = time.monotonic()
        if self._prev_io is None:
            # Prime with a short sample so a one-shot call still yields a rate.
            self._prev_io = (now, io.read_bytes, io.write_bytes)
            time.sleep(0.2)
            io = psutil.disk_io_counters()
            now = time.monotonic()
        prev_t, prev_r, prev_w = self._prev_io
        elapsed = max(now - prev_t, 1e-6)
        read_rate = max(io.read_bytes - prev_r, 0) / elapsed
        write_rate = max(io.write_bytes - prev_w, 0) / elapsed
        self._prev_io = (now, io.read_bytes, io.write_bytes)

        result.add(
            Metric(
                name="read_rate_bytes",
                value=round(read_rate),
                unit="B/s",
                tags={"human": f"{human_bytes(read_rate)}/s"},
            )
        )
        result.add(
            Metric(
                name="write_rate_bytes",
                value=round(write_rate),
                unit="B/s",
                tags={"human": f"{human_bytes(write_rate)}/s"},
            )
        )
