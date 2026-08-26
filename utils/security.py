"""Security primitives: input validation, path sanitisation, safe subprocess.

The monitor is a *read-mostly* tool, but it still touches the filesystem
(reports, config, database) and can perform privileged actions (killing
processes, querying services). This module centralises the guarantees:

* Output/config paths are resolved and, when configured, confined to allowed
  roots — no directory traversal.
* Sub-processes are executed without a shell and only from a curated
  allow-list, with a timeout — eliminating shell-injection and hangs.
* Process IDs and interval values are validated before use.
* Sensitive strings (command lines, environment) can be redacted before they
  are logged or exported.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from utils.exceptions import SecurityError

# Commands the tool is ever allowed to invoke (resolved to absolute paths at
# call time). Anything not on this list is refused outright.
_ALLOWED_COMMANDS = frozenset(
    {"systemctl", "sc", "sc.exe", "powershell", "powershell.exe", "sensors", "uptime"}
)

# Patterns that commonly indicate a secret embedded in a command line.
_SECRET_PATTERNS = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key)"
    r"\s*[=:]\s*\S+"
)


def resolve_path(path: str | os.PathLike[str], *, strict: bool = False) -> Path:
    """Resolve *path* to an absolute path, collapsing ``..`` segments."""
    # Rejected explicitly rather than left to the platform: a NUL byte raises
    # ValueError on POSIX and OSError on Windows up to 3.12, but Windows 3.13
    # resolves such a path without complaint, which would let it through
    # validation and fail later at the point of writing.
    if chr(0) in os.fspath(path):
        raise SecurityError(f"Invalid path {path!r}: embedded NUL byte")
    try:
        return Path(path).expanduser().resolve(strict=strict)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SecurityError(f"Invalid path {path!r}: {exc}") from exc


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    # Fail closed: an unresolvable path is not inside the allowed root.
    except (ValueError, OSError, RuntimeError):
        return False


def validate_output_path(
    path: str | os.PathLike[str],
    *,
    allowed_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> Path:
    """Validate a path we are about to WRITE to.

    Rejects traversal outside *allowed_roots* (when provided) and refuses to
    write onto an existing symlink (a classic redirection trick).
    """
    original = Path(path).expanduser()
    if original.is_symlink():
        raise SecurityError(f"Refusing to write through a symlink: {path}")
    resolved = resolve_path(path, strict=False)
    if allowed_roots:
        roots = [resolve_path(r) for r in allowed_roots]
        if not any(is_within(resolved, root) for root in roots):
            raise SecurityError(f"Path {resolved} is outside the allowed output roots")
    return resolved


def validate_interval(value: float, *, minimum: float = 0.1, maximum: float = 86_400) -> float:
    """Validate a polling interval (seconds) to a sane range."""
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise SecurityError(f"Interval must be a number, got {value!r}") from exc
    if not (minimum <= seconds <= maximum):
        raise SecurityError(f"Interval {seconds}s out of range [{minimum}, {maximum}]")
    return seconds


def validate_pid(pid: int) -> int:
    """Validate a process id is a positive integer (and not PID 0/1)."""
    try:
        value = int(pid)
    except (TypeError, ValueError) as exc:
        raise SecurityError(f"Invalid PID {pid!r}") from exc
    if value <= 1:
        # PID 0 and 1 are the kernel/init — never valid targets for kill.
        raise SecurityError(f"Refusing to target protected PID {value}")
    return value


def safe_run(
    command: Sequence[str],
    *,
    timeout: float = 5.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run *command* safely: no shell, allow-listed executable, with a timeout.

    Raises :class:`SecurityError` if the executable is not allow-listed.
    """
    if not command:
        raise SecurityError("Empty command")
    executable = Path(command[0]).name.lower()
    if executable not in _ALLOWED_COMMANDS:
        raise SecurityError(f"Command not permitted: {command[0]}")
    if shutil.which(command[0]) is None and not Path(command[0]).exists():
        raise SecurityError(f"Command not found: {command[0]}")
    try:
        return subprocess.run(  # noqa: S603 - shell=False, allow-listed, timed
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SecurityError(f"Command timed out: {command[0]}") from exc


def redact(text: str) -> str:
    """Redact obvious secrets from a string before logging/exporting it."""
    if not text:
        return text
    return _SECRET_PATTERNS.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", text)


def redact_iter(items: Iterable[str]) -> list[str]:
    return [redact(item) for item in items]
