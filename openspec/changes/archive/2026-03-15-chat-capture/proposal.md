## Why

El chat de TikTok es la fuente más rica de contexto durante un live — reacciones, pedidos, apoyo durante batallas — pero actualmente no se captura. Sin el chat, la página de detalle de batalla (planeada como change separado) no tendría su elemento principal. Además, el chat del host es valioso más allá de batallas: momentos graciosos, interacciones con guests, etc.

## What Changes

- Nueva clase `ChatSpy` que captura `CommentEvent` del WebSocket de TikTokLive y persiste mensajes a SQLite.
- Nueva tabla `chat_messages` en `clips.db` con FK a `sessions` y `battles`.
- Dos modos de operación orquestados por el monitor:
  - **Chat del host**: se lanza con la sesión, muere con la sesión. `battle_id` es NULL salvo cuando hay batalla activa.
  - **Chat del opponent**: se lanza cuando inicia una batalla (como TreasureSpy), muere cuando termina.
- Integración en `monitor.py`: nuevos campos en `ActiveSession`, launch/stop en el ciclo de vida existente.

## Capabilities

### New Capabilities
- `chat-capture`: Captura de mensajes de chat de TikTok lives a SQLite, con soporte para chat de host (permanente) y chat de opponent (durante batallas).

### Modified Capabilities

(ninguna)

## Impact

- **Archivos nuevos**: `apps/recorder/src/chat_spy.py`
- **Archivos modificados**: `apps/recorder/src/monitor.py` (integración), `apps/recorder/src/init_battles_db.py` (nueva tabla)
- **Dependencias**: ninguna nueva — usa `CommentEvent` de TikTokLive 6.6.5 (ya instalado)
- **Volumen de datos**: ~1-3 msgs/seg durante un live activo, ~50 bytes/msg → ~5-15 KB/min. Trivial para SQLite.
- **DB**: `clips.db` — misma base que sessions, battles, guests, chunks, clips.
