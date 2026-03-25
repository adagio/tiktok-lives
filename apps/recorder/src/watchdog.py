"""Watchdog — restarts monitor.py if it crashes or hangs, with exponential backoff."""

import logging
import os
import signal
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lockfile import acquire_lock, release_lock

MONITOR_SCRIPT = Path(__file__).resolve().parent / "monitor.py"
HEARTBEAT_PATH = Path(__file__).resolve().parent.parent / "monitor.heartbeat"
LOG_PATH = Path(__file__).resolve().parent.parent / "watchdog.log"
LOCK_PATH = Path(__file__).resolve().parent.parent / "watchdog.lock"
MIN_DELAY = 5       # seconds after first crash
MAX_DELAY = 300     # cap at 5 minutes
HEALTHY_AFTER = 120  # if it ran longer than this, reset delay
HANG_TIMEOUT = 120   # kill monitor if heartbeat older than this
POLL_INTERVAL = 10   # seconds between poll checks

# --- Logging setup ---

log = logging.getLogger("watchdog")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_sh = logging.StreamHandler(sys.stderr)
_sh.setFormatter(_fmt)
log.addHandler(_sh)

_fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_fh)


def _heartbeat_age() -> float | None:
    """Return age of heartbeat file in seconds, or None if missing."""
    try:
        mtime = HEARTBEAT_PATH.stat().st_mtime
        return time.time() - mtime
    except (FileNotFoundError, OSError):
        return None


def _kill_orphan_monitors():
    """Kill any orphaned monitor.py processes from previous runs."""
    try:
        result = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' and commandline like '%monitor.py%'",
             "get", "processid", "/format:list"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("ProcessId="):
                pid = int(line.split("=", 1)[1])
                try:
                    os.kill(pid, signal.SIGTERM)
                    log.info("Killed orphan monitor.py (pid=%d)", pid)
                except OSError:
                    pass
    except Exception:
        log.debug("Orphan monitor cleanup failed", exc_info=True)


def main():
    lock = acquire_lock(LOCK_PATH, caller="watchdog")
    if lock is None:
        sys.exit(0)

    # Clean up orphaned monitor processes from previous crashed runs
    _kill_orphan_monitors()
    time.sleep(2)  # let processes die and release locks

    delay = MIN_DELAY
    stopping = False

    def handle_signal(signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stopping:
        log.info("Starting monitor.py ...")
        started = time.time()

        proc = subprocess.Popen(
            [sys.executable, str(MONITOR_SCRIPT)],
            cwd=str(MONITOR_SCRIPT.parent.parent),
        )

        try:
            while proc.poll() is None:
                if stopping:
                    proc.terminate()
                    proc.wait(timeout=15)
                    break

                # Check for hang via heartbeat (skip grace period)
                uptime = time.time() - started
                if uptime > HANG_TIMEOUT:
                    age = _heartbeat_age()
                    if age is None:
                        log.warning("Heartbeat missing after %ds uptime — monitor hung. Killing.", int(uptime))
                        proc.kill()
                        proc.wait(timeout=10)
                        break
                    if age > HANG_TIMEOUT:
                        log.warning("Heartbeat stale (%ds old) — monitor hung. Killing.", int(age))
                        proc.kill()
                        proc.wait(timeout=10)
                        break

                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            stopping = True
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            break

        elapsed = time.time() - started
        code = proc.returncode

        if stopping:
            log.info("Stopped (monitor exit=%s).", code)
            break

        if elapsed >= HEALTHY_AFTER:
            delay = MIN_DELAY  # was stable, reset backoff

        log.info("Monitor exited (code=%s) after %ds. Restarting in %ds ...", code, int(elapsed), delay)

        # Interruptible sleep
        deadline = time.time() + delay
        while time.time() < deadline and not stopping:
            time.sleep(1)

        delay = min(delay * 2, MAX_DELAY)

    release_lock(lock)
    log.info("Bye.")


if __name__ == "__main__":
    main()
