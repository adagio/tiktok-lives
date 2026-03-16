"""Index a TikTok live session for clip discovery.

Parses an SRT file, groups segments into ~30s chunks,
embeds each chunk with multilingual-e5-large, and stores in SQLite.
Optionally embeds audio chunks via Gemini embedding-2 (--audio flag).
"""

import os
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
CHUNK_TARGET_SECONDS = 30.0
# Pause longer than this (seconds) forces a chunk boundary
PAUSE_THRESHOLD = 3.0

MODELS_DIR = Path(r"D:\files\models")
FFMPEG = r"D:\bin\ffmpeg.exe"

GEMINI_MODEL = "gemini-embedding-2-preview"
GEMINI_AUDIO_DIM = 768


# --- SRT parsing ---

def parse_timestamp(ts: str) -> float:
    """Parse SRT timestamp '00:01:23,456' to seconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of {index, start, end, text}."""
    content = srt_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(\d+)\s*\n"
        r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
        r"(.*?)(?=\n\n|\n*$)",
        re.DOTALL,
    )
    segments = []
    for m in pattern.finditer(content):
        segments.append({
            "index": int(m.group(1)),
            "start": parse_timestamp(m.group(2)),
            "end": parse_timestamp(m.group(3)),
            "text": m.group(4).replace("\n", " ").strip(),
        })
    return segments


# --- Chunking ---

def group_into_chunks(segments: list[dict]) -> list[dict]:
    """Group SRT segments into ~30s chunks, respecting pauses."""
    if not segments:
        return []

    chunks = []
    current_texts = []
    current_start = segments[0]["start"]
    current_end = segments[0]["end"]

    for i, seg in enumerate(segments):
        # Check if we should start a new chunk
        gap = seg["start"] - current_end if current_texts else 0
        duration = seg["end"] - current_start if current_texts else 0

        start_new = (
            current_texts
            and (
                duration >= CHUNK_TARGET_SECONDS
                or gap >= PAUSE_THRESHOLD
            )
        )

        if start_new:
            chunks.append({
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_texts),
            })
            current_texts = []
            current_start = seg["start"]

        current_texts.append(seg["text"])
        current_end = seg["end"]

    # Last chunk
    if current_texts:
        chunks.append({
            "start": current_start,
            "end": current_end,
            "text": " ".join(current_texts),
        })

    return chunks


# --- Embedding ---

def embed_to_blob(vec: np.ndarray) -> bytes:
    """Pack float32 numpy array to bytes."""
    return struct.pack(f"{len(vec)}f", *vec.tolist())


# --- Audio extraction ---

def extract_audio_chunk(audio_path: Path, start: float, duration: float, tmp_dir: str) -> Path:
    """Extract a chunk of audio to a temp opus file using ffmpeg."""
    tmp_path = Path(tmp_dir) / f"chunk_{start:.1f}.opus"
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", str(audio_path),
        "-c:a", "libopus", "-b:a", "64k",
        "-f", "opus",
        str(tmp_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return tmp_path


# --- Gemini audio embedding ---

def embed_audio_chunks(chunks: list[dict], audio_path: Path):
    """Embed audio chunks via Gemini embedding-2 API."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, chunk in enumerate(chunks):
            start = chunk["start"]
            duration = chunk["end"] - chunk["start"]
            # Clamp to 80s (Gemini limit)
            duration = min(duration, 80.0)

            try:
                audio_file = extract_audio_chunk(audio_path, start, duration, tmp_dir)
                audio_bytes = audio_file.read_bytes()
            except subprocess.CalledProcessError as e:
                print(f"  WARNING: ffmpeg failed for chunk {i} ({start:.1f}s), skipping audio embedding", flush=True)
                chunk["embedding_audio_blob"] = None
                continue

            try:
                response = client.models.embed_content(
                    model=GEMINI_MODEL,
                    contents=genai.types.Content(
                        parts=[genai.types.Part(inline_data=genai.types.Blob(mime_type="audio/opus", data=audio_bytes))]
                    ),
                    config=genai.types.EmbedContentConfig(output_dimensionality=GEMINI_AUDIO_DIM),
                )
                vec = np.array(response.embeddings[0].values, dtype=np.float32)
                # Normalize
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                chunk["embedding_audio_blob"] = embed_to_blob(vec)
            except Exception as e:
                print(f"  WARNING: Gemini API failed for chunk {i}: {e}", flush=True)
                chunk["embedding_audio_blob"] = None
                continue

            # Clean up temp file
            audio_file.unlink(missing_ok=True)

            # Progress
            if (i + 1) % 10 == 0 or i == len(chunks) - 1:
                print(f"  Audio embedded: {i + 1}/{len(chunks)}", flush=True)

            # Rate limit: ~60 RPM → 1 req/sec
            if i < len(chunks) - 1:
                time.sleep(1.0)


# --- Database ---

def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            date TEXT NOT NULL,
            ts_path TEXT,
            srt_path TEXT,
            audio_path TEXT,
            duration_seconds REAL,
            indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            session_id INTEGER REFERENCES sessions(id),
            chunk_index INTEGER,
            start_seconds REAL,
            end_seconds REAL,
            text TEXT,
            embedding BLOB,
            embedding_model TEXT DEFAULT 'intfloat/multilingual-e5-large',
            embedding_audio BLOB,
            embedding_audio_model TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_user_date ON sessions(username, date);

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

    # Migration: add audio columns if missing (existing DBs)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    if "embedding_audio" not in cols:
        conn.execute("ALTER TABLE chunks ADD COLUMN embedding_audio BLOB")
    if "embedding_audio_model" not in cols:
        conn.execute("ALTER TABLE chunks ADD COLUMN embedding_audio_model TEXT")

    return conn


def session_exists(conn: sqlite3.Connection, username: str, date: str, srt_path: str) -> bool:
    row = conn.execute(
        "SELECT id FROM sessions WHERE username=? AND date=? AND srt_path=?",
        (username, date, srt_path),
    ).fetchone()
    return row is not None


def find_monitor_session(conn: sqlite3.Connection, username: str, date: str) -> int | None:
    """Find a session created by monitor (srt_path IS NULL) for the same username and date prefix."""
    row = conn.execute(
        "SELECT id FROM sessions WHERE username=? AND date LIKE ? AND srt_path IS NULL ORDER BY date DESC LIMIT 1",
        (username, date[:10] + "%"),
    ).fetchone()
    return row[0] if row else None


def update_session(conn: sqlite3.Connection, session_id: int,
                   session_dir: Path, srt_name: str, duration: float) -> None:
    """Update a monitor-created session with SRT info."""
    conn.execute(
        "UPDATE sessions SET ts_path=?, srt_path=?, duration_seconds=? WHERE id=?",
        (str(session_dir), srt_name, duration, session_id),
    )
    conn.commit()


def insert_session(conn: sqlite3.Connection, username: str, date: str,
                   session_dir: Path, srt_name: str, duration: float) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (username, date, ts_path, srt_path, duration_seconds) VALUES (?,?,?,?,?)",
        (username, date, str(session_dir), srt_name, duration),
    )
    conn.commit()
    return cur.lastrowid


def insert_chunks(conn: sqlite3.Connection, session_id: int, chunks: list[dict]):
    conn.executemany(
        "INSERT INTO chunks (session_id, chunk_index, start_seconds, end_seconds, text, "
        "embedding, embedding_audio, embedding_audio_model) VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                session_id, i, c["start"], c["end"], c["text"],
                c["embedding_blob"],
                c.get("embedding_audio_blob"),
                GEMINI_MODEL if c.get("embedding_audio_blob") else None,
            )
            for i, c in enumerate(chunks)
        ],
    )
    conn.commit()


def update_audio_embeddings(conn: sqlite3.Connection, session_id: int, chunks: list[dict]):
    """Update existing chunks with audio embeddings (for re-indexing audio only)."""
    rows = conn.execute(
        "SELECT id, chunk_index FROM chunks WHERE session_id=? ORDER BY chunk_index",
        (session_id,),
    ).fetchall()
    for db_id, chunk_idx in rows:
        if chunk_idx < len(chunks):
            blob = chunks[chunk_idx].get("embedding_audio_blob")
            conn.execute(
                "UPDATE chunks SET embedding_audio=?, embedding_audio_model=? WHERE id=?",
                (blob, GEMINI_MODEL if blob else None, db_id),
            )
    conn.commit()


# --- CLI ---

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Index a TikTok live session for clip search")
    parser.add_argument("session_dir", help="Path to session directory (e.g. material/user/2026-03-13)")
    parser.add_argument("--srt", required=True, help="SRT filename inside session dir")
    parser.add_argument("--audio", help="Audio file (.opus/.wav) inside session dir for audio embeddings")
    parser.add_argument("--force", action="store_true", help="Re-index even if session exists")
    args = parser.parse_args()

    session_dir = Path(args.session_dir).resolve()
    srt_path = session_dir / args.srt

    if not srt_path.exists():
        sys.exit(f"SRT not found: {srt_path}")

    audio_path = None
    if args.audio:
        audio_path = session_dir / args.audio
        if not audio_path.exists():
            sys.exit(f"Audio file not found: {audio_path}")

    # Extract username and date from path: material/{username}/{date}/
    parts = session_dir.parts
    try:
        mat_idx = parts.index("material")
        username = parts[mat_idx + 1]
        date_str = parts[mat_idx + 2]
    except (ValueError, IndexError):
        sys.exit("Cannot extract username/date. Expected path: material/{username}/{date}/")

    # Extract time from SRT filename (e.g. live_155820_audio.srt → 15:58:20)
    time_match = re.search(r"live_(\d{2})(\d{2})(\d{2})", args.srt)
    if time_match:
        h, m, s = time_match.groups()
        date = f"{date_str}T{h}:{m}:{s}"
    else:
        date = date_str

    # Init DB
    conn = init_db(DB_PATH)

    if not args.force and session_exists(conn, username, date, args.srt):
        print(f"Session already indexed: {username}/{date}/{args.srt}")
        print("Use --force to re-index.")
        conn.close()
        return

    # If forcing, delete old session data
    if args.force:
        row = conn.execute(
            "SELECT id FROM sessions WHERE username=? AND date=? AND srt_path=?",
            (username, date, args.srt),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM chunks WHERE session_id=?", (row[0],))
            conn.execute("DELETE FROM sessions WHERE id=?", (row[0],))
            conn.commit()
            print(f"Deleted previous index for {username}/{date}/{args.srt}")

    # Parse SRT
    print(f"Parsing {srt_path} ...", flush=True)
    segments = parse_srt(srt_path)
    print(f"  {len(segments)} segments found", flush=True)

    if not segments:
        sys.exit("No segments found in SRT file.")

    # Chunk
    chunks = group_into_chunks(segments)
    duration = segments[-1]["end"]
    print(f"  {len(chunks)} chunks (~{CHUNK_TARGET_SECONDS:.0f}s each), total {duration:.0f}s", flush=True)

    # Load model
    print(f"Loading embedding model '{EMBEDDING_MODEL}' ...", flush=True)
    t0 = time.time()
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODELS_DIR))
    print(f"  Model loaded in {time.time() - t0:.1f}s", flush=True)

    # Embed chunks — prefix with "passage: " for e5 models
    texts = [f"passage: {c['text']}" for c in chunks]
    print("Embedding text chunks ...", flush=True)
    t0 = time.time()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    print(f"  {len(chunks)} chunks embedded in {time.time() - t0:.1f}s", flush=True)

    for chunk, emb in zip(chunks, embeddings):
        chunk["embedding_blob"] = embed_to_blob(emb)

    # Audio embeddings (optional)
    if audio_path:
        print(f"\nEmbedding audio chunks via Gemini ({GEMINI_MODEL}) ...", flush=True)
        t0 = time.time()
        embed_audio_chunks(chunks, audio_path)
        audio_count = sum(1 for c in chunks if c.get("embedding_audio_blob"))
        print(f"  {audio_count}/{len(chunks)} audio embeddings in {time.time() - t0:.1f}s", flush=True)

    # Store — check if monitor already created a session for this date
    monitor_sid = find_monitor_session(conn, username, date)
    if monitor_sid is not None:
        session_id = monitor_sid
        update_session(conn, session_id, session_dir, args.srt, duration)
        print(f"Updated existing session {session_id} (created by monitor)", flush=True)
    else:
        session_id = insert_session(conn, username, date, session_dir, args.srt, duration)

    insert_chunks(conn, session_id, chunks)
    conn.close()

    print(f"\nIndexed: {username}/{date}/{args.srt}")
    print(f"  {len(chunks)} chunks stored in {DB_PATH}")
    if audio_path:
        audio_count = sum(1 for c in chunks if c.get("embedding_audio_blob"))
        print(f"  {audio_count} audio embeddings stored")


if __name__ == "__main__":
    main()
