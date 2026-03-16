## 1. Queries y DB layer

- [x] 1.1 Agregar `getBattle(id)`, `getBattleChatMessages(battleId, since?)`, `isBattleActive(battleId)` en `db.ts`
- [x] 1.2 Agregar tipos `ChatMessageRow` en `db.ts`

## 2. Endpoint API

- [x] 2.1 Crear `pages/api/battle/[id]/messages.ts` — endpoint GET que retorna mensajes filtrados por `since` + scores + `is_active`

## 3. Página de detalle

- [x] 3.1 Crear `pages/batallas/[id].astro` — layout con header (host vs opponent, scores, hora, indicador live), dos paneles de chat, sección de guests
- [x] 3.2 Script inline de polling — fetch cada 3s, append mensajes a paneles, actualizar scores, auto-scroll inteligente, parar cuando `is_active: false`

## 4. Integración

- [x] 4.1 En `pages/sesiones/[id].astro` — hacer que cada batalla sea un link a `/batallas/[id]`
- [x] 4.2 Usar `<LocalTime>` en todos los timestamps de la página de batalla
