## 1. Schema y DB

- [x] 1.1 Agregar tabla `chat_messages` con índices en `init_battles_db.py`
- [x] 1.2 Agregar función `save_chat_messages(db_path, messages: list[dict])` en `battles.py` para insert batch

## 2. ChatSpy

- [x] 2.1 Crear `apps/recorder/src/chat_spy.py` — clase `ChatSpy` con `start()`/`stop()`, handler de `CommentEvent`, buffer con flush periódico, propiedad mutable `battle_id`

## 3. Integración en monitor

- [x] 3.1 Agregar campos `chat_spy`, `chat_task`, `opponent_chat_spy`, `opponent_chat_task` a `ActiveSession`
- [x] 3.2 Crear `_launch_chat_spy(sess)` y `_run_chat_spy_safe()` — lanzar al iniciar sesión
- [x] 3.3 En `_check_battle_sync` / loop principal: al detectar batalla nueva, setear `sess.chat_spy.battle_id` y lanzar `opponent_chat_spy`
- [x] 3.4 Al terminar batalla: resetear `sess.chat_spy.battle_id = None` y cancelar `opponent_chat_spy`
- [x] 3.5 En `_reap_finished` y `_shutdown_all`: cancelar chat tasks junto con los demás spy tasks
