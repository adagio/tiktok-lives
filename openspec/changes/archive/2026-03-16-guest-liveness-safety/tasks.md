## Tasks

- [x] **T1**: Agregar `close_orphaned_guests(db_path)` en `battles.py` — UPDATE guests SET left_at = NOW WHERE left_at IS NULL
- [x] **T2**: Llamar `close_orphaned_guests()` al inicio de `monitor.py`, antes del loop principal
- [x] **T3**: Modificar `getActiveGuests()` en `db.ts` para filtrar guests stale (joined_at > 4h sin chat reciente en 30min)
- [ ] **T4**: Verificar manualmente: insertar guest huérfano, confirmar que backoffice lo ignora después del umbral (pendiente: test manual con `npm run dev`)
