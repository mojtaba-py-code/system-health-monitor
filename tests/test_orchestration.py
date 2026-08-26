"""Tests for collector, database, alerts, reports, scheduler and dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import FakeMonitor, make_metric

from core.alert_manager import AlertManager
from core.base import MonitorResult, Severity
from core.collector import Collector, HealthSnapshot
from core.dashboard import _plain, render_snapshot, run_dashboard
from core.report_generator import generate_report, render
from core.scheduler import run_periodic
from database.metrics_db import MetricsDB
from utils.config import Config
from utils.exceptions import MonitorError


# --- database --------------------------------------------------------------
def test_database_store_and_query(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    result = MonitorResult(subsystem="cpu")
    result.add(make_metric("usage_percent", 55, Severity.OK, "cpu"))
    result.add(make_metric("usage_percent", 99, Severity.CRITICAL, "cpu"))
    stored = db.store_result(result)
    assert stored == 2
    rows = db.recent_metrics(subsystem="cpu", limit=10)
    assert len(rows) == 2
    agg = db.aggregate("cpu", "usage_percent")
    assert agg["count"] == 2 and agg["max"] == 99


def test_database_alerts_and_summary(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    metric = make_metric("usage_percent", 99, Severity.CRITICAL, "cpu")
    db.store_alert("cpu", metric, "cpu critical")
    assert db.recent_alerts()[0]["message"] == "cpu critical"
    summary = db.summary()
    assert summary["alert_rows"] == 1


def test_database_prune(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    old = MonitorResult(subsystem="cpu")
    m = make_metric("x", 1, Severity.OK, "cpu")
    m.timestamp = "2000-01-01T00:00:00+00:00"  # ancient
    old.add(m)
    db.store_result(old)
    removed = db.prune(retention_days=1)
    assert removed >= 1


# --- collector (with fake monitors) ---------------------------------------
def test_collector_runs_monitors_concurrently(default_config: Config) -> None:
    collector = Collector(default_config)
    # Replace real monitors with deterministic fakes.
    collector.monitors = [
        FakeMonitor("cpu", [make_metric("usage_percent", 10, Severity.OK, "cpu")]),
        FakeMonitor("memory", [make_metric("usage_percent", 99, Severity.CRITICAL, "memory")]),
    ]
    snapshot = collector.collect()
    assert len(snapshot.results) == 2
    assert snapshot.worst_severity == Severity.CRITICAL
    assert snapshot.by_subsystem("cpu") is not None


def test_collector_real_build(default_config: Config) -> None:
    collector = Collector(default_config)
    assert len(collector.monitors) == 9  # all enabled by default
    snapshot = collector.collect()
    assert snapshot.results


# --- alerts ----------------------------------------------------------------
def test_alert_manager_evaluates(critical_snapshot: HealthSnapshot, default_config: Config) -> None:
    manager = AlertManager(default_config)
    alerts = manager.evaluate(critical_snapshot)
    # CPU critical + memory warning = 2 alerts (disk OK excluded).
    assert len(alerts) == 2
    assert any(a.severity == Severity.CRITICAL for a in alerts)


def test_alert_manager_cooldown(critical_snapshot: HealthSnapshot, tmp_path: Path) -> None:
    cfg = Config.load(None, None)
    cfg.settings["alerts"]["channels"] = ["log"]
    cfg.settings["alerts"]["cooldown_seconds"] = 999
    db = MetricsDB(tmp_path / "m.db")
    manager = AlertManager(cfg, db)
    first = manager.process(critical_snapshot)
    second = manager.process(critical_snapshot)  # within cooldown
    assert len(first) == 2
    assert second == []  # suppressed
    assert len(db.recent_alerts()) == 2


def test_alert_webhook_rejects_non_https(default_config: Config) -> None:
    cfg = Config.load(None, None)
    cfg.settings["alerts"]["channels"] = ["webhook"]
    cfg.settings["alerts"]["webhook_url"] = "http://insecure.example.com/hook"
    manager = AlertManager(cfg)
    # Should not raise; the non-HTTPS URL is simply refused internally.
    from core.alert_manager import Alert

    manager._webhook(Alert("cpu", "x", Severity.CRITICAL, 99, "msg"), "msg")


# --- reports ---------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["json", "csv", "txt", "html"])
def test_report_formats(critical_snapshot: HealthSnapshot, tmp_path: Path, fmt: str) -> None:
    path = generate_report(critical_snapshot, fmt=fmt, output_dir=tmp_path)
    assert path.exists() and path.suffix == f".{fmt}"
    assert path.read_text(encoding="utf-8").strip()


def test_report_render_string(critical_snapshot: HealthSnapshot) -> None:
    assert "CRITICAL" in render(critical_snapshot, "txt")
    assert "usage_percent" in render(critical_snapshot, "csv")


def test_report_unsupported_format(critical_snapshot: HealthSnapshot, tmp_path: Path) -> None:
    with pytest.raises(MonitorError):
        generate_report(critical_snapshot, fmt="xml", output_dir=tmp_path)


# --- scheduler -------------------------------------------------------------
def test_scheduler_runs_bounded_cycles(default_config: Config, tmp_path: Path) -> None:
    collector = Collector(default_config)
    collector.monitors = [FakeMonitor("cpu", [make_metric("usage_percent", 99, Severity.CRITICAL, "cpu")])]
    db = MetricsDB(tmp_path / "m.db")
    manager = AlertManager(default_config, db)
    seen: list[HealthSnapshot] = []
    cycles = run_periodic(
        collector, interval=0.01, cycles=3, db=db, alert_manager=manager,
        on_snapshot=seen.append,
    )
    assert cycles == 3
    assert len(seen) == 3
    assert db.summary()["metric_rows"] == 3


# --- dashboard -------------------------------------------------------------
def test_dashboard_render(critical_snapshot: HealthSnapshot) -> None:
    # render_snapshot returns a rich renderable or a string; must not raise.
    rendered = render_snapshot(critical_snapshot)
    assert rendered is not None
    assert "CRITICAL" in _plain(critical_snapshot)


def test_dashboard_run_bounded(default_config: Config) -> None:
    collector = Collector(default_config)
    collector.monitors = [FakeMonitor("cpu", [make_metric("usage_percent", 10, Severity.OK, "cpu")])]
    count = run_dashboard(collector, interval=0.01, duration=0.05)
    assert count >= 1
