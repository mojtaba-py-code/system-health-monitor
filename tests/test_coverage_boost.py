"""Extra tests to raise coverage: sensors, services, PDF, alert channels, CLI."""

from __future__ import annotations

import types
from collections import namedtuple
from pathlib import Path

import main as cli
import pytest

from core import report_generator
from core.alert_manager import Alert, AlertManager
from core.base import Severity
from core.report_generator import render_pdf
from core.service_monitor import ServiceMonitor
from core.temperature_monitor import TemperatureMonitor
from utils.config import Config
from utils.exceptions import MonitorError


# --- temperature with faked sensors ---------------------------------------
def test_temperature_with_faked_sensors(monkeypatch: pytest.MonkeyPatch) -> None:
    Shwtemp = namedtuple("shwtemp", ["label", "current", "high", "critical"])
    fake = {"coretemp": [Shwtemp("Core 0", 55.0, 90.0, 100.0), Shwtemp("Core 1", 82.0, 90.0, 100.0)]}
    import psutil

    monkeypatch.setattr(psutil, "sensors_temperatures", lambda: fake, raising=False)
    result = TemperatureMonitor({"celsius": {"warning": 75, "critical": 90}}).collect()
    hottest = result.get("celsius")
    assert hottest is not None and hottest.value == 82.0
    assert hottest.severity == Severity.WARNING


# --- service monitor query paths ------------------------------------------
def test_service_monitor_with_faked_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = ServiceMonitor(watch=["svc-a", "svc-b"])
    monkeypatch.setattr(monitor, "_query", lambda name: "running" if name == "svc-a" else "stopped")
    result = monitor.collect()
    states = {m.tags["service"]: (m.value, m.severity) for m in result.metrics if m.name == "service_state"}
    assert states["svc-a"][0] == "running" and states["svc-a"][1] == Severity.OK
    assert states["svc-b"][1] == Severity.CRITICAL
    assert result.get("running_services").value == 1


# --- report PDF path (reportlab not installed -> clear error) --------------
def test_pdf_requires_reportlab(critical_snapshot, tmp_path: Path) -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        with pytest.raises(MonitorError):
            render_pdf(critical_snapshot, tmp_path / "r.pdf")
    else:  # pragma: no cover - only if reportlab happens to be installed
        render_pdf(critical_snapshot, tmp_path / "r.pdf")
        assert (tmp_path / "r.pdf").exists()


def test_report_render_html_contains_status(critical_snapshot) -> None:
    html = report_generator.render(critical_snapshot, "html")
    assert "System Health Report" in html
    assert "CRITICAL" in html


# --- alert channels --------------------------------------------------------
def test_alert_console_and_desktop_channels(critical_snapshot, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = Config.load(None, None)
    cfg.settings["alerts"]["channels"] = ["console", "desktop"]
    manager = AlertManager(cfg)
    fired = manager.process(critical_snapshot)
    assert len(fired) == 2
    out = capsys.readouterr().out
    assert "ALERT" in out  # console channel printed


def test_alert_webhook_https_monkeypatched(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config.load(None, None)
    cfg.settings["alerts"]["channels"] = ["webhook"]
    cfg.settings["alerts"]["webhook_url"] = "https://example.com/hook"
    manager = AlertManager(cfg)

    calls = {}

    def fake_post(url, json, timeout):
        calls["url"] = url
        calls["json"] = json
        return types.SimpleNamespace(status_code=200)

    import core.alert_manager as am

    monkeypatch.setattr(am.requests, "post", fake_post)
    manager._webhook(Alert("cpu", "usage_percent", Severity.CRITICAL, 99, "msg"), "msg")
    assert calls["url"] == "https://example.com/hook"


# --- extra CLI handlers ----------------------------------------------------
@pytest.fixture
def light_config(tmp_path: Path) -> Path:
    db_path = (tmp_path / "m.db").as_posix()
    content = (
        "monitors:\n  network: false\n  process: false\n  service: false\n"
        "  temperature: false\n  disk: false\n"
        f"database:\n  path: {db_path}\n"
        "logging:\n  console: false\n"
    )
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


def test_cli_dashboard_bounded(light_config: Path) -> None:
    assert cli.main(["dashboard", "--duration", "0.1", "--interval", "0.1", "--config", str(light_config)]) == 0


def test_cli_alerts_now(light_config: Path) -> None:
    assert cli.main(["alerts", "--now", "--config", str(light_config)]) == 0


def test_cli_processes_top(light_config: Path) -> None:
    assert cli.main(["processes", "--top", "3", "--config", str(light_config)]) == 0


def test_cli_processes_details_own(light_config: Path) -> None:
    import os

    assert cli.main(["processes", "--details", str(os.getpid()), "--config", str(light_config)]) == 0


def test_cli_processes_kill_protected_returns_error(light_config: Path) -> None:
    # Killing PID 1 with --force is blocked by validate_pid (SecurityError is a
    # MonitorError) -> the top-level handler reports it and returns exit code 2.
    assert cli.main(["processes", "--kill", "1", "--force", "--config", str(light_config)]) == 2
