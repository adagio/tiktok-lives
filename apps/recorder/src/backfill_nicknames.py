"""One-shot backfill: populate nickname for existing guests."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from battles import resolve_user_id, _ensure_nickname_column

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = REPO_ROOT / "clips.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    _ensure_nickname_column(conn)

    # Get distinct user_ids that have no nickname yet
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM guests WHERE nickname IS NULL"
    ).fetchall()

    if not rows:
        print("All guests already have nicknames.")
        conn.close()
        return

    print(f"Found {len(rows)} user_ids without nickname. Resolving...")

    resolved = 0
    for (user_id,) in rows:
        try:
            username, nickname = resolve_user_id(user_id)
            if nickname:
                conn.execute(
                    "UPDATE guests SET nickname = ? WHERE user_id = ? AND nickname IS NULL",
                    (nickname, user_id),
                )
                conn.commit()
                print(f"  ✓ {user_id} → @{username} ({nickname})")
                resolved += 1
            else:
                print(f"  - {user_id} → @{username} (no nickname found)")
        except Exception as e:
            print(f"  ✗ {user_id} → error: {e}")

        # Be polite to TikTok
        time.sleep(1)

    conn.close()
    print(f"\nDone. Updated {resolved}/{len(rows)} users.")


if __name__ == "__main__":
    main()
