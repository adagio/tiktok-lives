"""Process unindexed recorded sessions: extract audio, transcribe via Groq, index embeddings.

Usage:
    cd apps/cli && uv run src/process_sessions.py [--date 2026-03-24] [--session ID]
"""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
FFMPEG = r"D:\bin\ffmpeg.exe"


def extract_audio(ts_path: str) -> str:
    """Extract audio from .ts to .opus. Returns opus path."""
    ts = Path(ts_path)
    opus_path = ts.with_name(ts.stem + "_audio.opus")

    if opus_path.exists() and opus_path.stat().st_size > 0:
        print(f"  Audio already exists: {opus_path}", flush=True)
        return str(opus_path)

    print(f"  Extracting audio...", flush=True)
    t0 = time.time()
    result = subprocess.run(
        [FFMPEG, "-y", "-i", str(ts), "-vn", "-acodec", "libopus", "-b:a", "64k", str(opus_path)],
        capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-200:]}")
    print(f"  Audio extracted in {time.time() - t0:.0f}s: {opus_path}", flush=True)
    return str(opus_path)


def transcribe_audio(audio_path: str) -> str:
    """Transcribe via Groq. Returns SRT path."""
    srt_path = Path(audio_path).with_suffix(".srt")

    if srt_path.exists() and srt_path.stat().st_size > 0:
        print(f"  SRT already exists: {srt_path}", flush=True)
        return str(srt_path)

    from transcribe_groq import transcribe
    transcribe(audio_path)
    return str(srt_path)


def index_session_srt(srt_path: str, session_dir: str):
    """Index a session's SRT into embeddings by calling index_session.py."""
    script = Path(__file__).parent / "index_session.py"
    srt_name = Path(srt_path).name
    print(f"  Indexing SRT...", flush=True)
    result = subprocess.run(
        [sys.executable, str(script), session_dir, "--srt", srt_name],
        capture_output=True, text=True, timeout=600,
        cwd=str(Path(__file__).parent.parent),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else ""
        raise RuntimeError(f"index_session.py failed: {stderr_tail}")
    # Print last few lines of output
    for line in (result.stdout.strip().split("\n") or [""])[-3:]:
        print(f"  {line}", flush=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process recorded sessions: audio → transcribe → index")
    parser.add_argument("--date", help="Filter by date (e.g. 2026-03-24)")
    parser.add_argument("--session", type=int, help="Process only this session ID")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))

    # Find sessions with recordings but no chunks
    if args.session:
        sessions = conn.execute(
            "SELECT s.id, s.username, s.date, s.ts_path FROM sessions s "
            "WHERE s.id = ? AND s.ts_path != '' AND s.ts_path IS NOT NULL",
            (args.session,),
        ).fetchall()
    elif args.date:
        sessions = conn.execute(
            "SELECT s.id, s.username, s.date, s.ts_path FROM sessions s "
            "WHERE s.date LIKE ? AND s.ts_path != '' AND s.ts_path IS NOT NULL "
            "ORDER BY s.date",
            (f"{args.date}%",),
        ).fetchall()
    else:
        sessions = conn.execute(
            "SELECT s.id, s.username, s.date, s.ts_path FROM sessions s "
            "WHERE s.ts_path != '' AND s.ts_path IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.session_id = s.id) "
            "ORDER BY s.date",
        ).fetchall()

    conn.close()

    if not sessions:
        print("No hay sesiones pendientes de procesar.")
        return

    print(f"Procesando {len(sessions)} sesiones...\n", flush=True)

    for idx, (session_id, username, date, ts_path) in enumerate(sessions):
        print(f"[{idx + 1}/{len(sessions)}] #{session_id} @{username} — {date}", flush=True)

        if not Path(ts_path).exists():
            print(f"  WARNING: Recording not found: {ts_path}", flush=True)
            continue

        try:
            # Step 1: Extract audio
            audio_path = extract_audio(ts_path)

            # Step 2: Transcribe
            srt_path = transcribe_audio(audio_path)

            # Step 3: Index
            session_dir = str(Path(ts_path).parent)
            index_session_srt(srt_path, session_dir)

            print(f"  Done!\n", flush=True)

        except Exception as e:
            print(f"  ERROR: {e}\n", flush=True)

    print("Pipeline complete!", flush=True)


if __name__ == "__main__":
    main()
