## Context

All 13 CLI scripts in `apps/cli/src/` use `sqlite3.connect("clips.db")` for data access. Meanwhile, `libs/db.py` provides a PostgreSQL connection to `tiktok_manager` schema with pgvector 0.8.2. The PG schema already has all tables created (sessions, chunks, chat_chunks, etc.). Embeddings are stored as binary blobs in SQLite but should use pgvector's native `vector` type in PG.

## Goals / Non-Goals

**Goals:**
- Every CLI script uses `libs/db.py` `get_connection()` instead of SQLite
- Embeddings stored as pgvector `vector` type (not binary blobs)
- Semantic search uses pgvector's `<=>` (cosine distance) operator instead of numpy dot product
- All scripts remain runnable via `uv run src/<script>.py`

**Non-Goals:**
- Migrating existing data from `clips.db` to PG (separate task)
- Changing CLI arguments or script behavior
- Modifying the recorder scripts (`apps/recorder/`) — they already use PG via `libs/db.py`

## Decisions

### 1. Import pattern — `sys.path.insert` for libs/db.py

Each script will add `sys.path.insert(0, str(REPO_ROOT / "libs"))` and `from db import get_connection`. This matches how `apps/recorder/` already imports it.

**Alternative**: Install `libs` as a package — too much overhead for a personal project.

### 2. Embedding storage — pgvector native vectors, not blobs

Replace `embed_to_blob()` / `blob_to_array()` (struct.pack/unpack) with pgvector's native format. Use `pgvector.psycopg` register to handle numpy→vector conversion automatically.

```python
from pgvector.psycopg import register_vector
conn = get_connection()
register_vector(conn)
# Then just INSERT numpy arrays directly
```

### 3. Semantic search — pgvector operator vs numpy

For `find_clips.py`, use pgvector's `<=>` operator for cosine distance:
```sql
SELECT *, embedding <=> %s::vector AS distance
FROM chunks ORDER BY distance LIMIT 10
```
This leverages HNSW indexes. Fall back to numpy for combined text+audio scoring where PG can't do it in one query.

### 4. Parameter placeholders — `?` → `%s`

SQLite uses `?`, psycopg uses `%s`. Mechanical replacement across all scripts.

### 5. Transaction handling

SQLite uses explicit `conn.commit()`. psycopg connections are in transaction by default. Use `conn.commit()` after writes (same pattern, just works). For read-only scripts, use `autocommit=True` in `get_connection()`.

### 6. Remove init_tables / CREATE TABLE from scripts

All table creation is in `migrations/001_initial_schema.sql`. Scripts should not create tables.

### 7. Batch order — migrate in dependency order

Some scripts call others (e.g., `process_sessions.py` calls `index_session.py`). Migrate leaf scripts first:
1. `pipeline_telemetry.py` (standalone utility, used by others)
2. `index_session.py` (core embedding script)
3. `transcription_dispatcher.py`, `transcribe_groq.py` (no DB vectors, just telemetry)
4. `index_chat.py` (chat vectorization)
5. `analyze_topics.py`, `analyze_chat.py`, `summarize_sessions.py`
6. `find_clips.py` (search, benefits most from pgvector)
7. `process_sessions.py` (orchestrator, calls others)
8. Remaining: `consolidate_sessions.py`, `export_animation.py`, `migrate_battles.py`, `chat_topics.py`

## Risks / Trade-offs

- **[Risk] Scripts break if PG is down** → SQLite was always available. Acceptable for personal project.
- **[Risk] psycopg row format differs from sqlite3** → sqlite3 returns tuples by default, psycopg returns tuples too. `row_factory = sqlite3.Row` patterns need `conn.row_factory = psycopg.rows.dict_row` or just use tuples.
- **[Trade-off] pgvector search vs numpy** → pgvector `<=>` is faster for large datasets with HNSW, but for combined text+audio scoring we still need numpy. Use pgvector for single-mode search, numpy for combined.
