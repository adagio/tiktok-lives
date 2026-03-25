"""Extract topics and summaries from chat using Gemini 2.5 Flash.

Analyzes indexed chat chunks per session, stores results in SQLite.

Usage:
    cd apps/cli && uv run src/analyze_chat.py [--force] [--session ID]
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = REPO_ROOT / "clips.db"
GEMINI_MODEL = "gemini-2.0-flash-lite"
LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "UTC"))

PROMPT = """Analiza el siguiente chat de audiencia de un TikTok live y responde en JSON con exactamente esta estructura:
{
  "topics": ["tema 1", "tema 2", ...],
  "summary": "Resumen de 2-3 oraciones de qué se habló en el chat."
}

Los topics deben ser 3-5 temas concretos y específicos (no genéricos como "saludos" o "conversación").
El summary debe capturar la esencia de lo que la audiencia discutió.
Responde SOLO el JSON, sin markdown ni explicaciones.

CHAT:
"""

# Max chars of chat to send (Gemini 2.5 Flash handles 1M tokens, but let's be reasonable)
MAX_CHAT_CHARS = 50000


def init_table(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(id),
            topics TEXT NOT NULL,
            summary TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_chat_analysis_session ON chat_analysis(session_id);
    """)


def to_local_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16]


MAX_RETRIES = 3


def analyze_session(client: genai.Client, conn: sqlite3.Connection, session_id: int) -> dict | None:
    """Send chat chunks to Gemini and parse response. Retries on rate limit."""
    chunks = conn.execute(
        "SELECT text FROM chat_chunks WHERE session_id = ? ORDER BY start_time",
        (session_id,),
    ).fetchall()

    if not chunks:
        return None

    chat_text = "\n---\n".join(c[0] for c in chunks)
    if len(chat_text) > MAX_CHAT_CHARS:
        chat_text = chat_text[:MAX_CHAT_CHARS]

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=PROMPT + chat_text,
            )

            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            return json.loads(text)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 35 * (attempt + 1)
                print(f"    Rate limited, esperando {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise

    raise RuntimeError("Max retries exceeded")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract chat topics and summaries via Gemini")
    parser.add_argument("--force", action="store_true", help="Re-analyze all sessions")
    parser.add_argument("--session", type=int, help="Analyze only this session")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set in .env")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    init_table(conn)

    # Get sessions with chat chunks
    if args.session:
        sessions = conn.execute(
            "SELECT DISTINCT cc.session_id, s.username, s.date "
            "FROM chat_chunks cc JOIN sessions s ON cc.session_id = s.id "
            "WHERE cc.session_id = ?",
            (args.session,),
        ).fetchall()
    else:
        sessions = conn.execute(
            "SELECT DISTINCT cc.session_id, s.username, s.date "
            "FROM chat_chunks cc JOIN sessions s ON cc.session_id = s.id "
            "ORDER BY s.date",
        ).fetchall()

    if not sessions:
        print("No hay sesiones con chat chunks. Ejecuta index_chat.py primero.")
        conn.close()
        return

    # Idempotency
    if args.force:
        if args.session:
            conn.execute("DELETE FROM chat_analysis WHERE session_id = ?", (args.session,))
        else:
            conn.execute("DELETE FROM chat_analysis")
        conn.commit()
        to_process = sessions
    else:
        existing = {
            r[0] for r in conn.execute("SELECT session_id FROM chat_analysis").fetchall()
        }
        to_process = [s for s in sessions if s[0] not in existing]
        if not to_process:
            print("Todas las sesiones ya analizadas. Usa --force para re-analizar.")
            conn.close()
            return

    print(f"Analizando {len(to_process)} sesiones con Gemini 2.5 Flash...", flush=True)

    client = genai.Client(api_key=api_key)
    success = 0
    errors = 0

    for idx, (session_id, username, date) in enumerate(to_process):
        label = f"[{idx + 1}/{len(to_process)}] @{username} {to_local_date(date)}"
        try:
            result = analyze_session(client, conn, session_id)
            if not result:
                print(f"  {label}: sin chunks, saltando", flush=True)
                continue

            topics_json = json.dumps(result["topics"], ensure_ascii=False)
            summary = result["summary"]

            conn.execute(
                "INSERT OR REPLACE INTO chat_analysis (session_id, topics, summary, model) "
                "VALUES (?, ?, ?, ?)",
                (session_id, topics_json, summary, GEMINI_MODEL),
            )
            conn.commit()
            success += 1

            topics_preview = ", ".join(result["topics"][:3])
            print(f"  {label}: {topics_preview}", flush=True)

            # Rate limit: ~15 req/min to stay within free tier (20/min limit)
            time.sleep(4)

        except json.JSONDecodeError as e:
            errors += 1
            print(f"  {label}: JSON parse error — {e}", flush=True)
        except Exception as e:
            errors += 1
            print(f"  {label}: error — {e}", flush=True)
            time.sleep(2)

    conn.close()
    print(f"\nListo! {success} sesiones analizadas, {errors} errores.")


if __name__ == "__main__":
    main()
