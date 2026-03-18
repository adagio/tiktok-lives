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

log = logging.getLogger("monitor")

# Minimum diamond value to log a gift
GIFT_DIAMOND_THRESHOLD = 50


class TreasureSpy:
    """Watches an opponent's live for envelopes/chests during battles."""

    def __init__(self, username: str):
        self.username = username
        self.client: TikTokLiveClient | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

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

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            try:
                diamonds = getattr(event, "diamond_count", 0) or 0
                if diamonds < GIFT_DIAMOND_THRESHOLD:
                    return
                user = getattr(event, "user", None)
                nickname = getattr(user, "nickname", "???") if user else "???"
                gift_name = getattr(event, "gift", None)
                gift_name = getattr(gift_name, "name", "gift") if gift_name else "gift"
                log.info(
                    "💎 GIFT @%s — %s sent %s (%d diamonds)",
                    self.username, nickname, gift_name, diamonds,
                )
            except Exception:
                pass

        try:
            await asyncio.wait_for(self.client.connect(), timeout=30)
            while self._running:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning("TreasureSpy for @%s ended: %s", self.username, e)
        finally:
            self._running = False

    async def stop(self):
        self._running = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
