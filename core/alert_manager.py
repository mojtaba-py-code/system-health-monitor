"""Alert generation and dispatch.

Evaluates a :class:`HealthSnapshot`, raises an alert for every metric at
WARNING/CRITICAL, and dispatches it to the configured channels (console, log
file, desktop notification, webhook). A per-key cooldown prevents alert storms
when a metric hovers around a threshold.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.base import Metric, Severity
from core.collector import HealthSnapshot
from database.metrics_db import MetricsDB
from utils.config import Config
from utils.logging_config import get_alert_logger, get_logger
from utils.security import redact

logger = get_logger("alerts")
alert_logger = get_alert_logger()

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


@dataclass
class Alert:
    subsystem: str
    metric: str
    severity: Severity
    value: Any
    message: str

    @property
    def key(self) -> str:
        return f"{self.subsystem}:{self.metric}"


class AlertManager:
    """Turns threshold breaches into dispatched, de-duplicated alerts."""

    def __init__(self, config: Config, db: MetricsDB | None = None) -> None:
        self.config = config
        self.db = db
        self.channels = list(config.get("alerts.channels", ["console", "log"]) or [])
        self.cooldown = float(config.get("alerts.cooldown_seconds", 60))
        self.webhook_url = str(config.get("alerts.webhook_url", "") or "")
        self._redact = bool(config.get("security.redact_secrets", True))
        self._last_sent: dict[str, float] = {}

    # -- evaluation --------------------------------------------------------
    def evaluate(self, snapshot: HealthSnapshot) -> list[Alert]:
        alerts: list[Alert] = []
        for result in snapshot.results:
            for metric in result.metrics:
                if metric.severity in (Severity.WARNING, Severity.CRITICAL):
                    alerts.append(self._build_alert(result.subsystem, metric))
        return alerts

    @staticmethod
    def _build_alert(subsystem: str, metric: Metric) -> Alert:
        message = (
            f"{subsystem}.{metric.name} = {metric.value}{metric.unit} "
            f"[{metric.severity.label}]"
        )
        return Alert(subsystem, metric.name, metric.severity, metric.value, message)

    # -- dispatch ----------------------------------------------------------
    def process(self, snapshot: HealthSnapshot) -> list[Alert]:
        """Evaluate, de-duplicate by cooldown, dispatch and persist alerts."""
        dispatched: list[Alert] = []
        now = time.monotonic()
        for alert in self.evaluate(snapshot):
            last = self._last_sent.get(alert.key)
            if last is not None and (now - last) < self.cooldown:
                continue  # still within cooldown window
            self._last_sent[alert.key] = now
            self._dispatch(alert)
            self._persist(alert)
            dispatched.append(alert)
        return dispatched

    def _dispatch(self, alert: Alert) -> None:
        text = redact(alert.message) if self._redact else alert.message
        if "console" in self.channels:
            self._console(alert, text)
        if "log" in self.channels:
            alert_logger.warning(text)
        if "desktop" in self.channels:
            self._desktop(alert, text)
        if "webhook" in self.channels and self.webhook_url:
            self._webhook(alert, text)

    @staticmethod
    def _console(alert: Alert, text: str) -> None:
        colour = "\033[91m" if alert.severity == Severity.CRITICAL else "\033[93m"
        print(f"{colour}[ALERT] {text}\033[0m")

    def _desktop(self, alert: Alert, text: str) -> None:
        # Desktop toasts need a platform library that is not a hard dependency.
        # Attempt it best-effort and degrade to a log note otherwise.
        try:
            from plyer import notification  # type: ignore

            notification.notify(title=f"System Alert: {alert.subsystem}", message=text, timeout=5)
        except Exception:  # noqa: BLE001
            logger.debug("Desktop notifications unavailable (install 'plyer' to enable).")

    def _webhook(self, alert: Alert, text: str) -> None:
        if requests is None:
            logger.debug("Webhook channel requires the 'requests' package.")
            return
        if not self.webhook_url.lower().startswith("https://"):
            logger.warning("Refusing to send webhook to non-HTTPS URL.")
            return
        payload = {
            "subsystem": alert.subsystem,
            "metric": alert.metric,
            "severity": alert.severity.label,
            "value": alert.value,
            "message": text,
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as exc:  # noqa: BLE001 - a webhook failure must not crash monitoring
            logger.error("Webhook delivery failed: %s", exc)

    def _persist(self, alert: Alert) -> None:
        if self.db is None:
            return
        try:
            metric = Metric(name=alert.metric, value=alert.value, severity=alert.severity, subsystem=alert.subsystem)
            self.db.store_alert(alert.subsystem, metric, alert.message)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not persist alert: %s", exc)
