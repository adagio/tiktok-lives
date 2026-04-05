## 1. Foundation

- [x] 1.1 Migrate `pipeline_telemetry.py` — replace sqlite3 with get_connection, `?` → `%s`, remove CREATE TABLE
- [x] 1.2 Migrate `transcription_dispatcher.py` — replace sqlite3 with get_connection, `?` → `%s`

## 2. Core embedding scripts

- [x] 2.1 Migrate `index_session.py` — replace sqlite3/blob with get_connection/pgvector, remove init_db/CREATE TABLE, register_vector for numpy→vector
- [x] 2.2 Migrate `index_chat.py` — replace sqlite3/blob with get_connection/pgvector, remove init_tables
- [x] 2.3 Migrate `transcribe_groq.py` — no sqlite3 usage, already uses migrated pipeline_telemetry

## 3. Analysis scripts

- [x] 3.1 Migrate `analyze_topics.py` — replace sqlite3/blob with get_connection/pgvector, remove init_tables
- [x] 3.2 Migrate `analyze_chat.py` — replace sqlite3 with get_connection, `?` → `%s`
- [x] 3.3 Migrate `summarize_sessions.py` — replace sqlite3 with get_connection, `?` → `%s`

## 4. Search and query scripts

- [x] 4.1 Migrate `find_clips.py` — replace sqlite3/blob with get_connection/pgvector, use `<=>` operator for cosine search
- [x] 4.2 Migrate `chat_topics.py` — replace sqlite3 with get_connection, `?` → `%s`

## 5. Orchestrator and utilities

- [x] 5.1 Migrate `process_sessions.py` — replace sqlite3 with get_connection, `?` → `%s`, remove PRAGMA
- [x] 5.2 Migrate `consolidate_sessions.py` — replace sqlite3 with get_connection, `?` → `%s`
- [x] 5.3 Migrate `export_animation.py` — replace sqlite3 with get_connection, `?` → `%s`
- [x] 5.4 Migrate `migrate_battles.py` — replace sqlite3 with get_connection, `?` → `%s`

## 6. Validation

- [x] 6.1 Run smoke test: `index_session.py` on a session with SRT → 216 chunks stored, cosine distance works
- [x] 6.2 Run smoke test: `find_clips.py` with a query → pgvector <=> cosine search works, top 3 results returned
- [x] 6.3 Run smoke test: `process_sessions.py` on a pending session → connects to PG, finds sessions, pipeline starts
