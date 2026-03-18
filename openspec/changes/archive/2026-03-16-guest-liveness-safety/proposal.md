## Why

Con el fix de guests activos como señal de liveness (`is_live = chatActive OR activeGuests > 0`), un guest con `left_at IS NULL` mantiene al usuario como "en vivo" en `/vigilados`. Esto funciona bien en condiciones normales, pero si `monitor.py` muere sin ejecutar `_mark_all_left()` (kill -9, OOM, excepción no capturada), quedan guests huérfanos que mantienen `is_live = true` indefinidamente.

El chat heartbeat es fail-safe (timeout de 30s → offline automático). Los guests no lo son — requieren un evento explícito de leave para cerrarse.

## What Changes

Dos capas de protección complementarias:

1. **Cleanup en startup** — Al arrancar, `monitor.py` cierra todos los guests con `left_at IS NULL` de sesiones que ya no están activas. Cubre el caso más común: crash → reinicio.
2. **Staleness check en backoffice** — Al evaluar liveness, ignorar guests cuyo `joined_at` supera un umbral (ej. 4h) sin actividad de chat reciente. Safety net para el caso donde el monitor no reinicia.

## Capabilities

### New Capabilities
- `guest-orphan-cleanup`: Detección y cierre de guests huérfanos por crash del monitor o desconexión no limpia.

### Modified Capabilities
(ninguna)

## Impact

- **Archivos modificados**: `apps/recorder/src/monitor.py` (cleanup en startup), `apps/recorder/src/battles.py` (función de cleanup), `apps/app-backoffice/src/lib/db.ts` (staleness check en `getActiveGuests`)
- **Dependencias**: ninguna nueva
- **Riesgo**: bajo — es código defensivo, no cambia el happy path
- **DB**: no requiere migraciones, opera sobre la tabla `guests` existente
