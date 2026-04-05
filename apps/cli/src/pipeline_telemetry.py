"""Pipeline telemetry: log processing events to PostgreSQL for later visualization."""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "libs"))

from db import get_connection


def log_event(
    session_id: int | None,
    phase: str,
    *,
    step: str | None = None,
    context: str | None = None,
    status: str = "completed",
    started_at: str | None = None,
    finished_at: str | None = None,
    elapsed_seconds: float | None = None,
    input_bytes: int | None = None,
    output_bytes: int | None = None,
    record_count: int | None = None,
    provider: str | None = None,
    detail: dict | None = None,
) -> int:
    """Insert a pipeline event. Returns the row ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO pipeline_events
               (session_id, phase, step, context, status, started_at, finished_at,
                elapsed_seconds, input_bytes, output_bytes, record_count, provider, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                session_id, phase, step, context, status,
                started_at, finished_at, elapsed_seconds,
                input_bytes, output_bytes, record_count, provider,
                json.dumps(detail) if detail else None,
            ),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def track_step(
    session_id: int | None,
    phase: str,
    *,
    step: str | None = None,
    context: str | None = None,
    provider: str | None = None,
):
    """Context manager that auto-records started_at, finished_at, elapsed, and status.

    Yields a dict where the caller can set extra fields:
        with track_step(sid, "audio_extract") as t:
            t["input_bytes"] = file_size
            ... do work ...
            t["output_bytes"] = output_size
            t["record_count"] = 1
    """
    t = {
        "input_bytes": None,
        "output_bytes": None,
        "record_count": None,
        "provider": provider,
        "detail": None,
    }
    started = _now_iso()
    t0 = time.time()
    status = "completed"
    try:
        yield t
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.time() - t0
        finished = _now_iso()
        log_event(
            session_id, phase,
            step=step, context=context, status=status,
            started_at=started, finished_at=finished,
            elapsed_seconds=elapsed,
            input_bytes=t.get("input_bytes"),
            output_bytes=t.get("output_bytes"),
            record_count=t.get("record_count"),
            provider=t.get("provider"),
            detail=t.get("detail"),
        )
