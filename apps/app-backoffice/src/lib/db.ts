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

// --- Battles ---

export interface BattleRow {
  id: number;
  session_id: number;
  battle_id: number;
  opponent_username: string;
  opponent_user_id: number;
  host_score: number;
  opponent_score: number;
  detected_at: string;
}

export function getSessionBattles(sessionId: number): BattleRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        "SELECT * FROM battles WHERE session_id = ? ORDER BY detected_at",
      )
      .all(sessionId) as BattleRow[];
  } catch {
    // battles table may not exist yet
    return [];
  } finally {
    db.close();
  }
}

// --- Guests (ventanilla / link mic) ---

export interface GuestRow {
  id: number;
  session_id: number;
  user_id: number;
  username: string;
  nickname: string | null;
  joined_at: string;
  left_at: string | null;
}

export function getSessionGuests(sessionId: number): GuestRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        "SELECT * FROM guests WHERE session_id = ? ORDER BY joined_at",
      )
      .all(sessionId) as GuestRow[];
  } catch {
    // guests table may not exist yet
    return [];
  } finally {
    db.close();
  }
}

export function getActiveGuests(sessionId: number): { username: string; nickname: string | null; joined_at: string }[] {
  const db = getDb();
  try {
    // Staleness safety net: ignore guests joined >4h ago unless there's recent chat (30min).
    // Protects against orphaned guests from monitor crashes.
    return db
      .prepare(
        `SELECT username, nickname, joined_at FROM guests
         WHERE session_id = ? AND left_at IS NULL
           AND (
             joined_at > datetime('now', '-4 hours')
             OR EXISTS (
               SELECT 1 FROM chat_messages
               WHERE session_id = ? AND timestamp > datetime('now', '-30 minutes')
             )
           )
         ORDER BY joined_at`,
      )
      .all(sessionId, sessionId) as { username: string; nickname: string | null; joined_at: string }[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getLatestGuest(sessionId: number): { username: string; nickname: string | null; joined_at: string } | null {
  const db = getDb();
  try {
    return (db
      .prepare(
        "SELECT username, nickname, joined_at FROM guests WHERE session_id = ? ORDER BY joined_at DESC LIMIT 1",
      )
      .get(sessionId) as { username: string; nickname: string | null; joined_at: string }) ?? null;
  } catch {
    return null;
  } finally {
    db.close();
  }
}

export function getLatestViewerJoin(sessionId: number, roomUsername?: string): { username: string; joined_at: string } | null {
  const db = getDb();
  try {
    if (roomUsername) {
      return (db
        .prepare(
          "SELECT username, joined_at FROM viewer_joins WHERE session_id = ? AND room_username = ? ORDER BY joined_at DESC LIMIT 1",
        )
        .get(sessionId, roomUsername) as { username: string; joined_at: string }) ?? null;
    }
    return (db
      .prepare(
        "SELECT username, joined_at FROM viewer_joins WHERE session_id = ? ORDER BY joined_at DESC LIMIT 1",
      )
      .get(sessionId) as { username: string; joined_at: string }) ?? null;
  } catch {
    return null;
  } finally {
    db.close();
  }
}

// --- Chat messages ---

export interface ChatMessageRow {
  id: number;
  session_id: number;
  battle_id: number | null;
  room_username: string;
  user_id: number;
  username: string;
  text: string;
  timestamp: string;
}

export interface BattleDetail extends BattleRow {
  host_username: string;
}

export function getBattle(id: number): BattleDetail | null {
  const db = getDb();
  try {
    return (
      (db
        .prepare(
          `SELECT b.*, s.username as host_username
           FROM battles b
           JOIN sessions s ON b.session_id = s.id
           WHERE b.id = ?`,
        )
        .get(id) as BattleDetail) ?? null
    );
  } finally {
    db.close();
  }
}

export function getBattleChatMessages(
  battleId: number,
  since?: string,
): ChatMessageRow[] {
  const db = getDb();
  try {
    if (since) {
      return db
        .prepare(
          `SELECT * FROM chat_messages
           WHERE battle_id = ? AND timestamp > ?
           ORDER BY timestamp`,
        )
        .all(battleId, since) as ChatMessageRow[];
    }
    return db
      .prepare(
        `SELECT * FROM chat_messages
         WHERE battle_id = ?
         ORDER BY timestamp`,
      )
      .all(battleId) as ChatMessageRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function isBattleActive(battleId: number): boolean {
  const db = getDb();
  try {
    const row = db
      .prepare(
        `SELECT MAX(timestamp) as last_ts FROM chat_messages WHERE battle_id = ?`,
      )
      .get(battleId) as { last_ts: string | null } | undefined;
    if (!row?.last_ts) return false;
    const tsStr = row.last_ts;
    const lastTs = new Date(tsStr.includes("+") || tsStr.endsWith("Z") ? tsStr : tsStr + "Z").getTime();
    const now = Date.now();
    return now - lastTs < 30_000;
  } catch {
    return false;
  } finally {
    db.close();
  }
}

export function getSessionChatMessages(
  sessionId: number,
  since?: string,
): ChatMessageRow[] {
  const db = getDb();
  try {
    if (since) {
      return db
        .prepare(
          `SELECT * FROM chat_messages
           WHERE session_id = ? AND timestamp > ?
           ORDER BY timestamp`,
        )
        .all(sessionId, since) as ChatMessageRow[];
    }
    return db
      .prepare(
        `SELECT * FROM chat_messages
         WHERE session_id = ?
         ORDER BY timestamp`,
      )
      .all(sessionId) as ChatMessageRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function isSessionActive(sessionId: number): boolean {
  const db = getDb();
  try {
    const row = db
      .prepare(
        `SELECT MAX(timestamp) as last_ts FROM chat_messages WHERE session_id = ?`,
      )
      .get(sessionId) as { last_ts: string | null } | undefined;
    if (!row?.last_ts) return false;
    const tsStr = row.last_ts;
    const lastTs = new Date(tsStr.includes("+") || tsStr.endsWith("Z") ? tsStr : tsStr + "Z").getTime();
    const now = Date.now();
    return now - lastTs < 30_000;
  } catch {
    return false;
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

/** Get latest session for a given username */
export function getLatestSessionByUsername(username: string): SessionRow | null {
  const db = getDb();
  try {
    const sql = `
      SELECT s.id, s.username, s.date, s.duration_seconds, s.indexed_at,
        (SELECT COUNT(*) FROM chunks ch WHERE ch.session_id = s.id) as chunk_count,
        (SELECT COUNT(*) FROM clips c WHERE c.session_id = s.id) as clip_count
      FROM sessions s
      WHERE s.username = ?
      ORDER BY s.date DESC
      LIMIT 1
    `;
    return (db.prepare(sql).get(username) as SessionRow) ?? null;
  } finally {
    db.close();
  }
}

/** Get count of chat messages for a session */
export function getChatMessageCount(sessionId: number): number {
  const db = getDb();
  try {
    const row = db
      .prepare("SELECT COUNT(*) as c FROM chat_messages WHERE session_id = ?")
      .get(sessionId) as { c: number };
    return row.c;
  } catch {
    return 0;
  } finally {
    db.close();
  }
}

/** Get latest video uploaded by a username */
export interface UserVideoRow {
  id: number;
  username: string;
  video_id: string;
  description: string | null;
  create_time: string;
  detected_at: string;
}

export function getLatestVideo(username: string): UserVideoRow | null {
  const db = getDb();
  try {
    return (
      (db
        .prepare(
          "SELECT * FROM user_videos WHERE username = ? ORDER BY create_time DESC LIMIT 1",
        )
        .get(username) as UserVideoRow) ?? null
    );
  } catch {
    // table may not exist yet
    return null;
  } finally {
    db.close();
  }
}

// --- Authors ---

export interface AuthorListRow {
  username: string;
  total_sessions: number;
  first_session: string;
  last_session: string;
  total_duration: number | null;
}

export function getAuthorList(): AuthorListRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT
          s.username,
          COUNT(*) as total_sessions,
          MIN(DATE(s.date)) as first_session,
          MAX(DATE(s.date)) as last_session,
          SUM(s.duration_seconds) as total_duration
        FROM sessions s
        GROUP BY s.username
        ORDER BY MAX(s.date) DESC`,
      )
      .all() as AuthorListRow[];
  } finally {
    db.close();
  }
}

export interface AuthorDailySummaryRow {
  day: string;
  session_count: number;
  total_duration: number | null;
  battle_count: number;
  total_host_points: number;
  wins: number;
  losses: number;
  draws: number;
  unique_guests: number;
  chat_messages: number;
}

export function getAuthorDailySummary(username: string): AuthorDailySummaryRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT
          DATE(s.date) as day,
          COUNT(DISTINCT s.id) as session_count,
          SUM(s.duration_seconds) as total_duration,
          (SELECT COUNT(*) FROM battles b WHERE b.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as battle_count,
          (SELECT COALESCE(SUM(b.host_score), 0) FROM battles b WHERE b.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as total_host_points,
          (SELECT COALESCE(SUM(CASE WHEN b.host_score > b.opponent_score THEN 1 ELSE 0 END), 0)
            FROM battles b WHERE b.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as wins,
          (SELECT COALESCE(SUM(CASE WHEN b.host_score < b.opponent_score THEN 1 ELSE 0 END), 0)
            FROM battles b WHERE b.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as losses,
          (SELECT COALESCE(SUM(CASE WHEN b.host_score = b.opponent_score THEN 1 ELSE 0 END), 0)
            FROM battles b WHERE b.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as draws,
          (SELECT COUNT(DISTINCT g.user_id) FROM guests g WHERE g.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as unique_guests,
          (SELECT COUNT(*) FROM chat_messages cm WHERE cm.session_id IN
            (SELECT id FROM sessions WHERE username = ? AND DATE(date) = DATE(s.date))
          ) as chat_messages
        FROM sessions s
        WHERE s.username = ?
        GROUP BY DATE(s.date)
        ORDER BY day DESC`,
      )
      .all(username, username, username, username, username, username, username, username) as AuthorDailySummaryRow[];
  } catch {
    // battles/guests/chat_messages tables may not exist yet
    return db
      .prepare(
        `SELECT
          DATE(s.date) as day,
          COUNT(DISTINCT s.id) as session_count,
          SUM(s.duration_seconds) as total_duration,
          0 as battle_count,
          0 as total_host_points,
          0 as wins,
          0 as losses,
          0 as draws,
          0 as unique_guests,
          0 as chat_messages
        FROM sessions s
        WHERE s.username = ?
        GROUP BY DATE(s.date)
        ORDER BY day DESC`,
      )
      .all(username) as AuthorDailySummaryRow[];
  } finally {
    db.close();
  }
}

// --- Author interaction rankings ---

export interface DonorRankingRow {
  user_id: number;
  username: string;
  total_diamonds: number;
  gift_count: number;
}

export function getTopDonors(username: string, limit = 10): DonorRankingRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT g.user_id, g.username,
                SUM(g.diamond_count * g.repeat_count) as total_diamonds,
                COUNT(*) as gift_count
         FROM gifts g
         JOIN sessions s ON g.session_id = s.id
         WHERE s.username = ? AND g.room_username = ?
           AND g.event_type = 'gift'
         GROUP BY g.user_id
         ORDER BY total_diamonds DESC
         LIMIT ?`,
      )
      .all(username, username, limit) as DonorRankingRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export interface VentanillaRankingRow {
  user_id: number;
  username: string;
  nickname: string | null;
  total_seconds: number;
  visit_count: number;
}

export function getTopVentanilla(username: string, limit = 10): VentanillaRankingRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT g.user_id, g.username, g.nickname,
                SUM(
                  CAST((julianday(COALESCE(g.left_at, datetime('now'))) - julianday(g.joined_at)) * 86400 AS INTEGER)
                ) as total_seconds,
                COUNT(*) as visit_count
         FROM guests g
         JOIN sessions s ON g.session_id = s.id
         WHERE s.username = ?
         GROUP BY g.user_id
         ORDER BY total_seconds DESC
         LIMIT ?`,
      )
      .all(username, limit) as VentanillaRankingRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export interface OpponentRankingRow {
  opponent_username: string;
  total_battles: number;
  total_opponent_score: number;
  total_host_score: number;
  wins: number;
  losses: number;
}

export function getTopOpponents(username: string, limit = 10): OpponentRankingRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT b.opponent_username,
                COUNT(*) as total_battles,
                SUM(b.opponent_score) as total_opponent_score,
                SUM(b.host_score) as total_host_score,
                SUM(CASE WHEN b.host_score > b.opponent_score THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN b.host_score < b.opponent_score THEN 1 ELSE 0 END) as losses
         FROM battles b
         JOIN sessions s ON b.session_id = s.id
         WHERE s.username = ?
         GROUP BY b.opponent_username
         ORDER BY total_battles DESC
         LIMIT ?`,
      )
      .all(username, limit) as OpponentRankingRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

// --- Chat analysis (LLM-generated topics + summary) ---

export interface ChatAnalysisRow {
  topics: string;
  summary: string;
}

export function getChatAnalysis(sessionId: number): ChatAnalysisRow | null {
  const db = getDb();
  try {
    return (
      (db
        .prepare("SELECT topics, summary FROM chat_analysis WHERE session_id = ?")
        .get(sessionId) as ChatAnalysisRow) ?? null
    );
  } catch {
    return null;
  } finally {
    db.close();
  }
}

// --- Days page ---

export interface DayRow {
  day: string;
  session_count: number;
  total_duration: number;
  authors: string;
}

export function getDays(): DayRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT DATE(s.date) as day,
                COUNT(*) as session_count,
                COALESCE(SUM(s.duration_seconds), 0) as total_duration,
                GROUP_CONCAT(DISTINCT s.username) as authors
         FROM sessions s
         GROUP BY DATE(s.date)
         ORDER BY day DESC`,
      )
      .all() as DayRow[];
  } finally {
    db.close();
  }
}

export interface DayDetailRow {
  session_id: number;
  username: string;
  date: string;
  duration_seconds: number | null;
  summary: string | null;
  chat_summary: string | null;
  chat_topics: string | null;
  battle_count: number;
  guest_count: number;
  chat_message_count: number;
  chunk_count: number;
}

export function getDayDetail(day: string): DayDetailRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date, s.duration_seconds, s.summary,
                ca.summary as chat_summary, ca.topics as chat_topics,
                (SELECT COUNT(*) FROM battles b WHERE b.session_id = s.id) as battle_count,
                (SELECT COUNT(DISTINCT g.user_id) FROM guests g WHERE g.session_id = s.id) as guest_count,
                (SELECT COUNT(*) FROM chat_messages cm WHERE cm.session_id = s.id) as chat_message_count,
                (SELECT COUNT(*) FROM chunks c WHERE c.session_id = s.id) as chunk_count
         FROM sessions s
         LEFT JOIN chat_analysis ca ON ca.session_id = s.id
         WHERE DATE(s.date) = ?
         ORDER BY s.date`,
      )
      .all(day) as DayDetailRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

// --- Stats page ---

export interface StatSessionRow {
  session_id: number;
  username: string;
  date: string;
  value: number;
}

export function getTopByDuration(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COALESCE(s.duration_seconds, 0) as value
         FROM sessions s
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } finally {
    db.close();
  }
}

export function getTopByGuests(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COUNT(DISTINCT g.user_id) as value
         FROM sessions s
         JOIN guests g ON g.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getTopByPoints(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                SUM(b.host_score) as value
         FROM sessions s
         JOIN battles b ON b.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getTopByChatMessages(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COUNT(*) as value
         FROM sessions s
         JOIN chat_messages cm ON cm.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getTopByTranscriptDensity(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COUNT(*) as value
         FROM sessions s
         JOIN chunks c ON c.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getTopByBattles(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COUNT(*) as value
         FROM sessions s
         JOIN battles b ON b.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
  } finally {
    db.close();
  }
}

export function getTopByUniqueViewers(limit = 5): StatSessionRow[] {
  const db = getDb();
  try {
    return db
      .prepare(
        `SELECT s.id as session_id, s.username, s.date,
                COUNT(DISTINCT vj.user_id) as value
         FROM sessions s
         JOIN viewer_joins vj ON vj.session_id = s.id
         GROUP BY s.id
         ORDER BY value DESC LIMIT ?`,
      )
      .all(limit) as StatSessionRow[];
  } catch {
    return [];
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
