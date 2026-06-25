# voice-command-api

API local para normalizar comandos de voz transcritos y convertirlos en comandos canónicos estructurados.

El API recibe texto libre como:

```text
monitor two and zoom in
pon el monitor dos a la izquierda
hazlo más grande
stop stream
```

Y lo convierte en comandos internos como:

```text
SELECT_MONITOR
MOVE_LEFT
ZOOM_IN
SET_SIZE
START_STREAM
STOP_STREAM
```

---

## Requisitos

* Python 3.11
* pip
* Opcional: Docker
* Opcional: Docker Compose
* Opcional: Ollama para fallback local con LLM

---

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

En Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Ejecutar el servidor

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

El API quedará disponible en:

```text
http://localhost:8000
```

---

## Docker Compose

Para levantar API + MySQL juntos:

```bash
docker compose up --build
```

Esto hace:

* levanta `mysql:8.0`
* ejecuta `alembic upgrade head`
* corre el seed inicial con `python -m app.db.seed`
* inicia la API en `http://localhost:8000`
* no expone MySQL al host por defecto, para no chocar con un MySQL local en `3306`
* usa una imagen de desarrollo más liviana sin `sentence-transformers`, porque `ENABLE_SEMANTIC_MATCHER=false`

Probar:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
```

Panel admin:

```text
http://localhost:8000/admin
```

Credenciales por defecto:

```text
admin@example.com
admin123
```

Si necesitas exponer MySQL al host, puedes agregar temporalmente en `docker-compose.yml`:

```yaml
ports:
  - "3307:3306"
```

Notas:

* En `docker-compose.yml` el matcher semántico queda desactivado con `ENABLE_SEMANTIC_MATCHER=false` para un arranque inicial más rápido.
* El `Dockerfile` usa por defecto `requirements-docker.txt` para evitar descargar dependencias pesadas como `torch` cuando el matcher semántico está apagado.
* Si necesitas una imagen con el stack completo, puedes construirla con:

```bash
docker build --build-arg REQUIREMENTS_FILE=requirements.txt -t voice-command-api-full .
```

* La ejecución local sin Docker sigue funcionando igual con `uvicorn`.

---

## Probar salud del servicio

```bash
curl http://localhost:8000/health
```

Respuesta esperada:

```json
{
  "status": "ok"
}
```

---

## Variables de entorno

Puedes crear un archivo `.env` o definir las variables directamente en la terminal.

```bash
ENV=development
ALLOWED_ORIGINS=*
DATABASE_URL=mysql+pymysql://voice_user:voice_password@localhost:3306/voice_command_api?charset=utf8mb4
ADMIN_SESSION_SECRET=change-me-in-production
ADMIN_COOKIE_NAME=voice_admin_session
ADMIN_SESSION_MAX_AGE_SECONDS=86400
ENABLE_SEMANTIC_MATCHER=true
ENABLE_OLLAMA_FALLBACK=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
SEMANTIC_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
FUZZY_THRESHOLD=88
SEMANTIC_THRESHOLD=0.72
SEMANTIC_CONFIRMATION_THRESHOLD=0.62
MAX_TEXT_LENGTH=500
```

Para Docker Compose, la API usa internamente:

```bash
DATABASE_URL=mysql+pymysql://voice_user:voice_password@mysql:3306/voice_command_api?charset=utf8mb4
ENV=development
ALLOWED_ORIGINS=*
ENABLE_SEMANTIC_MATCHER=false
```

Para producción:

```bash
ENV=production
ALLOWED_ORIGINS=https://example.com,https://app.example.com
DATABASE_URL=mysql+pymysql://voice_user:voice_password@localhost:3306/voice_command_api?charset=utf8mb4
ADMIN_SESSION_SECRET=change-me-in-production
ADMIN_COOKIE_NAME=voice_admin_session
ADMIN_SESSION_MAX_AGE_SECONDS=86400
ENABLE_SEMANTIC_MATCHER=true
ENABLE_OLLAMA_FALLBACK=false
MAX_TEXT_LENGTH=500
```

Nota:

La primera llamada que use el matcher semántico puede demorar porque `sentence-transformers` puede descargar el modelo en el primer uso.

---

## Admin en producción

Antes de exponer el panel admin:

* Cambia `ADMIN_SESSION_SECRET`.
* Cambia el password por defecto del admin inicial.
* Usa `ENV=production`.
* Sirve la app detrás de HTTPS en un reverse proxy.
* Configura `ALLOWED_ORIGINS` con orígenes explícitos.
* Mantén `POST /admin/dev/seed` deshabilitado en producción.

Protecciones actuales del panel:

* cookie de sesión `HttpOnly`
* `Secure=true` cuando `ENV=production`
* `SameSite=lax`
* expiración controlada por `ADMIN_SESSION_MAX_AGE_SECONDS`
* rate limit básico de login en memoria
* CSRF básico en formularios autenticados
* roles `admin`, `editor`, `viewer`

Permisos:

* `viewer`: dashboard, commands, tester
* `editor`: edición de examples, review y entidades
* `admin`: settings, publish, import/export YAML y administración completa

Nota:

La protección CSRF actual cubre formularios autenticados del panel. Como siguiente endurecimiento, conviene agregar una estrategia dedicada también para el formulario de login si el panel va a exponerse públicamente.

---

## Endpoints disponibles

```text
GET  /
GET  /health
GET  /health/db
GET  /v1/commands/catalog
GET  /v1/commands/examples
POST /v1/commands/normalize
POST /v1/commands/warmup
POST /v1/commands/debug
```

Notas:

* `POST /v1/commands/debug` solo está disponible fuera de producción.
* `POST /v1/commands/warmup` sirve para cargar manualmente el modelo semántico antes de recibir comandos reales.
* `GET /health/db` intenta ejecutar `SELECT 1` contra MySQL.

---

## MySQL

SQL para crear base y usuario:

```sql
CREATE DATABASE voice_command_api CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'voice_user'@'localhost' IDENTIFIED BY 'voice_password';
GRANT ALL PRIVILEGES ON voice_command_api.* TO 'voice_user'@'localhost';
FLUSH PRIVILEGES;
```

El endpoint:

```http
GET /health/db
```

Devuelve:

```json
{
  "status": "ok",
  "database": "ok"
}
```

Si la base no está disponible, responde `503` con:

```json
{
  "status": "error",
  "database": "unavailable"
}
```

Con Docker Compose no necesitas crear la base manualmente; MySQL la crea con las variables del servicio `mysql`.

---

## Alembic

Crear una migración nueva:

```bash
alembic revision --autogenerate -m "message"
```

Aplicar migraciones:

```bash
alembic upgrade head
```

Revertir una migración:

```bash
alembic downgrade -1
```

En producción, usa Alembic como mecanismo de cambios de esquema. No uses `create_all()` para reemplazar migraciones.

---

## Seed inicial

Para cargar comandos, examples, entidades, settings y un usuario admin inicial:

```bash
python -m app.db.seed
```

Esto importa desde `app/commands/catalog.yml` hacia MySQL.

---

# Endpoint principal

## Normalizar comando

```http
POST /v1/commands/normalize
```

Ejemplo:

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"monitor two and zoom in","language_hint":"en"}'
```

Respuesta esperada:

```json
{
  "ok": true,
  "raw_text": "monitor two and zoom in",
  "normalized_text": "monitor two and zoom in",
  "language": "en",
  "commands": [
    {
      "command": "SELECT_MONITOR",
      "confidence": 1.0,
      "method": "entity_rule",
      "monitor": 2,
      "layout": null,
      "size_inches": null,
      "value": null,
      "raw_fragment": "monitor two"
    },
    {
      "command": "ZOOM_IN",
      "confidence": 1.0,
      "method": "exact_rule",
      "monitor": null,
      "layout": null,
      "size_inches": null,
      "value": null,
      "raw_fragment": "zoom in"
    }
  ],
  "needs_confirmation": false,
  "message": null
}
```

---

# Ejemplos rápidos

## Seleccionar monitor

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"monitor one"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"selecciona monitor dos"}'
```

---

## Mover monitor

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"left"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"mueve el monitor a la derecha"}'
```

---

## Zoom

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"zoom in"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"acercalo"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"zoom out"}'
```

---

## Tamaño del monitor

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"increase"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"hazlo más grande"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"decrease"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"ponlo en 65 pulgadas"}'
```

---

## Layouts

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"layout one"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"layout dos"}'
```

---

## Seguimiento y posición

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"follow me"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"stop follow me"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"recenter objects"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"reset position"}'
```

---

## Paneles y UI

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"show aitrol"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"close aitrol"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"show voice commands"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"close voice commands"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"settings"}'
```

---

## Captura, stream y grabación

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"capture"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"stream"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"record"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"stop stream"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"stop"}'
```

---

## Multi-comando

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"monitor two, move left and make it 65 inches"}'
```

Respuesta esperada:

```json
{
  "ok": true,
  "raw_text": "monitor two, move left and make it 65 inches",
  "normalized_text": "monitor two move left and make it 65 inches",
  "language": null,
  "commands": [
    {
      "command": "SELECT_MONITOR",
      "confidence": 1.0,
      "method": "entity_rule",
      "monitor": 2,
      "layout": null,
      "size_inches": null,
      "value": null,
      "raw_fragment": "monitor two"
    },
    {
      "command": "MOVE_LEFT",
      "confidence": 1.0,
      "method": "exact_rule",
      "monitor": null,
      "layout": null,
      "size_inches": null,
      "value": null,
      "raw_fragment": "move left"
    },
    {
      "command": "SET_SIZE",
      "confidence": 1.0,
      "method": "entity_rule",
      "monitor": null,
      "layout": null,
      "size_inches": 65,
      "value": null,
      "raw_fragment": "make it 65 inches"
    }
  ],
  "needs_confirmation": false,
  "message": null
}
```

---

# Comandos soportados

## Monitores

| Frase recibida  | Comando interno | Parámetro  |
| --------------- | --------------- | ---------- |
| monitor one     | SELECT_MONITOR  | monitor: 1 |
| monitor 1       | SELECT_MONITOR  | monitor: 1 |
| monitor two     | SELECT_MONITOR  | monitor: 2 |
| monitor 2       | SELECT_MONITOR  | monitor: 2 |
| monitor uno     | SELECT_MONITOR  | monitor: 1 |
| monitor dos     | SELECT_MONITOR  | monitor: 2 |
| primer monitor  | SELECT_MONITOR  | monitor: 1 |
| segundo monitor | SELECT_MONITOR  | monitor: 2 |

---

## Movimiento

| Frase recibida       | Comando interno |
| -------------------- | --------------- |
| left                 | MOVE_LEFT       |
| right                | MOVE_RIGHT      |
| up                   | MOVE_UP         |
| down                 | MOVE_DOWN       |
| izquierda            | MOVE_LEFT       |
| derecha              | MOVE_RIGHT      |
| arriba               | MOVE_UP         |
| abajo                | MOVE_DOWN       |
| mueve a la izquierda | MOVE_LEFT       |
| mueve a la derecha   | MOVE_RIGHT      |
| mover hacia arriba   | MOVE_UP         |
| mover hacia abajo    | MOVE_DOWN       |

---

## Zoom y tamaño

| Frase recibida    | Comando interno | Parámetro        |
| ----------------- | --------------- | ---------------- |
| zoom in           | ZOOM_IN         | -                |
| zoom out          | ZOOM_OUT        | -                |
| acercar           | ZOOM_IN         | -                |
| alejar            | ZOOM_OUT        | -                |
| increase          | INCREASE_SIZE   | -                |
| decrease          | DECREASE_SIZE   | -                |
| aumenta           | INCREASE_SIZE   | -                |
| disminuye         | DECREASE_SIZE   | -                |
| hazlo más grande  | INCREASE_SIZE   | -                |
| hazlo más pequeño | DECREASE_SIZE   | -                |
| 55 inch           | SET_SIZE        | size_inches: 55  |
| 65 inch           | SET_SIZE        | size_inches: 65  |
| 75 inch           | SET_SIZE        | size_inches: 75  |
| 95 inch           | SET_SIZE        | size_inches: 95  |
| 120 inch          | SET_SIZE        | size_inches: 120 |
| 55 pulgadas       | SET_SIZE        | size_inches: 55  |
| 65 pulgadas       | SET_SIZE        | size_inches: 65  |
| 75 pulgadas       | SET_SIZE        | size_inches: 75  |
| 95 pulgadas       | SET_SIZE        | size_inches: 95  |
| 120 pulgadas      | SET_SIZE        | size_inches: 120 |

---

## Seguimiento y posición

| Frase recibida      | Comando interno  |
| ------------------- | ---------------- |
| follow me           | FOLLOW_ME        |
| sígueme             | FOLLOW_ME        |
| sigueme             | FOLLOW_ME        |
| que me siga         | FOLLOW_ME        |
| stop follow me      | STOP_FOLLOW_ME   |
| stop following me   | STOP_FOLLOW_ME   |
| deja de seguirme    | STOP_FOLLOW_ME   |
| detener seguimiento | STOP_FOLLOW_ME   |
| recenter objects    | RECENTER_OBJECTS |
| center objects      | RECENTER_OBJECTS |
| recentrar objetos   | RECENTER_OBJECTS |
| centrar objetos     | RECENTER_OBJECTS |
| reset position      | RESET_POSITION   |
| restaurar posición  | RESET_POSITION   |
| posición inicial    | RESET_POSITION   |

---

## Layouts

| Frase recibida | Comando interno | Parámetro |
| -------------- | --------------- | --------- |
| layout one     | SET_LAYOUT      | layout: 1 |
| layout 1       | SET_LAYOUT      | layout: 1 |
| layout two     | SET_LAYOUT      | layout: 2 |
| layout 2       | SET_LAYOUT      | layout: 2 |
| layout uno     | SET_LAYOUT      | layout: 1 |
| layout dos     | SET_LAYOUT      | layout: 2 |
| primer layout  | SET_LAYOUT      | layout: 1 |
| segundo layout | SET_LAYOUT      | layout: 2 |

---

## Paneles y UI

| Frase recibida          | Comando interno      |
| ----------------------- | -------------------- |
| show aitrol             | SHOW_AITROL          |
| open aitrol             | SHOW_AITROL          |
| mostrar aitrol          | SHOW_AITROL          |
| abre aitrol             | SHOW_AITROL          |
| close aitrol            | CLOSE_AITROL         |
| cerrar aitrol           | CLOSE_AITROL         |
| show voice commands     | SHOW_VOICE_COMMANDS  |
| show voice command      | SHOW_VOICE_COMMANDS  |
| open voice commands     | SHOW_VOICE_COMMANDS  |
| mostrar comandos de voz | SHOW_VOICE_COMMANDS  |
| close voice commands    | CLOSE_VOICE_COMMANDS |
| close voice command     | CLOSE_VOICE_COMMANDS |
| cerrar comandos de voz  | CLOSE_VOICE_COMMANDS |
| settings                | OPEN_SETTINGS        |
| ajustes                 | OPEN_SETTINGS        |
| configuration           | OPEN_SETTINGS        |
| configuración           | OPEN_SETTINGS        |

---

## Captura, stream y grabación

| Frase recibida      | Comando interno |
| ------------------- | --------------- |
| capture             | CAPTURE         |
| screenshot          | CAPTURE         |
| captura             | CAPTURE         |
| pantallazo          | CAPTURE         |
| stream              | START_STREAM    |
| start stream        | START_STREAM    |
| iniciar stream      | START_STREAM    |
| transmitir          | START_STREAM    |
| record              | START_RECORDING |
| start recording     | START_RECORDING |
| grabar              | START_RECORDING |
| iniciar grabación   | START_RECORDING |
| stop stream         | STOP_STREAM     |
| stop streaming      | STOP_STREAM     |
| detener stream      | STOP_STREAM     |
| detener transmisión | STOP_STREAM     |
| stop                | STOP_ACTIVE     |
| detener             | STOP_ACTIVE     |
| parar               | STOP_ACTIVE     |
| cancelar            | STOP_ACTIVE     |

---

# Comandos internos disponibles

```text
SELECT_MONITOR
MOVE_LEFT
MOVE_RIGHT
MOVE_UP
MOVE_DOWN
ZOOM_IN
ZOOM_OUT
INCREASE_SIZE
DECREASE_SIZE
SET_SIZE
FOLLOW_ME
STOP_FOLLOW_ME
RECENTER_OBJECTS
RESET_POSITION
SET_LAYOUT
SHOW_AITROL
CLOSE_AITROL
SHOW_VOICE_COMMANDS
CLOSE_VOICE_COMMANDS
OPEN_SETTINGS
CAPTURE
START_STREAM
START_RECORDING
STOP_STREAM
STOP_ACTIVE
UNKNOWN
```

---

# Reglas de prioridad

Algunos comandos son más específicos que otros.

```text
STOP_FOLLOW_ME > FOLLOW_ME
STOP_STREAM > STOP_ACTIVE
RECENTER_OBJECTS > movimientos individuales
SET_SIZE > INCREASE_SIZE / DECREASE_SIZE cuando hay pulgadas
SELECT_MONITOR > comando genérico de monitor
SET_LAYOUT > comando genérico de layout
```

Ejemplo:

```text
stop stream
```

Debe convertirse en:

```text
STOP_STREAM
```

No en:

```text
STOP_ACTIVE
```

Ejemplo:

```text
stop follow me
```

Debe convertirse en:

```text
STOP_FOLLOW_ME
```

No en:

```text
FOLLOW_ME
```

---

# Debug

El endpoint de debug ayuda a inspeccionar fragmentos, entidades, matches por reglas y candidatos fuzzy/semánticos para mejorar el catálogo durante desarrollo.

```bash
curl -X POST http://localhost:8000/v1/commands/debug \
  -H "Content-Type: application/json" \
  -d '{"text":"monitor two and zoom in"}'
```

Este endpoint solo está disponible cuando:

```bash
ENV=development
```

En producción se oculta automáticamente.

---

# Warmup del matcher semántico

```bash
curl -X POST http://localhost:8000/v1/commands/warmup
```

Este comando carga el modelo semántico antes de recibir comandos reales.

Si `ENABLE_SEMANTIC_MATCHER=false`, el endpoint debe responder que el matcher semántico está desactivado.

---

# Fallback local opcional con Ollama

El proyecto puede usar Ollama como último fallback local si reglas, fuzzy matching y semantic matcher no tienen suficiente confianza.

Instalar modelo:

```bash
ollama pull qwen2.5:3b
```

Ejecutar Ollama:

```bash
ollama serve
```

Ejecutar API con fallback:

```bash
ENABLE_OLLAMA_FALLBACK=true uvicorn app.main:app --reload
```

Nota:

Ollama debe usarse solo como fallback. El flujo principal debe seguir siendo:

```text
reglas → fuzzy matching → semantic matcher → Ollama opcional
```

---

# Casos ambiguos

Si el API no está seguro, debe responder con `needs_confirmation: true`.

Ejemplo:

```json
{
  "ok": true,
  "raw_text": "start broadcast maybe",
  "normalized_text": "start broadcast maybe",
  "language": "en",
  "commands": [
    {
      "command": "START_STREAM",
      "confidence": 0.68,
      "method": "semantic",
      "monitor": null,
      "layout": null,
      "size_inches": null,
      "value": null,
      "raw_fragment": "start broadcast maybe"
    }
  ],
  "needs_confirmation": true,
  "message": "El comando fue interpretado con baja confianza."
}
```

La app puede usar `needs_confirmation` para pedir confirmación antes de ejecutar el comando.

---

# Ejecutar tests

```bash
pytest
```

Con salida detallada:

```bash
pytest -v
```

Ejecutar un test específico:

```bash
pytest tests/test_normalizer.py -v
```

---

# Docker

## Build

```bash
docker build -t voice-command-api .
```

## Run

```bash
docker run --rm -p 8000:8000 voice-command-api
```

## Run con variables de entorno

```bash
docker run --rm -p 8000:8000 \
  -e ENV=production \
  -e ALLOWED_ORIGINS=https://example.com \
  -e ENABLE_SEMANTIC_MATCHER=true \
  -e ENABLE_OLLAMA_FALLBACK=false \
  voice-command-api
```

## Test

```bash
curl http://localhost:8000/health
```

---

# Flujo interno del API

```text
Texto recibido
   ↓
Normalización
   ↓
División en fragmentos
   ↓
Extracción de entidades
   ↓
Reglas exactas
   ↓
Fuzzy matching
   ↓
Semantic matcher local
   ↓
Ollama opcional
   ↓
Respuesta JSON
```

---

# Producción

Recomendaciones para producción:

* Usar `ENV=production`.
* Ocultar `/v1/commands/debug`.
* Definir `ALLOWED_ORIGINS` con dominios reales.
* Mantener `MAX_TEXT_LENGTH` bajo, por ejemplo `500`.
* Mantener `ENABLE_OLLAMA_FALLBACK=false` salvo que realmente se necesite.
* Guardar logs de comandos no reconocidos para mejorar `catalog.yml`.
* Ejecutar tests antes de desplegar.

Ejemplo:

```bash
ENV=production \
ALLOWED_ORIGINS=https://tu-app.com \
ENABLE_SEMANTIC_MATCHER=true \
ENABLE_OLLAMA_FALLBACK=false \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

# Mejorar el catálogo

Cuando el API no entienda una frase, se debe agregar como ejemplo en:

```text
app/commands/catalog.yml
```

Ejemplo de frase no reconocida:

```json
{
  "text": "ponlo como pantalla grande",
  "predicted": "UNKNOWN",
  "confidence": 0.0
}
```

Puede agregarse como ejemplo de:

```text
INCREASE_SIZE
```

Después de modificar el catálogo, ejecutar:

```bash
pytest
```

Y probar manualmente:

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -d '{"text":"ponlo como pantalla grande"}'
```

---

# Notas

* El API no recibe audio.
* El API recibe texto ya transcrito.
* El idioma puede enviarse en `language_hint`, pero no es obligatorio.
* Los comandos internos deben mantenerse estables.
* Las frases de usuario se amplían en `catalog.yml`.
* No se necesita una LLM pagada para la primera versión.
* Ollama es opcional y solo se recomienda como fallback.
