"""Find who a TikTok user is battling right now.

Usage: uv run src/battle_spy.py <username>
"""
import sys

from battles import get_battle_info, get_room_id, resolve_user_id

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "alejandra_blankita"


def main():
    room_id = get_room_id(USERNAME)
    if not room_id:
        print(f"@{USERNAME} is not live right now.")
        return

    print(f"@{USERNAME} is live (room {room_id})")

    info = get_battle_info(room_id)
    if not info:
        print("No active battle.")
        return

    rival_id = info.get("rival_anchor_id")
    scores = info.get("scores", {})

    # Resolve all user IDs
    user_ids = set(scores.keys())
    if rival_id:
        user_ids.add(rival_id)

    handles = {}
    for uid in user_ids:
        handles[uid], _ = resolve_user_id(uid)

    # Print results
    battle_id = info.get("battle_id")
    print(f"\nBattle (id={battle_id}):")

    for uid, pts in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        handle = handles.get(uid, f"id:{uid}")
        tag = "  << OPPONENT" if uid == rival_id else ""
        if handle.lower() == USERNAME.lower():
            tag = "  (host)"
        print(f"  {pts:>8} pts  @{handle}{tag}")

    if rival_id and rival_id in handles:
        print(f"\nOpponent: @{handles[rival_id]}")


if __name__ == "__main__":
    main()
