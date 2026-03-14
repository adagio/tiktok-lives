"""Router de clips."""

from fastapi import APIRouter, Query

from src.api.schemas.clips import ClipResponse, FiltersResponse, StatsResponse
from src.db.connection import get_db

router = APIRouter()


@router.get("/", response_model=list[ClipResponse], summary="Listar clips")
async def list_clips(
    author: str | None = Query(None),
    query: str | None = Query(None, alias="q"),
    mode: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    try:
        conditions: list[str] = []
        params: list[str] = []

        if author:
            conditions.append("c.username = ?")
            params.append(author)
        if query:
            conditions.append("c.query = ?")
            params.append(query)
        if mode:
            conditions.append("c.search_mode = ?")
            params.append(mode)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql = f"""
            SELECT c.*, ch.text, s.date
            FROM clips c
            LEFT JOIN chunks ch ON c.chunk_id = ch.id
            LEFT JOIN sessions s ON c.session_id = s.id
            {where}
            ORDER BY c.score DESC
            LIMIT ? OFFSET ?
        """
        params.extend([str(limit), str(offset)])
        rows = db.execute(sql, params).fetchall()

        return [
            ClipResponse(
                id=r["id"],
                chunk_id=r["chunk_id"],
                session_id=r["session_id"],
                username=r["username"],
                query=r["query"],
                search_mode=r["search_mode"],
                score=r["score"],
                start_seconds=r["start_seconds"],
                end_seconds=r["end_seconds"],
                duration_seconds=round(r["end_seconds"] - r["start_seconds"], 1),
                filename=r["filename"],
                created_at=r["created_at"],
                text=r["text"],
                date=r["date"],
            )
            for r in rows
        ]
    finally:
        db.close()


@router.get("/stats", response_model=StatsResponse, summary="Estadísticas de clips")
async def get_stats():
    db = get_db()
    try:
        total_clips = db.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        total_sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        unique_authors = db.execute(
            "SELECT COUNT(DISTINCT username) FROM clips"
        ).fetchone()[0]
        unique_queries = db.execute(
            "SELECT COUNT(DISTINCT query) FROM clips"
        ).fetchone()[0]

        return StatsResponse(
            total_clips=total_clips,
            total_sessions=total_sessions,
            unique_authors=unique_authors,
            unique_queries=unique_queries,
        )
    finally:
        db.close()


@router.get(
    "/filters", response_model=FiltersResponse, summary="Valores disponibles para filtros"
)
async def get_filters():
    db = get_db()
    try:
        authors = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT username FROM clips ORDER BY username"
            ).fetchall()
        ]
        queries = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT query FROM clips ORDER BY query"
            ).fetchall()
        ]
        modes = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT search_mode FROM clips ORDER BY search_mode"
            ).fetchall()
        ]

        return FiltersResponse(authors=authors, queries=queries, modes=modes)
    finally:
        db.close()
