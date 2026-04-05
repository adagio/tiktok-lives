import pg from "pg";
import path from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Load .env from repo root
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.resolve(__dirname, "../../../../.env");
try {
  const envContent = readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match) {
      const key = match[1].trim();
      const val = match[2].trim();
      if (!process.env[key]) process.env[key] = val;
    }
  }
} catch {}

const SCHEMA = "tiktok_manager";

const pool = new pg.Pool({
  host: process.env.DB_HOST || "localhost",
  port: parseInt(process.env.DB_PORT || "5432"),
  database: process.env.DB_NAME || "PoCs_DB",
  user: process.env.DB_USER || "postgres",
  password: process.env.DB_PASSWORD || "",
});

async function query<T extends pg.QueryResultRow = any>(sql: string, params?: any[]): Promise<T[]> {
  const client = await pool.connect();
  try {
    await client.query(`SET search_path TO ${SCHEMA}`);
    const result = await client.query<T>(sql, params);
    return result.rows;
  } finally {
    client.release();
  }
}

async function queryOne<T extends pg.QueryResultRow = any>(sql: string, params?: any[]): Promise<T | null> {
  const rows = await query<T>(sql, params);
  return rows[0] ?? null;
}

// ─── Interfaces ───

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

export interface ClipFilters {
  author?: string;
  query?: string;
  mode?: string;
  limit?: number;
}

export interface SessionRow {
  id: number;
  username: string;
  date: string;
  duration_seconds: number | null;
  status: string;
  data_sources: number;
  data_duration_seconds: number | null;
  indexed_at: string;
  chunk_count: number;
  clip_count: number;
}

export interface SessionDetail {
  id: number;
  username: string;
  date: string;
  duration_seconds: number | null;
  status: string;
  data_sources: number;
  data_duration_seconds: number | null;
  ffmpeg_exit_code: number | null;
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
}

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

export interface GuestRow {
  id: number;
  session_id: number;
  user_id: number;
  username: string;
  nickname: string | null;
  joined_at: string;
  left_at: string | null;
}

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

export interface AuthorListRow {
  username: string;
  total_sessions: number;
  first_session: string;
  last_session: string;
  total_duration: number | null;
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

export interface DonorRankingRow {
  user_id: number;
  username: string;
  total_diamonds: number;
  gift_count: number;
}

export interface GlobalDonorRow {
  user_id: number;
  username: string;
  total_diamonds: number;
  total_coins: number;
  gift_count: number;
  total_repeats: number;
  sessions: number;
  streamers: number;
  top_gift: string | null;
  top_receiver: string | null;
  first_gift: string | null;
  last_gift: string | null;
}

export interface DonorGiftBreakdown {
  gift_name: string;
  diamond_count: number;
  coin_cost: number | null;
  total_sent: number;
  total_diamonds: number;
}

export interface GiftCatalogRow {
  gift_name: string;
  diamond_count: number;
  coin_cost: number | null;
  total_sent: number;
  total_diamonds: number;
  unique_senders: number;
}

export interface VentanillaRankingRow {
  user_id: number;
  username: string;
  nickname: string | null;
  total_seconds: number;
  visit_count: number;
}

export interface OpponentRankingRow {
  opponent_username: string;
  total_battles: number;
  total_opponent_score: number;
  total_host_score: number;
  wins: number;
  losses: number;
}

export interface ChatAnalysisRow {
  topics: string;
  summary: string;
}

export interface DayRow {
  day: string;
  session_count: number;
  total_duration: number;
  authors: string;
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

export interface StatSessionRow {
  session_id: number;
  username: string;
  date: string;
  value: number;
}

export interface UserVideoRow {
  id: number;
  username: string;
  video_id: string;
  description: string | null;
  create_time: string;
  detected_at: string;
}

// ─── Data source bitmask ───

export const DS_VIDEO = 1;
export const DS_CHAT = 2;
export const DS_GIFTS = 4;
export const DS_BATTLES = 8;
export const DS_GUESTS = 16;
export const DS_VIEWERS = 32;

export function getDataSourceLabels(bitmask: number): string[] {
  const labels: string[] = [];
  if (bitmask & DS_VIDEO) labels.push("video");
  if (bitmask & DS_CHAT) labels.push("chat");
  if (bitmask & DS_GIFTS) labels.push("gifts");
  if (bitmask & DS_BATTLES) labels.push("battles");
  if (bitmask & DS_GUESTS) labels.push("guests");
  if (bitmask & DS_VIEWERS) labels.push("viewers");
  return labels;
}

// ─── Queries ───

export async function getStats(): Promise<Stats> {
  const r = await queryOne<any>(`
    SELECT
      (SELECT COUNT(*) FROM clips) as "totalClips",
      (SELECT COUNT(*) FROM sessions) as "totalSessions",
      (SELECT COUNT(DISTINCT username) FROM clips) as "uniqueAuthors",
      (SELECT COUNT(DISTINCT query) FROM clips) as "uniqueQueries"
  `);
  return r!;
}

export async function getClips(filters: ClipFilters = {}): Promise<ClipRow[]> {
  const conditions: string[] = [];
  const params: any[] = [];
  let idx = 1;

  if (filters.author) {
    conditions.push(`c.username = $${idx++}`);
    params.push(filters.author);
  }
  if (filters.query) {
    conditions.push(`c.query = $${idx++}`);
    params.push(filters.query);
  }
  if (filters.mode) {
    conditions.push(`c.search_mode = $${idx++}`);
    params.push(filters.mode);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  const limit = filters.limit ? `LIMIT ${filters.limit}` : "";

  return query<ClipRow>(`
    SELECT c.*, ch.text, s.date
    FROM clips c
    LEFT JOIN chunks ch ON c.chunk_id = ch.id
    LEFT JOIN sessions s ON c.session_id = s.id
    ${where}
    ORDER BY c.score DESC
    ${limit}
  `, params);
}

export async function getAuthors(): Promise<string[]> {
  const rows = await query<{ username: string }>("SELECT DISTINCT username FROM clips ORDER BY username");
  return rows.map((r) => r.username);
}

export async function getQueries(): Promise<string[]> {
  const rows = await query<{ query: string }>("SELECT DISTINCT query FROM clips ORDER BY query");
  return rows.map((r) => r.query);
}

export async function getModes(): Promise<string[]> {
  const rows = await query<{ search_mode: string }>("SELECT DISTINCT search_mode FROM clips ORDER BY search_mode");
  return rows.map((r) => r.search_mode);
}

export async function getSessions(author?: string, status?: string): Promise<SessionRow[]> {
  const conditions: string[] = [];
  const params: any[] = [];
  let idx = 1;

  if (author) {
    conditions.push(`s.username = $${idx++}`);
    params.push(author);
  }
  if (status) {
    conditions.push(`s.status = $${idx++}`);
    params.push(status);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";

  return query<SessionRow>(`
    SELECT s.id, s.username, s.date, s.duration_seconds, s.status,
      s.data_sources, s.data_duration_seconds, s.indexed_at,
      (SELECT COUNT(*) FROM chunks ch WHERE ch.session_id = s.id) as chunk_count,
      (SELECT COUNT(*) FROM clips c WHERE c.session_id = s.id) as clip_count
    FROM sessions s
    ${where}
    ORDER BY s.date DESC
  `, params);
}

export async function getSessionAuthors(): Promise<string[]> {
  const rows = await query<{ username: string }>("SELECT DISTINCT username FROM sessions ORDER BY username");
  return rows.map((r) => r.username);
}

export async function getSession(id: number): Promise<SessionDetail | null> {
  return queryOne<SessionDetail>("SELECT * FROM sessions WHERE id = $1", [id]);
}

export async function getSessionChunks(sessionId: number): Promise<ChunkRow[]> {
  return query<ChunkRow>(
    "SELECT id, chunk_index, start_seconds, end_seconds, text FROM chunks WHERE session_id = $1 ORDER BY start_seconds",
    [sessionId],
  );
}

export async function getSessionClips(sessionId: number): Promise<ClipRow[]> {
  return query<ClipRow>(`
    SELECT c.*, ch.text, s.date
    FROM clips c
    LEFT JOIN chunks ch ON c.chunk_id = ch.id
    LEFT JOIN sessions s ON c.session_id = s.id
    WHERE c.session_id = $1
    ORDER BY c.start_seconds
  `, [sessionId]);
}

// --- Battles ---

export async function getSessionBattles(sessionId: number): Promise<BattleRow[]> {
  try {
    return await query<BattleRow>(
      `SELECT bp_host.id, bp_host.session_id, bv.battle_id,
              bp_opp.username AS opponent_username, bp_opp.user_id AS opponent_user_id,
              bp_host.score AS host_score, bp_opp.score AS opponent_score,
              bv.detected_at
       FROM battle_participants bp_host
       JOIN battles_v2 bv ON bp_host.battle_id = bv.battle_id
       JOIN battle_participants bp_opp ON bp_opp.battle_id = bv.battle_id AND bp_opp.user_id != bp_host.user_id
       WHERE bp_host.session_id = $1
       ORDER BY bv.detected_at`,
      [sessionId],
    );
  } catch {
    return [];
  }
}

// --- Guests ---

export async function getSessionGuests(sessionId: number): Promise<GuestRow[]> {
  try {
    return await query<GuestRow>(
      "SELECT * FROM guests WHERE session_id = $1 ORDER BY joined_at",
      [sessionId],
    );
  } catch {
    return [];
  }
}

export async function getActiveGuests(sessionId: number): Promise<{ username: string; nickname: string | null; joined_at: string }[]> {
  try {
    return await query(
      `SELECT username, nickname, joined_at FROM guests
       WHERE session_id = $1 AND left_at IS NULL
         AND (
           joined_at > NOW() - INTERVAL '4 hours'
           OR EXISTS (
             SELECT 1 FROM chat_messages
             WHERE session_id = $1 AND timestamp > NOW() - INTERVAL '30 minutes'
           )
         )
       ORDER BY joined_at`,
      [sessionId],
    );
  } catch {
    return [];
  }
}

export async function getLatestGuest(sessionId: number): Promise<{ username: string; nickname: string | null; joined_at: string } | null> {
  try {
    return await queryOne(
      "SELECT username, nickname, joined_at FROM guests WHERE session_id = $1 ORDER BY joined_at DESC LIMIT 1",
      [sessionId],
    );
  } catch {
    return null;
  }
}

export async function getLatestViewerJoin(sessionId: number, roomUsername?: string): Promise<{ username: string; joined_at: string } | null> {
  try {
    if (roomUsername) {
      return await queryOne(
        "SELECT username, joined_at FROM viewer_joins WHERE session_id = $1 AND room_username = $2 ORDER BY joined_at DESC LIMIT 1",
        [sessionId, roomUsername],
      );
    }
    return await queryOne(
      "SELECT username, joined_at FROM viewer_joins WHERE session_id = $1 ORDER BY joined_at DESC LIMIT 1",
      [sessionId],
    );
  } catch {
    return null;
  }
}

// --- Chat messages ---

export async function getBattle(id: number): Promise<BattleDetail | null> {
  return queryOne<BattleDetail>(`
    SELECT bp_host.id, bp_host.session_id, bv.battle_id,
           bp_opp.username AS opponent_username, bp_opp.user_id AS opponent_user_id,
           bp_host.score AS host_score, bp_opp.score AS opponent_score,
           bv.detected_at, s.username as host_username
    FROM battle_participants bp_host
    JOIN battles_v2 bv ON bp_host.battle_id = bv.battle_id
    JOIN battle_participants bp_opp ON bp_opp.battle_id = bv.battle_id AND bp_opp.user_id != bp_host.user_id
    JOIN sessions s ON bp_host.session_id = s.id
    WHERE bp_host.id = $1
  `, [id]);
}

export async function getBattleChatMessages(battleId: number, since?: string): Promise<ChatMessageRow[]> {
  try {
    if (since) {
      return await query<ChatMessageRow>(
        "SELECT * FROM chat_messages WHERE battle_id = $1 AND timestamp > $2 ORDER BY timestamp",
        [battleId, since],
      );
    }
    return await query<ChatMessageRow>(
      "SELECT * FROM chat_messages WHERE battle_id = $1 ORDER BY timestamp",
      [battleId],
    );
  } catch {
    return [];
  }
}

export async function isBattleActive(battleId: number): Promise<boolean> {
  try {
    const row = await queryOne<{ last_ts: string | null }>(
      "SELECT MAX(timestamp) as last_ts FROM chat_messages WHERE battle_id = $1",
      [battleId],
    );
    if (!row?.last_ts) return false;
    const lastTs = new Date(row.last_ts).getTime();
    return Date.now() - lastTs < 30_000;
  } catch {
    return false;
  }
}

// --- Battle gifts ---

export interface BattleGiftSummary {
  room_username: string;
  total_diamonds: number;
  total_gifts: number;
  unique_donors: number;
}

export interface BattleGiftDonor {
  room_username: string;
  user_id: number;
  username: string;
  total_diamonds: number;
  gift_count: number;
  top_gift: string | null;
}

export interface BattleGiftItem {
  room_username: string;
  gift_name: string;
  diamond_count: number;
  total_sent: number;
  total_diamonds: number;
}

export async function getBattleGiftSummary(battleId: number): Promise<BattleGiftSummary[]> {
  try {
    return await query<BattleGiftSummary>(`
      SELECT g.room_username,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds,
             COUNT(*) as total_gifts,
             COUNT(DISTINCT g.user_id) as unique_donors
      FROM gifts g
      WHERE g.battle_id = $1 AND g.event_type = 'gift'
      GROUP BY g.room_username
      ORDER BY total_diamonds DESC
    `, [battleId]);
  } catch {
    return [];
  }
}

export async function getBattleTopDonors(battleId: number, limit = 10): Promise<BattleGiftDonor[]> {
  try {
    return await query<BattleGiftDonor>(`
      SELECT g.room_username, g.user_id, g.username,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds,
             COUNT(*) as gift_count,
             (SELECT g2.gift_name FROM gifts g2
              WHERE g2.battle_id = $1 AND g2.user_id = g.user_id AND g2.event_type = 'gift'
              ORDER BY g2.diamond_count * g2.repeat_count DESC LIMIT 1) as top_gift
      FROM gifts g
      WHERE g.battle_id = $1 AND g.event_type = 'gift'
      GROUP BY g.room_username, g.user_id, g.username
      ORDER BY total_diamonds DESC
      LIMIT $2
    `, [battleId, limit]);
  } catch {
    return [];
  }
}

export async function getBattleTopGifts(battleId: number, limit = 10): Promise<BattleGiftItem[]> {
  try {
    return await query<BattleGiftItem>(`
      SELECT g.room_username, g.gift_name, g.diamond_count,
             SUM(g.repeat_count) as total_sent,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds
      FROM gifts g
      WHERE g.battle_id = $1 AND g.event_type = 'gift'
      GROUP BY g.room_username, g.gift_name, g.diamond_count
      ORDER BY total_diamonds DESC
      LIMIT $2
    `, [battleId, limit]);
  } catch {
    return [];
  }
}

export async function getSessionChatMessages(sessionId: number, since?: string): Promise<ChatMessageRow[]> {
  try {
    if (since) {
      return await query<ChatMessageRow>(
        "SELECT * FROM chat_messages WHERE session_id = $1 AND timestamp > $2 ORDER BY timestamp",
        [sessionId, since],
      );
    }
    return await query<ChatMessageRow>(
      "SELECT * FROM chat_messages WHERE session_id = $1 ORDER BY timestamp",
      [sessionId],
    );
  } catch {
    return [];
  }
}

export async function isSessionActive(sessionId: number): Promise<boolean> {
  try {
    const row = await queryOne<{ last_ts: string | null }>(
      "SELECT MAX(timestamp) as last_ts FROM chat_messages WHERE session_id = $1",
      [sessionId],
    );
    if (!row?.last_ts) return false;
    const lastTs = new Date(row.last_ts).getTime();
    return Date.now() - lastTs < 30_000;
  } catch {
    return false;
  }
}

// --- Topic scoring ---

export async function getGlobalTopicScores(): Promise<{ topic: string; max_score: number }[]> {
  return query(
    "SELECT topic, MAX(max_score) as max_score FROM session_topics GROUP BY topic ORDER BY max_score DESC",
  );
}

export async function getSessionTopicScores(sessionId: number): Promise<SessionTopicRow[]> {
  return query<SessionTopicRow>(
    "SELECT topic, max_score, avg_score, best_chunk_id FROM session_topics WHERE session_id = $1 ORDER BY max_score DESC",
    [sessionId],
  );
}

export async function getHeatmapData(): Promise<HeatmapRow[]> {
  return query<HeatmapRow>(`
    SELECT st.session_id, s.username, s.date, st.topic, st.max_score
    FROM session_topics st
    JOIN sessions s ON st.session_id = s.id
    ORDER BY s.date ASC, st.topic
  `);
}

export async function getTopicHighlights(topic: string, limit = 5): Promise<TopicHighlightRow[]> {
  return query<TopicHighlightRow>(`
    SELECT th.topic, th.chunk_id, th.session_id, th.score,
           ch.text, ch.start_seconds, ch.end_seconds,
           s.username, s.date
    FROM topic_highlights th
    LEFT JOIN chunks ch ON th.chunk_id = ch.id
    LEFT JOIN sessions s ON th.session_id = s.id
    WHERE th.topic = $1
    ORDER BY th.score DESC
    LIMIT $2
  `, [topic, limit]);
}

// --- Sessions page ---

export async function getLatestSessionByUsername(username: string): Promise<SessionRow | null> {
  return queryOne<SessionRow>(`
    SELECT s.id, s.username, s.date, s.duration_seconds, s.indexed_at,
      (SELECT COUNT(*) FROM chunks ch WHERE ch.session_id = s.id) as chunk_count,
      (SELECT COUNT(*) FROM clips c WHERE c.session_id = s.id) as clip_count
    FROM sessions s
    WHERE s.username = $1
    ORDER BY s.date DESC
    LIMIT 1
  `, [username]);
}

export async function getChatMessageCount(sessionId: number): Promise<number> {
  try {
    const row = await queryOne<{ c: number }>(
      "SELECT COUNT(*) as c FROM chat_messages WHERE session_id = $1",
      [sessionId],
    );
    return Number(row?.c ?? 0);
  } catch {
    return 0;
  }
}

export async function getLatestVideo(username: string): Promise<UserVideoRow | null> {
  try {
    return await queryOne<UserVideoRow>(
      "SELECT * FROM user_videos WHERE username = $1 ORDER BY create_time DESC LIMIT 1",
      [username],
    );
  } catch {
    return null;
  }
}

// --- Authors ---

export async function getAuthorList(): Promise<AuthorListRow[]> {
  return query<AuthorListRow>(`
    SELECT
      s.username,
      COUNT(*) as total_sessions,
      MIN(DATE(s.date)) as first_session,
      MAX(DATE(s.date)) as last_session,
      SUM(s.duration_seconds) as total_duration
    FROM sessions s
    GROUP BY s.username
    ORDER BY MAX(s.date) DESC
  `);
}

export async function getAuthorDailySummary(username: string): Promise<AuthorDailySummaryRow[]> {
  try {
    return await query<AuthorDailySummaryRow>(`
      SELECT
        DATE(s.date) as day,
        COUNT(DISTINCT s.id) as session_count,
        SUM(s.duration_seconds) as total_duration,
        (SELECT COUNT(*) FROM battle_participants bp
         JOIN sessions s2 ON bp.session_id = s2.id
         WHERE s2.username = $1 AND DATE(s2.date) = DATE(s.date)
        ) as battle_count,
        (SELECT COALESCE(SUM(bp.score), 0) FROM battle_participants bp
         JOIN sessions s2 ON bp.session_id = s2.id
         WHERE s2.username = $1 AND DATE(s2.date) = DATE(s.date)
        ) as total_host_points,
        0 as wins, 0 as losses, 0 as draws,
        (SELECT COUNT(DISTINCT g.user_id) FROM guests g
         JOIN sessions s2 ON g.session_id = s2.id
         WHERE s2.username = $1 AND DATE(s2.date) = DATE(s.date)
        ) as unique_guests,
        (SELECT COUNT(*) FROM chat_messages cm
         JOIN sessions s2 ON cm.session_id = s2.id
         WHERE s2.username = $1 AND DATE(s2.date) = DATE(s.date)
        ) as chat_messages
      FROM sessions s
      WHERE s.username = $1
      GROUP BY DATE(s.date)
      ORDER BY day DESC
    `, [username]);
  } catch {
    return await query<AuthorDailySummaryRow>(`
      SELECT
        DATE(s.date) as day,
        COUNT(DISTINCT s.id) as session_count,
        SUM(s.duration_seconds) as total_duration,
        0 as battle_count, 0 as total_host_points,
        0 as wins, 0 as losses, 0 as draws,
        0 as unique_guests, 0 as chat_messages
      FROM sessions s
      WHERE s.username = $1
      GROUP BY DATE(s.date)
      ORDER BY day DESC
    `, [username]);
  }
}

// --- Donors ---

export async function getTopDonors(username: string, limit = 10): Promise<DonorRankingRow[]> {
  try {
    return await query<DonorRankingRow>(`
      SELECT g.user_id, g.username,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds,
             COUNT(*) as gift_count
      FROM gifts g
      JOIN sessions s ON g.session_id = s.id
      WHERE s.username = $1 AND g.room_username = $1
        AND g.event_type = 'gift'
      GROUP BY g.user_id, g.username
      ORDER BY total_diamonds DESC
      LIMIT $2
    `, [username, limit]);
  } catch {
    return [];
  }
}

export async function getGlobalDonors(limit = 50): Promise<GlobalDonorRow[]> {
  try {
    return await query<GlobalDonorRow>(`
      SELECT g.user_id, g.username,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds,
             SUM(COALESCE(gc.coin_cost, 0) * g.repeat_count) as total_coins,
             COUNT(*) as gift_count,
             SUM(g.repeat_count) as total_repeats,
             COUNT(DISTINCT g.session_id) as sessions,
             COUNT(DISTINCT g.room_username) as streamers,
             (SELECT g2.gift_name FROM gifts g2 WHERE g2.user_id = g.user_id AND g2.event_type = 'gift'
              ORDER BY g2.diamond_count * g2.repeat_count DESC LIMIT 1) as top_gift,
             (SELECT g3.room_username FROM gifts g3 WHERE g3.user_id = g.user_id AND g3.event_type = 'gift'
              GROUP BY g3.room_username ORDER BY SUM(g3.diamond_count * g3.repeat_count) DESC LIMIT 1) as top_receiver,
             MIN(g.timestamp) as first_gift,
             MAX(g.timestamp) as last_gift
      FROM gifts g
      LEFT JOIN gift_catalog gc ON gc.gift_name = g.gift_name
      WHERE g.event_type = 'gift'
      GROUP BY g.user_id, g.username
      ORDER BY total_diamonds DESC
      LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getDonorGifts(userId: number): Promise<DonorGiftBreakdown[]> {
  try {
    return await query<DonorGiftBreakdown>(`
      SELECT g.gift_name, g.diamond_count,
             gc.coin_cost,
             SUM(g.repeat_count) as total_sent,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds
      FROM gifts g
      LEFT JOIN gift_catalog gc ON gc.gift_name = g.gift_name
      WHERE g.user_id = $1 AND g.event_type = 'gift'
      GROUP BY g.gift_name, g.diamond_count, gc.coin_cost
      ORDER BY total_diamonds DESC
    `, [userId]);
  } catch {
    return [];
  }
}

export async function getGiftCatalogStats(): Promise<GiftCatalogRow[]> {
  try {
    return await query<GiftCatalogRow>(`
      SELECT g.gift_name, g.diamond_count,
             gc.coin_cost,
             SUM(g.repeat_count) as total_sent,
             SUM(g.diamond_count * g.repeat_count) as total_diamonds,
             COUNT(DISTINCT g.user_id) as unique_senders
      FROM gifts g
      LEFT JOIN gift_catalog gc ON gc.gift_name = g.gift_name
      WHERE g.event_type = 'gift'
      GROUP BY g.gift_name, g.diamond_count, gc.coin_cost
      ORDER BY total_diamonds DESC
    `);
  } catch {
    return [];
  }
}

export async function getTopVentanilla(username: string, limit = 10): Promise<VentanillaRankingRow[]> {
  try {
    return await query<VentanillaRankingRow>(`
      SELECT g.user_id, g.username, g.nickname,
             SUM(EXTRACT(EPOCH FROM (COALESCE(g.left_at, NOW()) - g.joined_at)))::int as total_seconds,
             COUNT(*) as visit_count
      FROM guests g
      JOIN sessions s ON g.session_id = s.id
      WHERE s.username = $1
      GROUP BY g.user_id, g.username, g.nickname
      ORDER BY total_seconds DESC
      LIMIT $2
    `, [username, limit]);
  } catch {
    return [];
  }
}

export async function getTopOpponents(username: string, limit = 10): Promise<OpponentRankingRow[]> {
  try {
    return await query<OpponentRankingRow>(`
      SELECT bp_opp.username as opponent_username,
             COUNT(*) as total_battles,
             SUM(bp_opp.score) as total_opponent_score,
             SUM(bp_host.score) as total_host_score,
             SUM(CASE WHEN bp_host.score > bp_opp.score THEN 1 ELSE 0 END) as wins,
             SUM(CASE WHEN bp_host.score < bp_opp.score THEN 1 ELSE 0 END) as losses
      FROM battle_participants bp_host
      JOIN battles_v2 bv ON bp_host.battle_id = bv.battle_id
      JOIN battle_participants bp_opp ON bp_opp.battle_id = bv.battle_id AND bp_opp.user_id != bp_host.user_id
      JOIN sessions s ON bp_host.session_id = s.id
      WHERE s.username = $1
      GROUP BY bp_opp.username
      ORDER BY total_battles DESC
      LIMIT $2
    `, [username, limit]);
  } catch {
    return [];
  }
}

// --- Chat analysis ---

export async function getChatAnalysis(sessionId: number): Promise<ChatAnalysisRow | null> {
  try {
    return await queryOne<ChatAnalysisRow>(
      "SELECT topics, summary FROM chat_analysis WHERE session_id = $1",
      [sessionId],
    );
  } catch {
    return null;
  }
}

// --- Days page ---

export async function getDays(): Promise<DayRow[]> {
  return query<DayRow>(`
    SELECT DATE(s.date) as day,
           COUNT(*) as session_count,
           COALESCE(SUM(s.duration_seconds), 0) as total_duration,
           STRING_AGG(DISTINCT s.username, ',') as authors
    FROM sessions s
    GROUP BY DATE(s.date)
    ORDER BY day DESC
  `);
}

export async function getDayDetail(day: string): Promise<DayDetailRow[]> {
  try {
    return await query<DayDetailRow>(`
      SELECT s.id as session_id, s.username, s.date, s.duration_seconds, s.summary,
             ca.summary as chat_summary, ca.topics as chat_topics,
             (SELECT COUNT(*) FROM battle_participants bp WHERE bp.session_id = s.id) as battle_count,
             (SELECT COUNT(DISTINCT g.user_id) FROM guests g WHERE g.session_id = s.id) as guest_count,
             (SELECT COUNT(*) FROM chat_messages cm WHERE cm.session_id = s.id) as chat_message_count,
             (SELECT COUNT(*) FROM chunks c WHERE c.session_id = s.id) as chunk_count
      FROM sessions s
      LEFT JOIN chat_analysis ca ON ca.session_id = s.id
      WHERE DATE(s.date) = $1
      ORDER BY s.date
    `, [day]);
  } catch {
    return [];
  }
}

// --- Stats page ---

export async function getTopByDuration(limit = 5): Promise<StatSessionRow[]> {
  return query<StatSessionRow>(`
    SELECT s.id as session_id, s.username, s.date,
           COALESCE(s.duration_seconds, 0) as value
    FROM sessions s
    ORDER BY value DESC LIMIT $1
  `, [limit]);
}

export async function getTopByGuests(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             COUNT(DISTINCT g.user_id) as value
      FROM sessions s
      JOIN guests g ON g.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getTopByPoints(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             SUM(bp.score) as value
      FROM sessions s
      JOIN battle_participants bp ON bp.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getTopByChatMessages(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             COUNT(*) as value
      FROM sessions s
      JOIN chat_messages cm ON cm.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getTopByTranscriptDensity(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             COUNT(*) as value
      FROM sessions s
      JOIN chunks c ON c.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getTopByBattles(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             COUNT(*) as value
      FROM sessions s
      JOIN battle_participants bp ON bp.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}

export async function getTopByUniqueViewers(limit = 5): Promise<StatSessionRow[]> {
  try {
    return await query<StatSessionRow>(`
      SELECT s.id as session_id, s.username, s.date,
             COUNT(DISTINCT vj.user_id) as value
      FROM sessions s
      JOIN viewer_joins vj ON vj.session_id = s.id
      GROUP BY s.id, s.username, s.date
      ORDER BY value DESC LIMIT $1
    `, [limit]);
  } catch {
    return [];
  }
}
