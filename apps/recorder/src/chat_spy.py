"""ChatSpy — capture chat messages from TikTok lives to SQLite.

Connects to a TikTok live WebSocket and persists CommentEvent messages.
Used in two modes:
  - Host chat: runs for the entire session, battle_id set externally
  - Opponent chat: runs during a battle, battle_id fixed at init
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent, JoinEvent

from battles import save_chat_messages, save_viewer_joins

log = logging.getLogger("monitor")

FLUSH_INTERVAL = 2.0  # seconds
FLUSH_SIZE = 20  # messages


class ChatSpy:
    """Captures chat messages from a TikTok live room."""

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
        self._flush_task: asyncio.Task | None = None

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

    async def _periodic_flush(self) -> None:
        """Flush buffer periodically."""
        try:
            while self._running:
                await asyncio.sleep(FLUSH_INTERVAL)
                if self._buffer or self._join_buffer:
                    await asyncio.to_thread(self._flush)
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        self._running = True
        log.info("💬 Starting ChatSpy for @%s (session=%s)", self.username, self.session_id)

        self.client = TikTokLiveClient(unique_id=self.username)

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            log.info("💬 ChatSpy connected to @%s (room=%s)", self.username, self.client.room_id)

        @self.client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent) -> None:
            log.info("💬 ChatSpy disconnected from @%s", self.username)
            self._running = False

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent) -> None:
            try:
                user = event.user
                msg = {
                    "session_id": self.session_id,
                    "battle_id": self.battle_id,
                    "room_username": self.username,
                    "user_id": user.id,
                    "username": user.unique_id or user.nickname or f"id:{user.id}",
                    "text": event.comment,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._buffer.append(msg)
                if len(self._buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        @self.client.on(JoinEvent)
        async def on_join(event: JoinEvent) -> None:
            try:
                user = event.user
                self._join_buffer.append({
                    "session_id": self.session_id,
                    "room_username": self.username,
                    "user_id": user.id,
                    "username": user.unique_id or user.nickname or f"id:{user.id}",
                    "joined_at": datetime.now(timezone.utc).isoformat(),
                })
                if len(self._join_buffer) >= FLUSH_SIZE:
                    await asyncio.to_thread(self._flush)
            except Exception:
                pass

        self._flush_task = asyncio.create_task(self._periodic_flush())

        try:
            await self.client.connect()
            while self._running:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning("ChatSpy for @%s ended: %s", self.username, e)
        finally:
            self._running = False
            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()
                try:
                    await self._flush_task
                except asyncio.CancelledError:
                    pass
            # Final flush
            if self._buffer:
                self._flush()

    async def stop(self) -> None:
        self._running = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        # Flush remaining
        if self._buffer:
            self._flush()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
