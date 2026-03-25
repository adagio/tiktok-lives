"""Query topic analysis from indexed chat messages.

Usage:
    cd apps/cli
    uv run src/chat_topics.py                              # global summary per author
    uv run src/chat_topics.py --user kelyalvarezh           # sessions for one author
    uv run src/chat_topics.py --session 84                  # topic breakdown for a session
    uv run src/chat_topics.py --session 84 --topic risas    # top chunks for a topic
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "UTC"))


def to_local(iso_str: str) -> str:
    """Convert ISO UTC timestamp to local time string (HH:MM)."""
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(LOCAL_TZ)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_str[:5]


def to_local_date(iso_str: str) -> str:
    """Convert ISO UTC timestamp to local date+time (YYYY-MM-DD HH:MM)."""
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16]


def global_summary(conn: sqlite3.Connection):
    """Show topic summary per author."""
    rows = conn.execute("""
        SELECT s.username,
            COUNT(DISTINCT cc.id) as chunks,
            SUM(cc.message_count) as msgs,
            COUNT(DISTINCT cc.session_id) as sesiones
        FROM chat_chunks cc
        JOIN sessions s ON cc.session_id = s.id
        GROUP BY s.username
        ORDER BY msgs DESC
    """).fetchall()

    if not rows:
        print("No hay chat chunks indexados. Ejecuta index_chat.py primero.")
        return

    print(f"{'Autor':<25} {'Sesiones':>8} {'Chunks':>8} {'Msgs':>8}  Top topics")
    print("-" * 90)

    for username, chunks, msgs, sesiones in rows:
        # Get top 3 topics by avg score for this author
        topics = conn.execute("""
            SELECT cct.topic, ROUND(AVG(cct.score), 3) as avg
            FROM chat_chunk_topics cct
            JOIN chat_chunks cc ON cct.chat_chunk_id = cc.id
            JOIN sessions s ON cc.session_id = s.id
            WHERE s.username = ?
            GROUP BY cct.topic
            ORDER BY avg DESC
            LIMIT 3
        """, (username,)).fetchall()

        topic_str = "  ".join(f"{t[0]}({t[1]:.3f})" for t in topics)
        print(f"{username:<25} {sesiones:>8} {chunks:>8} {msgs:>8}  {topic_str}")

    total_chunks = sum(r[1] for r in rows)
    total_msgs = sum(r[2] for r in rows)
    print("-" * 90)
    print(f"{'TOTAL':<25} {sum(r[3] for r in rows):>8} {total_chunks:>8} {total_msgs:>8}")


def user_sessions(conn: sqlite3.Connection, username: str):
    """Show sessions for a specific author with top topics."""
    rows = conn.execute("""
        SELECT cc.session_id, s.date,
            COUNT(cc.id) as chunks,
            SUM(cc.message_count) as msgs
        FROM chat_chunks cc
        JOIN sessions s ON cc.session_id = s.id
        WHERE s.username = ?
        GROUP BY cc.session_id
        ORDER BY s.date DESC
    """, (username,)).fetchall()

    if not rows:
        print(f"No hay chat chunks para @{username}.")
        return

    print(f"Sesiones de @{username} ({len(rows)} sesiones)")
    print()
    print(f"{'ID':>4}  {'Fecha':>16} {'Chunks':>7} {'Msgs':>6}  {'Topic #1':<18} {'Topic #2':<18}")
    print("-" * 80)

    for session_id, date, chunks, msgs in rows:
        topics = conn.execute("""
            SELECT cct.topic, ROUND(AVG(cct.score), 3) as avg
            FROM chat_chunk_topics cct
            JOIN chat_chunks cc ON cct.chat_chunk_id = cc.id
            WHERE cc.session_id = ?
            GROUP BY cct.topic
            ORDER BY avg DESC
            LIMIT 2
        """, (session_id,)).fetchall()

        t1 = f"{topics[0][0]}({topics[0][1]:.3f})" if len(topics) > 0 else ""
        t2 = f"{topics[1][0]}({topics[1][1]:.3f})" if len(topics) > 1 else ""
        print(f"{session_id:>4}  {to_local_date(date):>16} {chunks:>7} {msgs:>6}  {t1:<18} {t2:<18}")


def session_topics(conn: sqlite3.Connection, session_id: int):
    """Show topic breakdown for a session."""
    session = conn.execute(
        "SELECT username, date FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session:
        print(f"Sesion {session_id} no encontrada.")
        return

    username, date = session
    chunk_count = conn.execute(
        "SELECT COUNT(*), SUM(message_count) FROM chat_chunks WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    print(f"Sesion #{session_id} — @{username} — {to_local_date(date)}")
    print(f"{chunk_count[0]} chunks, {chunk_count[1]} mensajes")
    print()

    topics = conn.execute("""
        SELECT cct.topic,
            ROUND(MAX(cct.score), 3) as max_score,
            ROUND(AVG(cct.score), 3) as avg_score,
            cc.id as best_chunk_id
        FROM chat_chunk_topics cct
        JOIN chat_chunks cc ON cct.chat_chunk_id = cc.id
        WHERE cc.session_id = ?
        GROUP BY cct.topic
        ORDER BY avg_score DESC
    """, (session_id,)).fetchall()

    for topic, max_score, avg_score, _ in topics:
        # Get best chunk for this topic
        best = conn.execute("""
            SELECT cc.text, cc.start_time, cc.end_time, cct.score
            FROM chat_chunk_topics cct
            JOIN chat_chunks cc ON cct.chat_chunk_id = cc.id
            WHERE cc.session_id = ? AND cct.topic = ?
            ORDER BY cct.score DESC LIMIT 1
        """, (session_id, topic)).fetchone()

        print(f"  {topic:<12}  max={max_score:.3f}  avg={avg_score:.3f}")
        if best:
            snippet = best[0][:150].replace("\n", " | ")
            t_start = to_local(best[1])
            t_end = to_local(best[2])
            print(f"    [{t_start}-{t_end}] {snippet}")
        print()


def topic_drilldown(conn: sqlite3.Connection, session_id: int, topic: str):
    """Show top chunks for a specific topic in a session."""
    session = conn.execute(
        "SELECT username, date FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session:
        print(f"Sesion {session_id} no encontrada.")
        return

    username, date = session
    print(f"Sesion #{session_id} — @{username} — {to_local_date(date)}")
    print(f"Top chunks para topic: {topic}")
    print("=" * 80)

    rows = conn.execute("""
        SELECT cc.text, cc.start_time, cc.end_time, cc.message_count, cct.score
        FROM chat_chunk_topics cct
        JOIN chat_chunks cc ON cct.chat_chunk_id = cc.id
        WHERE cc.session_id = ? AND cct.topic = ?
        ORDER BY cct.score DESC
        LIMIT 5
    """, (session_id, topic)).fetchall()

    if not rows:
        print(f"No hay chunks para topic '{topic}' en sesion {session_id}.")
        return

    for i, (text, start, end, msg_count, score) in enumerate(rows, 1):
        t_start = to_local(start)
        t_end = to_local(end)
        print(f"\n#{i}  Score: {score:.3f}  |  {t_start}-{t_end}  |  {msg_count} msgs")
        print("-" * 40)
        # Indent each line of chat
        for line in text.split("\n"):
            print(f"  {line}")

    print("\n" + "=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Query chat topic analysis")
    parser.add_argument("--user", help="Filter by username")
    parser.add_argument("--session", type=int, help="Show topics for a specific session")
    parser.add_argument("--topic", help="Drill down into a specific topic (requires --session)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))

    try:
        if args.session and args.topic:
            topic_drilldown(conn, args.session, args.topic)
        elif args.session:
            session_topics(conn, args.session)
        elif args.user:
            user_sessions(conn, args.user)
        else:
            global_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
