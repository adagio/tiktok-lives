## Why

Chat timeline mixes real messages with system events (`__join__`, and future gifts/likes). This clutters the conversation flow and makes events hard to track. Joins already exist in the `guests` table — storing them also as `chat_messages` is redundant. We need a dedicated status line below the chat that shows the latest event, keeping chat clean and creating a channel for future event types.

## What Changes

- **Recorder**: `chat_spy.py` stops inserting `text='__join__'` into `chat_messages` — `guests` table is the single source of truth for joins
- **Backoffice UI**: Chat timeline renders only real messages (no `__join__` filter needed)
- **Backoffice UI**: New "update line" appears below chat, showing the last status event (currently: last user join). Each new event replaces the previous one — always 1 line visible
- **Backoffice API**: Messages endpoint extended to include `last_join` from `guests` table
- **Applies to both views**: `sesiones/[id]` (one update line) and `batallas/[id]` (one update line per chat panel — host and opponent)

## Capabilities

### New Capabilities
- `status-update-line`: Single-line status bar below chat panels showing the latest event (join, and future: gifts, likes). Replaces previous event on each update.

### Modified Capabilities
- `chat-capture`: Joins are no longer written as `chat_messages` rows. The `guests` table is the sole source for join events.

## Impact

- **Recorder**: `apps/recorder/src/chat_spy.py` — remove `__join__` message insertion
- **Backoffice API**: `apps/app-backoffice/src/pages/api/session/[id]/messages.ts` and `apps/app-backoffice/src/pages/api/battle/[id]/messages.ts` — add `last_join` field
- **Backoffice DB layer**: `apps/app-backoffice/src/lib/db.ts` — new query for latest guest join
- **Backoffice UI**: `apps/app-backoffice/src/pages/sesiones/[id].astro` and `apps/app-backoffice/src/pages/batallas/[id].astro` — filter `__join__` from rendered chat, add update line component
- **No DB schema changes** — `guests` table already has all needed data
