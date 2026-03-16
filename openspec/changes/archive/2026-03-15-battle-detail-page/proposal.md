## Why

Las batallas son el momento más intenso de un live de TikTok — scores cambiando, chat explotando, cofres apareciendo, guests entrando. Actualmente solo vemos una línea en la lista de batallas de la sesión (opponent, score, hora). Una página de detalle de batalla permitiría monitorear en vivo lo que pasa en ambas salas, y después revisar el replay completo con todo el contexto.

## What Changes

- Nueva página `/batallas/[id]` en app-backoffice con vista detallada de una batalla.
- Dos paneles de chat side-by-side (host + opponent) con auto-scroll.
- Auto-refresh via polling cada ~3s mientras la batalla está activa (scores + mensajes nuevos).
- Endpoint API `/api/battle/[id]/messages` para servir mensajes de chat con filtro `since`.
- Secciones adicionales: scores en vivo, cofres/gifts detectados, guests durante la batalla.
- Link desde la lista de batallas en `/sesiones/[id]` hacia la nueva página.

## Capabilities

### New Capabilities
- `battle-detail`: Página de detalle de batalla con chat en vivo, scores, y contexto completo de ambas salas.

### Modified Capabilities

(ninguna)

## Impact

- **Archivos nuevos**:
  - `apps/app-backoffice/src/pages/batallas/[id].astro` — página de detalle
  - `apps/app-backoffice/src/pages/api/battle/[id]/messages.ts` — endpoint API para polling
- **Archivos modificados**:
  - `apps/app-backoffice/src/lib/db.ts` — nuevas queries para chat messages y battle detail
  - `apps/app-backoffice/src/pages/sesiones/[id].astro` — link a batalla desde lista
  - `apps/app-backoffice/src/components/Sidebar.astro` — nuevo item de navegación (si aplica)
- **Dependencias**: ninguna nueva — usa Astro SSR, fetch API nativa del browser.
- **Prerequisito**: change `chat-capture` debe implementarse primero (la tabla `chat_messages` debe existir).
