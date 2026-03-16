## Requirements

### Requirement: Captura de chat del host durante todo el live

El sistema SHALL capturar todos los mensajes de chat (`CommentEvent`) de la sala del host durante toda la duración del live, persistiéndolos a SQLite.

#### Scenario: Live sin batalla
- **WHEN** el monitor detecta un live activo y lanza la sesión
- **THEN** se inicia un ChatSpy que captura mensajes de chat de la sala del host con `battle_id = NULL`

#### Scenario: Live con batalla activa
- **WHEN** el monitor detecta una batalla durante un live activo
- **THEN** los mensajes de chat del host capturados a partir de ese momento tienen el `battle_id` de la batalla activa

#### Scenario: Batalla termina
- **WHEN** una batalla termina durante un live activo
- **THEN** los mensajes de chat del host vuelven a capturarse con `battle_id = NULL`

### Requirement: Captura de chat del opponent durante batallas

El sistema SHALL capturar mensajes de chat de la sala del oponente mientras dure una batalla.

#### Scenario: Batalla inicia
- **WHEN** el monitor detecta una nueva batalla y resuelve el username del oponente
- **THEN** se lanza un ChatSpy contra la sala del oponente con el `battle_id` correspondiente

#### Scenario: Batalla termina
- **WHEN** la batalla termina
- **THEN** el ChatSpy del oponente se detiene y desconecta

#### Scenario: Nueva batalla con distinto oponente
- **WHEN** termina una batalla y comienza otra con un oponente diferente
- **THEN** se detiene el ChatSpy anterior y se lanza uno nuevo contra el nuevo oponente

### Requirement: Persistencia de mensajes a SQLite

Cada mensaje de chat SHALL persistirse en la tabla `chat_messages` de `clips.db` con los campos: `session_id`, `battle_id` (nullable), `room_username`, `user_id`, `username`, `text`, `timestamp`.

#### Scenario: Mensaje capturado
- **WHEN** se recibe un `CommentEvent` del WebSocket
- **THEN** se almacena un registro con el `session_id` de la sesión activa, el `battle_id` actual (o NULL), el `room_username` de la sala, y los datos del mensaje

#### Scenario: Escritura batch
- **WHEN** se acumulan mensajes en el buffer interno
- **THEN** se escriben a SQLite en batch cada ~2 segundos o al alcanzar el tamaño máximo del buffer

#### Scenario: Shutdown graceful
- **WHEN** el spy se detiene (por fin de sesión, fin de batalla, o shutdown del monitor)
- **THEN** se hace flush del buffer pendiente antes de desconectar

### Requirement: ChatSpy sigue el patrón de spy existente

La clase `ChatSpy` SHALL seguir el patrón arquitectónico de `VentanillaSpy`/`TreasureSpy`: clase con `start()`/`stop()`, logger compartido `"monitor"`, lanzada como `asyncio.Task` desde el monitor.

#### Scenario: Crash del ChatSpy no afecta al monitor
- **WHEN** el ChatSpy lanza una excepción no manejada
- **THEN** el wrapper `_run_chat_spy_safe` la captura, loggea el error, y el monitor sigue operando

### Requirement: Tabla chat_messages con índices adecuados

La tabla `chat_messages` SHALL tener índices en `session_id`, `battle_id`, y `timestamp` para soportar queries eficientes desde el backoffice.

#### Scenario: Query por batalla
- **WHEN** el backoffice consulta mensajes de una batalla específica
- **THEN** la query usa el índice `idx_chat_battle` para filtrar por `battle_id`

#### Scenario: Query por rango temporal
- **WHEN** el backoffice consulta mensajes nuevos desde un timestamp (polling)
- **THEN** la query usa el índice `idx_chat_timestamp` para filtrar eficientemente
