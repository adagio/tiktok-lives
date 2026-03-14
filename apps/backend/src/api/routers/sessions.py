"""Router de sessions."""

from pydantic import BaseModel
from fastapi import APIRouter

from src.db.connection import get_db

router = APIRouter()


class SessionResponse(BaseModel):
    id: int
    username: str
    date: str
    ts_path: str | None
    srt_path: str | None
    audio_path: str | None
    duration_seconds: float | None
    indexed_at: str
    chunk_count: int


@router.get("/", response_model=list[SessionResponse], summary="Listar sesiones")
async def list_sessions():
    db = get_db()
    try:
        rows = db.execute(
            """
            SELECT s.*, COUNT(ch.id) as chunk_count
            FROM sessions s
            LEFT JOIN chunks ch ON ch.session_id = s.id
            GROUP BY s.id
            ORDER BY s.date DESC
            """
        ).fetchall()

        return [
            SessionResponse(
                id=r["id"],
                username=r["username"],
                date=r["date"],
                ts_path=r["ts_path"],
                srt_path=r["srt_path"],
                audio_path=r["audio_path"],
                duration_seconds=r["duration_seconds"],
                indexed_at=r["indexed_at"],
                chunk_count=r["chunk_count"],
            )
            for r in rows
        ]
    finally:
        db.close()
