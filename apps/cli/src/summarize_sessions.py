"""Generate semantic summaries for indexed sessions using Gemini.

Usage:
    cd apps/cli && uv run src/summarize_sessions.py [--force]

Options:
    --force    Regenerate summaries even for sessions that already have one
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

DB_PATH = REPO_ROOT / "clips.db"


def build_prompt(username: str, duration_min: int | None, transcript: str) -> str:
    duration_note = f" ({duration_min} minutos)" if duration_min else ""
    # Truncate to ~8000 chars for token budget
    truncated = transcript[:8000]

    return f"""Eres un asistente que resume sesiones de TikTok Live en español.

Dado el siguiente transcrito de un live de "{username}"{duration_note}, genera un resumen breve y claro.

Reglas:
- Máximo 5 párrafos cortos (2 líneas cada uno)
- Cada párrafo cubre un tema o momento distinto de la sesión
- Usa un tono casual y directo, como notas personales
- No uses bullets, listas ni encabezados — solo párrafos separados por línea vacía
- Si la sesión es corta (<15 min), 2-3 párrafos bastan
- Captura el tono emocional: si fue divertida, emotiva, relajada, etc.

Transcrito:
{truncated}"""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Generate session summaries with Gemini")
    parser.add_argument("--force", action="store_true", help="Regenerate all summaries")
    args = parser.parse_args()

    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Get sessions needing summaries
    if args.force:
        sessions = conn.execute(
            "SELECT id, username, duration_seconds FROM sessions ORDER BY id"
        ).fetchall()
    else:
        sessions = conn.execute(
            "SELECT id, username, duration_seconds FROM sessions WHERE summary IS NULL ORDER BY id"
        ).fetchall()

    if not sessions:
        print("All sessions already have summaries. Use --force to regenerate.")
        return

    print(f"Generating summaries for {len(sessions)} session(s)...\n")

    for session_id, username, duration_seconds in sessions:
        # Get transcript
        chunks = conn.execute(
            "SELECT text FROM chunks WHERE session_id = ? ORDER BY start_seconds",
            (session_id,),
        ).fetchall()

        transcript = " ".join(row[0] for row in chunks if row[0])
        if not transcript.strip():
            print(f"  Session {session_id} ({username}): no transcript, skipping")
            continue

        duration_min = round(duration_seconds / 60) if duration_seconds else None
        prompt = build_prompt(username, duration_min, transcript)

        print(f"  Session {session_id} ({username}, {duration_min or '?'}min)...", end=" ", flush=True)

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=500,
                ),
            )
            summary = response.text.strip() if response.text else ""

            if summary:
                conn.execute(
                    "UPDATE sessions SET summary = ? WHERE id = ?",
                    (summary, session_id),
                )
                conn.commit()
                lines = summary.count("\n") + 1
                print(f"OK ({lines} lines)")
            else:
                print("empty response")

        except Exception as e:
            print(f"FAILED: {e}")

        # Rate limit
        time.sleep(1)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
