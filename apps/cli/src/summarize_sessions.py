"""Generate semantic summaries for indexed sessions using Gemini.

Usage:
    cd apps/cli && uv run src/summarize_sessions.py [--force] [--session ID] [--date 2026-03-24]
"""

import argparse
import os
import re
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
GEMINI_MODEL = "gemini-2.5-flash"
LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "UTC"))
MAX_RETRIES = 3
MAX_TEXT_CHARS = 50000


def build_prompt(username: str, duration_min: int | None, transcript: str) -> str:
    duration_note = f" ({duration_min} minutos)" if duration_min else ""
    truncated = transcript[:MAX_TEXT_CHARS]

    return f"""Eres un asistente que resume transmisiones en vivo de TikTok en español.

Dado el siguiente transcrito de un live de "@{username}"{duration_note}, genera un resumen breve y claro de lo que dijo el autor.

Reglas:
- Maximo 5 parrafos cortos (2 lineas cada uno)
- Cada parrafo cubre un tema o momento distinto de la sesion
- Usa un tono casual y directo, como notas personales
- No uses bullets, listas ni encabezados — solo parrafos separados por linea vacia
- Si la sesion es corta (<15 min), 2-3 parrafos bastan
- Captura el tono emocional: si fue divertida, emotiva, relajada, etc.
- Se especifico — menciona nombres, temas y detalles concretos

Transcrito:
{truncated}"""


def to_local_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str).astimezone(LOCAL_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16]


def summarize(client: genai.Client, prompt: str) -> str | None:
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=600,
                ),
            )
            return response.text.strip() if response.text else None
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                match = re.search(r"retry in (\d+)", str(e))
                wait = int(match.group(1)) + 5 if match else 60
                print(f"    Rate limited, esperando {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate session summaries with Gemini")
    parser.add_argument("--force", action="store_true", help="Regenerate all summaries")
    parser.add_argument("--session", type=int, help="Summarize only this session")
    parser.add_argument("--date", help="Filter by date (e.g. 2026-03-24)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Build query
    conditions = ["EXISTS (SELECT 1 FROM chunks c WHERE c.session_id = s.id)"]
    params = []

    if args.session:
        conditions.append("s.id = ?")
        params.append(args.session)
    if args.date:
        conditions.append("s.date LIKE ?")
        params.append(f"{args.date}%")
    if not args.force:
        conditions.append("(s.summary IS NULL OR s.summary = '')")

    sql = f"SELECT s.id, s.username, s.date, s.duration_seconds FROM sessions s WHERE {' AND '.join(conditions)} ORDER BY s.date"
    sessions = conn.execute(sql, params).fetchall()

    if not sessions:
        print("No hay sesiones pendientes de resumir.")
        conn.close()
        return

    print(f"Resumiendo {len(sessions)} sesiones con {GEMINI_MODEL}...\n", flush=True)

    success = 0
    errors = 0

    for idx, (session_id, username, date, duration_seconds) in enumerate(sessions):
        chunks = conn.execute(
            "SELECT text FROM chunks WHERE session_id = ? ORDER BY start_seconds",
            (session_id,),
        ).fetchall()

        transcript = " ".join(row[0] for row in chunks if row[0])
        if not transcript.strip():
            print(f"  [{idx+1}/{len(sessions)}] @{username} {to_local_date(date)}: sin transcripcion", flush=True)
            continue

        duration_min = round(duration_seconds / 60) if duration_seconds else None
        prompt = build_prompt(username, duration_min, transcript)

        label = f"[{idx+1}/{len(sessions)}] @{username} {to_local_date(date)}"
        try:
            summary = summarize(client, prompt)
            if summary:
                conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id))
                conn.commit()
                success += 1
                preview = summary[:80].replace("\n", " ")
                print(f"  {label}: {preview}...", flush=True)
            else:
                print(f"  {label}: respuesta vacia", flush=True)

            time.sleep(4)  # 20 req/day budget

        except Exception as e:
            errors += 1
            print(f"  {label}: error — {e}", flush=True)
            time.sleep(2)

    conn.close()
    print(f"\nListo! {success} sesiones resumidas, {errors} errores.")


if __name__ == "__main__":
    main()
