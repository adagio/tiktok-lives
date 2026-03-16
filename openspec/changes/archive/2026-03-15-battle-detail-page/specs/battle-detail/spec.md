## ADDED Requirements

### Requirement: Página de detalle de batalla

SHALL existir una página en `/batallas/[id]` que muestre el detalle completo de una batalla, incluyendo header con scores, chat de ambas salas, y contexto adicional (guests).

#### Scenario: Acceso a batalla existente
- **WHEN** el usuario navega a `/batallas/123` y la batalla existe
- **THEN** se muestra el header con host vs opponent, scores, hora, y duración

#### Scenario: Batalla no encontrada
- **WHEN** el usuario navega a `/batallas/999` y no existe
- **THEN** se redirige a la sesión o se muestra un error

### Requirement: Dos paneles de chat side-by-side

La página SHALL mostrar dos paneles de chat: uno para la sala del host y otro para la sala del opponent, identificados por `room_username`.

#### Scenario: Batalla con chat de ambas salas
- **WHEN** la batalla tiene mensajes de chat tanto del host como del opponent
- **THEN** se muestran en dos columnas separadas, cada una con su título (username de la sala)

#### Scenario: Batalla sin chat del opponent
- **WHEN** la batalla solo tiene chat del host (el opponent_chat_spy no pudo conectar)
- **THEN** el panel del opponent muestra un estado vacío, el panel del host funciona normalmente

### Requirement: Auto-refresh mientras la batalla está activa

La página SHALL hacer polling cada ~3 segundos para obtener mensajes nuevos y scores actualizados mientras la batalla esté activa.

#### Scenario: Batalla en curso
- **WHEN** la página se carga y la batalla está activa
- **THEN** se muestra un indicador "EN VIVO" y se inicia el polling automático

#### Scenario: Batalla terminada
- **WHEN** el endpoint retorna `is_active: false`
- **THEN** se detiene el polling y se oculta el indicador "EN VIVO"

#### Scenario: Reload de página
- **WHEN** el usuario recarga la página durante una batalla activa
- **THEN** se cargan todos los mensajes existentes y se reanuda el polling desde el último timestamp

### Requirement: Auto-scroll inteligente en paneles de chat

Los paneles de chat SHALL hacer auto-scroll al final cuando llegan mensajes nuevos, salvo que el usuario haya scrolleado manualmente hacia arriba.

#### Scenario: Usuario no ha scrolleado
- **WHEN** llegan mensajes nuevos y el panel está al final del scroll
- **THEN** el panel scrollea automáticamente para mostrar los mensajes nuevos

#### Scenario: Usuario scrolleó hacia arriba
- **WHEN** llegan mensajes nuevos pero el usuario ha scrolleado manualmente hacia arriba
- **THEN** los mensajes se agregan pero el scroll NO se mueve

### Requirement: Endpoint API para polling de mensajes

SHALL existir un endpoint `GET /api/battle/[id]/messages` que acepte un parámetro `since` (ISO timestamp) y retorne los mensajes nuevos junto con el estado actual de la batalla.

#### Scenario: Request con since
- **WHEN** se hace GET a `/api/battle/123/messages?since=2026-03-14T15:58:20`
- **THEN** se retornan solo los mensajes con `timestamp > since`, más los scores actuales y `is_active`

#### Scenario: Request sin since
- **WHEN** se hace GET a `/api/battle/123/messages` sin parámetro since
- **THEN** se retornan todos los mensajes de la batalla

### Requirement: Link desde sesión a batalla

Cada batalla listada en `/sesiones/[id]` SHALL ser un link clickeable a `/batallas/[battle_db_id]`.

#### Scenario: Click en batalla
- **WHEN** el usuario hace click en una batalla en la página de sesión
- **THEN** navega a `/batallas/[id]` con el detalle completo

### Requirement: Fechas en timezone local

Todas las fechas mostradas en la página de batalla SHALL usar el componente `LocalTime` para convertirse al timezone del browser (consistente con el resto del backoffice).

#### Scenario: Timestamp de mensaje en hora local
- **WHEN** un mensaje tiene `timestamp = "2026-03-14T15:58:20"` y el browser está en UTC-3
- **THEN** se muestra `12:58` (hora local)
