"""Find best clip candidates by semantic search over indexed sessions."""

import os
import re
import sqlite3
import struct
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
CLIPS_DIR = REPO_ROOT / "clips"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
FFMPEG = r"D:\bin\ffmpeg.exe"
MODELS_DIR = Path(r"D:\files\models")

GEMINI_MODEL = "gemini-embedding-2-preview"
GEMINI_AUDIO_DIM = 768


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug: 'momento gracioso' → 'momento-gracioso'."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:50] or "clip"


def blob_to_array(blob: bytes, dim: int) -> np.ndarray:
    return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)


def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS for ffmpeg and display."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def embed_query_gemini(query: str) -> np.ndarray:
    """Embed a text query via Gemini for audio-space search."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=GEMINI_MODEL,
        contents=query,
        config=genai.types.EmbedContentConfig(output_dimensionality=GEMINI_AUDIO_DIM),
    )
    vec = np.array(response.embeddings[0].values, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def resolve_ts_file(ts_path: str | None, srt_name: str | None) -> Path:
    """Find the .ts file matching the SRT name."""
    if ts_path:
        ts_dir = Path(ts_path)
        if srt_name:
            base = srt_name.split("_audio")[0].split(".srt")[0]
            candidate = ts_dir / f"{base}.ts"
            if candidate.exists():
                return candidate
        ts_files = list(ts_dir.glob("*.ts"))
        if ts_files:
            return ts_files[0]
        return ts_dir / "live_full.ts"
    return Path("live_full.ts")


def extract_clip(ts_file: Path, start: float, duration: float, out_path: Path) -> bool:
    """Extract a clip with ffmpeg. Returns True on success."""
    cmd = [
        FFMPEG, "-y",
        "-ss", format_time(start),
        "-i", str(ts_file),
        "-t", str(int(duration)),
        "-c:v", "libx264", "-c:a", "aac",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def search_chat(args) -> None:
    """Search chat chunks by semantic similarity."""
    conn = sqlite3.connect(str(DB_PATH))

    query_sql = (
        "SELECT cc.id, cc.start_time, cc.end_time, cc.text, cc.embedding, "
        "cc.message_count, s.username, s.date, s.id "
        "FROM chat_chunks cc "
        "JOIN sessions s ON cc.session_id = s.id "
        "WHERE cc.embedding IS NOT NULL"
    )
    if args.user:
        query_sql += " AND s.username = ?"
        rows = conn.execute(query_sql, (args.user,)).fetchall()
    else:
        rows = conn.execute(query_sql).fetchall()

    conn.close()

    if not rows:
        print("No chat chunks found." + (f" (user={args.user})" if args.user else ""))
        print("Run index_chat.py first.")
        return

    # Embed query
    print(f"Loading model ...", flush=True)
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODELS_DIR))
    query_emb = model.encode(
        f"query: {args.query}", normalize_embeddings=True,
    ).reshape(1, -1)

    # Compute similarities
    embeddings = np.stack([blob_to_array(row[4], dim=1024) for row in rows])
    scores = (embeddings @ query_emb.T).flatten()

    indices = np.argsort(scores)[::-1]

    print(f"\nQuery: \"{args.query}\"  |  Source: chat")
    print(f"Searched {len(rows)} chat chunks\n")
    print("=" * 80)

    shown = 0
    for idx in indices:
        score = float(scores[idx])
        if score < args.min_score:
            break
        if shown >= args.max_clips:
            break

        row = rows[idx]
        chunk_id, start_time, end_time, text, _, msg_count, username, date, session_id = row

        # Parse time for display
        try:
            t_start = datetime.fromisoformat(start_time).strftime("%H:%M")
            t_end = datetime.fromisoformat(end_time).strftime("%H:%M")
        except (ValueError, TypeError):
            t_start = start_time[:16]
            t_end = end_time[:16]

        shown += 1
        print(f"\n#{shown}  Score: {score:.3f}  |  {username}/{date.split('T')[0]}")
        print(f"  Time: {t_start} - {t_end}  |  {msg_count} messages")
        # Show first 300 chars of chat
        snippet = text[:300].replace("\n", "\n  ")
        print(f"  Chat:\n  {snippet}")
        if len(text) > 300:
            print(f"  ... ({len(text) - 300} more chars)")

    print("\n" + "=" * 80)
    if shown == 0:
        print("No results above minimum score.")
    else:
        print(f"\n{shown} chat moments found.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Search indexed sessions for clip candidates")
    parser.add_argument("query", help="Search query (e.g. 'momento gracioso')")
    parser.add_argument("--user", help="Filter by username")
    parser.add_argument("--max-clips", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--min-score", type=float, default=0.0, help="Min similarity score (default: 0.0)")
    parser.add_argument("--padding", type=float, default=5.0, help="Seconds of padding around clip (default: 5)")
    parser.add_argument("--mode", choices=["text", "audio", "combined"], default=None,
                        help="Search mode: text, audio, or combined (default: auto-detect)")
    parser.add_argument("--audio-weight", type=float, default=0.5,
                        help="Weight for audio score in combined mode (default: 0.5)")
    parser.add_argument("--min-duration", type=float, default=6.0,
                        help="Min chunk duration in seconds (default: 6)")
    parser.add_argument("--extract", action="store_true",
                        help="Extract clips to clips/ folder and save to DB")
    parser.add_argument("--source", choices=["transcript", "chat", "all"], default="transcript",
                        help="Search source: transcript (SRT chunks), chat (audience messages), or all (default: transcript)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}\nRun index_session.py first.")

    if args.source in ("chat", "all"):
        search_chat(args)
        if args.source == "chat":
            return
        print("\n\n" + "=" * 80)
        print("TRANSCRIPT RESULTS:")
        print("=" * 80)

    conn = sqlite3.connect(str(DB_PATH))

    # Ensure clips table exists (migration for existing DBs)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER REFERENCES chunks(id),
            session_id INTEGER REFERENCES sessions(id),
            username TEXT NOT NULL,
            query TEXT,
            search_mode TEXT,
            score REAL,
            start_seconds REAL,
            end_seconds REAL,
            filename TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_clips_username ON clips(username);
    """)

    # Load chunks with session info
    query_sql = (
        "SELECT c.id, c.start_seconds, c.end_seconds, c.text, c.embedding, "
        "c.embedding_audio, s.username, s.date, s.ts_path, s.srt_path, s.id "
        "FROM chunks c JOIN sessions s ON c.session_id = s.id"
    )
    if args.user:
        query_sql += " WHERE s.username = ?"
        rows = conn.execute(query_sql, (args.user,)).fetchall()
    else:
        rows = conn.execute(query_sql).fetchall()

    if not rows:
        sys.exit("No indexed chunks found." + (f" (user={args.user})" if args.user else ""))

    # Check if audio embeddings are available
    has_audio = any(row[5] is not None for row in rows)

    # Auto-detect mode
    mode = args.mode
    if mode is None:
        mode = "combined" if has_audio else "text"

    if mode in ("audio", "combined") and not has_audio:
        print("WARNING: No audio embeddings found. Falling back to text mode.", flush=True)
        mode = "text"

    # --- Text scores ---
    text_scores = None
    if mode in ("text", "combined"):
        text_embeddings = np.stack([blob_to_array(row[4], dim=1024) for row in rows])
        print(f"Loading model ...", flush=True)
        model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODELS_DIR))
        query_emb = model.encode(
            f"query: {args.query}", normalize_embeddings=True,
        ).reshape(1, -1)
        text_scores = (text_embeddings @ query_emb.T).flatten()

    # --- Audio scores ---
    audio_scores = None
    if mode in ("audio", "combined"):
        print(f"Embedding query via Gemini ({GEMINI_MODEL}) ...", flush=True)
        query_audio_emb = embed_query_gemini(args.query).reshape(1, -1)

        audio_scores = np.zeros(len(rows), dtype=np.float32)
        for i, row in enumerate(rows):
            if row[5] is not None:
                audio_emb = blob_to_array(row[5], dim=GEMINI_AUDIO_DIM)
                audio_scores[i] = float(np.dot(audio_emb, query_audio_emb.flatten()))
            else:
                audio_scores[i] = text_scores[i] if text_scores is not None else 0.0

    # --- Final scores ---
    if mode == "text":
        scores = text_scores
    elif mode == "audio":
        scores = audio_scores
    else:  # combined
        w = args.audio_weight
        scores = (1 - w) * text_scores + w * audio_scores

    # Rank
    indices = np.argsort(scores)[::-1]

    print(f"\nQuery: \"{args.query}\"  |  Mode: {mode}", end="")
    if mode == "combined":
        print(f"  |  Audio weight: {args.audio_weight}", end="")
    print(f"\nSearched {len(rows)} chunks\n")
    print("=" * 80)

    shown = 0
    extracted = 0
    for idx in indices:
        score = float(scores[idx])
        if score < args.min_score:
            break
        if shown >= args.max_clips:
            break

        row = rows[idx]
        chunk_id, start, end, text, _, _, username, date, ts_path, srt_name, session_id = row
        duration = end - start

        if duration < args.min_duration:
            continue

        shown += 1
        score_detail = f"Score: {score:.3f}"
        if mode == "combined":
            score_detail += f"  (text: {text_scores[idx]:.3f}, audio: {audio_scores[idx]:.3f})"
        print(f"\n#{shown}  {score_detail}  |  {username}/{date}")
        print(f"  Time: {format_time(start)} - {format_time(end)} ({duration:.0f}s)")
        print(f"  Text: {text[:200]}")

        # Clip boundaries with padding
        clip_start = max(0, start - args.padding)
        clip_duration = duration + 2 * args.padding

        ts_file = resolve_ts_file(ts_path, srt_name)

        # Structured path: {username}/{date}/clip_{HHMMSS}_{query_slug}.mp4
        date_str = date.split("T")[0] if "T" in date else date
        query_slug = slugify(args.query)
        time_tag = format_time(start).replace(":", "")
        clip_filename = f"clip_{time_tag}_{query_slug}.mp4"
        rel_path = f"{username}/{date_str}/{clip_filename}"

        if args.extract:
            out_path = CLIPS_DIR / username / date_str / clip_filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.exists():
                print(f"  Already exists: {out_path}")
            else:
                print(f"  Extracting: {out_path} ...", end=" ", flush=True)
                if extract_clip(ts_file, clip_start, clip_duration, out_path):
                    print("OK")
                else:
                    print("FAILED")
                    continue

            # Save to DB (skip if same chunk+query already saved)
            exists = conn.execute(
                "SELECT id FROM clips WHERE chunk_id=? AND query=?",
                (chunk_id, args.query),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO clips (chunk_id, session_id, username, query, search_mode, "
                    "score, start_seconds, end_seconds, filename) VALUES (?,?,?,?,?,?,?,?,?)",
                    (chunk_id, session_id, username, args.query, mode,
                     score, clip_start, clip_start + clip_duration, rel_path),
                )
                conn.commit()
            extracted += 1
        else:
            print(f"  Output: clips/{rel_path}")
            print(f"  ffmpeg: {FFMPEG} -ss {format_time(clip_start)} -i \"{ts_file}\" "
                  f"-t {clip_duration:.0f} -c:v libx264 -c:a aac \"{clip_filename}\"")

    print("\n" + "=" * 80)
    if shown == 0:
        print("No results above minimum score.")
    elif args.extract:
        print(f"\n{extracted} clips extracted to {CLIPS_DIR}/")
    else:
        print(f"\n{shown} clips found. Use --extract to save them.")

    conn.close()


if __name__ == "__main__":
    main()
