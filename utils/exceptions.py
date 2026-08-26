"""Typed exception hierarchy for the System Health Monitor."""

from __future__ import annotations


class MonitorError(Exception):
    """Base class for all application-specific errors."""


class ConfigError(MonitorError):
    """Configuration could not be loaded or is invalid."""


class SecurityError(MonitorError):
    """An operation would violate a security guarantee."""


class CollectionError(MonitorError):
    """A monitor failed to collect a metric."""


class UnsupportedPlatformError(MonitorError):
    """A feature is not available on the current operating system."""


class DatabaseError(MonitorError):
    """A database operation failed."""


class AlertError(MonitorError):
    """An alert channel failed to deliver."""
