"""Tests for secure process-control actions and the CLI entry point."""

from __future__ import annotations

import os
from pathlib import Path

import main as cli
import pytest

from core.process_monitor import ProcessAccessDeniedError, ProcessMonitor, ProcessNotFoundError
from utils.exceptions import SecurityError


# --- process control safety ------------------------------------------------
def test_kill_without_force_is_refused() -> None:
    monitor = ProcessMonitor()
    # Public API requires explicit force; otherwise a PermissionError is raised.
    with pytest.raises(PermissionError):
        monitor.kill(999_999, force=False)


def test_kill_protected_pid_refused() -> None:
    monitor = ProcessMonitor()
    with pytest.raises(SecurityError):
        monitor.kill(1, force=True)  # validate_pid blocks PID 0/1


def test_kill_own_process_refused() -> None:
    monitor = ProcessMonitor()
    with pytest.raises(ValueError):
        monitor.kill(os.getpid(), force=True)


def test_kill_nonexistent_pid() -> None:
    monitor = ProcessMonitor()
    with pytest.raises(ProcessNotFoundError):
        monitor.kill(999_999, force=True)


def test_details_of_own_process_is_redacted() -> None:
    monitor = ProcessMonitor()
    details = monitor.details(os.getpid())
    assert details["pid"] == os.getpid()
    assert "cmdline" in details  # present and (if secrets) redacted


def test_details_access_denied_or_not_found() -> None:
    monitor = ProcessMonitor()
    with pytest.raises((ProcessNotFoundError, ProcessAccessDeniedError)):
        monitor.details(999_999)


# --- CLI -------------------------------------------------------------------
@pytest.fixture
def temp_config(tmp_path: Path) -> Path:
    """A settings file that redirects db/reports into a temp directory."""
    db_path = (tmp_path / "metrics.db").as_posix()
    reports = (tmp_path / "reports").as_posix()
    content = (
        "monitors:\n"
        "  network: false\n"      # trim heavy monitors to keep the test quick
        "  process: false\n"
        "  service: false\n"
        f"database:\n  path: {db_path}\n"
        f"reporting:\n  directory: {reports}\n"
        "logging:\n  console: false\n"
    )
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


def test_cli_no_command() -> None:
    assert cli.main([]) == 0


def test_cli_version() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


def test_cli_config(temp_config: Path) -> None:
    assert cli.main(["config", "--config", str(temp_config)]) == 0


def test_cli_report_json(temp_config: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert cli.main(["report", "--json", "--quiet", "--config", str(temp_config), "-o", str(out)]) == 0
    assert list(out.glob("*.json"))


def test_cli_monitor_two_cycles(temp_config: Path) -> None:
    assert cli.main(["monitor", "--cycles", "2", "--interval", "0.1", "--quiet", "--config", str(temp_config)]) == 0


def test_cli_history_and_alerts(temp_config: Path) -> None:
    cli.main(["monitor", "--cycles", "1", "--interval", "0.1", "--quiet", "--config", str(temp_config)])
    assert cli.main(["history", "--summary", "--config", str(temp_config)]) == 0
    assert cli.main(["alerts", "--config", str(temp_config)]) == 0


def test_cli_services_no_watch(temp_config: Path) -> None:
    assert cli.main(["services", "--config", str(temp_config)]) == 0
