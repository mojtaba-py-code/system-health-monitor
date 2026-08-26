"""Tests for the core data model and utility helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.base import Metric, Monitor, MonitorResult, Severity, Threshold
from utils import formatting
from utils.config import Config, ConfigError
from utils.exceptions import SecurityError
from utils.security import (
    redact,
    safe_run,
    validate_interval,
    validate_output_path,
    validate_pid,
)


# --- Severity / Threshold --------------------------------------------------
def test_severity_ordering() -> None:
    assert Severity.CRITICAL > Severity.WARNING > Severity.OK
    assert max([Severity.OK, Severity.CRITICAL, Severity.WARNING]) == Severity.CRITICAL
    assert Severity.CRITICAL.label == "CRITICAL"


def test_threshold_higher_is_worse() -> None:
    t = Threshold(warning=80, critical=95)
    assert t.evaluate(50) == Severity.OK
    assert t.evaluate(85) == Severity.WARNING
    assert t.evaluate(96) == Severity.CRITICAL
    assert t.evaluate(None) == Severity.UNKNOWN


def test_threshold_lower_is_worse() -> None:
    t = Threshold(warning=20, critical=8, higher_is_worse=False)
    assert t.evaluate(50) == Severity.OK
    assert t.evaluate(15) == Severity.WARNING
    assert t.evaluate(5) == Severity.CRITICAL


def test_threshold_from_mapping() -> None:
    t = Threshold.from_mapping({"warning": 10, "critical": 20, "higher_is_worse": False})
    assert t.higher_is_worse is False
    assert t.critical == 20


# --- Metric / MonitorResult ------------------------------------------------
def test_monitor_result_worst_severity() -> None:
    r = MonitorResult(subsystem="cpu")
    r.add(Metric("a", 1, severity=Severity.OK))
    r.add(Metric("b", 2, severity=Severity.CRITICAL))
    assert r.worst_severity == Severity.CRITICAL
    assert r.get("b").value == 2
    assert r.get("missing") is None
    assert r.as_dict()["worst_severity"] == "CRITICAL"


def test_monitor_base_catches_errors() -> None:
    class Boom(Monitor):
        name = "boom"

        def _collect(self, result: MonitorResult) -> None:
            raise RuntimeError("kaboom")

    result = Boom().collect()
    assert result.errors and "kaboom" in result.errors[0]
    assert result.duration_ms >= 0


# --- formatting ------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [(0, "0 B"), (1024, "1.00 KB"), (1048576, "1.00 MB")])
def test_human_bytes(value: int, expected: str) -> None:
    assert formatting.human_bytes(value) == expected


def test_human_duration_and_percent_and_bar() -> None:
    assert formatting.human_duration(3661) == "01:01:01"
    assert formatting.human_duration(90061).startswith("1d ")
    assert formatting.percent(42.5) == "42.5%"
    assert len(formatting.bar(50, width=10)) == 10


# --- config ----------------------------------------------------------------
def test_config_defaults() -> None:
    cfg = Config.load(None, None)
    assert cfg.get("general.interval") == 2.0
    assert cfg.monitor_enabled("cpu") is True
    assert "usage_percent" in cfg.thresholds_for("cpu")


def test_config_yaml_merge(tmp_path: Path) -> None:
    settings = tmp_path / "s.yaml"
    settings.write_text("general:\n  interval: 5\n", encoding="utf-8")
    cfg = Config.load(settings, None)
    assert cfg.get("general.interval") == 5
    assert cfg.get("general.workers") == 6  # default preserved


def test_config_missing_explicit_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Config.load(tmp_path / "missing.yaml", None)


# --- security --------------------------------------------------------------
def test_validate_interval_range() -> None:
    assert validate_interval(2.0) == 2.0
    with pytest.raises(SecurityError):
        validate_interval(0)
    with pytest.raises(SecurityError):
        validate_interval("abc")


def test_validate_pid_rejects_protected() -> None:
    assert validate_pid(1234) == 1234
    for bad in (0, 1, -5):
        with pytest.raises(SecurityError):
            validate_pid(bad)


def test_validate_output_path_rejects_outside_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    assert validate_output_path(allowed / "r.json", allowed_roots=[allowed])
    with pytest.raises(SecurityError):
        validate_output_path(tmp_path / "elsewhere" / "r.json", allowed_roots=[allowed])


def test_safe_run_refuses_unlisted_command() -> None:
    with pytest.raises(SecurityError):
        safe_run(["rm", "-rf", "/"])
    with pytest.raises(SecurityError):
        safe_run([])


def test_redact_secrets() -> None:
    assert "***" in redact("--password=SuperSecret123")
    assert "***" in redact("token: abcdef")
    assert redact("nothing sensitive here") == "nothing sensitive here"
