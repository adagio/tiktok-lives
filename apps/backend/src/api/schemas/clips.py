"""Schemas Pydantic para clips."""

from pydantic import BaseModel


class ClipResponse(BaseModel):
    id: int
    chunk_id: int
    session_id: int
    username: str
    query: str | None
    search_mode: str | None
    score: float
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    filename: str
    created_at: str
    text: str | None = None
    date: str | None = None


class StatsResponse(BaseModel):
    total_clips: int
    total_sessions: int
    unique_authors: int
    unique_queries: int


class FiltersResponse(BaseModel):
    authors: list[str]
    queries: list[str]
    modes: list[str]
