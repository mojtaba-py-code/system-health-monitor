"""Logging setup with rotation and dedicated alert/error log files.

* ``monitoring.log`` — everything from the application logger.
* ``errors.log``     — only WARNING and above.
* ``alerts.log``     — messages emitted by the alert logger (``shm.alerts``).

The console handler is colourised when ``colorama`` is available.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

try:
    from colorama import Fore, Style
    from colorama import init as colorama_init

    colorama_init()
    _COLOURS = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.MAGENTA + Style.BRIGHT,
    }
    _RESET = Style.RESET_ALL
except ImportError:  # pragma: no cover
    _COLOURS = {}
    _RESET = ""

APP_LOGGER = "shm"
ALERT_LOGGER = "shm.alerts"
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _ColourFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        colour = _COLOURS.get(record.levelname)
        if colour:
            return message.replace(record.levelname, f"{colour}{record.levelname}{_RESET}", 1)
        return message


def _rotating(path: Path, level: int, cfg: dict[str, Any]) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=int(cfg.get("max_bytes", 5_242_880)),
        backupCount=int(cfg.get("backup_count", 5)),
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    return handler


def setup_logging(config: dict[str, Any] | None = None, *, root: Path | None = None) -> logging.Logger:
    """Configure the application and alert loggers; return the app logger."""
    config = config or {}
    root = root or Path(__file__).resolve().parent.parent
    level = getattr(logging, str(config.get("level", "INFO")).upper(), logging.INFO)

    log_dir = root / str(config.get("directory", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    app = logging.getLogger(APP_LOGGER)
    app.setLevel(level)
    app.propagate = False
    app.handlers.clear()

    app.addHandler(_rotating(log_dir / "monitoring.log", level, config))
    app.addHandler(_rotating(log_dir / "errors.log", logging.WARNING, config))

    if config.get("console", True):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(_ColourFormatter(_FORMAT, datefmt=_DATEFMT))
        app.addHandler(console)

    # Dedicated alerts logger writes to its own file (and bubbles to console
    # via the app logger only if explicitly configured — kept separate here).
    alerts = logging.getLogger(ALERT_LOGGER)
    alerts.setLevel(logging.INFO)
    alerts.propagate = True  # also appear in monitoring.log
    # Remove any alert-specific file handlers from a previous run.
    for handler in list(alerts.handlers):
        alerts.removeHandler(handler)
    alerts.addHandler(_rotating(log_dir / "alerts.log", logging.INFO, config))

    return app


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{APP_LOGGER}.{name}") if name else logging.getLogger(APP_LOGGER)


def get_alert_logger() -> logging.Logger:
    return logging.getLogger(ALERT_LOGGER)
