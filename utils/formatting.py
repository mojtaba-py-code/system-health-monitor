"""Human-friendly formatting helpers (sizes, rates, durations, bars)."""

from __future__ import annotations

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_bytes(num_bytes: float, *, precision: int = 2) -> str:
    """Format a byte count, e.g. ``1.50 GB``."""
    size = float(max(num_bytes, 0))
    for unit in _SIZE_UNITS:
        if size < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.{precision}f} PB"


def human_rate(bytes_per_sec: float) -> str:
    """Format a transfer rate, e.g. ``2.30 MB/s``."""
    return f"{human_bytes(bytes_per_sec)}/s"


def human_duration(seconds: float) -> str:
    """Format a duration as ``Dd HH:MM:SS`` (days omitted when zero)."""
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def percent(value: float, *, precision: int = 1) -> str:
    return f"{value:.{precision}f}%"


def bar(value: float, *, width: int = 20, maximum: float = 100.0) -> str:
    """Render a simple text progress bar for a 0..maximum value."""
    if maximum <= 0:
        maximum = 100.0
    ratio = min(max(value / maximum, 0.0), 1.0)
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)
