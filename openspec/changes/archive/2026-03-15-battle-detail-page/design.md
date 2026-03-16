## Context

El backoffice es una app Astro SSR con Node adapter. Todas las páginas son server-rendered. La única interactividad client-side actual son scripts inline vanilla (theme toggle, sidebar menu, UTC→local dates). No hay framework JS (React/Preact) ni islands.

La página de batalla necesita polling en vivo — un patrón nuevo para el backoffice, pero que encaja bien con un `setInterval` + `fetch` vanilla.

El cambio depende de `chat-capture` (la tabla `chat_messages` debe existir para que haya datos que mostrar).

## Goals / Non-Goals

**Goals:**
- Página de detalle de batalla con toda la información relevante en un solo lugar
- Chat en vivo de ambas salas (host + opponent) con auto-refresh
- Modo "en vivo" (polling) vs modo "replay" (estático) según estado de la batalla
- Consistente con el design system existente del backoffice

**Non-Goals:**
- No se implementa WebSocket/SSE — polling es suficiente
- No se agregan frameworks JS — vanilla scripts inline
- No se implementa paginación de chat — las batallas duran ~5 min, el volumen es manejable
- No se editan/eliminan mensajes de chat

## Decisions

### 1. Estructura de la página

```
┌─────────────────────────────────────────────────────┐
│  ← Volver a sesión    ⚔️ Batalla #123               │
│  @host vs @opponent   Score: 450 — 320  (W)        │
│  14/3/2026 12:58      Duración: 4m 32s    🔴 LIVE  │
├──────────────────────────┬──────────────────────────┤
│  💬 Chat @host           │  💬 Chat @opponent       │
│                          │                          │
│  (mensajes con scroll)   │  (mensajes con scroll)   │
│  auto-scroll al final    │  auto-scroll al final    │
│                          │                          │
├──────────────────────────┴──────────────────────────┤
│  💎 Cofres    │  🎁 Top Gifts    │  🎙️ Guests      │
└───────────────┴──────────────────┴──────────────────┘
```

Layout 2 columnas para chat (50/50). Secciones inferiores en grid de 3.

### 2. Endpoint API para polling

`GET /api/battle/[id]/messages?since=<ISO_TIMESTAMP>`

Retorna JSON:
```json
{
  "messages": [
    {
      "id": 123,
      "room_username": "opponent_123",
      "username": "fan1",
      "text": "vamos!!",
      "timestamp": "2026-03-14T15:58:20"
    }
  ],
  "battle": {
    "host_score": 450,
    "opponent_score": 320,
    "is_active": true
  }
}
```

El endpoint es Astro server endpoint (`.ts` file en `pages/api/`). Hace query a SQLite con `timestamp > ?since` y también retorna scores actualizados.

**Alternativa descartada**: Recargar la página completa — desperdicia ancho de banda y pierde scroll position.

### 3. Polling client-side

```javascript
// En la página de batalla
const POLL_INTERVAL = 3000; // 3 segundos
let lastTimestamp = initialLastTimestamp; // del SSR

setInterval(async () => {
  const res = await fetch(`/api/battle/${battleId}/messages?since=${lastTimestamp}`);
  const data = await res.json();

  // Append mensajes a los paneles
  // Actualizar scores
  // Si !data.battle.is_active → parar polling
}, POLL_INTERVAL);
```

Auto-scroll: cada panel tiene `overflow-y: auto`, y después de append se hace `scrollTop = scrollHeight`. Solo si el usuario no ha scrolleado manualmente hacia arriba.

### 4. Detección de batalla activa

La batalla se considera "activa" si el monitor todavía tiene un `last_battle_id` que coincide. Desde el endpoint, verificamos si hay mensajes recientes (< 30 seg) — si no los hay, la batalla probablemente terminó.

Approach más simple: el endpoint retorna `is_active: false` cuando la batalla ya no tiene datos frescos. El client deja de hacer polling.

### 5. Link desde sesión

En `/sesiones/[id]`, cada batalla en la lista se convierte en un link a `/batallas/[battle_db_id]` (el `id` de la tabla battles, no el `battle_id` de TikTok).

## Risks / Trade-offs

- **[Polling overhead]** 1 request/3s por tab abierta → Mitigación: es un query SQLite simple con índice, < 1ms. Solo se hace polling si la batalla está activa.
- **[Scroll behavior]** Auto-scroll puede ser molesto si el usuario quiere leer un mensaje anterior → Mitigación: detectar si el usuario scrolleó manualmente (offset del bottom) y pausar auto-scroll.
- **[Sin datos de cofres/gifts en DB]** TreasureSpy solo loggea a archivo, no persiste a SQLite → Mitigación: las secciones de cofres/gifts quedan vacías por ahora, o se planean como un tercer change. El chat es la pieza principal.
