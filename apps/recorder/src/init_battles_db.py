"""One-shot migration: create the battles table in clips.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = REPO_ROOT / "clips.db"

SQL = """
CREATE TABLE IF NOT EXISTS battles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER REFERENCES sessions(id),
  battle_id INTEGER NOT NULL,
  opponent_username TEXT NOT NULL,
  opponent_user_id INTEGER NOT NULL,
  host_score INTEGER DEFAULT 0,
  opponent_score INTEGER DEFAULT 0,
  detected_at TEXT NOT NULL,
  UNIQUE(battle_id, opponent_user_id)
);
CREATE INDEX IF NOT EXISTS idx_battles_session ON battles(session_id);
CREATE INDEX IF NOT EXISTS idx_battles_battle_id ON battles(battle_id);

CREATE TABLE IF NOT EXISTS guests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER REFERENCES sessions(id),
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  joined_at TEXT NOT NULL,
  left_at TEXT,
  UNIQUE(session_id, user_id, joined_at)
);
CREATE INDEX IF NOT EXISTS idx_guests_session ON guests(session_id);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  battle_id INTEGER,
  room_username TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  text TEXT NOT NULL,
  timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_battle ON chat_messages(battle_id);
CREATE INDEX IF NOT EXISTS idx_chat_timestamp ON chat_messages(timestamp);

CREATE TABLE IF NOT EXISTS viewer_joins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  room_username TEXT NOT NULL,
  user_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  joined_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_viewer_joins_session ON viewer_joins(session_id);
CREATE INDEX IF NOT EXISTS idx_viewer_joins_joined ON viewer_joins(joined_at);
"""


def main():
    print(f"Database: {DB_PATH}")
    if not DB_PATH.exists():
        print("WARNING: clips.db does not exist yet — creating it.")

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SQL)
        print("battles + guests + chat_messages + viewer_joins tables created (or already exist).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
