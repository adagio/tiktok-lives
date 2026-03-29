"""Process unindexed recorded sessions: extract audio, transcribe via Groq, index embeddings.

Usage:
    cd apps/cli && uv run src/process_sessions.py [--date 2026-03-24] [--session ID] [--parallel 4]
"""

import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
FFMPEG = r"D:\bin\ffmpeg.exe"


def extract_audio(ts_path: str) -> tuple[str, float, bool]:
    """Extract audio from .ts to .opus. Returns (opus_path, elapsed_seconds, was_cached)."""
    ts = Path(ts_path)
    opus_path = ts.with_name(ts.stem + "_audio.opus")

    if opus_path.exists() and opus_path.stat().st_size > 0:
        return str(opus_path), 0.0, True

    t0 = time.time()
    result = subprocess.run(
        [FFMPEG, "-y", "-i", str(ts), "-vn", "-acodec", "libopus", "-b:a", "64k", str(opus_path)],
        capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-200:]}")
    return str(opus_path), time.time() - t0, False


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


def _extract_audio_worker(args: tuple) -> tuple[int, str, str | None, float, bool, str | None]:
    """Worker for parallel audio extraction. Returns (session_id, username, audio_path, elapsed, cached, error)."""
    session_id, username, ts_path = args
    try:
        audio_path, elapsed, cached = extract_audio(ts_path)
        return (session_id, username, audio_path, elapsed, cached, None)
    except Exception as e:
        return (session_id, username, None, 0.0, False, str(e))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process recorded sessions: audio → transcribe → index")
    parser.add_argument("--date", help="Filter by date (e.g. 2026-03-24)")
    parser.add_argument("--session", type=int, help="Process only this session ID")
    parser.add_argument("--parallel", type=int, default=4, help="Parallel workers for audio extraction (default: 4)")
    parser.add_argument("--audio-only", action="store_true", help="Only extract audio, skip transcription and indexing")
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

    # Filter to sessions with valid files
    valid_sessions = [(sid, user, date, ts) for sid, user, date, ts in sessions if Path(ts).exists()]
    missing = len(sessions) - len(valid_sessions)
    if missing:
        print(f"Skipping {missing} sessions with missing files.", flush=True)

    if not valid_sessions:
        print("No hay sesiones con archivos válidos.")
        return

    # --- Phase 1: Parallel audio extraction ---
    workers = min(args.parallel, len(valid_sessions))
    total = len(valid_sessions)
    print(f"\n{'='*60}", flush=True)
    print(f"  Phase 1: Audio extraction — {total} sessions, {workers} workers", flush=True)
    print(f"{'='*60}\n", flush=True)

    audio_results: dict[int, str] = {}  # session_id -> audio_path
    extract_args = [(sid, user, ts) for sid, user, _, ts in valid_sessions]

    t0 = time.time()
    errors = 0
    cached = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_audio_worker, a): a for a in extract_args}
        for i, future in enumerate(as_completed(futures)):
            sid, username, audio_path, elapsed, was_cached, error = future.result()
            done = i + 1
            pct = done * 100 // total
            elapsed_total = time.time() - t0
            eta = (elapsed_total / done) * (total - done) if done > 0 else 0

            if error:
                errors += 1
                print(f"  [{done}/{total}] {pct}% ✗ #{sid} @{username} — {error}", flush=True)
            elif was_cached:
                cached += 1
                audio_results[sid] = audio_path
                print(f"  [{done}/{total}] {pct}% ● #{sid} @{username} — cached", flush=True)
            else:
                audio_results[sid] = audio_path
                print(f"  [{done}/{total}] {pct}% ✓ #{sid} @{username} — {elapsed:.0f}s (ETA {eta:.0f}s)", flush=True)

    elapsed_phase1 = time.time() - t0
    print(f"\n  Audio: {len(audio_results)} ok, {cached} cached, {errors} errors — {elapsed_phase1:.0f}s total\n", flush=True)

    # Update audio_path in DB for extracted files
    conn = sqlite3.connect(str(DB_PATH))
    for sid, audio_path in audio_results.items():
        conn.execute("UPDATE sessions SET audio_path = ? WHERE id = ? AND (audio_path IS NULL OR audio_path = '')", (audio_path, sid))
    conn.commit()
    conn.close()
    print(f"  Updated {len(audio_results)} sessions with audio_path in DB\n", flush=True)

    if args.audio_only:
        print("--audio-only: skipping transcription and indexing.", flush=True)
        return

    # --- Phase 2: Sequential transcription + indexing ---
    to_process = [(sid, user, date, ts) for sid, user, date, ts in valid_sessions if sid in audio_results]
    total2 = len(to_process)
    print(f"{'='*60}", flush=True)
    print(f"  Phase 2: Transcription + indexing — {total2} sessions, sequential", flush=True)
    print(f"{'='*60}\n", flush=True)

    ok = 0
    errs = 0
    t0 = time.time()
    for idx, (session_id, username, date, ts_path) in enumerate(to_process):
        done = idx + 1
        pct = done * 100 // total2
        elapsed_total = time.time() - t0
        eta = (elapsed_total / done) * (total2 - done) if done > 0 else 0

        print(f"  [{done}/{total2}] {pct}% #{session_id} @{username} — {date}", flush=True)

        try:
            audio_path = audio_results[session_id]
            srt_path = transcribe_audio(audio_path)
            session_dir = str(Path(ts_path).parent)
            index_session_srt(srt_path, session_dir)
            ok += 1
            print(f"    ✓ done (ETA {eta:.0f}s)\n", flush=True)
        except Exception as e:
            errs += 1
            print(f"    ✗ {e}\n", flush=True)

    elapsed_phase2 = time.time() - t0
    print(f"\n{'='*60}", flush=True)
    print(f"  Pipeline complete!", flush=True)
    print(f"  Audio: {len(audio_results)} extracted ({cached} cached)", flush=True)
    print(f"  Transcription+Index: {ok} ok, {errs} errors", flush=True)
    print(f"  Total time: {elapsed_phase1 + elapsed_phase2:.0f}s ({(elapsed_phase1 + elapsed_phase2)/60:.1f}min)", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
