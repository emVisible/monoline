"""One data directory, one live server.

`monoline start` resumes every job the DB left in `running`/`queued`. That is correct after a
crash and destructive when a *different live process* is the one working on them: a second
instance was measured hijacking a 377-second film and rendering a duplicate while the first
was still muxing it — both writing into the same workspace, neither knowing about the other.

So startup asks one narrow question — is there a process that both exists **and** answers on
the port it recorded? — and refuses rather than hijacking. Both conditions are required: a
stale lock from a crashed run must not lock the tool out, and a recycled pid must not either.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

LOCK_FILE = "instance.json"


def lock_path(settings) -> Path:
    return settings.app_dir / LOCK_FILE


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, just not ours to signal
    return True


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def live_instance(settings) -> dict | None:
    """Another instance that is provably serving this data directory, else None."""
    try:
        info = json.loads(lock_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    try:
        pid, port = int(info["pid"]), int(info["port"])
    except (KeyError, TypeError, ValueError):
        return None
    if pid == os.getpid():
        return None
    return info if (_pid_alive(pid) and _port_open(settings.host, port)) else None


def claim(settings) -> None:
    settings.app_dir.mkdir(parents=True, exist_ok=True)
    lock_path(settings).write_text(json.dumps(
        {"pid": os.getpid(), "port": settings.port, "started": time.strftime("%Y-%m-%dT%H:%M:%S")},
        ensure_ascii=False), encoding="utf-8")


def release(settings) -> None:
    """Drop the lock, but never somebody else's."""
    other = None
    try:
        other = json.loads(lock_path(settings).read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        pass
    if other is not None and int(other) != os.getpid():
        return
    lock_path(settings).unlink(missing_ok=True)
