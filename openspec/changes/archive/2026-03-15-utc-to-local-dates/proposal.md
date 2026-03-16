## Why

Todas las fechas en app-backoffice se muestran en UTC tal como están almacenadas en SQLite. Los autores monitoreados están en distintos timezones (Argentina, Perú, Colombia, México, República Dominicana, Bolivia, Ecuador), y el usuario que consulta el backoffice también puede estar en cualquiera de esos husos. Mostrar `15:58hs` cuando la sesión ocurrió a las `12:58` hora local es confuso y puede llevar a errores al correlacionar eventos.

## What Changes

- Crear un script client-side que convierta todas las fechas UTC al timezone del browser del usuario.
- Las fechas se renderizan en el server (Astro SSR) dentro de elementos `<time data-utc="...">` con el valor UTC como fallback visible.
- El script corre en el browser, busca todos los `[data-utc]`, parsea con suffix `Z`, y reemplaza el texto con la hora formateada según `Intl.DateTimeFormat` del browser.
- Los formatos de salida varían según contexto: solo fecha, solo hora, o fecha+hora.

## Capabilities

### New Capabilities
- `local-dates`: Conversión client-side de fechas UTC a timezone local del browser, aplicada a todos los componentes de app-backoffice que muestran timestamps.

### Modified Capabilities

(ninguna — no hay specs existentes)

## Impact

- **Archivos afectados**: todos los componentes y páginas de app-backoffice que renderizan fechas:
  - `pages/sesiones/index.astro` — columna Fecha en tabla de sesiones
  - `pages/sesiones/[id].astro` — header (fecha+hora), batallas (hora), guests (hora)
  - `components/ClipsTable.astro` — columna fecha de clips
  - `pages/topics.astro` — fecha en highlights de topics
  - `components/TopicHeatmap.astro` — fechas en headers del heatmap
- **Dependencias**: ninguna nueva — usa APIs nativas del browser (`Intl.DateTimeFormat`, `Date`).
- **No hay breaking changes** — el fallback sigue siendo el UTC legible que se muestra hoy.
