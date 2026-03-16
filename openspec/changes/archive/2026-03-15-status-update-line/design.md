## Context

Chat currently mixes real user messages with `__join__` system events in the `chat_messages` table. The backoffice renders them together, using `text === '__join__'` to style joins differently. Meanwhile, the `guests` table already tracks join/leave events with richer data (timestamps, durations). This is redundant.

The update line is designed as a generic event channel — currently only joins, but future events (gifts, likes) will follow the same pattern.

## Goals / Non-Goals

**Goals:**
- Separate chat messages from system events in both data and UI
- Create a single-line status bar below each chat panel showing the latest event
- Stop writing `__join__` to `chat_messages` — `guests` table is the source of truth
- Support both `sesiones/[id]` and `batallas/[id]` views (each chat panel gets its own update line)

**Non-Goals:**
- Gift/like capture (future work — the update line will support them, but capture is out of scope)
- Scrollable event history (the update line always shows only the latest event)
- New DB tables for events (joins come from `guests`, future events will have their own tables)

## Decisions

### 1. Remove `__join__` from `chat_messages`, not filter it

**Decision**: Stop inserting `__join__` rows in `chat_spy.py` rather than filtering them out at query time.

**Why**: The `guests` table already captures joins with more detail (user_id, joined_at, left_at). Keeping `__join__` in `chat_messages` is pure redundancy. Removing at the source is cleaner than adding `WHERE text != '__join__'` to every query.

**Backward compat**: Old `__join__` rows remain in the DB. The backoffice UI will filter them out during render to handle historical data gracefully.

### 2. Extend existing polling endpoint with `last_join`

**Decision**: Add a `last_join` field to the existing `/api/session/{id}/messages` and `/api/battle/{id}/messages` responses rather than creating a separate endpoint.

**Why**: Avoids doubling the number of polling requests. The 3-second polling interval already exists — piggybacking the latest join costs one extra SQL query per poll, which is negligible.

**Response shape**:
```json
{
  "messages": [...],
  "is_active": true,
  "last_join": { "username": "laura_live", "joined_at": "2026-03-15T22:31:15" }
}
```

### 3. Query latest guest per session/room, not per poll interval

**Decision**: The API returns the single most recent guest join for the session (or room in battles), not "joins since last poll".

**Why**: The update line only ever shows one event. Querying `ORDER BY joined_at DESC LIMIT 1` is simpler and stateless — no need to track "since" for joins. The client compares with its currently displayed join to decide whether to update.

### 4. Update line as inline HTML, not a separate component

**Decision**: The update line is a `<div>` below the chat panel styled as a footer bar, not an Astro component.

**Why**: It's a single line of HTML + a few lines in the existing polling script. Extracting a component adds complexity for minimal reuse — especially since the update line will evolve as new event types (gifts, likes) are added.

## Risks / Trade-offs

- **Historical data**: Old `__join__` rows stay in `chat_messages`. The UI filters them during render → slight overhead on old sessions, but no data migration needed.
- **Polling latency**: Joins appear with up to 3-second delay (same as chat). Acceptable for this use case.
- **Battle update line per panel**: Each chat panel (host/opponent) queries latest join by `room_username`. This means 2 extra queries per battle poll — still negligible.
