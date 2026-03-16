## ADDED Requirements

### Requirement: Update line below chat panel
Each chat panel SHALL have a single-line status bar at its bottom that displays the latest status event. Each new event replaces the previous one — only one event is visible at a time.

#### Scenario: User joins during active session
- **WHEN** a new guest join is detected via polling
- **THEN** the update line displays "👋 {username} se unió" replacing any previous content

#### Scenario: No events yet
- **WHEN** the session has no guest joins
- **THEN** the update line is empty or hidden

#### Scenario: Page load with existing joins
- **WHEN** the page loads and the session already has guest joins
- **THEN** the update line displays the most recent join

### Requirement: Update line in session view
The session detail page (`sesiones/[id]`) SHALL display one update line below the chat panel.

#### Scenario: Session with active chat and joins
- **WHEN** viewing a session with chat messages and guest joins
- **THEN** chat messages appear in the chat timeline and the latest join appears in the update line below

### Requirement: Update line in battle view
The battle detail page (`batallas/[id]`) SHALL display one update line per chat panel (host and opponent).

#### Scenario: Battle with two chat panels
- **WHEN** viewing a battle with host and opponent chat panels
- **THEN** each panel has its own update line showing the latest join for that room

### Requirement: API returns latest join
The messages API endpoints SHALL include a `last_join` field with the most recent guest join for the relevant scope.

#### Scenario: Session messages endpoint
- **WHEN** polling `/api/session/{id}/messages`
- **THEN** the response includes `last_join` with `username` and `joined_at` of the latest guest for that session, or `null` if none

#### Scenario: Battle messages endpoint
- **WHEN** polling `/api/battle/{id}/messages`
- **THEN** the response includes `last_join` per room (host and opponent) with `username` and `joined_at`, or `null` if none

### Requirement: Chat timeline excludes join events
The chat timeline SHALL render only real user messages, excluding `__join__` events from both historical and new data.

#### Scenario: Historical session with __join__ rows
- **WHEN** viewing a session that has old `__join__` rows in `chat_messages`
- **THEN** the chat timeline filters them out during render

#### Scenario: New session after change
- **WHEN** viewing a session recorded after this change
- **THEN** no `__join__` rows exist in `chat_messages` — the timeline only contains real messages
