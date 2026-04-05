"""Extract topics and summaries from chat via LLM providers.

Processes sessions one at a time, skipping already-analyzed ones.
Adaptive rate limiting tracks actual API responses per provider.
Falls back between providers on rate limit (Gemini → Groq → wait).

Usage:
    cd apps/cli && uv run src/analyze_chat.py [--force] [--session ID] [--provider gemini|groq|auto]
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection

LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "UTC"))
MAX_CHAT_CHARS = 50000

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


# ---------------------------------------------------------------------------
# Rate limit tracker (persisted in PostgreSQL)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Adaptive per-provider rate limiter. Learns from history in api_rate_log."""

    def __init__(self, provider: str, conn, initial_delay: float = 2.0):
        self.provider = provider
        self.conn = conn
        self.delay = initial_delay
        self.min_delay = 1.0
        self.max_delay = 120.0
        self.consecutive_ok = 0
        self.consecutive_429 = 0
        self._load_history()

    def _load_history(self):
        recent_429 = self.conn.execute(
            "SELECT COUNT(*) FROM api_rate_log "
            "WHERE provider = %s AND status = '429' AND timestamp > NOW() - INTERVAL '1 hour'",
            (self.provider,),
        ).fetchone()[0]
        recent_ok = self.conn.execute(
            "SELECT COUNT(*) FROM api_rate_log "
            "WHERE provider = %s AND status = 'ok' AND timestamp > NOW() - INTERVAL '10 minutes'",
            (self.provider,),
        ).fetchone()[0]
        if recent_429 > 5:
            self.delay = min(self.delay * 2, self.max_delay)
        elif recent_ok > 10 and recent_429 == 0:
            self.delay = max(self.delay * 0.8, self.min_delay)

    def _log(self, status: str, detail: str = ""):
        self.conn.execute(
            "INSERT INTO api_rate_log (provider, timestamp, status, delay_seconds, error_detail) "
            "VALUES (%s, %s, %s, %s, %s)",
            (self.provider, datetime.now(timezone.utc), status, self.delay, detail or None),
        )
        self.conn.commit()

    def record_ok(self):
        self.consecutive_ok += 1
        self.consecutive_429 = 0
        if self.consecutive_ok >= 3:
            self.delay = max(self.delay * 0.9, self.min_delay)
        self._log("ok")

    def record_429(self, detail: str = ""):
        self.consecutive_429 += 1
        self.consecutive_ok = 0
        self.delay = min(self.delay * (1.5 + self.consecutive_429 * 0.5), self.max_delay)
        self._log("429", detail)

    def record_error(self, detail: str = ""):
        self._log("error", detail)

    def wait(self):
        time.sleep(self.delay)

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_429 < 3

    def stats_line(self) -> str:
        row = self.conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='429' THEN 1 ELSE 0 END) "
            "FROM api_rate_log WHERE provider = %s AND timestamp > NOW() - INTERVAL '1 hour'",
            (self.provider,),
        ).fetchone()
        return f"{row[1] or 0} ok / {row[2] or 0} rate-limited (last hour), delay={self.delay:.1f}s"


# ---------------------------------------------------------------------------
# Provider callables
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
    result = json.loads(text)
    if "topics" not in result or "summary" not in result:
        raise ValueError("Missing topics or summary in response")
    return result


def _call_gemini(chat_text: str) -> tuple[dict, str]:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(model="gemini-2.0-flash-lite", contents=PROMPT + chat_text)
    return _parse_json(resp.text), "gemini-2.0-flash-lite"


def _call_groq(chat_text: str) -> tuple[dict, str]:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": PROMPT + chat_text}],
        temperature=0.3,
    )
    return _parse_json(resp.choices[0].message.content), "llama-3.3-70b-versatile"


# provider name → (callable, env var required, default delay)
PROVIDERS = {
    "gemini": (_call_gemini, "GEMINI_API_KEY", 2.0),
    "groq": (_call_groq, "GROQ_API_KEY", 2.0),
}


def _is_rate_limit(err: Exception) -> bool:
    s = str(err).lower()
    return "429" in s or "resource_exhausted" in s or "rate_limit" in s


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _get_pending(conn, force: bool, session_id: int | None) -> list[tuple]:
    if session_id:
        rows = conn.execute(
            "SELECT DISTINCT cc.session_id, s.username, s.date "
            "FROM chat_chunks cc JOIN sessions s ON cc.session_id = s.id "
            "WHERE cc.session_id = %s",
            (session_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT cc.session_id, s.username, s.date "
            "FROM chat_chunks cc JOIN sessions s ON cc.session_id = s.id "
            "ORDER BY s.date",
        ).fetchall()

    if force:
        return rows

    existing = {r[0] for r in conn.execute("SELECT session_id FROM chat_analysis").fetchall()}
    return [r for r in rows if r[0] not in existing]


def _get_chat_text(conn, session_id: int) -> str | None:
    chunks = conn.execute(
        "SELECT text FROM chat_chunks WHERE session_id = %s ORDER BY start_time",
        (session_id,),
    ).fetchall()
    if not chunks:
        return None
    text = "\n---\n".join(c[0] for c in chunks)
    return text[:MAX_CHAT_CHARS] if len(text) > MAX_CHAT_CHARS else text


def _save_analysis(conn, session_id: int, result: dict, model: str):
    conn.execute(
        "INSERT INTO chat_analysis (session_id, topics, summary, model) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (session_id) DO UPDATE SET topics = EXCLUDED.topics, summary = EXCLUDED.summary, model = EXCLUDED.model",
        (session_id, json.dumps(result["topics"], ensure_ascii=False), result["summary"], model),
    )
    conn.commit()


def _to_local(date_val) -> str:
    try:
        if isinstance(date_val, str):
            dt = datetime.fromisoformat(date_val)
        else:
            dt = date_val
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(date_val)[:16]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Chat analysis via LLM (Gemini/Groq)")
    parser.add_argument("--force", action="store_true", help="Re-analyze all sessions")
    parser.add_argument("--session", type=int, help="Analyze only this session")
    parser.add_argument("--provider", choices=["gemini", "groq", "auto"], default="auto")
    args = parser.parse_args()

    conn = get_connection()

    if args.force and args.session:
        conn.execute("DELETE FROM chat_analysis WHERE session_id = %s", (args.session,))
        conn.commit()
    elif args.force:
        conn.execute("DELETE FROM chat_analysis")
        conn.commit()

    # Resolve available providers
    if args.provider == "auto":
        order = [name for name, (_, env, _) in PROVIDERS.items() if os.environ.get(env)]
    else:
        order = [args.provider]
    if not order:
        sys.exit("No API keys configured. Set GEMINI_API_KEY or GROQ_API_KEY in .env")

    limiters = {name: RateLimiter(name, conn, PROVIDERS[name][2]) for name in order}

    pending = _get_pending(conn, args.force, args.session)
    total = len(pending)

    if total == 0:
        print("Nada pendiente. Usa --force para re-analizar.")
        conn.close()
        return

    print(f"\n{'='*60}", flush=True)
    print(f"  Chat analysis — {total} sessions pending", flush=True)
    print(f"  Providers: {', '.join(order)}", flush=True)
    for name in order:
        print(f"    {name}: {limiters[name].stats_line()}", flush=True)
    print(f"{'='*60}\n", flush=True)

    from pipeline_telemetry import log_event

    success = 0
    errors = 0
    skipped = 0
    t0 = time.time()

    for idx, (session_id, username, date) in enumerate(pending):
        done = idx + 1
        pct = done * 100 // total
        elapsed = time.time() - t0
        eta = (elapsed / max(success + errors, 1)) * (total - done)

        already = conn.execute(
            "SELECT 1 FROM chat_analysis WHERE session_id = %s", (session_id,)
        ).fetchone()
        if already and not args.force:
            skipped += 1
            continue

        chat_text = _get_chat_text(conn, session_id)
        if not chat_text:
            skipped += 1
            print(f"  [{done}/{total}] {pct}% — #{session_id} @{username} — sin texto, saltando", flush=True)
            continue

        label = f"[{done}/{total}] {pct}% #{session_id} @{username} {_to_local(date)}"
        analyzed = False

        for provider_name in order:
            limiter = limiters[provider_name]
            if not limiter.is_healthy:
                continue

            try:
                call_fn = PROVIDERS[provider_name][0]
                result, model = call_fn(chat_text)
                limiter.record_ok()

                _save_analysis(conn, session_id, result, model)
                success += 1
                analyzed = True

                topics_preview = ", ".join(result["topics"][:3])
                print(f"  {label} OK [{provider_name}] {topics_preview} (ETA {eta:.0f}s)", flush=True)

                log_event(session_id, "analyze_chat", status="completed",
                          elapsed_seconds=time.time() - t0 if idx == 0 else None,
                          provider=provider_name,
                          record_count=len(result.get("topics", [])),
                          detail={"model": model, "topics": result.get("topics", [])})

                limiter.wait()
                break

            except json.JSONDecodeError as e:
                limiter.record_error(str(e)[:200])
                errors += 1
                log_event(session_id, "analyze_chat", status="error",
                          provider=provider_name, detail={"error": "json_parse"})
                print(f"  {label} FAIL [{provider_name}] JSON parse error", flush=True)
                break

            except Exception as e:
                if _is_rate_limit(e):
                    limiter.record_429(str(e)[:200])
                    print(f"  {label} WAIT [{provider_name}] rate limited, delay={limiter.delay:.0f}s", flush=True)
                else:
                    limiter.record_error(str(e)[:200])
                    errors += 1
                    log_event(session_id, "analyze_chat", status="error",
                              provider=provider_name, detail={"error": str(e)[:200]})
                    print(f"  {label} FAIL [{provider_name}] {str(e)[:80]}", flush=True)
                    break

        if not analyzed and not already:
            healthy = [n for n in order if limiters[n].is_healthy]
            if not healthy:
                best = min(order, key=lambda n: limiters[n].delay)
                wait = limiters[best].delay
                print(f"  WAIT All providers exhausted. Waiting {wait:.0f}s for {best}...", flush=True)
                time.sleep(wait)
                limiters[best].consecutive_429 = 0

    elapsed_total = time.time() - t0
    print(f"\n{'='*60}", flush=True)
    print(f"  Done: {success} analyzed, {errors} errors, {skipped} skipped", flush=True)
    print(f"  Time: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)", flush=True)
    for name in order:
        print(f"    {name}: {limiters[name].stats_line()}", flush=True)
    print(f"{'='*60}", flush=True)

    conn.close()


if __name__ == "__main__":
    main()
