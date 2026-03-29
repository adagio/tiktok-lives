"""TikTok Live Monitor — async orchestrator for recording, battles, and ventanilla."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from subprocess import Popen

from battles import (
    close_orphaned_guests,
    close_orphaned_sessions,
    create_session,
    finalize_session,
    get_battle_info,
    get_host_user_id,
    get_room_id,
    resolve_user_id,
    save_battle,
    update_battle_scores,
    update_session_duration,
)
from chat_spy import ChatSpy
from profile_checker import check_and_save as check_profile
from recording import AdoptedProcess, check_is_live, start_recording
from treasure_spy import TreasureSpy
from ventanilla_spy import VentanillaSpy

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"
LOG_PATH = Path(__file__).resolve().parent.parent / "monitor.log"
HEARTBEAT_PATH = Path(__file__).resolve().parent.parent / "monitor.heartbeat"
LOCK_PATH = Path(__file__).resolve().parent.parent / "monitor.lock"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = str(REPO_ROOT / "clips.db")
BACKUP_DIR = REPO_ROOT / "backups"
BACKUP_INTERVAL = 3600  # seconds (1 hour)
BACKUP_KEEP = 4  # number of recent backups to keep

# --- Logging setup ---

log = logging.getLogger("monitor")
log.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_sh = logging.StreamHandler(sys.stderr)
_sh.setFormatter(_fmt)
log.addHandler(_sh)

_fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_fh)


# --- Data structures ---


@dataclass
class ActiveSession:
    username: str
    started_at: float
    process: Popen | None = None
    path: Path | None = None
    session_id: int | None = None
    monitor_only: bool = False
    room_id: str | None = None
    last_battle_id: int | None = None
    spy: VentanillaSpy | None = None
    spy_task: asyncio.Task | None = None
    treasure_spy: TreasureSpy | None = None
    treasure_task: asyncio.Task | None = None
    chat_spy: ChatSpy | None = None
    chat_task: asyncio.Task | None = None
    opponent_chat_spy: ChatSpy | None = None
    opponent_chat_task: asyncio.Task | None = None


# --- Monitor ---


MIN_GOOD_DURATION = 120  # seconds — recordings shorter than this count as failures
CIRCUIT_BREAKER_WINDOW = 300  # seconds — look at failures within this window
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive short failures before backoff
CIRCUIT_BREAKER_BASE_DELAY = 60  # seconds — initial backoff (1 min)
CIRCUIT_BREAKER_MAX_DELAY = 300  # seconds — max backoff (5 min)


class Monitor:
    def __init__(self):
        self.active: dict[str, ActiveSession] = {}
        self.resolved_users: dict[int, str] = {}
        self._shutdown = False
        # Circuit breaker: track recent recording failures per user
        self._fail_times: dict[str, list[float]] = {}  # username -> list of failure timestamps
        self._backoff_until: dict[str, float] = {}  # username -> timestamp when backoff expires

    async def _heartbeat_loop(self):
        """Write timestamp to heartbeat file every 30s for watchdog hang detection."""
        while not self._shutdown:
            try:
                HEARTBEAT_PATH.write_text(str(time.time()), encoding="utf-8")
                active_users = list(self.active.keys())
                if active_users:
                    log.info("♥ heartbeat — %d active: %s", len(active_users), ", ".join(active_users))
                else:
                    log.info("♥ heartbeat — idle")
            except Exception:
                log.debug("Heartbeat write failed", exc_info=True)
            await asyncio.sleep(30)

    def _resolve(self, user_id: int) -> str:
        if user_id not in self.resolved_users:
            try:
                username, _ = resolve_user_id(user_id)
                self.resolved_users[user_id] = username
            except Exception:
                self.resolved_users[user_id] = f"id:{user_id}"
        return self.resolved_users[user_id]

    def _load_watchlist(self) -> tuple[int, list[dict]]:
        try:
            data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
            interval = data.get("poll_interval_seconds", 90)
            users = [u for u in data.get("users", []) if u.get("enabled", True)]
            return interval, users
        except (json.JSONDecodeError, FileNotFoundError) as e:
            log.error("Failed to load watchlist: %s", e)
            return 90, []

    def _record_failure(self, username: str):
        """Record a recording failure and activate backoff if threshold reached."""
        now = time.time()
        times = self._fail_times.setdefault(username, [])
        times.append(now)
        # Keep only failures within the window
        cutoff = now - CIRCUIT_BREAKER_WINDOW
        times[:] = [t for t in times if t >= cutoff]

        if len(times) >= CIRCUIT_BREAKER_THRESHOLD:
            # Fibonacci backoff: 1, 1, 2, 3, 5, 8, 13... × base_delay
            streak = len(times) - CIRCUIT_BREAKER_THRESHOLD
            a, b = 1, 1
            for _ in range(streak):
                a, b = b, a + b
            delay = min(a * CIRCUIT_BREAKER_BASE_DELAY, CIRCUIT_BREAKER_MAX_DELAY)
            self._backoff_until[username] = now + delay
            log.warning(
                "⏸️  Circuit breaker for @%s: %d failures in %ds, backing off %.0fmin",
                username, len(times), CIRCUIT_BREAKER_WINDOW, delay / 60,
            )

    def _clear_failures(self, username: str):
        """Reset failure tracking after a successful recording."""
        self._fail_times.pop(username, None)
        self._backoff_until.pop(username, None)

    def _is_backed_off(self, username: str) -> bool:
        """Check if user is in backoff period."""
        until = self._backoff_until.get(username)
        if until is None:
            return False
        if time.time() >= until:
            # Backoff expired — allow one retry but keep fail history
            del self._backoff_until[username]
            log.info("⏸️  Backoff expired for @%s, will retry", username)
            return False
        return True

    def _cleanup_empty_file(self, path: Path | None):
        """Remove 0-byte .ts files left by crashed ffmpeg."""
        if path is None:
            return
        try:
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
                log.info("🗑️  Removed empty file %s", path)
        except Exception:
            log.debug("Failed to clean up %s", path, exc_info=True)

    def _reap_finished(self):
        """Remove entries for ffmpeg processes that have exited."""
        finished = []
        for username, sess in self.active.items():
            if sess.monitor_only:
                continue  # monitor-only sessions are reaped async
            ret = sess.process.poll()
            if ret is not None:
                elapsed = time.time() - sess.started_at
                log.info(
                    "Recording ended for @%s (exit %s, %.0fs) → %s",
                    username, ret, elapsed, sess.path,
                )
                if sess.session_id is not None:
                    try:
                        update_session_duration(DB_PATH, sess.session_id, elapsed)
                        log.info("Updated session %d duration: %.0fs", sess.session_id, elapsed)
                    except Exception:
                        log.warning("Failed to update session duration for @%s", username, exc_info=True)

                    # Finalize session: compute data sources and set status
                    try:
                        has_video = bool(
                            sess.path and sess.path.exists() and sess.path.stat().st_size > 0
                        )
                        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                        status = finalize_session(
                            DB_PATH, sess.session_id, date_str,
                            ffmpeg_exit_code=ret, has_video=has_video,
                        )
                        log.info("Session %d finalized: status=%s", sess.session_id, status)
                    except Exception:
                        log.warning("Failed to finalize session for @%s", username, exc_info=True)

                # Track failures vs successes for circuit breaker
                if ret != 0 and elapsed < MIN_GOOD_DURATION:
                    self._record_failure(username)
                    self._cleanup_empty_file(sess.path)
                else:
                    self._clear_failures(username)

                # Cancel spy tasks
                if sess.spy_task and not sess.spy_task.done():
                    sess.spy_task.cancel()
                if sess.treasure_task and not sess.treasure_task.done():
                    sess.treasure_task.cancel()
                if sess.chat_task and not sess.chat_task.done():
                    sess.chat_task.cancel()
                if sess.opponent_chat_task and not sess.opponent_chat_task.done():
                    sess.opponent_chat_task.cancel()
                finished.append(username)
        for u in finished:
            del self.active[u]

    def _start_session(self, username: str, result: dict) -> ActiveSession:
        """Start recording + create DB session."""
        proc, path = start_recording(username, result["url"])
        started_at = time.time()

        session_id = None
        try:
            date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            session_id = create_session(DB_PATH, username, date_iso, str(path), pid=proc.pid, status="recording")
            log.info("Created session %d for @%s (pid=%d)", session_id, username, proc.pid)
        except Exception:
            log.warning("Failed to create session for @%s", username, exc_info=True)

        sess = ActiveSession(
            username=username,
            process=proc,
            path=path,
            started_at=started_at,
            session_id=session_id,
        )
        self.active[username] = sess
        log.info("🔴 Recording started for @%s → %s", username, path)
        return sess

    def _start_monitor_session(self, username: str) -> ActiveSession:
        """Start a monitor-only session (no recording)."""
        started_at = time.time()

        session_id = None
        try:
            date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            session_id = create_session(DB_PATH, username, date_iso, "", pid=0, status="monitor_only")
            log.info("Created monitor-only session %d for @%s", session_id, username)
        except Exception:
            log.warning("Failed to create session for @%s", username, exc_info=True)

        sess = ActiveSession(
            username=username,
            started_at=started_at,
            session_id=session_id,
            monitor_only=True,
        )
        self.active[username] = sess
        log.info("👁️ Monitoring started for @%s (no recording)", username)
        return sess

    async def _launch_spy(self, sess: ActiveSession):
        """Launch VentanillaSpy for a session (if possible)."""
        if sess.session_id is None:
            return
        try:
            host_uid = await asyncio.wait_for(asyncio.to_thread(get_host_user_id, sess.username), timeout=20)
        except asyncio.TimeoutError:
            log.warning("Timeout: get_host_user_id for @%s", sess.username)
            host_uid = None
        if not host_uid:
            log.debug("Could not get host user_id for @%s, skipping spy", sess.username)
            return
        spy = VentanillaSpy(
            username=sess.username,
            session_id=sess.session_id,
            host_user_id=host_uid,
            db_path=DB_PATH,
        )
        sess.spy = spy
        sess.spy_task = asyncio.create_task(self._run_spy_safe(spy, sess.username))

    async def _run_spy_safe(self, spy: VentanillaSpy, username: str):
        """Wrapper so spy crashes don't kill the monitor."""
        try:
            await spy.start()
        except asyncio.CancelledError:
            await spy.stop()
        except Exception:
            log.warning("Spy for @%s crashed", username, exc_info=True)

    async def _launch_chat_spy(self, sess: ActiveSession):
        """Launch ChatSpy for the host's room (runs for entire session)."""
        if sess.session_id is None:
            return
        spy = ChatSpy(
            username=sess.username,
            session_id=sess.session_id,
            db_path=DB_PATH,
        )
        sess.chat_spy = spy
        sess.chat_task = asyncio.create_task(self._run_chat_spy_safe(spy, sess.username))

    async def _run_chat_spy_safe(self, spy: ChatSpy, label: str):
        """Wrapper so chat spy crashes don't kill the monitor."""
        try:
            await spy.start()
        except asyncio.CancelledError:
            await spy.stop()
        except Exception:
            log.warning("ChatSpy for @%s crashed", label, exc_info=True)

    async def _revive_spies(self, sess: ActiveSession):
        """Restart spies that died while the session is still active."""
        if sess.spy_task and sess.spy_task.done():
            log.info("🔌 Reviving VentanillaSpy for @%s", sess.username)
            await self._launch_spy(sess)
        if sess.chat_task and sess.chat_task.done():
            log.info("💬 Reviving ChatSpy for @%s", sess.username)
            await self._launch_chat_spy(sess)

    async def _launch_opponent_chat_spy(self, sess: ActiveSession, opponent_username: str, battle_id: int):
        """Launch ChatSpy for the opponent's room during a battle."""
        if sess.session_id is None:
            return
        spy = ChatSpy(
            username=opponent_username,
            session_id=sess.session_id,
            db_path=DB_PATH,
            battle_id=battle_id,
        )
        sess.opponent_chat_spy = spy
        sess.opponent_chat_task = asyncio.create_task(self._run_chat_spy_safe(spy, f"opponent:{opponent_username}"))

    async def _stop_opponent_chat_spy(self, sess: ActiveSession):
        """Stop the opponent ChatSpy if running."""
        if sess.opponent_chat_task and not sess.opponent_chat_task.done():
            sess.opponent_chat_task.cancel()
            try:
                await sess.opponent_chat_task
            except (asyncio.CancelledError, Exception):
                pass
        sess.opponent_chat_spy = None
        sess.opponent_chat_task = None

    async def _launch_treasure_spy(self, sess: ActiveSession, opponent_username: str):
        """Launch TreasureSpy against the opponent's live room."""
        spy = TreasureSpy(opponent_username, session_id=sess.session_id, battle_id=sess.last_battle_id, db_path=DB_PATH)
        sess.treasure_spy = spy
        sess.treasure_task = asyncio.create_task(self._run_treasure_spy_safe(spy, opponent_username))

    async def _run_treasure_spy_safe(self, spy: TreasureSpy, opponent_username: str):
        """Wrapper so treasure spy crashes don't kill the monitor."""
        try:
            await spy.start()
        except asyncio.CancelledError:
            await spy.stop()
        except Exception:
            log.warning("TreasureSpy for @%s crashed", opponent_username, exc_info=True)

    async def _stop_treasure_spy(self, sess: ActiveSession):
        """Stop the TreasureSpy if running."""
        if sess.treasure_task and not sess.treasure_task.done():
            sess.treasure_task.cancel()
            try:
                await sess.treasure_task
            except (asyncio.CancelledError, Exception):
                pass
        sess.treasure_spy = None
        sess.treasure_task = None

    def _check_battle_sync(self, username: str) -> str | None:
        """Check battles (sync, meant to run in to_thread).

        Returns opponent username when a new battle is detected, "__ended__"
        when a battle just ended, or None otherwise.
        """
        sess = self.active.get(username)
        if not sess:
            return None

        if not sess.room_id:
            try:
                sess.room_id = get_room_id(username)
            except Exception:
                log.debug("Failed to get room_id for @%s", username, exc_info=True)
                return None
            if not sess.room_id:
                return None

        try:
            info = get_battle_info(sess.room_id)
        except Exception:
            log.debug("Failed to get battle info for @%s", username, exc_info=True)
            return None

        if not info:
            if sess.last_battle_id is not None:
                log.info("⚔️  Battle ended for @%s", username)
                sess.last_battle_id = None
                return "__ended__"
            return None

        battle_id = info.get("battle_id")
        if not battle_id:
            return None

        scores = info.get("scores", {})
        rival_id = info.get("rival_anchor_id")
        is_new = battle_id != sess.last_battle_id
        sess.last_battle_id = battle_id

        # Identify host vs opponents
        host_uid = None
        opponent_uids = []
        for uid in scores:
            handle = self._resolve(uid)
            if handle.lower() == username.lower():
                host_uid = uid
            else:
                opponent_uids.append(uid)

        if not opponent_uids and rival_id:
            opponent_uids = [rival_id]

        host_score = scores.get(host_uid, 0) if host_uid else 0

        opponent_handle = None
        for opp_uid in opponent_uids:
            opp_handle = self._resolve(opp_uid)
            opp_score = scores.get(opp_uid, 0)

            if is_new:
                opponent_handle = opp_handle
                try:
                    save_battle(DB_PATH, sess.session_id, battle_id, opp_handle, opp_uid, host_score, opp_score)
                except Exception:
                    log.warning("Failed to save battle to DB", exc_info=True)
            else:
                try:
                    update_battle_scores(DB_PATH, battle_id, opp_uid, host_score, opp_score)
                except Exception:
                    log.debug("Failed to update battle scores", exc_info=True)

        if is_new:
            rival_handle = self._resolve(rival_id) if rival_id else "?"
            score_parts = []
            for uid, pts in sorted(scores.items(), key=lambda x: x[1], reverse=True):
                handle = self._resolve(uid)
                score_parts.append(f"@{handle} {pts}")
            log.info(
                "⚔️  @%s in battle vs @%s  |  %s  (battle_id=%s)",
                username, rival_handle, "  vs  ".join(score_parts), battle_id,
            )
            return opponent_handle

        return None

    async def _shutdown_all(self):
        """Graceful shutdown: terminate recordings, stop spies."""
        log.info("Shutting down...")
        for username, sess in self.active.items():
            if sess.process:
                log.info("Terminating recording for @%s", username)
                sess.process.terminate()
            else:
                log.info("Stopping monitor-only session for @%s", username)
            if sess.spy_task and not sess.spy_task.done():
                sess.spy_task.cancel()
            if sess.treasure_task and not sess.treasure_task.done():
                sess.treasure_task.cancel()
            if sess.chat_task and not sess.chat_task.done():
                sess.chat_task.cancel()
            if sess.opponent_chat_task and not sess.opponent_chat_task.done():
                sess.opponent_chat_task.cancel()

        # Wait for spy tasks to finish
        spy_tasks = [s.spy_task for s in self.active.values() if s.spy_task and not s.spy_task.done()]
        spy_tasks += [s.treasure_task for s in self.active.values() if s.treasure_task and not s.treasure_task.done()]
        spy_tasks += [s.chat_task for s in self.active.values() if s.chat_task and not s.chat_task.done()]
        spy_tasks += [s.opponent_chat_task for s in self.active.values() if s.opponent_chat_task and not s.opponent_chat_task.done()]
        if spy_tasks:
            await asyncio.gather(*spy_tasks, return_exceptions=True)

        # Wait for ffmpeg processes and finalize sessions
        for username, sess in self.active.items():
            ret = None
            if sess.process:
                try:
                    sess.process.wait(timeout=10)
                    ret = sess.process.poll()
                except Exception:
                    sess.process.kill()
                    ret = -1

            elapsed = time.time() - sess.started_at
            if sess.session_id is not None:
                try:
                    update_session_duration(DB_PATH, sess.session_id, elapsed)
                except Exception:
                    pass
                try:
                    has_video = bool(
                        sess.path and sess.path.exists() and sess.path.stat().st_size > 0
                    )
                    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                    finalize_session(
                        DB_PATH, sess.session_id, date_str,
                        ffmpeg_exit_code=ret, has_video=has_video,
                    )
                except Exception:
                    pass

        self.active.clear()
        log.info("Monitor stopped.")

    async def _backup_db_loop(self):
        """Backup clips.db every hour, keeping only the last N copies."""
        import shutil

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        while not self._shutdown:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = BACKUP_DIR / f"clips_{ts}.db"
                await asyncio.to_thread(shutil.copy2, DB_PATH, str(dest))
                log.info("💾 DB backup → %s", dest.name)

                # Rotate: keep only the last N backups
                backups = sorted(BACKUP_DIR.glob("clips_*.db"))
                for old in backups[:-BACKUP_KEEP]:
                    old.unlink()
                    log.info("💾 Removed old backup %s", old.name)
            except Exception:
                log.warning("DB backup failed", exc_info=True)
            await asyncio.sleep(BACKUP_INTERVAL)

    async def _profile_check_loop(self):
        """Periodically check all watchlist users for new video uploads."""
        PROFILE_CHECK_INTERVAL = 300  # 5 minutes
        while not self._shutdown:
            _, users = self._load_watchlist()
            for user in users:
                if self._shutdown:
                    break
                username = user["username"]
                try:
                    new_count = await asyncio.wait_for(asyncio.to_thread(check_profile, DB_PATH, username), timeout=30)
                    if new_count > 0:
                        log.info("📹 @%s uploaded %d new video(s)", username, new_count)
                except asyncio.TimeoutError:
                    log.warning("Timeout: check_profile for @%s", username)
                except Exception:
                    log.debug("Profile check failed for @%s", username, exc_info=True)
                await asyncio.sleep(2)  # small delay between profile fetches
            await asyncio.sleep(PROFILE_CHECK_INTERVAL)

    async def run(self):
        # Close orphaned sessions / re-attach alive ffmpeg from previous runs
        try:
            closed, alive = close_orphaned_sessions(DB_PATH)
            orphaned_guests = close_orphaned_guests(DB_PATH)
            if orphaned_guests:
                log.info("Closed %d orphaned guest(s) from previous run", orphaned_guests)
            for s in closed:
                log.info("Closed orphaned session %d (@%s, %.0fs)", s["id"], s["username"], s["duration"])
            for s in alive:
                proc = AdoptedProcess(s["pid"])
                sess = ActiveSession(
                    username=s["username"],
                    process=proc,
                    path=Path(s["ts_path"]),
                    started_at=datetime.fromisoformat(s["date"]).timestamp(),
                    session_id=s["id"],
                )
                self.active[s["username"]] = sess
                log.info("Re-attached session %d (@%s, pid=%d)", s["id"], s["username"], s["pid"])
                await self._launch_spy(sess)
                await self._launch_chat_spy(sess)
        except Exception:
            log.warning("Failed to handle orphaned sessions", exc_info=True)

        log.info("Monitor started. Watchlist: %s", WATCHLIST_PATH)

        # Launch background tasks
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        profile_task = asyncio.create_task(self._profile_check_loop())
        backup_task = asyncio.create_task(self._backup_db_loop())

        while not self._shutdown:
            interval, users = self._load_watchlist()

            if not users:
                log.warning("No enabled users in watchlist, sleeping %ds", interval)
                await asyncio.sleep(interval)
                continue

            self._reap_finished()

            delay_between = interval / len(users)

            for i, user in enumerate(users):
                if self._shutdown:
                    break

                username = user["username"]

                if username in self.active:
                    sess = self.active[username]
                    # For monitor-only sessions, check if live ended
                    if sess.monitor_only:
                        try:
                            still_live = await asyncio.wait_for(asyncio.to_thread(check_is_live, username), timeout=45)
                        except (asyncio.TimeoutError, Exception):
                            still_live = True  # assume still live on error
                        if not still_live:
                            elapsed = time.time() - sess.started_at
                            log.info("👁️ Live ended for @%s (%.0fs, monitor-only)", username, elapsed)
                            if sess.session_id is not None:
                                try:
                                    update_session_duration(DB_PATH, sess.session_id, elapsed)
                                except Exception:
                                    log.warning("Failed to update session duration for @%s", username, exc_info=True)
                                try:
                                    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                                    finalize_session(DB_PATH, sess.session_id, date_str, has_video=False)
                                except Exception:
                                    log.warning("Failed to finalize session for @%s", username, exc_info=True)
                            if sess.spy_task and not sess.spy_task.done():
                                sess.spy_task.cancel()
                            if sess.chat_task and not sess.chat_task.done():
                                sess.chat_task.cancel()
                            if sess.treasure_task and not sess.treasure_task.done():
                                sess.treasure_task.cancel()
                            if sess.opponent_chat_task and not sess.opponent_chat_task.done():
                                sess.opponent_chat_task.cancel()
                            del self.active[username]
                            continue
                    await self._revive_spies(sess)
                    try:
                        battle_result = await asyncio.wait_for(asyncio.to_thread(self._check_battle_sync, username), timeout=30)
                    except asyncio.TimeoutError:
                        log.warning("Timeout: _check_battle_sync for @%s", username)
                        battle_result = None
                    if battle_result == "__ended__":
                        await self._stop_treasure_spy(sess)
                        await self._stop_opponent_chat_spy(sess)
                        if sess.chat_spy:
                            sess.chat_spy.battle_id = None
                    elif battle_result is not None:
                        # New battle — stop previous spies if any, launch new ones
                        await self._stop_treasure_spy(sess)
                        await self._stop_opponent_chat_spy(sess)
                        await self._launch_treasure_spy(sess, battle_result)
                        if sess.chat_spy:
                            sess.chat_spy.battle_id = sess.last_battle_id
                        await self._launch_opponent_chat_spy(sess, battle_result, sess.last_battle_id)
                    continue

                # Circuit breaker: skip if in backoff
                if self._is_backed_off(username):
                    remaining = self._backoff_until[username] - time.time()
                    log.debug("Skipping @%s (backed off, %.0fs remaining)", username, remaining)
                    if i < len(users) - 1 and not self._shutdown:
                        await asyncio.sleep(delay_between)
                    continue

                log.info("Checking @%s ...", username)
                try:
                    result = await asyncio.wait_for(asyncio.to_thread(check_is_live, username), timeout=45)
                except asyncio.TimeoutError:
                    log.warning("Timeout: check_is_live for @%s", username)
                    result = None
                except Exception:
                    log.warning("Error checking @%s", username, exc_info=True)
                    result = None

                if result is not None:
                    should_record = user.get("record", True)
                    sess = self._start_session(username, result) if should_record else self._start_monitor_session(username)
                    try:
                        battle_result = await asyncio.wait_for(asyncio.to_thread(self._check_battle_sync, username), timeout=30)
                    except asyncio.TimeoutError:
                        log.warning("Timeout: _check_battle_sync for @%s (new session)", username)
                        battle_result = None
                    if battle_result and battle_result != "__ended__":
                        await self._launch_treasure_spy(sess, battle_result)
                    await self._launch_spy(sess)
                    await self._launch_chat_spy(sess)
                    if battle_result and battle_result != "__ended__" and sess.chat_spy:
                        sess.chat_spy.battle_id = sess.last_battle_id
                        await self._launch_opponent_chat_spy(sess, battle_result, sess.last_battle_id)

                if i < len(users) - 1 and not self._shutdown:
                    await asyncio.sleep(delay_between)

            if not self._shutdown:
                await asyncio.sleep(delay_between)

        heartbeat_task.cancel()
        profile_task.cancel()
        backup_task.cancel()
        try:
            await asyncio.gather(heartbeat_task, profile_task, backup_task, return_exceptions=True)
        except (asyncio.CancelledError, Exception):
            pass

        # Clean up heartbeat file
        try:
            HEARTBEAT_PATH.unlink(missing_ok=True)
        except Exception:
            pass

        await self._shutdown_all()


def main():
    from TikTokLive.client.web.web_settings import WebDefaults

    from lockfile import acquire_lock, release_lock

    lock = acquire_lock(LOCK_PATH, caller="monitor")
    if lock is None:
        sys.exit(1)

    api_key = os.environ.get("SIGN_API_KEY")
    if api_key:
        WebDefaults.tiktok_sign_api_key = api_key
        log.info("EulerStream API key configured")
    else:
        log.warning("SIGN_API_KEY not set — may hit rate limits")

    monitor = Monitor()

    def handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down...", signal.Signals(signum).name)
        monitor._shutdown = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        asyncio.run(monitor.run())
    finally:
        release_lock(lock)


if __name__ == "__main__":
    main()
