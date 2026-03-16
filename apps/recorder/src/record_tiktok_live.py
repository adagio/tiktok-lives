"""Record a TikTok live stream using yt-dlp + ffmpeg."""

import sys

from recording import check_is_live, start_recording

if len(sys.argv) < 2:
    sys.exit("Usage: record_tiktok_live.py <tiktok_username>")

username = sys.argv[1]

print(f"Checking if @{username} is live...")
result = check_is_live(username)
if result is None:
    sys.exit(f"@{username} is not live or no stream URL found.")

print(f"Stream URL obtained ({result['url'][:80]}...)")

proc, output_path = start_recording(username, result["url"])
print(f"Recording to {output_path}")
print("Press Ctrl+C to stop.\n")

try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()
    print("\nStopped by user.")

print(f"Done. File: {output_path}")
