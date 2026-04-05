import pg from "pg";
import path from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

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

async function execute(sql: string, params?: any[]): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query(`SET search_path TO ${SCHEMA}`);
    await client.query(sql, params);
  } finally {
    client.release();
  }
}

export interface WatchlistUser {
  id: number;
  username: string;
  enabled: boolean;
  record: boolean;
  poll_interval_seconds: number;
  added_at: string;
  updated_at: string;
}

export interface Watchlist {
  poll_interval_seconds: number;
  users: WatchlistUser[];
}

export async function readWatchlist(): Promise<Watchlist> {
  const rows = await query<WatchlistUser>(
    "SELECT * FROM watchlist ORDER BY id",
  );
  const interval = rows.length > 0 ? rows[0].poll_interval_seconds : 30;
  return { poll_interval_seconds: interval, users: rows };
}

export async function getWatchlistUser(username: string): Promise<WatchlistUser | null> {
  const rows = await query<WatchlistUser>(
    "SELECT * FROM watchlist WHERE username = $1",
    [username],
  );
  return rows[0] ?? null;
}

export async function addUser(username: string, record = true): Promise<WatchlistUser> {
  const rows = await query<WatchlistUser>(
    `INSERT INTO watchlist (username, enabled, record)
     VALUES ($1, true, $2)
     ON CONFLICT (username) DO UPDATE SET enabled = true, updated_at = NOW()
     RETURNING *`,
    [username, record],
  );
  return rows[0];
}

export async function updateUser(username: string, updates: { enabled?: boolean; record?: boolean; poll_interval_seconds?: number }): Promise<WatchlistUser | null> {
  const sets: string[] = [];
  const params: any[] = [];
  let idx = 1;

  if (updates.enabled !== undefined) {
    sets.push(`enabled = $${idx++}`);
    params.push(updates.enabled);
  }
  if (updates.record !== undefined) {
    sets.push(`record = $${idx++}`);
    params.push(updates.record);
  }
  if (updates.poll_interval_seconds !== undefined) {
    sets.push(`poll_interval_seconds = $${idx++}`);
    params.push(updates.poll_interval_seconds);
  }

  if (sets.length === 0) return null;

  sets.push("updated_at = NOW()");
  params.push(username);

  const rows = await query<WatchlistUser>(
    `UPDATE watchlist SET ${sets.join(", ")} WHERE username = $${idx} RETURNING *`,
    params,
  );
  return rows[0] ?? null;
}

export async function removeUser(username: string): Promise<boolean> {
  await execute("DELETE FROM watchlist WHERE username = $1", [username]);
  return true;
}
