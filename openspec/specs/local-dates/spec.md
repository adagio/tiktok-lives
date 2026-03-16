## Requirements

### Requirement: Fechas se muestran en timezone local del browser

Todas las fechas visibles en app-backoffice que provienen de la base de datos (almacenadas en UTC) SHALL ser convertidas al timezone local del browser del usuario.

#### Scenario: Sesión grabada en UTC se muestra en hora local
- **WHEN** una sesión tiene `date = "2026-03-14T15:58:20"` en la DB y el browser está en UTC-3
- **THEN** el header de la sesión muestra `14/3/2026 12:58` (o equivalente según locale del browser)

#### Scenario: Hora de batalla se muestra en hora local
- **WHEN** una batalla tiene `detected_at = "2026-03-14T20:30:00"` y el browser está en UTC-5
- **THEN** la hora mostrada es `15:30` (o equivalente según locale)

#### Scenario: Fecha en tabla de sesiones se muestra en fecha local
- **WHEN** una sesión tiene `date = "2026-03-15T02:30:00"` y el browser está en UTC-3
- **THEN** la fecha mostrada en la tabla es `14/3/2026` (día anterior por el offset)

### Requirement: Fallback legible cuando JS no está disponible

El contenido inicial renderizado por el server SHALL ser una representación legible de la fecha UTC, de modo que si JavaScript no ejecuta, el usuario aún ve información útil.

#### Scenario: JavaScript deshabilitado
- **WHEN** el browser no ejecuta JavaScript
- **THEN** las fechas se muestran en formato UTC legible (ej: `2026-03-14 15:58`)

### Requirement: Tres formatos de fecha según contexto

El sistema SHALL soportar tres formatos de salida controlados por un atributo `data-fmt`:

- `date`: solo fecha (para tablas, heatmaps)
- `time`: solo hora (para batallas, guests)
- `datetime`: fecha y hora (para headers de sesión)

#### Scenario: Formato date
- **WHEN** un elemento tiene `data-fmt="date"` y `data-utc="2026-03-14T15:58:20"` con browser en UTC-3
- **THEN** el texto se reemplaza con solo la fecha local (ej: `14/3/2026`)

#### Scenario: Formato time
- **WHEN** un elemento tiene `data-fmt="time"` y `data-utc="2026-03-14T15:58:20"` con browser en UTC-3
- **THEN** el texto se reemplaza con solo la hora local (ej: `12:58`)

#### Scenario: Formato datetime
- **WHEN** un elemento tiene `data-fmt="datetime"` y `data-utc="2026-03-14T15:58:20"` con browser en UTC-3
- **THEN** el texto se reemplaza con fecha y hora local (ej: `14/3/2026 12:58`)

### Requirement: Componente centralizado para generar time tags

SHALL existir un componente Astro reutilizable que encapsule la generación del elemento `<time>` con los atributos `data-utc` y `data-fmt`, evitando repetir el patrón manualmente en cada página.

#### Scenario: Uso del componente en una página
- **WHEN** un developer usa `<LocalTime utc={session.date} fmt="datetime" />` en un archivo Astro
- **THEN** se renderiza un `<time data-utc="..." data-fmt="datetime">` con fallback UTC legible

### Requirement: Script global en Layout

El script de conversión SHALL estar incluido en el Layout compartido para que aplique automáticamente en todas las páginas sin necesidad de importarlo individualmente.

#### Scenario: Página nueva con fechas
- **WHEN** se crea una nueva página que usa el componente `<LocalTime>`
- **THEN** las fechas se convierten automáticamente sin añadir scripts adicionales
