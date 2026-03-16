"""VentanillaSpy — detect link mic guests via TikTok WebSocket.

Reusable component: connect to a live room and track guest join/leave
via LinkMicFanTicketMethodEvent. Persists to clips.db via battles module.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, LinkMicFanTicketMethodEvent

from battles import resolve_user_id, save_guest, update_guest_left

log = logging.getLogger("monitor")


class VentanillaSpy:
    """Watches a single user's live for link mic guests."""

    def __init__(
        self,
        username: str,
        session_id: int,
        host_user_id: int,
        db_path: str,
    ):
        self.username = username
        self.session_id = session_id
        self.host_user_id = host_user_id
        self.db_path = db_path
        self.client: TikTokLiveClient | None = None
        self.current_guests: set[int] = set()
        self._running = False
        self._resolved: dict[int, str] = {}  # local cache

    @property
    def is_running(self) -> bool:
        return self._running

    def _resolve(self, user_id: int) -> str:
        if user_id not in self._resolved:
            try:
                self._resolved[user_id] = resolve_user_id(user_id)
            except Exception:
                self._resolved[user_id] = f"id:{user_id}"
        return self._resolved[user_id]

    async def start(self):
        self._running = True
        log.info(
            "🔌 Starting spy for @%s (host_uid=%s, session=%s)",
            self.username, self.host_user_id, self.session_id,
        )

        self.client = TikTokLiveClient(unique_id=self.username)

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log.info("🔌 Spy connected to @%s (room=%s)", self.username, self.client.room_id)

        @self.client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            log.info("🔌 Spy disconnected from @%s", self.username)
            self._running = False

        @self.client.on(LinkMicFanTicketMethodEvent)
        async def on_fanticket(event: LinkMicFanTicketMethodEvent):
            await self._handle_fanticket(event)

        try:
            await self.client.connect()
            while self._running:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning("Spy for @%s ended: %s", self.username, e)
        finally:
            self._running = False
            self._mark_all_left()

    async def _handle_fanticket(self, event: LinkMicFanTicketMethodEvent):
        try:
            data = event.to_dict()
        except Exception:
            return

        fan_ticket_notice = data.get("fanTicketRoomNotice", {})
        user_tickets = fan_ticket_notice.get("userFanTicket", [])
        if not user_tickets:
            return

        all_uids = set()
        for entry in user_tickets:
            uid_str = entry.get("userId")
            if uid_str:
                all_uids.add(int(uid_str))

        guest_uids = all_uids - {self.host_user_id}
        now_iso = datetime.now(timezone.utc).isoformat()

        # New guests
        for uid in guest_uids - self.current_guests:
            uname = await asyncio.to_thread(self._resolve, uid)
            log.info("🎙️  @%s joined ventanilla of @%s", uname, self.username)
            try:
                save_guest(self.db_path, self.session_id, uid, uname, now_iso)
            except Exception:
                log.warning("Failed to save guest @%s", uname, exc_info=True)

        # Departed guests
        for uid in self.current_guests - guest_uids:
            uname = self._resolved.get(uid, str(uid))
            log.info("🎙️  user %s left ventanilla of @%s", uname, self.username)
            try:
                update_guest_left(self.db_path, self.session_id, uid, now_iso)
            except Exception:
                log.warning("Failed to update guest left for %s", uid, exc_info=True)

        self.current_guests = guest_uids

    def _mark_all_left(self):
        if not self.current_guests:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        for uid in self.current_guests:
            try:
                update_guest_left(self.db_path, self.session_id, uid, now_iso)
            except Exception:
                pass
        self.current_guests.clear()

    async def stop(self):
        self._running = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
