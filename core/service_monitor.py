"""Service monitoring for Windows services and Linux systemd units.

Only the services named in the configured watch-list are queried, and only via
read-only, allow-listed commands (Linux) or psutil's service API (Windows).
Nothing is ever started or stopped by this monitor.
"""

from __future__ import annotations

import platform

import psutil

from core.base import Metric, Monitor, MonitorResult, Severity
from utils.security import safe_run

_IS_WINDOWS = platform.system() == "Windows"
_IS_LINUX = platform.system() == "Linux"


class ServiceMonitor(Monitor):
    name = "service"

    def __init__(self, thresholds=None, *, watch: list[str] | None = None) -> None:
        super().__init__(thresholds)
        self.watch = list(watch or [])

    def _collect(self, result: MonitorResult) -> None:
        if not self.watch:
            result.add(Metric(name="watched_services", value=0, unit="count",
                              tags={"note": "no services configured to watch"}))
            return

        running = 0
        for service in self.watch:
            state = self._query(service)
            healthy = state in ("running", "active")
            running += int(healthy)
            result.add(
                Metric(
                    name="service_state",
                    value=state,
                    unit="",
                    severity=Severity.OK if healthy else Severity.CRITICAL,
                    tags={"service": service},
                )
            )
        result.add(Metric(name="watched_services", value=len(self.watch), unit="count"))
        result.add(Metric(name="running_services", value=running, unit="count"))

    def _query(self, service: str) -> str:
        try:
            if _IS_WINDOWS:
                return self._query_windows(service)
            if _IS_LINUX:
                return self._query_linux(service)
        except Exception:  # noqa: BLE001 - a query failure is reported as "unknown"
            return "unknown"
        return "unsupported"

    @staticmethod
    def _query_windows(service: str) -> str:
        try:
            svc = psutil.win_service_get(service)  # type: ignore[attr-defined]
            return svc.status()  # e.g. "running", "stopped"
        except Exception:  # noqa: BLE001
            return "not_found"

    @staticmethod
    def _query_linux(service: str) -> str:
        proc = safe_run(["systemctl", "is-active", service], timeout=3.0)
        # systemctl prints active/inactive/failed and returns non-zero when
        # inactive — the stdout is the authoritative state string.
        state = (proc.stdout or "").strip()
        return state or "unknown"
