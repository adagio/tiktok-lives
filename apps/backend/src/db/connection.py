"""Conexión SQLite readonly a clips.db."""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv(
    "CLIPS_DB_PATH",
    str(Path(__file__).resolve().parents[4] / "clips.db"),
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
