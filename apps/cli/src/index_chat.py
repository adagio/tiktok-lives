"""Vectorize chat messages for semantic search and topic analysis.

Groups non-battle chat messages into 2-minute time windows, embeds them
with multilingual-e5-large, and computes topic scores.

Usage:
    cd apps/cli && uv run src/index_chat.py [--force] [--session ID]
"""

import json
import sqlite3
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
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
MODELS_DIR = Path(r"D:\files\models")
TOPIC_EMBEDDINGS_PATH = REPO_ROOT / "apps" / "app-backoffice" / "src" / "data" / "topic_embeddings.json"

WINDOW_MINUTES = 2
MIN_MESSAGES = 3
MAX_MESSAGES_PER_CHUNK = 50


def init_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            message_count INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB,
            embedding_model TEXT DEFAULT 'intfloat/multilingual-e5-large',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, start_time)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_chunks_session ON chat_chunks(session_id);

        CREATE TABLE IF NOT EXISTS chat_chunk_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_chunk_id INTEGER NOT NULL REFERENCES chat_chunks(id),
            topic TEXT NOT NULL,
            score REAL NOT NULL,
            UNIQUE(chat_chunk_id, topic)
        );
        CREATE INDEX IF NOT EXISTS idx_cct_chunk ON chat_chunk_topics(chat_chunk_id);
    """)


def embed_to_blob(vec: np.ndarray) -> bytes:
    """Pack float32 numpy array to bytes."""
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def parse_embedding(blob: bytes) -> np.ndarray:
    """Unpack float32 BLOB into numpy array."""
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _window_key(ts_str: str) -> str:
    """Floor an ISO timestamp to the nearest WINDOW_MINUTES boundary."""
    dt = datetime.fromisoformat(ts_str)
    floored_minute = (dt.minute // WINDOW_MINUTES) * WINDOW_MINUTES
    floored = dt.replace(minute=floored_minute, second=0, microsecond=0)
    return floored.isoformat()


def group_chat_chunks(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """Group non-battle chat messages into 2-minute windows."""
    rows = conn.execute(
        "SELECT username, text, timestamp FROM chat_messages "
        "WHERE session_id = ? AND battle_id IS NULL "
        "ORDER BY timestamp",
        (session_id,),
    ).fetchall()

    if not rows:
        return []

    # Group by time window
    windows: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for username, text, timestamp in rows:
        key = _window_key(timestamp)
        windows[key].append((username, text, timestamp))

    chunks = []
    for window_start, messages in sorted(windows.items()):
        if len(messages) < MIN_MESSAGES:
            continue

        # Sub-chunk if too many messages
        for i in range(0, len(messages), MAX_MESSAGES_PER_CHUNK):
            batch = messages[i : i + MAX_MESSAGES_PER_CHUNK]
            text = "\n".join(f"[{u}]: {t}" for u, t, _ in batch)
            chunks.append({
                "session_id": session_id,
                "start_time": batch[0][2],   # first message timestamp
                "end_time": batch[-1][2],     # last message timestamp
                "message_count": len(batch),
                "text": text,
            })

    return chunks


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vectorize chat messages for semantic search")
    parser.add_argument("--force", action="store_true", help="Re-process all sessions")
    parser.add_argument("--session", type=int, help="Process only this session ID")
    args = parser.parse_args()

    # Load topic embeddings (optional)
    topic_embeddings = {}
    topic_ids = []
    if TOPIC_EMBEDDINGS_PATH.exists():
        with open(TOPIC_EMBEDDINGS_PATH, encoding="utf-8") as f:
            topic_data = json.load(f)
        topic_ids = list(topic_data.keys())
        topic_embeddings = {
            tid: np.array(topic_data[tid]["embedding"], dtype=np.float32)
            for tid in topic_ids
        }
        print(f"Loaded {len(topic_ids)} topics: {', '.join(topic_ids)}", flush=True)
    else:
        print("Warning: topic_embeddings.json not found, skipping topic scores", flush=True)

    # Connect to DB
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    init_tables(conn)

    # Get sessions with chat messages
    if args.session:
        sessions = conn.execute(
            "SELECT DISTINCT s.id, s.username, s.date FROM sessions s "
            "JOIN chat_messages cm ON cm.session_id = s.id "
            "WHERE s.id = ? AND cm.battle_id IS NULL",
            (args.session,),
        ).fetchall()
    else:
        sessions = conn.execute(
            "SELECT DISTINCT s.id, s.username, s.date FROM sessions s "
            "JOIN chat_messages cm ON cm.session_id = s.id "
            "WHERE cm.battle_id IS NULL "
            "ORDER BY s.date",
        ).fetchall()

    print(f"Found {len(sessions)} sessions with chat messages", flush=True)

    if not sessions:
        print("No sessions to process.")
        conn.close()
        return

    # Idempotency
    if args.force:
        if args.session:
            conn.execute(
                "DELETE FROM chat_chunk_topics WHERE chat_chunk_id IN "
                "(SELECT id FROM chat_chunks WHERE session_id = ?)",
                (args.session,),
            )
            conn.execute("DELETE FROM chat_chunks WHERE session_id = ?", (args.session,))
        else:
            conn.execute("DELETE FROM chat_chunk_topics")
            conn.execute("DELETE FROM chat_chunks")
        conn.commit()
        sessions_to_process = sessions
        print("Force mode: re-processing", flush=True)
    else:
        existing = {
            row[0]
            for row in conn.execute("SELECT DISTINCT session_id FROM chat_chunks").fetchall()
        }
        sessions_to_process = [s for s in sessions if s[0] not in existing]
        if not sessions_to_process:
            print("All sessions already processed. Use --force to re-process.")
            conn.close()
            return
        print(
            f"Skipping {len(existing)} already-processed, processing {len(sessions_to_process)}",
            flush=True,
        )

    # Load embedding model
    print(f"Loading embedding model '{EMBEDDING_MODEL}' ...", flush=True)
    t_model = time.time()
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODELS_DIR))
    print(f"  Model loaded in {time.time() - t_model:.1f}s", flush=True)

    total_chunks = 0
    total_topics = 0

    t0 = time.time()
    for idx, (session_id, username, date) in enumerate(sessions_to_process):
        chunks = group_chat_chunks(conn, session_id)

        if not chunks:
            print(
                f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: no chunks (< {MIN_MESSAGES} msgs per window)",
                flush=True,
            )
            continue

        # Embed all chunks in batch
        texts = [f"passage: {c['text']}" for c in chunks]
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        # Insert chunks
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            cur = conn.execute(
                "INSERT INTO chat_chunks (session_id, start_time, end_time, message_count, text, embedding, embedding_model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk["session_id"],
                    chunk["start_time"],
                    chunk["end_time"],
                    chunk["message_count"],
                    chunk["text"],
                    embed_to_blob(embeddings[i]),
                    EMBEDDING_MODEL,
                ),
            )
            chunk_ids.append(cur.lastrowid)

        # Compute topic scores
        if topic_embeddings and chunk_ids:
            chunk_emb_matrix = np.array(embeddings, dtype=np.float32)
            for tid in topic_ids:
                scores = chunk_emb_matrix @ topic_embeddings[tid]
                for j, score in enumerate(scores):
                    conn.execute(
                        "INSERT OR REPLACE INTO chat_chunk_topics (chat_chunk_id, topic, score) "
                        "VALUES (?, ?, ?)",
                        (chunk_ids[j], tid, float(score)),
                    )
            total_topics += len(chunk_ids) * len(topic_ids)

        conn.commit()
        total_chunks += len(chunks)
        msg_count = sum(c["message_count"] for c in chunks)
        print(
            f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: "
            f"{len(chunks)} chunks ({msg_count} messages)",
            flush=True,
        )

    elapsed = time.time() - t0
    conn.close()

    print(f"\nDone in {elapsed:.1f}s! Processed {len(sessions_to_process)} sessions.")
    print(f"  chat_chunks: {total_chunks} rows")
    if topic_ids:
        print(f"  chat_chunk_topics: {total_topics} rows")


if __name__ == "__main__":
    main()
