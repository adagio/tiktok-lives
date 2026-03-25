"""TreasureSpy — detect envelopes/chests in opponent TikTok lives.

Connects to a TikTok live WebSocket and alerts when an EnvelopeEvent
(chest/envelope/bolsita) is detected. Launched automatically by the monitor
when a battle starts, targeting the opponent's live room.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, DisconnectEvent, EnvelopeEvent, GiftEvent

from battles import save_gifts

log = logging.getLogger("monitor")

# Minimum diamond value to log a gift
GIFT_DIAMOND_THRESHOLD = 50


class TreasureSpy:
    """Watches an opponent's live for envelopes/chests during battles."""

    def __init__(self, username: str, session_id: int | None = None, battle_id: int | None = None, db_path: str | None = None):
        self.username = username
        self.session_id = session_id
        self.battle_id = battle_id
        self.db_path = db_path
        self.client: TikTokLiveClient | None = None
        self._running = False
        self._gift_buffer: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    def _flush(self) -> None:
        """Write buffered gifts to SQLite."""
        if self._gift_buffer and self.db_path:
            batch = self._gift_buffer[:]
            self._gift_buffer.clear()
            try:
                save_gifts(self.db_path, batch)
            except Exception:
                log.warning("TreasureSpy: failed to flush %d gifts for @%s", len(batch), self.username, exc_info=True)

    async def start(self):
        self._running = True
        log.info("💎 Starting TreasureSpy for @%s", self.username)

        self.client = TikTokLiveClient(unique_id=self.username)

        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log.info("💎 TreasureSpy connected to @%s (room=%s)", self.username, self.client.room_id)

        @self.client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            log.info("💎 TreasureSpy disconnected from @%s", self.username)
            self._running = False

        @self.client.on(EnvelopeEvent)
        async def on_envelope(event: EnvelopeEvent):
            info = event.envelope_info
            unpack_dt = ""
            if info.unpack_at:
                try:
                    unpack_dt = datetime.fromtimestamp(info.unpack_at, tz=timezone.utc).strftime("%H:%M:%S UTC")
                except (OSError, ValueError):
                    unpack_dt = str(info.unpack_at)

            log.info(
                "\n"
                "╔══════════════════════════════════════════╗\n"
                "║  COFRE / BOLSITA DETECTADO!              ║\n"
                "╠══════════════════════════════════════════╣\n"
                "║  Room:        @%-26s ║\n"
                "║  Enviado por: %-26s ║\n"
                "║  Diamantes:   %-26s ║\n"
                "║  Personas:    %-26s ║\n"
                "║  Abrir a las: %-26s ║\n"
                "║  Envelope ID: %-26s ║\n"
                "╚══════════════════════════════════════════╝",
                self.username,
                info.send_user_name or "???",
                info.diamond_count,
                info.people_count,
                unpack_dt or "—",
                info.envelope_id or "—",
            )
            if self.session_id is not None:
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            try:
                diamonds = getattr(event, "diamond_count", 0) or 0
                user = getattr(event, "user", None)
                nickname = getattr(user, "nickname", "???") if user else "???"
                gift_obj = getattr(event, "gift", None)
                gift_name = getattr(gift_obj, "name", "gift") if gift_obj else "gift"
                if diamonds >= GIFT_DIAMOND_THRESHOLD:
                    log.info(
                        "💎 GIFT @%s — %s sent %s (%d diamonds)",
                        self.username, nickname, gift_name, diamonds,
                    )
                if self.session_id is not None:
                    user_id = getattr(user, "id", 0) if user else 0
                    username = (getattr(user, "unique_id", None) or nickname) if user else "unknown"
                    self._gift_buffer.append({
                        "session_id": self.session_id,
                        "battle_id": self.battle_id,
                        "room_username": self.username,
                        "user_id": user_id,
                        "username": username,
                        "gift_name": gift_name,
                        "diamond_count": diamonds,
                        "repeat_count": getattr(event, "repeat_count", 1) or 1,
                        "event_type": "gift",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            except Exception:
                pass

        try:
            await asyncio.wait_for(self.client.connect(), timeout=30)
            while self._running:
                await asyncio.sleep(5)
                if self._gift_buffer:
                    await asyncio.to_thread(self._flush)
        except Exception as e:
            log.warning("TreasureSpy for @%s ended: %s", self.username, e)
        finally:
            self._running = False
            self._flush()

    async def stop(self):
        self._running = False
        self._flush()
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
