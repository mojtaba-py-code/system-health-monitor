"""Tests for real-time filesystem monitoring and the `watch` CLI command."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import main as cli
import pytest

from core import filesystem_monitor
from utils.exceptions import MonitorError


def test_watch_detects_file_creation(tmp_path: Path) -> None:
    watched = tmp_path / "dir"
    watched.mkdir()
    seen: list[tuple[str, str]] = []

    def make_files() -> None:
        time.sleep(0.4)
        (watched / "new.txt").write_text("hello", encoding="utf-8")
        (watched / "new.txt").write_text("changed", encoding="utf-8")

    worker = threading.Thread(target=make_files)
    worker.start()
    counts = filesystem_monitor.watch([watched], duration=1.2, callback=lambda k, p: seen.append((k, p)))
    worker.join()

    assert sum(counts.values()) >= 1
    assert seen  # callback fired at least once


def test_watch_requires_paths() -> None:
    with pytest.raises(MonitorError):
        filesystem_monitor.watch([])


def test_watch_rejects_nonexistent_dir(tmp_path: Path) -> None:
    with pytest.raises(MonitorError):
        filesystem_monitor.watch([tmp_path / "does-not-exist"])


def test_cli_watch(tmp_path: Path) -> None:
    watched = tmp_path / "w"
    watched.mkdir()
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("logging:\n  console: false\n", encoding="utf-8")
    assert cli.main(["watch", str(watched), "--duration", "0.3", "--config", str(cfg)]) == 0


def test_cli_watch_no_paths(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("logging:\n  console: false\n", encoding="utf-8")
    assert cli.main(["watch", "--config", str(cfg)]) == 1
