"""Historical metric and alert storage backed by SQLite.

All queries are parameterised (no string interpolation of values) to eliminate
SQL-injection risk. The database is created lazily and can prune old rows based
on a configurable retention window.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.base import Metric, MonitorResult
from utils.exceptions import DatabaseError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    subsystem  TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    value      REAL,
    unit       TEXT,
    severity   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts   ON metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_key  ON metrics(subsystem, name);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    subsystem  TEXT    NOT NULL,
    metric     TEXT    NOT NULL,
    severity   TEXT    NOT NULL,
    value      REAL,
    message    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp);
"""


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class MetricsDB:
    """Thin, safe wrapper around the metrics/alerts SQLite database."""

    def __init__(self, db_path: str | Path = "database/metrics.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(self.db_path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Cannot open database {self.db_path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise DatabaseError(str(exc)) from exc
        finally:
            conn.close()

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- writes ------------------------------------------------------------
    def store_result(self, result: MonitorResult) -> int:
        """Persist every metric in a :class:`MonitorResult`; return row count."""
        rows: list[Sequence[Any]] = [
            (m.timestamp, m.subsystem, m.name, _numeric(m.value), m.unit, m.severity.label)
            for m in result.metrics
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO metrics (timestamp, subsystem, name, value, unit, severity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def store_results(self, results: Sequence[MonitorResult]) -> int:
        return sum(self.store_result(r) for r in results)

    def store_alert(self, subsystem: str, metric: Metric, message: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO alerts (timestamp, subsystem, metric, severity, value, message) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    metric.timestamp,
                    subsystem,
                    metric.name,
                    metric.severity.label,
                    _numeric(metric.value),
                    message,
                ),
            )
            return int(cursor.lastrowid)

    # -- reads -------------------------------------------------------------
    def recent_metrics(
        self, *, subsystem: str | None = None, name: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM metrics"
        clauses: list[str] = []
        params: list[Any] = []
        if subsystem:
            clauses.append("subsystem = ?")
            params.append(subsystem)
        if name:
            clauses.append("name = ?")
            params.append(name)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def aggregate(self, subsystem: str, name: str) -> dict[str, Any]:
        """Return avg/min/max/count for a metric across all stored samples."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count, AVG(value) AS avg, MIN(value) AS min, "
                "MAX(value) AS max FROM metrics WHERE subsystem = ? AND name = ?",
                (subsystem, name),
            ).fetchone()
        return {
            "subsystem": subsystem,
            "name": name,
            "count": row["count"],
            "avg": round(row["avg"], 2) if row["avg"] is not None else None,
            "min": row["min"],
            "max": row["max"],
        }

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            metrics = conn.execute("SELECT COUNT(*) AS c FROM metrics").fetchone()["c"]
            alerts = conn.execute("SELECT COUNT(*) AS c FROM alerts").fetchone()["c"]
            span = conn.execute(
                "SELECT MIN(timestamp) AS first, MAX(timestamp) AS last FROM metrics"
            ).fetchone()
        return {
            "metric_rows": metrics,
            "alert_rows": alerts,
            "first_sample": span["first"],
            "last_sample": span["last"],
        }

    # -- maintenance -------------------------------------------------------
    def prune(self, retention_days: int) -> int:
        """Delete rows older than *retention_days*; return rows removed."""
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            cur1 = conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
            cur2 = conn.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff,))
            removed = cur1.rowcount + cur2.rowcount
        return int(removed)
