"""Real-time file-system monitoring for important folders.

Unlike the metric monitors (which sample a point-in-time value), this watches
directories continuously and reports create / modify / delete / move events via
``watchdog``. Paths are validated before watching, and if ``watchdog`` is not
installed a clear, actionable error is raised instead of an obscure failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from utils.exceptions import MonitorError
from utils.logging_config import get_logger
from utils.security import resolve_path

logger = get_logger("filesystem")

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG = True
except ImportError:  # pragma: no cover - exercised only without watchdog
    _WATCHDOG = False
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


EventCallback = Callable[[str, str], None]


class _EventHandler(FileSystemEventHandler):  # type: ignore[misc]
    """Logs every relevant event and forwards it to an optional callback."""

    def __init__(self, callback: EventCallback | None = None) -> None:
        super().__init__()
        self.callback = callback
        self.counts: dict[str, int] = {"created": 0, "modified": 0, "deleted": 0, "moved": 0}

    def on_any_event(self, event: FileSystemEvent) -> None:  # type: ignore[name-defined]
        kind = event.event_type
        if kind not in self.counts:
            return
        # Directory "modified" events are noisy and rarely actionable.
        if event.is_directory and kind == "modified":
            return
        self.counts[kind] += 1
        path = getattr(event, "dest_path", "") or event.src_path
        logger.info("[FS] %-8s %s", kind.upper(), path)
        if self.callback:
            try:
                self.callback(kind, path)
            except Exception as exc:  # noqa: BLE001 - a callback must not kill the watcher
                logger.error("Filesystem callback error: %s", exc)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def watch(
    paths: list[str | Path],
    *,
    recursive: bool = True,
    duration: float | None = None,
    callback: EventCallback | None = None,
) -> dict[str, int]:
    """Watch *paths* for filesystem changes.

    Parameters
    ----------
    duration:
        Seconds to watch before stopping. ``None`` watches until Ctrl-C.

    Returns a mapping of event-type -> count observed.
    """
    if not _WATCHDOG:
        raise MonitorError(
            "The 'watchdog' package is required for filesystem monitoring. "
            "Install it with: pip install watchdog"
        )
    if not paths:
        raise MonitorError("No paths to watch. Provide paths or set filesystem.watch in config.")

    targets: list[Path] = []
    for raw in paths:
        resolved = resolve_path(raw, strict=False)
        if not resolved.exists() or not resolved.is_dir():
            logger.warning("Skipping non-directory watch path: %s", resolved)
            continue
        targets.append(resolved)
    if not targets:
        raise MonitorError("None of the provided watch paths are valid directories.")

    handler = _EventHandler(callback)
    observer = Observer()
    for target in targets:
        observer.schedule(handler, str(target), recursive=recursive)
    observer.start()
    logger.info("Watching %d folder(s) for changes. Press Ctrl-C to stop.", len(targets))

    start = time.monotonic()
    try:
        while True:
            time.sleep(0.5)
            if duration is not None and (time.monotonic() - start) >= duration:
                break
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.info("Filesystem monitoring interrupted by user.")
    finally:
        observer.stop()
        observer.join()

    logger.info("Filesystem monitoring stopped after %d event(s).", handler.total)
    return dict(handler.counts)
