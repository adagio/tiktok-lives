## Context

Las fechas en SQLite se almacenan como strings ISO 8601 sin timezone (`2026-03-14T15:58:20`) pero generadas en UTC. Astro renderiza server-side (SSR), donde no existe el concepto de timezone del usuario. El browser sí conoce su timezone local.

Los autores monitoreados están en múltiples países latinoamericanos (ARG, PER, COL, MEX, DOM, BOL, ECU), así que no se puede asumir un timezone fijo.

## Goals / Non-Goals

**Goals:**
- Mostrar todas las fechas/horas en el timezone local del browser
- Fallback graceful: si JS no corre, el UTC sigue siendo legible
- Solución centralizada: un solo script + un helper para generar los `<time>` tags

**Non-Goals:**
- No se cambia el formato de almacenamiento en SQLite (sigue siendo UTC sin suffix)
- No se añade selector de timezone manual
- No se usa ninguna librería externa (date-fns, luxon, etc.)

## Decisions

### 1. Patrón `<time data-utc>` + script global

Cada fecha se renderiza dentro de un `<time>` con atributos data:

```html
<time data-utc="2026-03-14T15:58:20" data-fmt="datetime">
  2026-03-14 15:58
</time>
```

Un script global (en el Layout) busca todos los `[data-utc]` y reemplaza el `textContent` con la fecha formateada al locale del browser.

**Alternativa descartada**: Componente Astro con `client:load` (React/Preact island). Overkill para algo que es puro DOM manipulation. Un `<script>` vanilla es más ligero y no añade framework JS.

### 2. Formatos via `data-fmt`

Tres formatos según el contexto:

| `data-fmt` | Uso | Output ejemplo (ARG) |
|---|---|---|
| `date` | Tabla de sesiones, heatmap | `14/3/2026` |
| `time` | Hora de batallas, guests | `12:58` |
| `datetime` | Header de sesión detalle | `14/3/2026 12:58` |

Se usa `Intl.DateTimeFormat` del browser — respeta el locale del sistema sin hardcodear formato.

**Alternativa descartada**: `toLocaleString()` directo. `Intl.DateTimeFormat` permite cachear el formatter y es más explícito en las opciones.

### 3. Script placement y timing

El script va en el `<Layout>` compartido, al final del `<body>`. Se ejecuta sincrónicamente (no `type="module"`, no `defer`). Como está al final del body, el DOM ya está parseado — no necesita `DOMContentLoaded`.

Sin flash perceptible porque:
- El script corre antes del primer paint (está inline en el HTML)
- La operación es O(n) sobre ~20-50 elementos máximo

### 4. Helper Astro para generar `<time>` tags

Un componente funcional `<LocalTime>` o un helper function que encapsule:

```astro
<!-- Uso -->
<LocalTime utc={session.date} fmt="datetime" fallback="2026-03-14 15:58" />

<!-- Output HTML -->
<time data-utc="2026-03-14T15:58:20" data-fmt="datetime">2026-03-14 15:58</time>
```

Esto centraliza la lógica de generar el `<time>` tag y el fallback, evitando repetir el patrón en cada archivo.

## Risks / Trade-offs

- **[Flash of UTC]** Si el script falla o JS está deshabilitado, el usuario ve UTC crudo → Mitigación: es el comportamiento actual, no es una regresión. El fallback es legible.
- **[Locale inconsistency]** `Intl.DateTimeFormat` puede formatear diferente entre browsers → Mitigación: aceptable para herramienta personal. Los campos principales (día, hora) son consistentes.
- **[Heatmap dates]** El `TopicHeatmap` usa fechas como keys de agrupación. Si se convierte a local, una sesión cerca de medianoche UTC podría caer en otro día → Mitigación: el heatmap agrupa por fecha de la DB (server-side), solo el label visual se convierte. La agrupación no cambia.
