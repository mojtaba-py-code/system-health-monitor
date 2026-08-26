"""Layered configuration: built-in defaults merged with YAML overrides.

Two files are recognised:

* ``settings.yaml`` — general behaviour (intervals, logging, alerts, paths).
* ``thresholds.yaml`` — per-subsystem warning/critical values.

Missing files fall back to safe defaults; an explicitly requested file that is
absent raises, so typos are caught instead of silently ignored.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from utils.exceptions import ConfigError

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

DEFAULT_SETTINGS: dict[str, Any] = {
    "general": {
        "interval": 2.0,          # seconds between samples
        "workers": 6,             # ThreadPoolExecutor size for the collector
        "top_processes": 5,       # how many hottest processes to report
    },
    "security": {
        "allowed_output_roots": [],  # confine reports/db writes when set
        "redact_secrets": True,
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
        "max_bytes": 5_242_880,
        "backup_count": 5,
        "console": True,
    },
    "database": {
        "path": "database/metrics.db",
        "retention_days": 30,
    },
    "reporting": {
        "directory": "reports",
        "default_format": "json",
    },
    "alerts": {
        "channels": ["console", "log"],  # console | log | desktop | webhook
        "webhook_url": "",
        "cooldown_seconds": 60,          # suppress repeat alerts for the same key
    },
    "monitors": {
        # Enable/disable individual subsystems.
        "cpu": True,
        "memory": True,
        "disk": True,
        "network": True,
        "process": True,
        "service": True,
        "temperature": True,
        "battery": True,
        "uptime": True,
    },
    "services": {
        # Critical services to watch (names are OS-specific).
        "watch": [],
    },
    "filesystem": {
        # Directories to watch for create/modify/delete/move events.
        "watch": [],
        "recursive": True,
    },
}

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "cpu": {
        "usage_percent": {"warning": 80, "critical": 95},
        "load_per_core": {"warning": 1.5, "critical": 2.5},
    },
    "memory": {
        "usage_percent": {"warning": 80, "critical": 92},
        "swap_percent": {"warning": 50, "critical": 80},
    },
    "disk": {
        "usage_percent": {"warning": 80, "critical": 92},
        "free_percent": {"warning": 20, "critical": 8, "higher_is_worse": False},
    },
    "network": {
        "throughput_mbps": {"warning": 500, "critical": 900},
    },
    "temperature": {
        "celsius": {"warning": 75, "critical": 90},
    },
    "battery": {
        "percent": {"warning": 20, "critical": 10, "higher_is_worse": False},
    },
    "process": {
        "cpu_percent": {"warning": 70, "critical": 90},
        "memory_percent": {"warning": 20, "critical": 40},
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path, *, explicit: bool, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        if explicit:
            raise ConfigError(f"Config file not found: {path}")
        return copy.deepcopy(default)
    if yaml is None:  # pragma: no cover
        raise ConfigError("PyYAML is required to read configuration files")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # type: ignore[union-attr]
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return _deep_merge(default, loaded)


class Config:
    """Access point for settings and thresholds with dotted lookups."""

    def __init__(self, settings: dict[str, Any], thresholds: dict[str, Any]) -> None:
        self._settings = settings
        self._thresholds = thresholds

    @classmethod
    def load(
        cls,
        settings_path: str | Path | None = None,
        thresholds_path: str | Path | None = None,
    ) -> Config:
        s_path = Path(settings_path) if settings_path else CONFIG_DIR / "settings.yaml"
        t_path = Path(thresholds_path) if thresholds_path else CONFIG_DIR / "thresholds.yaml"
        settings = _load_yaml(s_path, explicit=settings_path is not None, default=DEFAULT_SETTINGS)
        thresholds = _load_yaml(t_path, explicit=thresholds_path is not None, default=DEFAULT_THRESHOLDS)
        return cls(settings, thresholds)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._settings
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def thresholds_for(self, subsystem: str) -> dict[str, Any]:
        value = self._thresholds.get(subsystem, {})
        return value if isinstance(value, dict) else {}

    def monitor_enabled(self, name: str) -> bool:
        return bool(self.get(f"monitors.{name}", True))

    @property
    def settings(self) -> dict[str, Any]:
        return self._settings

    @property
    def thresholds(self) -> dict[str, Any]:
        return self._thresholds
