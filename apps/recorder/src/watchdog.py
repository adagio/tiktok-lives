"""Watchdog — restarts monitor.py if it crashes, with exponential backoff."""

import signal
import subprocess
import sys
import time
from pathlib import Path

MONITOR_SCRIPT = Path(__file__).resolve().parent / "monitor.py"
MIN_DELAY = 5       # seconds after first crash
MAX_DELAY = 300     # cap at 5 minutes
HEALTHY_AFTER = 120  # if it ran longer than this, reset delay


def main():
    delay = MIN_DELAY
    stopping = False

    def handle_signal(signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stopping:
        print(f"[watchdog] Starting monitor.py ...", flush=True)
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
                time.sleep(1)
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
            print(f"[watchdog] Stopped (monitor exit={code}).", flush=True)
            break

        if elapsed >= HEALTHY_AFTER:
            delay = MIN_DELAY  # was stable, reset backoff

        print(
            f"[watchdog] Monitor exited (code={code}) after {elapsed:.0f}s. "
            f"Restarting in {delay}s ...",
            flush=True,
        )

        # Interruptible sleep
        deadline = time.time() + delay
        while time.time() < deadline and not stopping:
            time.sleep(1)

        delay = min(delay * 2, MAX_DELAY)

    print("[watchdog] Bye.", flush=True)


if __name__ == "__main__":
    main()
