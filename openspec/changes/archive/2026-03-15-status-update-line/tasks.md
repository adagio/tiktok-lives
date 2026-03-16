## 1. Recorder — stop writing __join__ to chat_messages

- [x] 1.1 Remove the `JoinEvent` handler in `apps/recorder/src/chat_spy.py` that inserts `text='__join__'` rows into `chat_messages`

## 2. Backoffice API — add last_join to responses

- [x] 2.1 Add `getLatestGuest(sessionId)` query to `apps/app-backoffice/src/lib/db.ts` — returns latest guest row (`username`, `joined_at`) for a session
- [x] 2.2 Extend `/api/session/[id]/messages.ts` to include `last_join` in response
- [x] 2.3 Extend `/api/battle/[id]/messages.ts` to include `last_join` per room (host and opponent)

## 3. Backoffice UI — update line + clean chat

- [x] 3.1 In `sesiones/[id].astro`: filter `__join__` rows from chat render (SSR initial + polling), add update line div below chat panel
- [x] 3.2 In `sesiones/[id].astro`: update polling script to read `last_join` from response and update the update line
- [x] 3.3 In `batallas/[id].astro`: filter `__join__` rows from both chat panels, add update line div below each panel
- [x] 3.4 In `batallas/[id].astro`: update polling script to read `last_join` per room and update each update line
