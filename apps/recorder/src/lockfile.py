"""Robust PID-based lockfile for Windows using msvcrt byte-range locks.

Usage:
    lock = acquire_lock(Path("my.lock"))
    if lock is None:
        sys.exit(1)  # another instance is running
    # ... do work ...
    release_lock(lock)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import msvcrt

log = logging.getLogger(__name__)

LOCK_BYTES = 32  # byte range to lock (enough for a PID string)


@dataclass
class Lock:
    path: Path
    fh: object  # file handle


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running on Windows."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == 0:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        # Fallback: try os.kill with signal 0 (doesn't work well on Windows but worth trying)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _read_pid(path: Path) -> int | None:
    """Read PID from lockfile without truncating."""
    try:
        content = path.read_text(encoding="utf-8").strip()
        return int(content) if content else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def acquire_lock(path: Path, caller: str = "process") -> Lock | None:
    """Acquire an exclusive lockfile.

    - Opens without truncating (a+ mode) to avoid destroying existing content.
    - Locks FIRST, then writes PID.
    - If lock fails, checks whether the holding PID is still alive.
      If the holder is dead, removes the stale lock and retries once.

    Returns a Lock handle on success, or None if another instance is running.
    """
    for attempt in range(2):
        try:
            fh = open(path, "a+", encoding="utf-8")
        except OSError as e:
            log.error("Cannot open lockfile %s: %s", path, e)
            return None

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, LOCK_BYTES)
        except (OSError, IOError):
            # Lock failed — someone else holds it
            fh.close()

            if attempt == 0:
                # Check if the holder is still alive
                existing_pid = _read_pid(path)
                if existing_pid is not None and not _is_pid_alive(existing_pid):
                    log.warning(
                        "Stale lockfile %s (pid=%d is dead). Removing and retrying.",
                        path, existing_pid,
                    )
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    time.sleep(0.5)
                    continue  # retry once

            log.info(
                "Another %s instance is already running (lock: %s). Exiting.",
                caller, path,
            )
            return None

        # Lock acquired — now truncate and write our PID
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()).ljust(LOCK_BYTES))
            fh.flush()
        except OSError as e:
            log.error("Failed to write PID to lockfile: %s", e)
            # Still hold the lock, continue anyway

        return Lock(path=path, fh=fh)

    return None


def release_lock(lock: Lock) -> None:
    """Release the lockfile: unlock bytes, close handle, delete file."""
    if lock is None:
        return
    try:
        lock.fh.seek(0)
        msvcrt.locking(lock.fh.fileno(), msvcrt.LK_UNLCK, LOCK_BYTES)
    except Exception:
        pass
    try:
        lock.fh.close()
    except Exception:
        pass
    try:
        lock.path.unlink(missing_ok=True)
    except Exception:
        pass
