## Edge Cases Identificados

### 1. Monitor crash sin cleanup

```
monitor.py ───X (kill -9, OOM, excepción no capturada)
                │
                │  _mark_all_left() NUNCA se ejecuta
                ▼
guests con left_at IS NULL → is_live = true para siempre
```

**Frecuencia**: rara pero inevitable a largo plazo. El monitor corre 24/7.

### 2. WebSocket disconnect sin evento de leave

El `VentanillaSpy` depende de `LinkMicFanTicketMethodEvent` para detectar departures. Si TikTok deja de enviar eventos pero el WebSocket sigue abierto, los guests quedan como activos.

**Frecuencia**: desconocida — depende de la fiabilidad de TikTok.

### 3. Sesión larga con guest estable

Un guest legítimo que dura horas en ventanilla podría ser filtrado por un staleness check demasiado agresivo.

**Mitigación**: el umbral debe ser generoso (4h+) y combinar con ausencia de chat.

## Decisiones de Diseño

### Cleanup en startup (monitor.py)

```python
# Al arrancar, antes del loop principal:
close_orphaned_guests(db_path)
```

```
┌─────────────────────────────────────┐
│           monitor.py startup        │
├─────────────────────────────────────┤
│ 1. close_orphaned_guests()          │
│    UPDATE guests                    │
│    SET left_at = NOW               │
│    WHERE left_at IS NULL            │
│                                     │
│ 2. loop principal (como antes)      │
└─────────────────────────────────────┘
```

**Scope del cleanup**: cerrar TODOS los guests con `left_at IS NULL`, no solo los de sesiones "viejas". Si el monitor está arrancando, cualquier guest abierto es sospechoso — la sesión se re-detectará y los guests legítimos se volverán a registrar.

### Staleness check (backoffice)

```
getActiveGuests(session_id)
  ├─ left_at IS NULL (como ahora)
  └─ joined_at > NOW - 4 horas        ← nuevo filtro
      O hay chat reciente (30min)      ← actividad correlacionada
```

Esto es un safety net para el backoffice independiente del monitor. Si no hay chat hace 30 minutos y el guest lleva 4+ horas, probablemente es huérfano.

### Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Heartbeat en guests (`last_seen_at`) | Requiere migración de DB + cambio en VentanillaSpy para actualizar periódicamente. Overhead alto para un edge case raro. |
| Cron job de cleanup | Complejidad operacional innecesaria. El monitor ya es el proceso long-running — que él mismo limpie. |
| TTL en la query SQL | Demasiado simple, no distingue entre guest legítimo largo y huérfano. El combo staleness + chat es más preciso. |
