"""Watchdog — restarts monitor.py if it crashes or hangs, with exponential backoff."""

import logging
import signal
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

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


def _acquire_lock():
    """Acquire exclusive lockfile. Returns file handle or None if already locked."""
    import msvcrt

    fh = open(LOCK_PATH, "w")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except (OSError, IOError):
        fh.close()
        return None


def main():
    lock_fh = _acquire_lock()
    if lock_fh is None:
        log.info("Another watchdog instance is already running (lock: %s). Exiting.", LOCK_PATH)
        sys.exit(0)

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
                    if age is not None and age > HANG_TIMEOUT:
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

    log.info("Bye.")


if __name__ == "__main__":
    main()
