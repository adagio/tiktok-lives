## guest-orphan-cleanup

### Requisitos

1. **Cleanup en startup**: Cuando `monitor.py` arranca, DEBE cerrar todos los guests con `left_at IS NULL` seteando `left_at` al timestamp actual.

2. **Staleness en backoffice**: `getActiveGuests()` DEBE ignorar guests que cumplan AMBAS condiciones:
   - `joined_at` es anterior a 4 horas
   - No hay mensajes de chat en la sesión en los últimos 30 minutos

3. **No afectar happy path**: El flujo normal de join/leave via `VentanillaSpy` NO debe cambiar.

4. **Idempotencia**: El cleanup en startup debe ser seguro de ejecutar múltiples veces sin efectos secundarios.

### Comportamiento esperado

| Escenario | Resultado |
|---|---|
| Monitor crashea y reinicia | Guests huérfanos se cierran en startup, sesión se re-detecta normalmente |
| Monitor crashea y NO reinicia | Backoffice filtra guests huérfanos después de 4h sin chat |
| Guest legítimo de larga duración con chat activo | Se muestra normalmente (chat reciente bypasea el filtro de staleness) |
| Guest legítimo de larga duración sin chat | Se filtra después de 4h — aceptable, caso extremadamente raro |
