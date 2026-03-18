"""Check TikTok profiles for latest video/status uploads."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

import httpx

log = logging.getLogger("monitor.profile")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def _ensure_table(db_path: str) -> None:
    """Create user_videos table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                video_id TEXT NOT NULL,
                description TEXT,
                create_time TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                UNIQUE(username, video_id)
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def fetch_latest_videos(username: str) -> list[dict] | None:
    """Scrape latest videos from a TikTok profile page.

    Returns a list of dicts with keys: video_id, description, create_time (ISO).
    Returns None on failure.
    """
    try:
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(f"https://www.tiktok.com/@{username}")
            if resp.status_code != 200:
                log.debug("Profile fetch for @%s returned %d", username, resp.status_code)
                return None

            # TikTok embeds JSON state in a <script> tag
            # Try __UNIVERSAL_DATA_FOR_REHYDRATION__ first
            match = re.search(
                r'<script\s+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
                resp.text,
                re.DOTALL,
            )
            if match:
                data = json.loads(match.group(1))
                return _extract_from_universal(data, username)

            # Fallback: SIGI_STATE
            match = re.search(
                r'<script\s+id="SIGI_STATE"[^>]*>(.*?)</script>',
                resp.text,
                re.DOTALL,
            )
            if match:
                data = json.loads(match.group(1))
                return _extract_from_sigi(data, username)

            log.debug("No embedded JSON found for @%s", username)
            return None
    except Exception:
        log.debug("Failed to fetch profile for @%s", username, exc_info=True)
        return None


def _extract_from_universal(data: dict, username: str) -> list[dict]:
    """Extract video list from __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON."""
    videos = []
    try:
        # Navigate the nested structure
        default_scope = data.get("__DEFAULT_SCOPE__", {})
        user_detail = default_scope.get("webapp.user-detail", {})
        item_list = user_detail.get("userInfo", {}).get("user", {})

        # Videos are typically in userPost or itemList
        user_post = default_scope.get("webapp.user-detail", {})
        post_data = default_scope.get("webapp.video-detail", {})

        # Try direct itemList path
        for key in ("webapp.user-detail",):
            section = default_scope.get(key, {})
            items = section.get("itemList", [])
            if items:
                for item in items[:5]:  # Only latest 5
                    vid = _parse_video_item(item)
                    if vid:
                        videos.append(vid)
                return videos

        # Try nested post list
        for key, val in default_scope.items():
            if isinstance(val, dict):
                items = val.get("itemList", [])
                if items:
                    for item in items[:5]:
                        vid = _parse_video_item(item)
                        if vid:
                            videos.append(vid)
                    return videos
    except Exception:
        log.debug("Error parsing universal data for @%s", username, exc_info=True)

    return videos


def _extract_from_sigi(data: dict, username: str) -> list[dict]:
    """Extract video list from SIGI_STATE JSON."""
    videos = []
    try:
        item_module = data.get("ItemModule", {})
        for vid_id, item in list(item_module.items())[:5]:
            create_ts = item.get("createTime")
            if create_ts:
                videos.append({
                    "video_id": str(vid_id),
                    "description": item.get("desc", ""),
                    "create_time": datetime.fromtimestamp(
                        int(create_ts), tz=timezone.utc
                    ).isoformat(),
                })
    except Exception:
        log.debug("Error parsing SIGI data for @%s", username, exc_info=True)

    return videos


def _parse_video_item(item: dict) -> dict | None:
    """Parse a single video item from TikTok JSON."""
    video_id = item.get("id") or item.get("video", {}).get("id")
    create_time = item.get("createTime")
    if not video_id or not create_time:
        return None
    try:
        ts = datetime.fromtimestamp(int(create_time), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None
    return {
        "video_id": str(video_id),
        "description": item.get("desc", ""),
        "create_time": ts,
    }


def save_new_videos(db_path: str, username: str, videos: list[dict]) -> int:
    """Save newly detected videos. Returns count of new videos inserted."""
    _ensure_table(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    new_count = 0
    try:
        for v in videos:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO user_videos
                       (username, video_id, description, create_time, detected_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (username, v["video_id"], v["description"], v["create_time"], now),
                )
                if conn.total_changes > 0:
                    new_count += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return new_count
    finally:
        conn.close()


def check_and_save(db_path: str, username: str) -> int:
    """Fetch latest videos for a user and save new ones. Returns new video count."""
    _ensure_table(db_path)
    videos = fetch_latest_videos(username)
    if videos is None:
        return 0
    return save_new_videos(db_path, username, videos)
