"""Migrate battles table to normalized schema (battles_v2 + battle_participants).

Creates a backward-compatible view so existing queries keep working.

Usage:
    cd apps/cli && uv run src/migrate_battles.py [--execute]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection


def check_already_migrated(conn) -> bool:
    """Check if battles_v2 already has data."""
    row = conn.execute("SELECT COUNT(*) FROM battles_v2").fetchone()
    return row[0] > 0


def build_user_lookup(conn) -> dict[str, int]:
    """Build username -> user_id mapping from existing battle data."""
    rows = conn.execute(
        "SELECT DISTINCT opponent_username, opponent_user_id FROM battles"
    ).fetchall()
    lookup = {username: user_id for username, user_id in rows}

    host_rows = conn.execute("""
        SELECT DISTINCT s.username FROM battles b
        JOIN sessions s ON b.session_id = s.id
        WHERE s.username NOT IN (SELECT opponent_username FROM battles)
    """).fetchall()

    for (username,) in host_rows:
        try:
            import httpx, re
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            with httpx.Client(headers=headers, timeout=15, follow_redirects=True) as client:
                resp = client.get(f"https://www.tiktok.com/@{username}/live")
                match = re.search(r"roomId[^0-9]*(\d{10,})", resp.text)
                if match:
                    room_id = match.group(1)
                    resp2 = client.get(f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}")
                    uid = resp2.json().get("data", {}).get("owner_user_id")
                    if uid:
                        lookup[username] = int(uid)
                        print(f"  Resolved @{username} -> {uid} via API")
        except Exception:
            pass

    return lookup


def migrate(conn, *, dry_run: bool = True) -> dict:
    """Run the migration. Returns stats dict."""
    stats = {"battles_v2": 0, "participants": 0, "unknown_hosts": []}

    user_lookup = build_user_lookup(conn)
    print(f"User lookup: {len(user_lookup)} users found")
    for username, uid in sorted(user_lookup.items()):
        print(f"  @{username} -> {uid}")

    rows = conn.execute("""
        SELECT b.id, b.session_id, b.battle_id, b.opponent_username,
               b.opponent_user_id, b.host_score, b.opponent_score,
               b.detected_at, s.username as host_username
        FROM battles b
        LEFT JOIN sessions s ON b.session_id = s.id
        ORDER BY b.battle_id, b.detected_at
    """).fetchall()

    battles: dict[int, list] = {}
    for row in rows:
        bid = row[2]
        battles.setdefault(bid, []).append(row)

    print(f"\nFound {len(rows)} battle rows -> {len(battles)} unique battles")

    if dry_run:
        for battle_id, entries in sorted(battles.items()):
            participants = set()
            for entry in entries:
                host_username = entry[8]
                if host_username:
                    host_uid = user_lookup.get(host_username)
                    participants.add((host_username, host_uid, entry[1]))
                    if host_uid is None:
                        stats["unknown_hosts"].append(host_username)
                opp_username = entry[3]
                opp_uid = entry[4]
                participants.add((opp_username, opp_uid, None))

            stats["battles_v2"] += 1
            stats["participants"] += len(participants)

        unknown = set(stats["unknown_hosts"])
        if unknown:
            print(f"\nWARNING: {len(unknown)} host(s) without user_id: {unknown}")
            print("These users never appeared as opponents. They will get user_id=0.")

        print(f"\nDry-run result: {stats['battles_v2']} battles, {stats['participants']} participants")
        return stats

    # Execute migration — tables already exist in PG schema
    for battle_id, entries in battles.items():
        earliest = min(e[7] for e in entries)
        conn.execute(
            "INSERT INTO battles_v2 (battle_id, detected_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (battle_id, earliest),
        )
        stats["battles_v2"] += 1

        participants: dict[int, dict] = {}

        for entry in entries:
            _id, session_id, _bid, opp_username, opp_uid, host_score, opp_score, _det, host_username = entry

            if host_username:
                host_uid = user_lookup.get(host_username, 0)
                if host_uid != 0:
                    if host_uid not in participants or host_score > participants[host_uid]["score"]:
                        participants.setdefault(host_uid, {
                            "username": host_username,
                            "session_id": session_id,
                            "score": host_score,
                        })
                        participants[host_uid]["score"] = max(participants[host_uid]["score"], host_score)
                        if session_id is not None:
                            participants[host_uid]["session_id"] = session_id

            if opp_uid not in participants or opp_score > participants[opp_uid]["score"]:
                opp_session = None
                for other_entry in entries:
                    if other_entry[8] == opp_username:
                        opp_session = other_entry[1]
                        break
                participants.setdefault(opp_uid, {
                    "username": opp_username,
                    "session_id": opp_session,
                    "score": opp_score,
                })
                participants[opp_uid]["score"] = max(participants[opp_uid]["score"], opp_score)
                if opp_session is not None:
                    participants[opp_uid]["session_id"] = opp_session

        for uid, p in participants.items():
            conn.execute(
                """INSERT INTO battle_participants
                   (battle_id, user_id, username, session_id, score)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (battle_id, user_id) DO NOTHING""",
                (battle_id, uid, p["username"], p["session_id"], p["score"]),
            )
            stats["participants"] += 1

    conn.commit()
    print(f"\nMigrated: {stats['battles_v2']} battles, {stats['participants']} participants")
    return stats


def verify(conn) -> bool:
    """Verify migration."""
    v2_count = conn.execute("SELECT COUNT(*) FROM battles_v2").fetchone()[0]
    bp_count = conn.execute("SELECT COUNT(*) FROM battle_participants").fetchone()[0]
    print(f"\nVerification:")
    print(f"  battles_v2:   {v2_count}")
    print(f"  participants: {bp_count}")
    print("  OK" if v2_count > 0 else "  EMPTY")
    return v2_count > 0


def main():
    parser = argparse.ArgumentParser(description="Migrate battles to normalized schema")
    parser.add_argument("--execute", action="store_true", help="Actually run migration (default: dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        if check_already_migrated(conn):
            print("battles_v2 already has data. Migration already done.")
            verify(conn)
            return

        migrate(conn, dry_run=not args.execute)

        if args.execute:
            verify(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
