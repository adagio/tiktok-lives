## Why

All CLI scripts (`apps/cli/src/`) still use SQLite (`clips.db`) for data access, while `libs/db.py` already provides a centralized PostgreSQL connection with `tiktok_manager` schema and pgvector. This split means vector operations (embeddings in `chunks`, `chat_chunks`) can't leverage pgvector's native HNSW indexes, and data lives in two places. With PG17 + pgvector 0.8.2 now installed, it's time to unify.

## What Changes

- **BREAKING**: All CLI scripts switch from `sqlite3.connect(clips.db)` to `libs/db.py` `get_connection()` (PostgreSQL)
- Replace `?` parameter placeholders with `%s` (psycopg format)
- Replace binary blob embeddings (`struct.pack`/`numpy.tobytes`) with pgvector's native `vector` type
- Remove SQLite-specific pragmas (`PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys`)
- Remove inline `CREATE TABLE` / `init_tables()` calls — schema is managed by migrations
- Adapt `sqlite3.Row` / `row_factory` patterns to psycopg cursor behavior
- Update `sys.path` inserts to import from `libs/db.py`

## Capabilities

### New Capabilities
- `pg-data-access`: Unified PostgreSQL data access pattern for all CLI scripts, replacing per-script SQLite connections

### Modified Capabilities
_(none — no existing spec-level requirements change, only the storage backend)_

## Impact

- **Code**: 13 scripts in `apps/cli/src/` — `process_sessions.py`, `index_session.py`, `index_chat.py`, `analyze_topics.py`, `analyze_chat.py`, `summarize_sessions.py`, `find_clips.py`, `consolidate_sessions.py`, `transcription_dispatcher.py`, `pipeline_telemetry.py`, `export_animation.py`, `migrate_battles.py`, `chat_topics.py`
- **Dependencies**: `psycopg` must be added to `apps/cli/pyproject.toml` (may already be there via `libs/db.py`)
- **Data**: `clips.db` becomes read-only archive; all new writes go to PostgreSQL
- **Migration**: Existing data in `clips.db` needs one-time migration to PG (separate task)
