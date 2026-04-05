## ADDED Requirements

### Requirement: All CLI scripts use PostgreSQL via libs/db.py
Every script in `apps/cli/src/` SHALL use `get_connection()` from `libs/db.py` for database access. No script SHALL import `sqlite3` or reference `clips.db`.

#### Scenario: Script connects to PostgreSQL
- **WHEN** any CLI script is executed
- **THEN** it connects to PostgreSQL `PoCs_DB` database, schema `tiktok_manager`, via `libs/db.py`

#### Scenario: Script uses psycopg parameter format
- **WHEN** a script executes a parameterized query
- **THEN** it uses `%s` placeholders (psycopg format), not `?` (sqlite3 format)

### Requirement: Embeddings use pgvector native type
Scripts that store or query embeddings SHALL use pgvector's native `vector` type via `pgvector.psycopg.register_vector()`. Embeddings SHALL NOT be stored as binary blobs.

#### Scenario: Storing text embeddings
- **WHEN** `index_session.py` inserts chunks with embeddings
- **THEN** embeddings are stored as `vector(1024)` using numpy arrays directly (no struct.pack)

#### Scenario: Storing chat embeddings
- **WHEN** `index_chat.py` inserts chat_chunks with embeddings
- **THEN** embeddings are stored as `vector(1024)` using numpy arrays directly

#### Scenario: Querying embeddings
- **WHEN** `find_clips.py` performs semantic search
- **THEN** it uses pgvector's `<=>` cosine distance operator for single-mode search

### Requirement: No inline schema creation
Scripts SHALL NOT contain `CREATE TABLE` or `CREATE INDEX` statements. Schema management is handled exclusively by `migrations/001_initial_schema.sql`.

#### Scenario: Script startup
- **WHEN** a CLI script starts and connects to the database
- **THEN** it assumes all tables exist and does not attempt to create them

### Requirement: Transaction handling
Write operations SHALL use explicit `conn.commit()`. Read-only scripts MAY use `autocommit=True`.

#### Scenario: Write operation
- **WHEN** a script inserts or updates rows
- **THEN** it calls `conn.commit()` after the operation completes

### Requirement: REPO_ROOT and sys.path for libs
Each script SHALL set `sys.path` to include `libs/` from `REPO_ROOT` and import `get_connection` from `db`.

#### Scenario: Import pattern
- **WHEN** a script needs database access
- **THEN** it uses `sys.path.insert(0, str(REPO_ROOT / "libs"))` and `from db import get_connection`
