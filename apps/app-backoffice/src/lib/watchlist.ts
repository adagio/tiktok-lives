import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const watchlistPath = path.resolve(
  __dirname,
  "../../../../apps/recorder/watchlist.json",
);

export interface WatchlistUser {
  username: string;
  enabled: boolean;
}

export interface Watchlist {
  poll_interval_seconds: number;
  users: WatchlistUser[];
}

export function readWatchlist(): Watchlist {
  const raw = fs.readFileSync(watchlistPath, "utf-8");
  return JSON.parse(raw) as Watchlist;
}
