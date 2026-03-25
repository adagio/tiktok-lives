"""Install/uninstall/status for the TikTokMonitorWatchdog scheduled task.

Uses schtasks.exe — works without admin elevation.
The task runs run_watchdog.vbs every 5 minutes via wscript (hidden, no console window).
The watchdog lockfile prevents duplicate instances.
"""

import argparse
import os
import subprocess
import sys

TASK_NAME = "TikTokMonitorWatchdog"
VBS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_watchdog.vbs")


def _run_schtasks(*args: str) -> subprocess.CompletedProcess:
    cmd = ["schtasks", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def install():
    if not os.path.exists(VBS_PATH):
        print(f"ERROR: {VBS_PATH} not found", file=sys.stderr)
        sys.exit(1)

    # Delete existing task if present
    _run_schtasks("/Delete", "/TN", TASK_NAME, "/F")

    # Create task: every 5 minutes, run the VBS wrapper (hidden)
    result = _run_schtasks(
        "/Create", "/TN", TASK_NAME,
        "/SC", "MINUTE", "/MO", "5",
        "/TR", f"wscript.exe {VBS_PATH}",
        "/F",
    )
    if result.returncode != 0:
        print(f"Failed to register task:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Task '{TASK_NAME}' registered (every 5 min).")
    print(f"VBS wrapper: {VBS_PATH}")


def uninstall():
    result = _run_schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if result.returncode == 0:
        print(f"Task '{TASK_NAME}' removed.")
    else:
        print(f"Task '{TASK_NAME}' not found.")


def status():
    result = _run_schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V")
    if result.returncode != 0:
        print(f"Task '{TASK_NAME}' not found.")
        return
    keys = {"TaskName", "Status", "Last Run Time", "Last Result", "Next Run Time"}
    for line in result.stdout.strip().splitlines():
        for key in keys:
            if line.strip().startswith(key + ":"):
                print(line.strip())


def main():
    parser = argparse.ArgumentParser(description="Manage TikTokMonitorWatchdog scheduled task")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Register the scheduled task")
    group.add_argument("--uninstall", action="store_true", help="Remove the scheduled task")
    group.add_argument("--status", action="store_true", help="Show task status")
    args = parser.parse_args()

    if args.install:
        install()
    elif args.uninstall:
        uninstall()
    elif args.status:
        status()


if __name__ == "__main__":
    main()
