"""Record a TikTok live stream using yt-dlp + ffmpeg."""

import subprocess
import sys
from pathlib import Path

import yt_dlp

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

FFMPEG = r"D:\bin\ffmpeg.exe"

if len(sys.argv) < 2:
    sys.exit("Usage: record_tiktok_live.py <tiktok_username>")

TIKTOK_USER = sys.argv[1]
TIKTOK_URL = f"https://www.tiktok.com/@{TIKTOK_USER}/live"
NOW = __import__("datetime").datetime.now()
OUTPUT_DIR = REPO_ROOT / "material" / TIKTOK_USER / NOW.strftime("%Y-%m-%d")
OUTPUT_FILE = OUTPUT_DIR / f"live_{NOW.strftime('%H%M%S')}.ts"


def get_stream_url() -> str:
    print(f"Extracting stream URL from {TIKTOK_URL} ...")
    ydl_opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(TIKTOK_URL, download=False)

    url = info.get("url")
    if not url:
        formats = info.get("formats", [])
        if not formats:
            sys.exit("ERROR: No stream URL found. Is the live active?")
        url = formats[-1]["url"]

    print(f"Stream URL obtained ({url[:80]}...)")
    return url


def record(stream_url: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        FFMPEG,
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "300",
        "-i", stream_url,
        "-c", "copy",
        "-f", "mpegts",
        str(OUTPUT_FILE),
    ]

    print(f"Recording to {OUTPUT_FILE}")
    print("Press Ctrl+C to stop.\n")

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nStopped by user.")

    print(f"Done. File: {OUTPUT_FILE}")


if __name__ == "__main__":
    stream_url = get_stream_url()
    record(stream_url)
