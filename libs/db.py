"""Centralized PostgreSQL connection for all apps.

Usage:
    from db import get_connection

    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM sessions").fetchall()
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

SCHEMA = "tiktok_manager"


def get_connection(**kwargs) -> psycopg.Connection:
    """Get a PostgreSQL connection with search_path set to tiktok_manager."""
    db_name = os.environ.get("DB_NAME", "PoCs_DB")
    db_user = os.environ.get("DB_USER", "postgres")
    db_password = os.environ.get("DB_PASSWORD", "")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")

    conn = psycopg.connect(
        host=db_host,
        port=int(db_port),
        dbname=db_name,
        user=db_user,
        password=db_password,
        **kwargs,
    )
    conn.execute(f"SET search_path TO {SCHEMA}")
    return conn
