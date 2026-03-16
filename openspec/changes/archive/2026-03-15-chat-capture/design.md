## Context

El monitor ya orquesta tres tipos de "spies" sobre WebSocket de TikTok:
- `VentanillaSpy` — detecta guests (link mic), persiste a SQLite, vive con la sesión
- `TreasureSpy` — detecta cofres/gifts del opponent, solo logging, vive con la batalla

Cada spy sigue el mismo patrón: clase con `start()`/`stop()`, lanzada como `asyncio.Task` desde el monitor, usando `TikTokLiveClient` de la librería TikTokLive 6.6.5.

El chat necesita dos instancias simultáneas: una permanente (host) y una efímera (opponent durante batalla).

## Goals / Non-Goals

**Goals:**
- Capturar todos los mensajes de chat del host durante el live completo
- Capturar mensajes de chat del opponent durante batallas
- Persistir a SQLite con FK a sessions y battles
- Asociar mensajes del host al `battle_id` correcto cuando hay batalla activa

**Non-Goals:**
- No se construye UI en este change (eso es `battle-detail-page`)
- No se filtran ni moderan mensajes — se graba todo
- No se capturan otros eventos (gifts, likes, shares) — esos ya los manejan otros spies
- No se deduplican mensajes entre salas (un usuario puede comentar en ambas)

## Decisions

### 1. Clase `ChatSpy` — una sola clase, dos modos de uso

Una sola clase `ChatSpy` que recibe `username`, `session_id`, y `db_path`. El `battle_id` se setea externamente via propiedad mutable para que el chat del host pueda cambiar de batalla sin reiniciar el spy.

```
ChatSpy del host:
  - battle_id = None al inicio
  - Monitor setea battle_id cuando detecta batalla
  - Monitor resetea battle_id = None cuando termina

ChatSpy del opponent:
  - battle_id = X desde el inicio (fijo)
  - Se cancela cuando termina la batalla
```

**Alternativa descartada**: Dos clases separadas `HostChatSpy` y `OpponentChatSpy`. Comparten 95% del código — la única diferencia es el lifecycle del `battle_id`.

### 2. Tabla `chat_messages` en `clips.db`

```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    battle_id INTEGER REFERENCES battles(battle_id),
    room_username TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    text TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_chat_session ON chat_messages(session_id);
CREATE INDEX idx_chat_battle ON chat_messages(battle_id);
CREATE INDEX idx_chat_timestamp ON chat_messages(timestamp);
```

- `room_username`: de quién es la sala (permite filtrar host vs opponent)
- `battle_id`: nullable — NULL cuando no hay batalla activa
- `timestamp`: ISO 8601 UTC (consistente con el resto del schema)

**Alternativa descartada**: MongoDB — overkill, nuevo stack, no se joinea con el resto.
**Alternativa descartada**: Archivos JSONL — no queryable, no joineable, patrón distinto al resto.

### 3. Escritura batch con buffer

Los mensajes de chat pueden llegar a 1-3/seg. En vez de un INSERT por mensaje, acumular en un buffer y flush cada ~2 segundos o cuando el buffer llegue a N mensajes. Esto reduce la carga de I/O en SQLite.

```python
self._buffer: list[dict] = []
FLUSH_INTERVAL = 2.0  # seconds
FLUSH_SIZE = 20       # messages
```

Un `asyncio.Task` interno hace el flush periódico. En `stop()`, flush final.

### 4. Integración en monitor.py

**ActiveSession** — nuevos campos:
```python
chat_spy: ChatSpy | None = None
chat_task: asyncio.Task | None = None
opponent_chat_spy: ChatSpy | None = None
opponent_chat_task: asyncio.Task | None = None
```

**Lifecycle:**
- `_launch_chat_spy(sess)` — se llama junto con `_launch_spy()` al iniciar sesión
- Cuando inicia batalla: `sess.chat_spy.battle_id = battle_id` + lanzar `opponent_chat_spy`
- Cuando termina batalla: `sess.chat_spy.battle_id = None` + cancelar `opponent_chat_spy`
- Shutdown: cancelar ambos chat tasks

### 5. Evento `CommentEvent` de TikTokLive

El `CommentEvent` expone:
- `event.user.unique_id` — username del autor
- `event.user.user_id` — ID numérico
- `event.comment` — texto del mensaje

Se registra con `@client.on(CommentEvent)`.

## Risks / Trade-offs

- **[SQLite write contention]** Con VentanillaSpy, TreasureSpy, y dos ChatSpies escribiendo a la misma DB → Mitigación: WAL mode + buffer batch reduce contención. Volumen total es bajo (~5 writes/seg max).
- **[CommentEvent no documentado]** La API exacta de `CommentEvent` en TikTokLive 6.6.5 puede variar → Mitigación: verificar los campos disponibles al implementar, loggear el evento raw si hay dudas.
- **[Chat spam]** Lives populares pueden tener ráfagas de muchos mensajes → Mitigación: el buffer batch maneja esto. No filtramos — todo se graba. SQLite maneja el volumen sin problemas.
- **[battle_id mutable]** Setear `battle_id` desde fuera del spy introduce shared state → Mitigación: es un solo int/None, seteado desde un solo lugar (el monitor loop), sin race conditions reales porque el event loop es single-threaded.
