## 1. Script global de conversión

- [x] 1.1 Crear script inline en el Layout que busque `[data-utc]`, parsee con suffix `Z`, y reemplace `textContent` usando `Intl.DateTimeFormat` con los tres formatos (`date`, `time`, `datetime`)

## 2. Componente LocalTime

- [x] 2.1 Crear componente `LocalTime.astro` que reciba `utc`, `fmt`, y opcionalmente `class`, y renderice `<time data-utc data-fmt>` con fallback UTC legible

## 3. Migrar páginas y componentes

- [x] 3.1 `pages/sesiones/index.astro` — reemplazar columna Fecha con `<LocalTime fmt="date">`
- [x] 3.2 `pages/sesiones/[id].astro` — header (fecha+hora) con `<LocalTime fmt="datetime">`
- [x] 3.3 `pages/sesiones/[id].astro` — hora de batallas con `<LocalTime fmt="time">`
- [x] 3.4 `pages/sesiones/[id].astro` — hora de guests con `<LocalTime fmt="time">`
- [x] 3.5 `components/ClipsTable.astro` — columna fecha con `<LocalTime fmt="date">`
- [x] 3.6 `pages/topics.astro` — fecha en highlights con `<LocalTime fmt="date">`
- [x] 3.7 `components/TopicHeatmap.astro` — labels de fecha con `<LocalTime fmt="date">`
