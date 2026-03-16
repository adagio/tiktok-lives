"""Battle detection via TikTok Webcast REST API (sync) + SQLite persistence."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

import httpx
import psutil

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def get_room_id(username: str) -> str | None:
    """Scrape room_id from the TikTok live page."""
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        resp = client.get(f"https://www.tiktok.com/@{username}/live")
        match = re.search(r"roomId[^0-9]*(\d{10,})", resp.text)
        return match.group(1) if match else None


def get_host_user_id(username: str) -> int | None:
    """Get the TikTok user_id for a host via room/info API."""
    try:
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(f"https://www.tiktok.com/@{username}/live")
            match = re.search(r"roomId[^0-9]*(\d{10,})", resp.text)
            if not match:
                return None
            room_id = match.group(1)
            resp = client.get(
                f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}"
            )
            uid = resp.json().get("data", {}).get("owner_user_id")
            return int(uid) if uid else None
    except Exception:
        return None


def get_battle_info(room_id: str) -> dict | None:
    """Fetch battle data from Webcast room info API.

    Returns a dict with battle_id, rival_anchor_id, scores, etc.
    Returns None if no battle is active.
    """
    url = f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}"
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as client:
        resp = client.get(url)
        data = resp.json()

    link_mic = data.get("data", {}).get("link_mic")
    if not link_mic:
        return None

    battle = link_mic.get("battle_settings", {})
    scores = link_mic.get("battle_scores", [])
    rival_id = link_mic.get("rival_anchor_id")

    if not rival_id and not scores:
        return None

    return {
        "battle_id": battle.get("battle_id"),
        "battle_status": battle.get("battle_status"),
        "duration": battle.get("duration"),
        "rival_anchor_id": rival_id,
        "scores": {s["user_id"]: s.get("score", 0) for s in scores},
    }


def get_session_id(db_path: str, username: str) -> int | None:
    """Find the latest session_id for a username in clips.db."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE username = ? ORDER BY date DESC LIMIT 1",
            (username,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _ensure_pid_column(conn: sqlite3.Connection) -> None:
    """Add pid column to sessions table if it doesn't exist."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "pid" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN pid INTEGER")
        conn.commit()


def create_session(db_path: str, username: str, date_iso: str, ts_path: str, pid: int | None = None) -> int:
    """Insert a session row when recording starts, return session_id."""
    conn = sqlite3.connect(db_path)
    try:
        _ensure_pid_column(conn)
        cur = conn.execute(
            "INSERT INTO sessions (username, date, ts_path, pid) VALUES (?, ?, ?, ?)",
            (username, date_iso, ts_path, pid),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_session_duration(db_path: str, session_id: int, duration_seconds: float) -> None:
    """Update duration_seconds when recording ends."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE sessions SET duration_seconds = ? WHERE id = ?",
            (duration_seconds, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_battle(
    db_path: str,
    session_id: int | None,
    battle_id: int,
    opponent_username: str,
    opponent_user_id: int,
    host_score: int = 0,
    opponent_score: int = 0,
) -> None:
    """Insert a new battle row (or ignore if already exists)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO battles
               (session_id, battle_id, opponent_username, opponent_user_id,
                host_score, opponent_score, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                battle_id,
                opponent_username,
                opponent_user_id,
                host_score,
                opponent_score,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_battle_scores(
    db_path: str,
    battle_id: int,
    opponent_user_id: int,
    host_score: int,
    opponent_score: int,
) -> None:
    """Update scores for an existing battle row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE battles SET host_score = ?, opponent_score = ?
               WHERE battle_id = ? AND opponent_user_id = ?""",
            (host_score, opponent_score, battle_id, opponent_user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_linked_users(room_id: str) -> list[dict]:
    """Fetch linked users from room info API.

    Returns list of {"user_id": int, "username": str} or empty list.
    Logs raw object on first non-empty hit for field discovery.
    """
    url = f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}"
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as client:
        resp = client.get(url)
        data = resp.json()

    link_mic = data.get("data", {}).get("link_mic")
    if not link_mic:
        return []

    linked = link_mic.get("linked_user_list") or []
    show = link_mic.get("show_user_list") or []

    # Merge both lists, dedup by user id
    all_users_raw = linked + show
    if not all_users_raw:
        return []

    # Discovery: log raw structure on first non-empty result
    import logging
    log = logging.getLogger("monitor")
    if not getattr(get_linked_users, "_logged_raw", False):
        log.info("🔍 Raw linked_user_list sample: %s", json.dumps(all_users_raw[:2], default=str))
        get_linked_users._logged_raw = True

    seen_ids: set[int] = set()
    result: list[dict] = []
    for u in all_users_raw:
        # Try common TikTok user object field names
        uid = u.get("id") or u.get("user_id")
        uname = u.get("display_id") or u.get("unique_id") or u.get("nickname") or f"id:{uid}"
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            result.append({"user_id": int(uid), "username": str(uname)})

    return result


def save_guest(db_path: str, session_id: int, user_id: int, username: str, joined_at: str) -> None:
    """Insert a new guest row (or ignore if already exists)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO guests
               (session_id, user_id, username, joined_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, user_id, username, joined_at),
        )
        conn.commit()
    finally:
        conn.close()


def update_guest_left(db_path: str, session_id: int, user_id: int, left_at: str) -> None:
    """Update left_at for the most recent guest entry without left_at."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE guests SET left_at = ?
               WHERE session_id = ? AND user_id = ? AND left_at IS NULL""",
            (left_at, session_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_viewer_joins(db_path: str, joins: list[dict]) -> None:
    """Insert a batch of viewer join events."""
    if not joins:
        return
    conn = sqlite3.connect(db_path)
    try:
        # Inline migration
        conn.execute(
            """CREATE TABLE IF NOT EXISTS viewer_joins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id),
                room_username TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                joined_at TEXT NOT NULL
            )"""
        )
        conn.executemany(
            """INSERT INTO viewer_joins
               (session_id, room_username, user_id, username, joined_at)
               VALUES (:session_id, :room_username, :user_id, :username, :joined_at)""",
            joins,
        )
        conn.commit()
    finally:
        conn.close()


def save_chat_messages(db_path: str, messages: list[dict]) -> None:
    """Insert a batch of chat messages."""
    if not messages:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """INSERT INTO chat_messages
               (session_id, battle_id, room_username, user_id, username, text, timestamp)
               VALUES (:session_id, :battle_id, :room_username, :user_id, :username, :text, :timestamp)""",
            messages,
        )
        conn.commit()
    finally:
        conn.close()


def _is_ffmpeg_alive(pid: int) -> bool:
    """Check if a PID is a running ffmpeg process."""
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and "ffmpeg" in proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def close_orphaned_sessions(db_path: str) -> tuple[list[dict], list[dict]]:
    """Handle sessions with duration_seconds IS NULL.

    Returns (closed, alive):
    - closed: sessions whose ffmpeg died — duration computed and saved
    - alive: sessions whose ffmpeg PID is still running — candidates for re-attach
    """
    conn = sqlite3.connect(db_path)
    try:
        _ensure_pid_column(conn)
        orphans = conn.execute(
            "SELECT id, username, date, ts_path, pid FROM sessions WHERE duration_seconds IS NULL"
        ).fetchall()
        if not orphans:
            return [], []

        closed = []
        alive = []
        for sid, username, date_str, ts_path, pid in orphans:
            # If we have a PID and it's still a running ffmpeg, mark as alive
            if pid and _is_ffmpeg_alive(pid):
                alive.append({
                    "id": sid, "username": username, "date": date_str,
                    "ts_path": ts_path, "pid": pid,
                })
                continue

            # Otherwise close the session with computed duration
            last_activity = None
            for query in [
                "SELECT MAX(timestamp) FROM chat_messages WHERE session_id = ?",
                "SELECT MAX(detected_at) FROM battles WHERE session_id = ?",
                "SELECT MAX(COALESCE(left_at, joined_at)) FROM guests WHERE session_id = ?",
            ]:
                row = conn.execute(query, (sid,)).fetchone()
                ts = row[0] if row else None
                if ts and (last_activity is None or ts > last_activity):
                    last_activity = ts

            if last_activity:
                try:
                    t_start = datetime.fromisoformat(date_str)
                    t_end = datetime.fromisoformat(last_activity)
                    duration = (t_end - t_start).total_seconds()
                    if duration < 0:
                        duration = 0.0
                except (ValueError, TypeError):
                    duration = 0.0
            else:
                duration = 0.0

            conn.execute(
                "UPDATE sessions SET duration_seconds = ? WHERE id = ?",
                (duration, sid),
            )
            closed.append({"id": sid, "username": username, "duration": duration})

        conn.commit()
        return closed, alive
    finally:
        conn.close()


def resolve_user_id(user_id: int) -> str:
    """Resolve a TikTok numeric user ID to @username via share redirect."""
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        resp = client.get(f"https://www.tiktok.com/share/user/{user_id}")
        match = re.search(r"tiktok\.com/@([^/?]+)", str(resp.url))
        return match.group(1) if match else f"id:{user_id}"
