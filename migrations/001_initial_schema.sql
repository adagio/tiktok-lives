-- PostgreSQL schema for TikTok Live Recording project
-- Target: PoCs_DB, schema tiktok_manager
-- Migrated from SQLite clips.db

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS tiktok_manager;
SET search_path TO tiktok_manager;

-- ============================================================
-- Core session tracking
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    date TIMESTAMPTZ NOT NULL,
    ts_path TEXT,
    srt_path TEXT,
    audio_path TEXT,
    duration_seconds DOUBLE PRECISION,
    pid INTEGER,
    status TEXT DEFAULT 'complete',
    data_sources INTEGER DEFAULT 0,
    data_duration_seconds DOUBLE PRECISION,
    ffmpeg_exit_code INTEGER,
    summary TEXT,
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Transcript chunks & embeddings
-- ============================================================

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    chunk_index INTEGER,
    start_seconds DOUBLE PRECISION,
    end_seconds DOUBLE PRECISION,
    text TEXT,
    embedding vector(1024),
    embedding_model TEXT DEFAULT 'intfloat/multilingual-e5-large',
    embedding_audio vector(768),
    embedding_audio_model TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Clip results (from semantic search)
-- ============================================================

CREATE TABLE IF NOT EXISTS clips (
    id SERIAL PRIMARY KEY,
    chunk_id INTEGER REFERENCES chunks(id),
    session_id INTEGER REFERENCES sessions(id),
    username TEXT NOT NULL,
    query TEXT,
    search_mode TEXT,
    score DOUBLE PRECISION,
    start_seconds DOUBLE PRECISION,
    end_seconds DOUBLE PRECISION,
    filename TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Chat vectorization
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_chunks (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    message_count INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1024),
    embedding_model TEXT DEFAULT 'intfloat/multilingual-e5-large',
    context TEXT NOT NULL DEFAULT 'organic',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, start_time, context)
);

CREATE TABLE IF NOT EXISTS chat_chunk_topics (
    id SERIAL PRIMARY KEY,
    chat_chunk_id INTEGER NOT NULL REFERENCES chat_chunks(id),
    topic TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    UNIQUE(chat_chunk_id, topic)
);

-- ============================================================
-- Battle system (normalized)
-- ============================================================

CREATE TABLE IF NOT EXISTS battles_v2 (
    id SERIAL PRIMARY KEY,
    battle_id BIGINT NOT NULL UNIQUE,
    detected_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS battle_participants (
    id SERIAL PRIMARY KEY,
    battle_id BIGINT NOT NULL REFERENCES battles_v2(battle_id),
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    session_id INTEGER REFERENCES sessions(id),
    score INTEGER NOT NULL DEFAULT 0,
    UNIQUE(battle_id, user_id)
);

-- Legacy battles table (kept for historical data)
CREATE TABLE IF NOT EXISTS battles (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    battle_id BIGINT NOT NULL,
    opponent_username TEXT NOT NULL,
    opponent_user_id BIGINT NOT NULL,
    host_score INTEGER DEFAULT 0,
    opponent_score INTEGER DEFAULT 0,
    detected_at TIMESTAMPTZ NOT NULL,
    UNIQUE(battle_id, opponent_user_id)
);

-- ============================================================
-- Live event capture
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    battle_id BIGINT,
    room_username TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    text TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS guests (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    nickname TEXT,
    joined_at TIMESTAMPTZ NOT NULL,
    left_at TIMESTAMPTZ,
    UNIQUE(session_id, user_id, joined_at)
);

CREATE TABLE IF NOT EXISTS gifts (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    battle_id BIGINT,
    room_username TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    gift_name TEXT,
    gift_id INTEGER,
    diamond_count INTEGER NOT NULL DEFAULT 0,
    repeat_count INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL DEFAULT 'gift',
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS gift_catalog (
    gift_id INTEGER PRIMARY KEY,
    gift_name TEXT NOT NULL UNIQUE,
    diamond_count INTEGER NOT NULL,
    coin_cost INTEGER,
    first_seen TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS viewer_joins (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    room_username TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL
);

-- ============================================================
-- Metadata & logging
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_events (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    phase TEXT NOT NULL,
    step TEXT,
    context TEXT,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    elapsed_seconds DOUBLE PRECISION,
    input_bytes BIGINT,
    output_bytes BIGINT,
    record_count INTEGER,
    provider TEXT,
    detail TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_rate_log (
    id SERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    delay_seconds DOUBLE PRECISION,
    error_detail TEXT
);

CREATE TABLE IF NOT EXISTS chat_analysis (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(id),
    topics TEXT NOT NULL,
    summary TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_topics (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    topic TEXT NOT NULL,
    max_score DOUBLE PRECISION NOT NULL,
    avg_score DOUBLE PRECISION NOT NULL,
    best_chunk_id INTEGER REFERENCES chunks(id),
    UNIQUE(session_id, topic)
);

CREATE TABLE IF NOT EXISTS topic_highlights (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    chunk_id INTEGER REFERENCES chunks(id),
    session_id INTEGER REFERENCES sessions(id),
    score DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS user_videos (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    video_id TEXT NOT NULL,
    description TEXT,
    create_time TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    UNIQUE(username, video_id)
);

-- ============================================================
-- pgvector indexes (HNSW for approximate nearest neighbor search)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_audio
    ON chunks USING hnsw (embedding_audio vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chat_chunks_embedding
    ON chat_chunks USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- Useful indexes for common queries
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_chunks_session_id ON chunks(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_gifts_session_id ON gifts(session_id);
CREATE INDEX IF NOT EXISTS idx_viewer_joins_session_id ON viewer_joins(session_id);
CREATE INDEX IF NOT EXISTS idx_guests_session_id ON guests(session_id);
