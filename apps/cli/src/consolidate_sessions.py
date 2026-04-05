"""Consolidate fragmented short sessions into single logical sessions.

When the recorder fails repeatedly (e.g. HLS URL expiration), it creates many
short sessions that belong to the same continuous live stream. This script
detects those fragment groups and merges them: child records (chat, gifts,
battles, etc.) are moved to the earliest session, and the absorbed sessions
are deleted.

Usage:
    cd apps/cli && uv run src/consolidate_sessions.py [OPTIONS]

Dry-run by default. Add --execute to apply changes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

sys.path.insert(0, str(REPO_ROOT / "libs"))
from db import get_connection

# Data-source bitmask (mirrors battles.py)
DS_VIDEO = 1
DS_CHAT = 2
DS_GIFTS = 4
DS_BATTLES = 8
DS_GUESTS = 16
DS_VIEWERS = 32

DEFAULT_GAP = 180  # seconds between fragments
DEFAULT_MAX_DURATION = 120  # max duration to qualify as a fragment


def parse_date(date_val) -> datetime:
    """Parse date value (string or datetime) to datetime."""
    if isinstance(date_val, datetime):
        return date_val.replace(tzinfo=None) if date_val.tzinfo else date_val
    s = str(date_val)
    if s.endswith("Z"):
        s = s[:-1]
    elif "+" in s[10:]:
        s = s[: s.rindex("+")]
    elif s.count("-") > 2:
        parts = s.rsplit("-", 1)
        if ":" in parts[-1] and len(parts[-1]) <= 6:
            s = parts[0]

    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_val}")


def find_fragment_groups(
    conn,
    *,
    username: str | None = None,
    date: str | None = None,
    max_duration: float = DEFAULT_MAX_DURATION,
    gap: float = DEFAULT_GAP,
) -> list[list[dict]]:
    """Find groups of fragmented sessions that should be consolidated."""
    query = """
        SELECT id, username, date, duration_seconds, status, ts_path,
               data_sources, data_duration_seconds
        FROM sessions
        WHERE status IN ('partial', 'failed')
          AND duration_seconds IS NOT NULL
          AND duration_seconds < %s
    """
    params: list = [max_duration]

    if username:
        query += " AND username = %s"
        params.append(username)
    if date:
        query += " AND date::text LIKE %s"
        params.append(f"{date}%")

    query += " ORDER BY username, date"

    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()

    sessions = [dict(zip(cols, row)) for row in rows]

    # Group by username, then by temporal proximity
    groups: list[list[dict]] = []
    current_group: list[dict] = []

    for sess in sessions:
        if not current_group:
            current_group = [sess]
            continue

        prev = current_group[-1]

        if sess["username"] != prev["username"]:
            if len(current_group) > 1:
                groups.append(current_group)
            current_group = [sess]
            continue

        prev_end = parse_date(prev["date"]).timestamp() + (prev["duration_seconds"] or 0)
        curr_start = parse_date(sess["date"]).timestamp()
        time_gap = curr_start - prev_end

        if time_gap <= gap:
            current_group.append(sess)
        else:
            if len(current_group) > 1:
                groups.append(current_group)
            current_group = [sess]

    if len(current_group) > 1:
        groups.append(current_group)

    return groups


def count_child_records(conn, session_ids: list[int]) -> dict[str, int]:
    """Count records in child tables for given session IDs."""
    placeholders = ",".join(["%s"] * len(session_ids))
    counts = {}
    for table in ("chat_messages", "gifts", "guests", "viewer_joins"):
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()
        counts[table] = row[0]

    row = conn.execute(
        f"SELECT COUNT(*) FROM battle_participants WHERE session_id IN ({placeholders})",
        session_ids,
    ).fetchone()
    counts["battles"] = row[0]
    return counts


def count_battle_duplicates(conn, survivor_id: int, absorbed_ids: list[int]) -> int:
    """Count battle participants in absorbed sessions that already exist on the survivor."""
    if not absorbed_ids:
        return 0
    placeholders = ",".join(["%s"] * len(absorbed_ids))
    row = conn.execute(
        f"""SELECT COUNT(*) FROM battle_participants bp1
            WHERE bp1.session_id IN ({placeholders})
              AND EXISTS (
                  SELECT 1 FROM battle_participants bp2
                  WHERE bp2.session_id = %s
                    AND bp2.battle_id = bp1.battle_id
                    AND bp2.user_id = bp1.user_id
              )""",
        [*absorbed_ids, survivor_id],
    ).fetchone()
    return row[0]


def check_ts_files(sessions: list[dict]) -> str | None:
    """Find the first valid (non-empty) .ts file among sessions."""
    for sess in sessions:
        ts = sess.get("ts_path")
        if ts:
            p = Path(ts)
            if p.exists() and p.stat().st_size > 0:
                return ts
    return None


def compute_data_sources(conn, session_id: int) -> tuple[int, float | None]:
    """Recompute data_sources bitmask and data_duration for a session."""
    sources = 0
    all_timestamps: list = []

    row = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM chat_messages WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row and row[0]:
        sources |= DS_CHAT
        all_timestamps.extend([row[0], row[1]])

    row = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM gifts WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row and row[0]:
        sources |= DS_GIFTS
        all_timestamps.extend([row[0], row[1]])

    row = conn.execute(
        """SELECT MIN(bv.detected_at), MAX(bv.detected_at)
           FROM battle_participants bp
           JOIN battles_v2 bv ON bp.battle_id = bv.battle_id
           WHERE bp.session_id = %s""",
        (session_id,),
    ).fetchone()
    if row and row[0]:
        sources |= DS_BATTLES
        all_timestamps.extend([row[0], row[1]])

    row = conn.execute(
        "SELECT MIN(joined_at), MAX(COALESCE(left_at, joined_at)) FROM guests WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row and row[0]:
        sources |= DS_GUESTS
        all_timestamps.extend([row[0], row[1]])

    row = conn.execute(
        "SELECT MIN(joined_at), MAX(joined_at) FROM viewer_joins WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row and row[0]:
        sources |= DS_VIEWERS
        all_timestamps.extend([row[0], row[1]])

    if not all_timestamps:
        return sources, None

    ts_parsed = [parse_date(t) for t in all_timestamps if t]
    if len(ts_parsed) < 2:
        return sources, 0.0

    span = (max(ts_parsed) - min(ts_parsed)).total_seconds()
    return sources, span


def preview_group(conn, group: list[dict], index: int) -> None:
    """Print a preview of what consolidation would do."""
    survivor = group[0]
    absorbed = group[1:]
    absorbed_ids = [s["id"] for s in absorbed]
    all_ids = [s["id"] for s in group]

    first_start = parse_date(survivor["date"])
    last = absorbed[-1]
    last_end = parse_date(last["date"]).timestamp() + (last["duration_seconds"] or 0)
    span_seconds = last_end - first_start.timestamp()
    span_minutes = span_seconds / 60

    counts = count_child_records(conn, all_ids)
    battle_dupes = count_battle_duplicates(conn, survivor["id"], absorbed_ids)
    ts_path = check_ts_files(group)

    print(f"\n{'='*50}")
    print(f"  Fragment Group {index + 1}")
    print(f"{'='*50}")
    print(f"  User:     @{survivor['username']}")
    print(f"  Survivor: #{survivor['id']}  {survivor['date']}  ({survivor['duration_seconds']:.0f}s, {survivor['status']})")
    print(f"  Absorbed: {len(absorbed)} sessions (#{absorbed[0]['id']}..#{absorbed[-1]['id']})")
    print(f"  Span:     {first_start.strftime('%H:%M:%S')} - {datetime.fromtimestamp(last_end).strftime('%H:%M:%S')} ({span_minutes:.1f} min)")
    print(f"  Records to merge:")
    print(f"    chat_messages:  {counts['chat_messages']}")
    print(f"    gifts:          {counts['gifts']}")
    print(f"    battles:        {counts['battles']}  ({battle_dupes} duplicates)")
    print(f"    guests:         {counts['guests']}")
    print(f"    viewer_joins:   {counts['viewer_joins']}")
    print(f"  Video: {'exists -> ' + ts_path if ts_path else 'no files -> will clear'}")
    print(f"  New duration: {span_seconds:.0f}s ({span_minutes:.1f} min)")


def consolidate_group(conn, group: list[dict]) -> None:
    """Execute consolidation for one fragment group."""
    survivor = group[0]
    survivor_id = survivor["id"]
    absorbed = group[1:]
    absorbed_ids = [s["id"] for s in absorbed]
    placeholders = ",".join(["%s"] * len(absorbed_ids))

    # 1. Move simple child records
    for table in ("chat_messages", "gifts", "viewer_joins"):
        conn.execute(
            f"UPDATE {table} SET session_id = %s WHERE session_id IN ({placeholders})",
            [survivor_id, *absorbed_ids],
        )

    # 2. Guests — handle UNIQUE(session_id, user_id, joined_at)
    conn.execute(
        f"""DELETE FROM guests WHERE session_id IN ({placeholders})
            AND EXISTS (
                SELECT 1 FROM guests g2
                WHERE g2.session_id = %s
                  AND g2.user_id = guests.user_id
                  AND g2.joined_at = guests.joined_at
            )""",
        [*absorbed_ids, survivor_id],
    )
    conn.execute(
        f"UPDATE guests SET session_id = %s WHERE session_id IN ({placeholders})",
        [survivor_id, *absorbed_ids],
    )

    # 3. Battles — move battle_participants session references
    conn.execute(
        f"UPDATE battle_participants SET session_id = %s WHERE session_id IN ({placeholders})",
        [survivor_id, *absorbed_ids],
    )

    # 4. Clean derived tables
    for table in ("chunks", "clips", "session_topics", "topic_highlights"):
        conn.execute(
            f"DELETE FROM {table} WHERE session_id IN ({placeholders})",
            absorbed_ids,
        )

    # chat_chunks -> first delete associated chat_chunk_topics
    chunk_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM chat_chunks WHERE session_id IN ({placeholders})",
            absorbed_ids,
        ).fetchall()
    ]
    if chunk_ids:
        cph = ",".join(["%s"] * len(chunk_ids))
        conn.execute(f"DELETE FROM chat_chunk_topics WHERE chat_chunk_id IN ({cph})", chunk_ids)
    conn.execute(
        f"DELETE FROM chat_chunks WHERE session_id IN ({placeholders})",
        absorbed_ids,
    )

    # chat_analysis
    conn.execute(
        f"DELETE FROM chat_analysis WHERE session_id IN ({placeholders})",
        absorbed_ids,
    )

    # 5. Update survivor
    first_start = parse_date(survivor["date"])
    last = absorbed[-1]
    last_end = parse_date(last["date"]).timestamp() + (last["duration_seconds"] or 0)
    total_duration = last_end - first_start.timestamp()

    ts_path = check_ts_files(group) or ""
    has_video = bool(ts_path)

    sources, data_dur = compute_data_sources(conn, survivor_id)
    if has_video:
        sources |= DS_VIDEO

    if has_video:
        status = "complete"
    elif sources > 0:
        status = "partial"
    else:
        status = "failed"

    conn.execute(
        """UPDATE sessions SET
               duration_seconds = %s,
               ts_path = %s,
               status = %s,
               data_sources = %s,
               data_duration_seconds = %s
           WHERE id = %s""",
        [total_duration, ts_path, status, sources, data_dur, survivor_id],
    )

    # 6. Delete absorbed sessions
    conn.execute(
        f"DELETE FROM sessions WHERE id IN ({placeholders})",
        absorbed_ids,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate fragmented short sessions into single logical sessions."
    )
    parser.add_argument("--username", help="Only process this username")
    parser.add_argument("--date", help="Only process sessions on this date (e.g. 2026-03-30)")
    parser.add_argument(
        "--gap",
        type=float,
        default=DEFAULT_GAP,
        help=f"Max gap in seconds between fragments (default: {DEFAULT_GAP})",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=DEFAULT_MAX_DURATION,
        help=f"Max duration to consider a fragment (default: {DEFAULT_MAX_DURATION})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform consolidation (default: dry-run)",
    )
    args = parser.parse_args()

    conn = get_connection()
    try:
        groups = find_fragment_groups(
            conn,
            username=args.username,
            date=args.date,
            max_duration=args.max_duration,
            gap=args.gap,
        )

        if not groups:
            print("No fragment groups found.")
            return

        total_absorbed = sum(len(g) - 1 for g in groups)
        print(f"Found {len(groups)} fragment group(s), {total_absorbed} sessions to absorb.\n")

        for i, group in enumerate(groups):
            preview_group(conn, group, i)

        if not args.execute:
            print(f"\n--- DRY RUN --- Add --execute to apply changes.")
            return

        for i, group in enumerate(groups):
            survivor = group[0]
            absorbed_count = len(group) - 1
            try:
                consolidate_group(conn, group)
                conn.commit()
                print(f"  Consolidated group {i + 1}: #{survivor['id']} absorbed {absorbed_count} sessions")
            except Exception as e:
                conn.rollback()
                print(f"  ERROR on group {i + 1}: {e}")

        print("\nDone.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
