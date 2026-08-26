"""Memory monitoring: RAM and swap usage."""

from __future__ import annotations

import psutil

from core.base import Metric, Monitor, MonitorResult
from utils.formatting import human_bytes


class MemoryMonitor(Monitor):
    name = "memory"

    def _collect(self, result: MonitorResult) -> None:
        vm = psutil.virtual_memory()
        result.add(
            Metric(
                name="usage_percent",
                value=round(vm.percent, 1),
                unit="%",
                severity=self.severity_for("usage_percent", vm.percent),
                tags={
                    "total": human_bytes(vm.total),
                    "used": human_bytes(vm.used),
                    "available": human_bytes(vm.available),
                },
            )
        )
        result.add(Metric(name="total_bytes", value=vm.total, unit="B"))
        result.add(Metric(name="used_bytes", value=vm.used, unit="B"))
        result.add(Metric(name="available_bytes", value=vm.available, unit="B"))

        # Cached / buffers are platform-specific attributes.
        for attr in ("cached", "buffers"):
            value = getattr(vm, attr, None)
            if value is not None:
                result.add(Metric(name=f"{attr}_bytes", value=value, unit="B"))

        # swap_memory() can raise on Windows when performance counters are
        # disabled; degrade gracefully so RAM metrics are still reported.
        try:
            swap = psutil.swap_memory()
        except (RuntimeError, OSError) as exc:
            result.error(f"swap unavailable: {exc}")
            return
        result.add(
            Metric(
                name="swap_percent",
                value=round(swap.percent, 1),
                unit="%",
                severity=self.severity_for("swap_percent", swap.percent),
                tags={"total": human_bytes(swap.total), "used": human_bytes(swap.used)},
            )
        )
        result.add(Metric(name="swap_total_bytes", value=swap.total, unit="B"))
        result.add(Metric(name="swap_used_bytes", value=swap.used, unit="B"))
