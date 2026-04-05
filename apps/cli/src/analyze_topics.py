"""Pre-compute topic scores for all sessions and store in PostgreSQL.

Reads topic embeddings from topic_embeddings.json, computes dot products
against all chunk embeddings, and stores per-session scores + global highlights.

Usage:
    cd apps/cli && uv run src/analyze_topics.py [--force]
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection

TOPIC_EMBEDDINGS_PATH = REPO_ROOT / "apps" / "app-backoffice" / "src" / "data" / "topic_embeddings.json"
TOP_N_HIGHLIGHTS = 5


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Pre-compute topic scores for all sessions")
    parser.add_argument("--force", action="store_true", help="Recalculate all sessions (default: skip already computed)")
    args = parser.parse_args()

    if not TOPIC_EMBEDDINGS_PATH.exists():
        sys.exit(f"Topic embeddings not found: {TOPIC_EMBEDDINGS_PATH}")

    # Load topic embeddings
    with open(TOPIC_EMBEDDINGS_PATH, encoding="utf-8") as f:
        topic_data = json.load(f)

    topic_ids = list(topic_data.keys())
    topic_embeddings = {
        tid: np.array(topic_data[tid]["embedding"], dtype=np.float32)
        for tid in topic_ids
    }
    print(f"Loaded {len(topic_ids)} topics: {', '.join(topic_ids)}", flush=True)

    # Connect to DB
    conn = get_connection()
    from pgvector.psycopg import register_vector
    register_vector(conn)

    # Get all sessions
    sessions = conn.execute("SELECT id, username, date FROM sessions ORDER BY date").fetchall()
    print(f"Found {len(sessions)} sessions", flush=True)

    if not sessions:
        print("No sessions to analyze.")
        conn.close()
        return

    # Determine which sessions to process
    if args.force:
        conn.execute("DELETE FROM session_topics")
        conn.execute("DELETE FROM topic_highlights")
        conn.commit()
        sessions_to_process = sessions
        print("Force mode: recalculating all sessions", flush=True)
    else:
        existing = {
            row[0]
            for row in conn.execute("SELECT DISTINCT session_id FROM session_topics").fetchall()
        }
        sessions_to_process = [s for s in sessions if s[0] not in existing]
        if not sessions_to_process:
            print("All sessions already analyzed. Use --force to recalculate.")
            conn.close()
            return
        print(f"Skipping {len(existing)} already-analyzed sessions, processing {len(sessions_to_process)}", flush=True)

    # Collect all (topic, chunk_id, session_id, score) for global highlights
    all_scores: dict[str, list[tuple[int, int, float]]] = {tid: [] for tid in topic_ids}

    from pipeline_telemetry import log_event
    t0 = time.time()
    for idx, (session_id, username, date) in enumerate(sessions_to_process):
        # Load chunk embeddings for this session — pgvector returns numpy arrays
        chunks = conn.execute(
            "SELECT id, embedding FROM chunks WHERE session_id = %s AND embedding IS NOT NULL ORDER BY chunk_index",
            (session_id,),
        ).fetchall()

        if not chunks:
            print(f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: no embeddings, skipping", flush=True)
            continue

        chunk_ids = [c[0] for c in chunks]
        chunk_embeddings = np.array([np.array(c[1], dtype=np.float32) for c in chunks], dtype=np.float32)

        # Compute scores for each topic
        for tid in topic_ids:
            topic_emb = topic_embeddings[tid]
            scores = chunk_embeddings @ topic_emb
            max_idx = int(np.argmax(scores))
            max_score = float(scores[max_idx])
            avg_score = float(np.mean(scores))
            best_chunk_id = chunk_ids[max_idx]

            conn.execute(
                "INSERT INTO session_topics (session_id, topic, max_score, avg_score, best_chunk_id) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id, topic) DO UPDATE SET max_score = EXCLUDED.max_score, "
                "avg_score = EXCLUDED.avg_score, best_chunk_id = EXCLUDED.best_chunk_id",
                (session_id, tid, max_score, avg_score, best_chunk_id),
            )

            # Collect for global highlights
            for i, score in enumerate(scores):
                all_scores[tid].append((chunk_ids[i], session_id, float(score)))

        conn.commit()

        log_event(session_id, "analyze_topics", status="completed",
                  record_count=len(chunks) * len(topic_ids),
                  detail={"chunk_count": len(chunks), "topic_count": len(topic_ids)})

        if (idx + 1) % 5 == 0 or idx == len(sessions_to_process) - 1:
            print(f"  [{idx + 1}/{len(sessions_to_process)}] {username}/{date}: {len(chunks)} chunks analyzed", flush=True)

    elapsed = time.time() - t0
    print(f"\nScores computed in {elapsed:.1f}s", flush=True)

    # Compute global top highlights
    print("Computing global highlights ...", flush=True)
    conn.execute("DELETE FROM topic_highlights")

    if args.force:
        for tid in topic_ids:
            sorted_scores = sorted(all_scores[tid], key=lambda x: x[2], reverse=True)[:TOP_N_HIGHLIGHTS]
            for chunk_id, session_id, score in sorted_scores:
                conn.execute(
                    "INSERT INTO topic_highlights (topic, chunk_id, session_id, score) VALUES (%s, %s, %s, %s)",
                    (tid, chunk_id, session_id, score),
                )
    else:
        for tid in topic_ids:
            topic_emb = topic_embeddings[tid]
            all_chunks = conn.execute(
                "SELECT id, session_id, embedding FROM chunks WHERE embedding IS NOT NULL"
            ).fetchall()
            scored = []
            for chunk_id, sess_id, emb in all_chunks:
                emb_arr = np.array(emb, dtype=np.float32)
                score = float(np.dot(topic_emb, emb_arr))
                scored.append((chunk_id, sess_id, score))
            scored.sort(key=lambda x: x[2], reverse=True)
            for chunk_id, sess_id, score in scored[:TOP_N_HIGHLIGHTS]:
                conn.execute(
                    "INSERT INTO topic_highlights (topic, chunk_id, session_id, score) VALUES (%s, %s, %s, %s)",
                    (tid, chunk_id, sess_id, score),
                )

    conn.commit()
    conn.close()

    print(f"\nDone! Analyzed {len(sessions_to_process)} sessions.")
    print(f"  session_topics: {len(sessions_to_process) * len(topic_ids)} rows")
    print(f"  topic_highlights: {len(topic_ids) * TOP_N_HIGHLIGHTS} rows")


if __name__ == "__main__":
    main()
