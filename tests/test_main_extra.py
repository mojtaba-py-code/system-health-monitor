"""Extra CLI-path tests to exercise remaining main.py branches."""

from __future__ import annotations

from pathlib import Path

import main as cli
import pytest


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    db_path = (tmp_path / "m.db").as_posix()
    reports = (tmp_path / "reports").as_posix()
    content = (
        "monitors:\n"
        "  network: false\n  process: false\n  service: false\n"
        "  temperature: false\n  disk: false\n  battery: false\n"
        f"database:\n  path: {db_path}\n"
        f"reporting:\n  directory: {reports}\n  default_format: txt\n"
        "logging:\n  console: false\n"
        "alerts:\n  channels: [log]\n"
    )
    path = tmp_path / "settings.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_cli_verbose_flag(cfg_file: Path) -> None:
    assert cli.main(["config", "-v", "--config", str(cfg_file)]) == 0


def test_cli_report_default_format(cfg_file: Path, tmp_path: Path) -> None:
    # No --json/--csv shortcut: falls back to configured default (txt).
    out = tmp_path / "r"
    assert cli.main(["report", "--quiet", "--config", str(cfg_file), "-o", str(out)]) == 0
    assert list(out.glob("*.txt"))


def test_cli_history_rows_and_alerts_history(cfg_file: Path) -> None:
    # Produce data, then read it back (non-summary paths).
    assert cli.main(["monitor", "--cycles", "2", "--interval", "0.1", "--quiet", "--config", str(cfg_file)]) == 0
    assert cli.main(["history", "--limit", "5", "--config", str(cfg_file)]) == 0
    assert cli.main(["alerts", "--limit", "5", "--config", str(cfg_file)]) == 0


def test_cli_services_with_watch_override(cfg_file: Path) -> None:
    # Provide an explicit watch list so the services listing branch runs.
    assert cli.main(["services", "--watch", "nonexistent-svc", "--config", str(cfg_file)]) == 0
