"""Final targeted tests to push coverage past 90% (monkeypatched hardware)."""

from __future__ import annotations

import os
import platform
from collections import namedtuple

import psutil
import pytest

from core.cpu_monitor import CpuMonitor
from core.memory_monitor import MemoryMonitor
from core.process_monitor import ProcessMonitor
from core.service_monitor import ServiceMonitor
from utils import security
from utils.exceptions import SecurityError


def test_memory_swap_with_faked_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    Swap = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])
    monkeypatch.setattr(psutil, "swap_memory", lambda: Swap(1000, 400, 600, 40.0, 0, 0))
    result = MemoryMonitor({"swap_percent": {"warning": 50, "critical": 80}}).collect()
    swap = result.get("swap_percent")
    assert swap is not None and swap.value == 40.0
    assert result.get("swap_total_bytes").value == 1000


def test_cpu_with_faked_loadavg_and_freq(monkeypatch: pytest.MonkeyPatch) -> None:
    Freq = namedtuple("scpufreq", ["current", "min", "max"])
    monkeypatch.setattr(psutil, "cpu_freq", lambda: Freq(2400.0, 800.0, 3200.0))
    monkeypatch.setattr(os, "getloadavg", lambda: (1.0, 0.5, 0.2), raising=False)
    result = CpuMonitor({"load_per_core": {"warning": 1.5, "critical": 2.5}}).collect()
    assert result.get("frequency_mhz") is not None
    assert result.get("load_per_core") is not None


def test_process_suspend_resume_guards() -> None:
    monitor = ProcessMonitor()
    with pytest.raises(ValueError):
        monitor.suspend(os.getpid(), force=True)
    with pytest.raises(PermissionError):
        monitor.resume(999_999, force=False)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows service query")
def test_service_query_windows_real() -> None:
    monitor = ServiceMonitor(watch=[])
    # A service that exists on essentially every Windows install.
    state = monitor._query("Dhcp")
    assert isinstance(state, str) and state
    # A service that does not exist resolves to a sentinel, never crashes.
    assert monitor._query("definitely-not-a-real-service-xyz") in ("not_found", "unknown", "stopped")


def test_safe_run_success_with_allowed_command() -> None:
    if platform.system() == "Windows":
        proc = security.safe_run(["sc", "query", "Dhcp"], timeout=8.0)
    else:  # pragma: no cover - exercised on POSIX CI
        proc = security.safe_run(["uptime"], timeout=8.0)
    assert proc.returncode is not None


def test_security_resolve_and_is_within_errors(tmp_path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert security.is_within(a, b) is False
    with pytest.raises(SecurityError):
        security.resolve_path("bad\x00path", strict=True)
