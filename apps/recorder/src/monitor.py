"""TikTok Live Monitor — async orchestrator for recording, battles, and ventanilla."""

from __future__ import annotations

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
    close_orphaned_sessions,
    create_session,
    get_battle_info,
    get_host_user_id,
    get_room_id,
    resolve_user_id,
    save_battle,
    update_battle_scores,
    update_session_duration,
)
from chat_spy import ChatSpy
from recording import AdoptedProcess, check_is_live, start_recording
from treasure_spy import TreasureSpy
from ventanilla_spy import VentanillaSpy

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"
LOG_PATH = Path(__file__).resolve().parent.parent / "monitor.log"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = str(REPO_ROOT / "clips.db")

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
    process: Popen
    path: Path
    started_at: float
    session_id: int | None = None
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


class Monitor:
    def __init__(self):
        self.active: dict[str, ActiveSession] = {}
        self.resolved_users: dict[int, str] = {}
        self._shutdown = False

    def _resolve(self, user_id: int) -> str:
        if user_id not in self.resolved_users:
            try:
                self.resolved_users[user_id] = resolve_user_id(user_id)
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

    def _reap_finished(self):
        """Remove entries for ffmpeg processes that have exited."""
        finished = []
        for username, sess in self.active.items():
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
            session_id = create_session(DB_PATH, username, date_iso, str(path), pid=proc.pid)
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

    async def _launch_spy(self, sess: ActiveSession):
        """Launch VentanillaSpy for a session (if possible)."""
        if sess.session_id is None:
            return
        host_uid = await asyncio.to_thread(get_host_user_id, sess.username)
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
        spy = TreasureSpy(opponent_username)
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
            log.info("Terminating recording for @%s", username)
            sess.process.terminate()
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

        # Wait for ffmpeg processes
        for username, sess in self.active.items():
            try:
                sess.process.wait(timeout=10)
            except Exception:
                sess.process.kill()

            # Update duration
            elapsed = time.time() - sess.started_at
            if sess.session_id is not None:
                try:
                    update_session_duration(DB_PATH, sess.session_id, elapsed)
                except Exception:
                    pass

        self.active.clear()
        log.info("Monitor stopped.")

    async def run(self):
        # Close orphaned sessions / re-attach alive ffmpeg from previous runs
        try:
            closed, alive = close_orphaned_sessions(DB_PATH)
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
                    battle_result = await asyncio.to_thread(self._check_battle_sync, username)
                    sess = self.active[username]
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

                log.info("Checking @%s ...", username)
                try:
                    result = await asyncio.to_thread(check_is_live, username)
                except Exception:
                    log.warning("Error checking @%s", username, exc_info=True)
                    result = None

                if result is not None:
                    sess = self._start_session(username, result)
                    battle_result = await asyncio.to_thread(self._check_battle_sync, username)
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

        await self._shutdown_all()


def main():
    from TikTokLive.client.web.web_settings import WebDefaults

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

    asyncio.run(monitor.run())


if __name__ == "__main__":
    main()
