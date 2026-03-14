import Database from "better-sqlite3";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dbPath = path.resolve(__dirname, "../../../../clips.db");

function getDb() {
  return new Database(dbPath, { readonly: true });
}

export interface ClipRow {
  id: number;
  chunk_id: number;
  session_id: number;
  username: string;
  query: string;
  search_mode: string;
  score: number;
  start_seconds: number;
  end_seconds: number;
  filename: string;
  created_at: string;
  text: string | null;
  date: string | null;
}

export interface Stats {
  totalClips: number;
  totalSessions: number;
  uniqueAuthors: number;
  uniqueQueries: number;
}

export function getStats(): Stats {
  const db = getDb();
  try {
    const totalClips = (db.prepare("SELECT COUNT(*) as c FROM clips").get() as any).c;
    const totalSessions = (db.prepare("SELECT COUNT(*) as c FROM sessions").get() as any).c;
    const uniqueAuthors = (db.prepare("SELECT COUNT(DISTINCT username) as c FROM clips").get() as any).c;
    const uniqueQueries = (db.prepare("SELECT COUNT(DISTINCT query) as c FROM clips").get() as any).c;
    return { totalClips, totalSessions, uniqueAuthors, uniqueQueries };
  } finally {
    db.close();
  }
}

export interface ClipFilters {
  author?: string;
  query?: string;
  mode?: string;
  limit?: number;
}

export function getClips(filters: ClipFilters = {}): ClipRow[] {
  const db = getDb();
  try {
    const conditions: string[] = [];
    const params: any[] = [];

    if (filters.author) {
      conditions.push("c.username = ?");
      params.push(filters.author);
    }
    if (filters.query) {
      conditions.push("c.query = ?");
      params.push(filters.query);
    }
    if (filters.mode) {
      conditions.push("c.search_mode = ?");
      params.push(filters.mode);
    }

    const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
    const limit = filters.limit ? `LIMIT ${filters.limit}` : "";

    const sql = `
      SELECT c.*, ch.text, s.date
      FROM clips c
      LEFT JOIN chunks ch ON c.chunk_id = ch.id
      LEFT JOIN sessions s ON c.session_id = s.id
      ${where}
      ORDER BY c.score DESC
      ${limit}
    `;

    return db.prepare(sql).all(...params) as ClipRow[];
  } finally {
    db.close();
  }
}

export function getAuthors(): string[] {
  const db = getDb();
  try {
    const rows = db.prepare("SELECT DISTINCT username FROM clips ORDER BY username").all() as any[];
    return rows.map((r) => r.username);
  } finally {
    db.close();
  }
}

export function getQueries(): string[] {
  const db = getDb();
  try {
    const rows = db.prepare("SELECT DISTINCT query FROM clips ORDER BY query").all() as any[];
    return rows.map((r) => r.query);
  } finally {
    db.close();
  }
}

export function getModes(): string[] {
  const db = getDb();
  try {
    const rows = db.prepare("SELECT DISTINCT search_mode FROM clips ORDER BY search_mode").all() as any[];
    return rows.map((r) => r.search_mode);
  } finally {
    db.close();
  }
}

export interface SessionRow {
  id: number;
  username: string;
  date: string;
  duration_seconds: number | null;
  indexed_at: string;
  chunk_count: number;
  clip_count: number;
}

export function getSessions(author?: string): SessionRow[] {
  const db = getDb();
  try {
    const where = author ? "WHERE s.username = ?" : "";
    const params = author ? [author] : [];

    const sql = `
      SELECT s.id, s.username, s.date, s.duration_seconds, s.indexed_at,
        (SELECT COUNT(*) FROM chunks ch WHERE ch.session_id = s.id) as chunk_count,
        (SELECT COUNT(*) FROM clips c WHERE c.session_id = s.id) as clip_count
      FROM sessions s
      ${where}
      ORDER BY s.date DESC
    `;

    return db.prepare(sql).all(...params) as SessionRow[];
  } finally {
    db.close();
  }
}

export function getSessionAuthors(): string[] {
  const db = getDb();
  try {
    const rows = db.prepare("SELECT DISTINCT username FROM sessions ORDER BY username").all() as any[];
    return rows.map((r) => r.username);
  } finally {
    db.close();
  }
}

export interface SessionDetail {
  id: number;
  username: string;
  date: string;
  duration_seconds: number | null;
  ts_path: string | null;
  srt_path: string | null;
  audio_path: string | null;
  indexed_at: string;
  summary: string | null;
}

export interface ChunkRow {
  id: number;
  chunk_index: number;
  start_seconds: number;
  end_seconds: number;
  text: string;
  embedding: Buffer | null;
}

export function getSession(id: number): SessionDetail | null {
  const db = getDb();
  try {
    return (db.prepare("SELECT * FROM sessions WHERE id = ?").get(id) as SessionDetail) ?? null;
  } finally {
    db.close();
  }
}

export function getSessionChunks(sessionId: number): ChunkRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        "SELECT id, chunk_index, start_seconds, end_seconds, text, embedding FROM chunks WHERE session_id = ? ORDER BY start_seconds",
      )
      .all(sessionId) as ChunkRow[];
  } finally {
    db.close();
  }
}

export function getSessionClips(sessionId: number): ClipRow[] {
  const db = getDb();
  try {
    const sql = `
      SELECT c.*, ch.text, s.date
      FROM clips c
      LEFT JOIN chunks ch ON c.chunk_id = ch.id
      LEFT JOIN sessions s ON c.session_id = s.id
      WHERE c.session_id = ?
      ORDER BY c.start_seconds
    `;
    return db.prepare(sql).all(sessionId) as ClipRow[];
  } finally {
    db.close();
  }
}

// --- Topic scoring (pre-computed) ---

export interface SessionTopicRow {
  topic: string;
  max_score: number;
  avg_score: number;
  best_chunk_id: number;
}

export interface TopicHighlightRow {
  topic: string;
  chunk_id: number;
  session_id: number;
  score: number;
  text: string | null;
  start_seconds: number;
  end_seconds: number;
  username: string | null;
  date: string | null;
}

export interface HeatmapRow {
  session_id: number;
  username: string;
  date: string;
  topic: string;
  max_score: number;
}

/** Get max score per topic across all sessions (for global ranking) */
export function getGlobalTopicScores(): { topic: string; max_score: number }[] {
  const db = getDb();
  try {
    return db
      .prepare(
        "SELECT topic, MAX(max_score) as max_score FROM session_topics GROUP BY topic ORDER BY max_score DESC",
      )
      .all() as { topic: string; max_score: number }[];
  } finally {
    db.close();
  }
}

/** Get topic scores for a specific session */
export function getSessionTopicScores(sessionId: number): SessionTopicRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        "SELECT topic, max_score, avg_score, best_chunk_id FROM session_topics WHERE session_id = ? ORDER BY max_score DESC",
      )
      .all(sessionId) as SessionTopicRow[];
  } finally {
    db.close();
  }
}

/** Get the full session×topic matrix for heatmap */
export function getHeatmapData(): HeatmapRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT st.session_id, s.username, s.date, st.topic, st.max_score
         FROM session_topics st
         JOIN sessions s ON st.session_id = s.id
         ORDER BY s.date ASC, st.topic`,
      )
      .all() as HeatmapRow[];
  } finally {
    db.close();
  }
}

/** Get top chunks for a topic (global highlights) */
export function getTopicHighlights(topic: string, limit = 5): TopicHighlightRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT th.topic, th.chunk_id, th.session_id, th.score,
                ch.text, ch.start_seconds, ch.end_seconds,
                s.username, s.date
         FROM topic_highlights th
         LEFT JOIN chunks ch ON th.chunk_id = ch.id
         LEFT JOIN sessions s ON th.session_id = s.id
         WHERE th.topic = ?
         ORDER BY th.score DESC
         LIMIT ?`,
      )
      .all(topic, limit) as TopicHighlightRow[];
  } finally {
    db.close();
  }
}
