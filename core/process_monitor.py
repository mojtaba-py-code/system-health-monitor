"""Process monitoring: hottest processes, zombies and safe control actions.

The control actions (kill / suspend / resume) are the only "write" operations
in the whole application, so they are guarded: PIDs are validated, protected
PIDs (0/1) are refused, and the caller must pass ``force=True`` or confirm.
"""

from __future__ import annotations

import time

import psutil

from core.base import Metric, Monitor, MonitorResult
from utils.logging_config import get_logger
from utils.security import redact, validate_pid

logger = get_logger("process")


class ProcessMonitor(Monitor):
    name = "process"

    def __init__(self, thresholds=None, *, top_n: int = 5) -> None:
        super().__init__(thresholds)
        self.top_n = max(1, int(top_n))

    # Pseudo-processes that represent idle time, not real load (skip in tops).
    _IDLE_NAMES = frozenset({"System Idle Process", "Idle"})

    def _collect(self, result: MonitorResult) -> None:
        procs = list(psutil.process_iter(["pid", "name", "username", "status"]))
        cpu_count = psutil.cpu_count() or 1

        # Prime cpu_percent for all processes, then sample after a short delay
        # so the reported per-process CPU is meaningful rather than zero.
        for proc in procs:
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.15)

        snapshots: list[dict] = []
        zombies = 0
        for proc in procs:
            try:
                with proc.oneshot():
                    name = proc.info.get("name") or "?"
                    if proc.pid == 0 or name in self._IDLE_NAMES:
                        continue  # idle/kernel pseudo-process, not real load
                    status = proc.info.get("status")
                    if status == psutil.STATUS_ZOMBIE:
                        zombies += 1
                    # Normalise to % of total system capacity (0-100), since
                    # psutil reports up to 100% *per core*.
                    cpu = proc.cpu_percent(interval=None) / cpu_count
                    mem = proc.memory_percent()
                    snapshots.append(
                        {
                            "pid": proc.pid,
                            "name": proc.info.get("name") or "?",
                            "user": proc.info.get("username") or "?",
                            "cpu_percent": round(cpu, 1),
                            "memory_percent": round(mem, 1),
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        result.add(Metric(name="process_count", value=len(procs), unit="count"))
        result.add(Metric(name="zombie_count", value=zombies, unit="count",
                          severity=self.severity_for("zombie_count", zombies)))

        top_cpu = sorted(snapshots, key=lambda s: s["cpu_percent"], reverse=True)[: self.top_n]
        for rank, snap in enumerate(top_cpu, start=1):
            result.add(
                Metric(
                    name=f"top_cpu_{rank}",
                    value=snap["cpu_percent"],
                    unit="%",
                    severity=self.severity_for("cpu_percent", snap["cpu_percent"]),
                    tags={"pid": snap["pid"], "name": snap["name"], "user": snap["user"]},
                )
            )

        top_mem = sorted(snapshots, key=lambda s: s["memory_percent"], reverse=True)[: self.top_n]
        for rank, snap in enumerate(top_mem, start=1):
            result.add(
                Metric(
                    name=f"top_mem_{rank}",
                    value=snap["memory_percent"],
                    unit="%",
                    severity=self.severity_for("memory_percent", snap["memory_percent"]),
                    tags={"pid": snap["pid"], "name": snap["name"]},
                )
            )

    # -- control actions ---------------------------------------------------
    def details(self, pid: int) -> dict:
        """Return safe, redacted details for a single process."""
        pid = validate_pid(pid)
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                cmdline = " ".join(proc.cmdline())
                return {
                    "pid": pid,
                    "name": proc.name(),
                    "status": proc.status(),
                    "user": proc.username(),
                    "cpu_percent": proc.cpu_percent(interval=0.1),
                    "memory_percent": round(proc.memory_percent(), 2),
                    "create_time": proc.create_time(),
                    "cmdline": redact(cmdline),
                }
        except psutil.NoSuchProcess as exc:
            raise ProcessNotFoundError(pid) from exc
        except psutil.AccessDenied as exc:
            raise ProcessAccessDeniedError(pid) from exc

    def _action(self, pid: int, verb: str, force: bool) -> bool:
        pid = validate_pid(pid)
        if pid == psutil.Process().pid:
            raise ValueError("Refusing to target the monitor's own process")
        if not force:
            # Callers must explicitly authorise; the CLI handles confirmation.
            raise PermissionError(f"{verb} on PID {pid} requires explicit confirmation")
        try:
            proc = psutil.Process(pid)
            getattr(proc, verb)()
            logger.warning("Process %s (%s) -> %s", pid, proc.name(), verb)
            return True
        except psutil.NoSuchProcess as exc:
            raise ProcessNotFoundError(pid) from exc
        except psutil.AccessDenied as exc:
            raise ProcessAccessDeniedError(pid) from exc

    def kill(self, pid: int, *, force: bool = False) -> bool:
        return self._action(pid, "terminate", force)

    def suspend(self, pid: int, *, force: bool = False) -> bool:
        return self._action(pid, "suspend", force)

    def resume(self, pid: int, *, force: bool = False) -> bool:
        return self._action(pid, "resume", force)


class ProcessNotFoundError(LookupError):
    def __init__(self, pid: int) -> None:
        super().__init__(f"No process with PID {pid}")
        self.pid = pid


class ProcessAccessDeniedError(PermissionError):
    def __init__(self, pid: int) -> None:
        super().__init__(f"Access denied to PID {pid} (try elevated privileges)")
        self.pid = pid
