"""Vectorize chat messages for semantic search and topic analysis.

Groups chat messages into 2-minute time windows, embeds them with
multilingual-e5-large, and computes topic scores.

Three chat contexts, stored separately:
  - organic:         non-battle chat from the host's room
  - battle_host:     host's room chat during a battle
  - battle_opponent: opponent's room chat during a battle

Usage:
    cd apps/cli && uv run src/index_chat.py [--force] [--session ID]
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
MODELS_DIR = Path(r"D:\files\models")
TOPIC_EMBEDDINGS_PATH = REPO_ROOT / "apps" / "app-backoffice" / "src" / "data" / "topic_embeddings.json"

WINDOW_MINUTES = 2
MIN_MESSAGES = 3
MAX_MESSAGES_PER_CHUNK = 50


def _window_key(ts) -> str:
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
    else:
        dt = ts
    floored_minute = (dt.minute // WINDOW_MINUTES) * WINDOW_MINUTES
    floored = dt.replace(minute=floored_minute, second=0, microsecond=0)
    return floored.isoformat()


def _messages_to_chunks(messages: list[tuple], session_id: int, context: str) -> list[dict]:
    """Group messages into windowed chunks. Each message is (username, text, timestamp)."""
    if not messages:
        return []

    windows: dict[str, list[tuple]] = defaultdict(list)
    for username, text, timestamp in messages:
        key = _window_key(timestamp)
        windows[key].append((username, text, timestamp))

    chunks = []
    for window_start, msgs in sorted(windows.items()):
        if len(msgs) < MIN_MESSAGES:
            continue
        for i in range(0, len(msgs), MAX_MESSAGES_PER_CHUNK):
            batch = msgs[i : i + MAX_MESSAGES_PER_CHUNK]
            text = "\n".join(f"[{u}]: {t}" for u, t, _ in batch)
            # Convert timestamps to ISO strings if they're datetime objects
            start_ts = batch[0][2]
            end_ts = batch[-1][2]
            if not isinstance(start_ts, str):
                start_ts = start_ts.isoformat()
            if not isinstance(end_ts, str):
                end_ts = end_ts.isoformat()
            chunks.append({
                "session_id": session_id,
                "start_time": start_ts,
                "end_time": end_ts,
                "message_count": len(batch),
                "text": text,
                "context": context,
            })
    return chunks


def group_chat_chunks(conn, session_id: int) -> list[dict]:
    """Group all chat messages into chunks, separated by context."""
    host = conn.execute("SELECT username FROM sessions WHERE id = %s", (session_id,)).fetchone()
    host_username = host[0] if host else ""

    all_chunks = []

    # 1. Organic chat (no battle)
    organic = conn.execute(
        "SELECT username, text, timestamp FROM chat_messages "
        "WHERE session_id = %s AND battle_id IS NULL "
        "ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    all_chunks.extend(_messages_to_chunks(organic, session_id, "organic"))

    # 2. Battle chat — split by room (host vs opponent)
    battle_msgs = conn.execute(
        "SELECT room_username, username, text, timestamp FROM chat_messages "
        "WHERE session_id = %s AND battle_id IS NOT NULL "
        "ORDER BY timestamp",
        (session_id,),
    ).fetchall()

    if battle_msgs:
        host_battle = [(u, t, ts) for room, u, t, ts in battle_msgs if room == host_username]
        opponent_battle = [(u, t, ts) for room, u, t, ts in battle_msgs if room != host_username]

        all_chunks.extend(_messages_to_chunks(host_battle, session_id, "battle_host"))
        all_chunks.extend(_messages_to_chunks(opponent_battle, session_id, "battle_opponent"))

    return all_chunks


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

    conn = get_connection()
    from pgvector.psycopg import register_vector
    register_vector(conn)

    # Get ALL sessions with any chat messages (organic or battle)
    if args.session:
        sessions = conn.execute(
            "SELECT DISTINCT s.id, s.username, s.date FROM sessions s "
            "JOIN chat_messages cm ON cm.session_id = s.id "
            "WHERE s.id = %s",
            (args.session,),
        ).fetchall()
    else:
        sessions = conn.execute(
            "SELECT DISTINCT s.id, s.username, s.date FROM sessions s "
            "JOIN chat_messages cm ON cm.session_id = s.id "
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
                "(SELECT id FROM chat_chunks WHERE session_id = %s)",
                (args.session,),
            )
            conn.execute("DELETE FROM chat_chunks WHERE session_id = %s", (args.session,))
        else:
            conn.execute("DELETE FROM chat_chunk_topics")
            conn.execute("DELETE FROM chat_chunks")
        conn.commit()
        sessions_to_process = sessions
        print("Force mode: re-processing all", flush=True)
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
    context_counts = defaultdict(int)

    from pipeline_telemetry import log_event
    t0 = time.time()
    for idx, (session_id, username, date) in enumerate(sessions_to_process):
        _step_t0 = time.time()
        chunks = group_chat_chunks(conn, session_id)

        if not chunks:
            print(
                f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: "
                f"no chunks (< {MIN_MESSAGES} msgs per window)",
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
                "INSERT INTO chat_chunks "
                "(session_id, start_time, end_time, message_count, text, embedding, embedding_model, context) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id, start_time, context) DO NOTHING "
                "RETURNING id",
                (
                    chunk["session_id"],
                    chunk["start_time"],
                    chunk["end_time"],
                    chunk["message_count"],
                    chunk["text"],
                    embeddings[i],  # pgvector handles numpy array
                    EMBEDDING_MODEL,
                    chunk["context"],
                ),
            )
            row = cur.fetchone()
            chunk_ids.append(row[0] if row else None)
            context_counts[chunk["context"]] += 1

        # Compute topic scores
        if topic_embeddings and chunk_ids:
            chunk_emb_matrix = np.array(embeddings, dtype=np.float32)
            for tid in topic_ids:
                scores = chunk_emb_matrix @ topic_embeddings[tid]
                for j, score in enumerate(scores):
                    if chunk_ids[j]:
                        conn.execute(
                            "INSERT INTO chat_chunk_topics (chat_chunk_id, topic, score) "
                            "VALUES (%s, %s, %s) "
                            "ON CONFLICT (chat_chunk_id, topic) DO UPDATE SET score = EXCLUDED.score",
                            (chunk_ids[j], tid, float(score)),
                        )
            total_topics += sum(1 for cid in chunk_ids if cid) * len(topic_ids)

        conn.commit()
        total_chunks += len(chunks)
        by_ctx = defaultdict(int)
        for c in chunks:
            by_ctx[c["context"]] += 1
        ctx_str = " + ".join(f"{v} {k}" for k, v in sorted(by_ctx.items()))
        msg_count = sum(c["message_count"] for c in chunks)

        log_event(
            session_id, "index_chat",
            status="completed", elapsed_seconds=time.time() - _step_t0,
            record_count=len(chunks),
            detail={"msg_count": msg_count, "contexts": dict(by_ctx)},
        )

        print(
            f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: "
            f"{len(chunks)} chunks ({msg_count} msgs) — {ctx_str}",
            flush=True,
        )

    elapsed = time.time() - t0
    conn.close()

    print(f"\nDone in {elapsed:.1f}s! Processed {len(sessions_to_process)} sessions.")
    print(f"  chat_chunks: {total_chunks} rows")
    for ctx, count in sorted(context_counts.items()):
        print(f"    {ctx}: {count}")
    if topic_ids:
        print(f"  chat_chunk_topics: {total_topics} rows")


if __name__ == "__main__":
    main()
