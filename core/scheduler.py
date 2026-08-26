"""Periodic monitoring scheduler.

Runs a collection callback at a fixed interval, persisting metrics and firing
alerts each cycle. Supports a bounded number of cycles (for tests / one-off
runs) or unbounded until interrupted.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from core.collector import Collector, HealthSnapshot
from utils.logging_config import get_logger

logger = get_logger("scheduler")


def run_periodic(
    collector: Collector,
    *,
    interval: float = 5.0,
    cycles: int | None = None,
    db=None,
    alert_manager=None,
    on_snapshot: Callable[[HealthSnapshot], None] | None = None,
) -> int:
    """Collect a snapshot every *interval* seconds.

    Parameters
    ----------
    cycles:
        Number of collection cycles to run. ``None`` runs until Ctrl-C.

    Returns the number of cycles completed.
    """
    completed = 0
    logger.info("Starting periodic monitoring every %.1fs%s", interval,
                f" for {cycles} cycle(s)" if cycles else " (until interrupted)")
    try:
        while cycles is None or completed < cycles:
            snapshot = collector.collect()
            completed += 1

            if db is not None:
                try:
                    stored = db.store_results(snapshot.results)
                    logger.debug("Stored %d metric row(s)", stored)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to store metrics: %s", exc)

            if alert_manager is not None:
                fired = alert_manager.process(snapshot)
                if fired:
                    logger.info("Dispatched %d alert(s) this cycle", len(fired))

            if on_snapshot is not None:
                on_snapshot(snapshot)

            if cycles is not None and completed >= cycles:
                break
            time.sleep(interval)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        logger.info("Monitoring stopped by user after %d cycle(s).", completed)
    return completed
