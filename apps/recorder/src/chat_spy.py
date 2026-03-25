"""ChatSpy — capture chat messages from TikTok lives to SQLite.

Connects to a TikTok live WebSocket and persists CommentEvent messages.
Used in two modes:
  - Host chat: runs for the entire session, battle_id set externally
  - Opponent chat: runs during a battle, battle_id fixed at init
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent, EnvelopeEvent, GiftEvent, JoinEvent

from battles import save_chat_messages, save_gifts, save_viewer_joins

log = logging.getLogger("monitor")

FLUSH_INTERVAL = 2.0  # seconds
FLUSH_SIZE = 20  # messages


class ChatSpy:
    """Captures chat messages from a TikTok live room."""

    @staticmethod
    def _server_timestamp(event) -> str:
        """Extract server timestamp from event, fallback to now()."""
        try:
            ts = event.base_message.create_time
            if ts > 0:
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (AttributeError, OSError):
            pass
        return datetime.now(timezone.utc).isoformat()

    def __init__(
        self,
        username: str,
        session_id: int,
        db_path: str,
        battle_id: int | None = None,
    ):
        self.username = username
        self.session_id = session_id
        self.db_path = db_path
        self.battle_id = battle_id
        self.client: TikTokLiveClient | None = None
        self._running = False
        self._buffer: list[dict] = []
        self._join_buffer: list[dict] = []
        self._gift_buffer: list[dict] = []
        self._flush_task: asyncio.Task | None = None
        self._liveness_task: asyncio.Task | None = None
        self._last_event_at: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    def _flush(self) -> None:
        """Write buffered messages and joins to SQLite."""
        if self._buffer:
            batch = self._buffer[:]
            self._buffer.clear()
            try:
                save_chat_messages(self.db_path, batch)
            except Exception:
                log.warning("ChatSpy: failed to flush %d messages for @%s", len(batch), self.username, exc_info=True)
        if self._join_buffer:
            joins = self._join_buffer[:]
            self._join_buffer.clear()
            try:
                save_viewer_joins(self.db_path, joins)
            except Exception:
                log.warning("ChatSpy: failed to flush %d joins for @%s", len(joins), self.username, exc_info=True)
        if self._gift_buffer:
            gifts = self._gift_buffer[:]
            self._gift_buffer.clear()
            try:
                save_gifts(self.db_path, gifts)
            except Exception:
                log.warning("ChatSpy: failed to flush %d gifts for @%s", len(gifts), self.username, exc_info=True)

    async def _periodic_flush(self) -> None:
        """Flush buffer periodically."""
        try:
            while self._running:
                await asyncio.sleep(FLUSH_INTERVAL)
                if self._buffer or self._join_buffer or self._gift_buffer:
                    await asyncio.to_thread(self._flush)
        except asyncio.CancelledError:
            pass

    async def _liveness_check(self) -> None:
        """Kill connection if no events received for 300s."""
        try:
            while self._running:
                await asyncio.sleep(10)
                if self._last_event_at and (time.monotonic() - self._last_event_at) > 300:
                    log.warning("💬 ChatSpy for @%s: no events in 300s, assuming dead connection", self.username)
                    self._running = False
                    if self.client:
                        await self.client.disconnect()
                    return
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        self._running = True
        log.info("💬 Starting ChatSpy for @%s (session=%s)", self.username, self.session_id)

        self.client = TikTokLiveClient(unique_id=self.username)

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            self._last_event_at = time.monotonic()
            log.info("💬 ChatSpy connected to @%s (room=%s)", self.username, self.client.room_id)

        @self.client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent) -> None:
            log.info("💬 ChatSpy disconnected from @%s", self.username)
            self._running = False

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent) -> None:
            self._last_event_at = time.monotonic()
            try:
                user = event.user
                msg = {
                    "session_id": self.session_id,
                    "battle_id": self.battle_id,
                    "room_username": self.username,
                    "user_id": user.id,
                    "username": user.unique_id or user.nickname or f"id:{user.id}",
                    "text": event.comment,
                    "timestamp": self._server_timestamp(event),
                }
                self._buffer.append(msg)
                if len(self._buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        @self.client.on(JoinEvent)
        async def on_join(event: JoinEvent) -> None:
            self._last_event_at = time.monotonic()
            try:
                user = event.user
                self._join_buffer.append({
                    "session_id": self.session_id,
                    "room_username": self.username,
                    "user_id": user.id,
                    "username": user.unique_id or user.nickname or f"id:{user.id}",
                    "joined_at": self._server_timestamp(event),
                })
                if len(self._join_buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent) -> None:
            self._last_event_at = time.monotonic()
            try:
                user = event.user
                gift = getattr(event, "gift", None)
                self._gift_buffer.append({
                    "session_id": self.session_id,
                    "battle_id": self.battle_id,
                    "room_username": self.username,
                    "user_id": user.id,
                    "username": user.unique_id or user.nickname or f"id:{user.id}",
                    "gift_name": getattr(gift, "name", None) if gift else None,
                    "diamond_count": getattr(event, "diamond_count", 0) or 0,
                    "repeat_count": getattr(event, "repeat_count", 1) or 1,
                    "event_type": "gift",
                    "timestamp": self._server_timestamp(event),
                })
                if len(self._gift_buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        @self.client.on(EnvelopeEvent)
        async def on_envelope(event: EnvelopeEvent) -> None:
            self._last_event_at = time.monotonic()
            try:
                info = event.envelope_info
                self._gift_buffer.append({
                    "session_id": self.session_id,
                    "battle_id": self.battle_id,
                    "room_username": self.username,
                    "user_id": 0,
                    "username": info.send_user_name or "unknown",
                    "gift_name": "envelope",
                    "diamond_count": info.diamond_count or 0,
                    "repeat_count": 1,
                    "event_type": "envelope",
                    "timestamp": self._server_timestamp(event),
                })
                if len(self._gift_buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        self._flush_task = asyncio.create_task(self._periodic_flush())
        self._liveness_task = asyncio.create_task(self._liveness_check())

        try:
            await self.client.connect()
        except Exception as e:
            log.warning("ChatSpy for @%s ended: %s", self.username, e)
        finally:
            self._running = False
            for task in (self._flush_task, self._liveness_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            # Final flush
            if self._buffer or self._gift_buffer:
                self._flush()

    async def stop(self) -> None:
        self._running = False
        for task in (self._flush_task, self._liveness_task):
            if task and not task.done():
                task.cancel()
        # Flush remaining
        if self._buffer or self._gift_buffer:
            self._flush()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
