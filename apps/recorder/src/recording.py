"""Shared recording logic for TikTok live streams."""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

import psutil
import yt_dlp
from yt_dlp.utils import DownloadError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FFMPEG = r"D:\bin\ffmpeg.exe"


class AdoptedProcess:
    """Wraps a psutil.Process to match subprocess.Popen interface for re-attached ffmpeg."""

    def __init__(self, pid: int):
        self._proc = psutil.Process(pid)
        self.pid = pid

    def poll(self) -> int | None:
        try:
            if not self._proc.is_running() or self._proc.status() == psutil.STATUS_ZOMBIE:
                return -1
            return None
        except psutil.NoSuchProcess:
            return -1

    def terminate(self):
        self._proc.terminate()

    def kill(self):
        self._proc.kill()

    def wait(self, timeout=None):
        self._proc.wait(timeout=timeout)


def check_is_live(username: str) -> dict | None:
    """Return {"url": stream_url} if user is live, None if not.

    Catches DownloadError (user not live / page unavailable).
    Other exceptions propagate.
    """
    tiktok_url = f"https://www.tiktok.com/@{username}/live"
    ydl_opts = {"quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tiktok_url, download=False)
    except DownloadError:
        return None

    url = info.get("url")
    if not url:
        formats = info.get("formats", [])
        if not formats:
            return None
        url = formats[-1]["url"]

    return {"url": url}


def make_output_path(username: str) -> Path:
    """Build output path: material/{user}/{date}/live_{HHMMSS}.ts"""
    now = datetime.datetime.now()
    output_dir = REPO_ROOT / "material" / username / now.strftime("%Y-%m-%d")
    return output_dir / f"live_{now.strftime('%H%M%S')}.ts"


def start_recording(username: str, stream_url: str) -> tuple[subprocess.Popen, Path]:
    """Launch ffmpeg as a subprocess, return (process, output_path)."""
    output_path = make_output_path(username)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        FFMPEG,
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "300",
        "-i", stream_url,
        "-c", "copy",
        "-f", "mpegts",
        str(output_path),
    ]

    proc = subprocess.Popen(cmd)
    return proc, output_path
