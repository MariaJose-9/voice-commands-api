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

Guía rápida de consumo del endpoint principal: [USAGE.md](USAGE.md).

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
* publica el catálogo inicial con `python -m app.db.publish_initial_catalog`
* inicia la API en `http://localhost:8000`
* expone MySQL al host en `3307`, para no chocar con un MySQL local en `3306`
* usa una imagen de desarrollo más liviana sin `sentence-transformers`, porque `ENABLE_SEMANTIC_MATCHER=false`
* habilita transcripción de audio con `faster-whisper` usando `TRANSCRIPTION_MODEL_NAME=tiny`
* monta caché persistente para modelos en `hf_cache`
* monta temporales de audio en `audio_tmp`
* apunta Ollama por defecto a `http://host.docker.internal:11434`
* habilita `LLM_COMMAND_MODE=hybrid` sin bloquear el startup si Ollama no está disponible

Probar:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
API_TOKEN="UU75xrlDeV6up7wyYdOMxhhMsUTP03G6WJaGdh5aQcMOo70p8ykKDLDxOpRy5MjE"
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer ${API_TOKEN}"
```

Ese token es el valor de desarrollo definido en `docker-compose.yml`. Cámbialo antes de exponer el API.

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
* En Docker la transcripción de audio queda activa con `faster-whisper` y modelo `tiny`, para reducir tiempo de arranque y consumo en desarrollo.
* Ollama es opcional. Si no está disponible, `/v1/commands/normalize` sigue funcionando con reglas, fuzzy y semantic matcher; simplemente no completa con LLM.
* El `Dockerfile` usa por defecto `requirements-docker.txt`; ese archivo ya incluye `faster-whisper`.
* No se fuerza `warmup` al startup. El modelo de audio se carga lazy cuando llamas `/v1/audio/transcribe`, `/v1/audio/normalize` o `/v1/audio/warmup`.
* Si necesitas una imagen con el stack completo, puedes construirla con:

```bash
docker build --build-arg REQUIREMENTS_FILE=requirements.txt -t voice-command-api-full .
```

* La ejecución local sin Docker sigue funcionando igual con `uvicorn`.

---

## Docker Compose con Ollama opcional

Por defecto, el servicio `api` usa:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:3b
ENABLE_OLLAMA_FALLBACK=true
LLM_COMMAND_MODE=hybrid
```

Esto está pensado para Docker Desktop con Ollama corriendo en tu máquina host:

```bash
ollama pull qwen2.5:3b
ollama serve
docker compose up --build
```

También puedes levantar Ollama como contenedor opcional:

```bash
docker compose --profile ollama up -d
```

Luego descarga el modelo dentro del servicio:

```bash
docker compose --profile ollama exec ollama ollama pull qwen2.5:3b
```

El build no descarga modelos de Ollama. Si Ollama no está levantado o no tiene el modelo, el API no se cae: el normalizador devuelve el resultado base de reglas/fuzzy/semantic y omite la completación con LLM.

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

## Real Testing Guide

Esta guía es el flujo recomendado para una prueba real con doctores o técnicos, incluyendo texto, audio, panel admin y publicación del catálogo.

### 1. Setup local

```bash
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.db.seed
python -m app.db.publish_initial_catalog
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

El comando `python -m app.db.publish_initial_catalog` es importante: crea la primera versión activa del catálogo. Si no se ejecuta, el panel puede mostrar `Active Version: none`.

### 2. Setup Docker

```bash
docker compose up --build
```

El compose ejecuta migraciones, seed, publicación inicial del catálogo y arranca la API con MySQL.

### 3. Verificar salud

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
API_TOKEN="UU75xrlDeV6up7wyYdOMxhhMsUTP03G6WJaGdh5aQcMOo70p8ykKDLDxOpRy5MjE"
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer ${API_TOKEN}"
```

En `/v1/audio/status` revisa:

* `model`: modelo actual de transcripción.
* `semantic_matcher_enabled`: si semantic matcher está activo.
* `active_catalog_version`: debe tener un número publicado.
* `catalog_dirty`: debe ser `false` si no hay cambios pendientes.

### 4. Probar comando de texto

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas","language_hint":"es"}'
```

Respuesta esperada a alto nivel:

```text
SELECT_MONITOR monitor=2
MOVE_RIGHT
SET_SIZE size_inches=55
```

### 5. Probar audio

```bash
curl -X POST http://localhost:8000/v1/audio/normalize \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -F "file=@sample.mp3" \
  -F "language_hint=es"
```

El endpoint transcribe el audio y luego ejecuta el normalizer sobre el texto transcrito.

### 6. Panel admin

```text
http://localhost:8000/admin
```

Credenciales default:

```text
admin@example.com
admin123
```

Cambia estas credenciales antes de cualquier exposición real.

### 7. Flujo para mejorar frases reales

1. Revisar `/admin/review`.
2. Convertir una frase fallida o ambigua a example.
3. Probar la frase en `/admin/tester` o `/admin/audio-tester`.
4. Publicar catálogo desde el panel admin.
5. Volver a probar la frase.

Después de convertir frases a examples, el panel muestra cambios pendientes. Esos cambios no quedan activos en runtime hasta publicar el catálogo.

### 8. Configuración recomendada para prueba real

```bash
ENABLE_SEMANTIC_MATCHER=true
TRANSCRIPTION_MODEL_NAME=base
TRANSCRIPTION_COMPUTE_TYPE=int8
FUZZY_THRESHOLD=86
SEMANTIC_THRESHOLD=0.72
SEMANTIC_CONFIRMATION_THRESHOLD=0.62
```

### 9. Configuración para desarrollo rápido

```bash
ENABLE_SEMANTIC_MATCHER=false
TRANSCRIPTION_MODEL_NAME=tiny
FUZZY_THRESHOLD=88
```

### 10. Notas operativas

* `tiny` es rápido, pero se equivoca más al transcribir.
* `base` es el recomendado inicial para pruebas con doctores.
* `small` puede mejorar precisión si la máquina tiene suficiente CPU/RAM.
* El audio no se guarda; solo se usa temporalmente y se borra después de procesarlo.
* Si `ENABLE_AUDIO_TRANSCRIPTION_LOGS=true`, sí se guardan logs de transcripción con metadata y texto transcrito, pero no el archivo de audio.
* El catálogo debe estar publicado para que el panel muestre una versión activa y para activar cambios hechos desde admin.

### Critical Test Phrases

Estas frases deben funcionar antes de una prueba real:

```text
pon pantalla 2 en 55
pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas
coja la pantalla una y mueve la licuada
hazlo un poco más grande
bájale el tamaño
pon el monitor dos en sesenta y cinco pulgadas
cambia pantalla uno a ciento veinte pulgadas
abre comandos de voz
detén stream
```

También están cubiertas por tests E2E:

```bash
pytest tests/test_e2e_critical_commands.py
pytest tests/test_e2e_audio_normalize.py
```

### Production Checklist

Antes de una prueba real o despliegue:

* MySQL operativo.
* `alembic upgrade head` ejecutado.
* `python -m app.db.seed` ejecutado.
* `python -m app.db.publish_initial_catalog` ejecutado.
* `Active Version` visible en admin.
* `API_AUTH_TOKEN` configurado con un token largo y secreto.
* `ENABLE_SEMANTIC_MATCHER=true` configurado si se requiere prueba real flexible.
* `/v1/audio/status` responde con modelo y límites correctos.
* Modelo `base` descargado o `POST /v1/audio/warmup` ejecutado.
* `pytest` pasando.
* `python scripts/nlu_coverage_report.py --fixture tests/fixtures/production_natural_phrases.json --min-coverage 95` pasando.

---

## Variables de entorno

Puedes crear un archivo `.env` o definir las variables directamente en la terminal.

```bash
ENV=development
ALLOWED_ORIGINS=*
API_AUTH_TOKEN=
DATABASE_URL=mysql+pymysql://voice_user:voice_password@localhost:3306/voice_command_api?charset=utf8mb4
ADMIN_SESSION_SECRET=change-me-in-production
ADMIN_COOKIE_NAME=voice_admin_session
ADMIN_SESSION_MAX_AGE_SECONDS=86400
ENABLE_SEMANTIC_MATCHER=true
ENABLE_OLLAMA_FALLBACK=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
SEMANTIC_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENABLE_AUDIO_TRANSCRIPTION=true
ENABLE_AUDIO_TRANSCRIPTION_LOGS=true
TRANSCRIPTION_ENGINE=faster_whisper
TRANSCRIPTION_MODEL_NAME=base
TRANSCRIPTION_DEVICE=cpu
TRANSCRIPTION_COMPUTE_TYPE=int8
TRANSCRIPTION_BEAM_SIZE=1
TRANSCRIPTION_VAD_FILTER=false
TRANSCRIPTION_LANGUAGE_DEFAULT=
MAX_AUDIO_FILE_MB=10
MAX_AUDIO_DURATION_SECONDS=30
ALLOWED_AUDIO_EXTENSIONS=.ogg,.mp3,.m4a
ALLOWED_AUDIO_MIME_TYPES=audio/ogg,audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a,application/octet-stream
AUDIO_TEMP_DIR=/tmp/voice-command-audio
AUDIO_MODEL_WARMUP_ON_STARTUP=false
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
TRANSCRIPTION_MODEL_NAME=tiny
FUZZY_THRESHOLD=88
```

Para producción:

```bash
ENV=production
ALLOWED_ORIGINS=https://example.com,https://app.example.com
API_AUTH_TOKEN=replace-with-a-long-random-token
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

### API authentication token

`API_AUTH_TOKEN` protege los endpoints públicos bajo `/v1/*`. En `development` puede quedar vacío para pruebas locales. En `production` es obligatorio: si `ENV=production` y no configuras `API_AUTH_TOKEN`, las rutas `/v1/*` responden `503` y no procesan requests.

Si configuras:

```bash
API_AUTH_TOKEN=replace-with-a-long-random-token
```

Las rutas `/v1/commands/*` y `/v1/audio/*` requieren uno de estos headers:

```http
Authorization: Bearer replace-with-a-long-random-token
```

o:

```http
X-API-Token: replace-with-a-long-random-token
```

Ejemplo:

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer replace-with-a-long-random-token" \
  -d '{"text":"monitor 1","language_hint":"es"}'
```

`/`, `/health`, `/health/db` y el panel `/admin` no usan este token. El panel mantiene autenticación con cookie firmada y CSRF.

---

## LLM Command Interpreter

El parser por reglas es rápido y estable, pero puede quedarse corto cuando una frase natural contiene una intención que las reglas no cubrieron por completo. Ejemplo:

```text
Redimensiona a 72 pulgadas el monitor 1
```

El parser base puede detectar solo:

```json
{"command": "SELECT_MONITOR", "monitor": 1}
```

El modo híbrido permite que una LLM local complete el resultado con:

```json
{"command": "SET_SIZE", "size_inches": 72}
```

### Completeness checker

Antes de llamar a la LLM, el API evalúa si el resultado base está completo. Detecta señales como:

* tamaño exacto sin `SET_SIZE`.
* intención de grande/pequeño sin `INCREASE_SIZE` o `DECREASE_SIZE`.
* dirección izquierda/derecha/arriba/abajo sin `MOVE_*`.
* comando `UNKNOWN`.
* baja cobertura de `raw_fragment`, cuando partes importantes del texto no fueron explicadas por los comandos detectados.

### Modos

`LLM_COMMAND_MODE` controla cuándo se usa la LLM:

* `off`: nunca usa LLM.
* `fallback`: usa LLM solo si reglas, fuzzy y semantic no resolvieron o requieren confirmación.
* `hybrid`: usa reglas primero y llama LLM si el resultado parece incompleto. Es el modo recomendado.
* `primary`: intenta LLM primero y deja reglas como validación/fallback.

### LLM completeness, canonicalization and deduplication

El parser base puede resolver una frase completa sin ayuda de LLM:

```text
Necesito que el monitor 2 esté en 75 pulgadas
```

Resultado esperado:

```json
{
  "commands": [
    {"command": "SELECT_MONITOR", "monitor": 2},
    {"command": "SET_SIZE", "size_inches": 75}
  ]
}
```

En ese caso `completeness.is_complete=true` y no se llama LLM.

Si el parser base queda incompleto, el completeness checker sí puede activar la LLM. Ejemplo:

```text
Redimensiona a 72 pulgadas el monitor 1
```

Si el parser base solo detecta:

```json
{"command": "SELECT_MONITOR", "monitor": 1}
```

Entonces `completeness.should_call_llm=true` con razón `explicit_size_intent_missing_set_size`, y la LLM puede completar:

```json
{"command": "SET_SIZE", "size_inches": 72}
```

La LLM puede devolver comandos con monitor embebido, por ejemplo:

```json
{"command": "SET_SIZE", "monitor": 2, "size_inches": 75}
```

El sistema canonicaliza esa salida a la forma compatible con la app:

```json
[
  {"command": "SELECT_MONITOR", "monitor": 2},
  {"command": "SET_SIZE", "size_inches": 75}
]
```

Después se deduplican comandos por significado. Si `entity_rule` y `llm` detectan el mismo `SET_SIZE 75`, se conserva `entity_rule` porque viene de extracción determinística.

Prioridad de método:

```text
entity_rule > exact_rule > llm > semantic > fuzzy
```

Si hay conflicto, no se resuelve silenciosamente. Por ejemplo, si `entity_rule` detecta `SET_SIZE 75` pero la LLM propone `SET_SIZE 72`, el sistema conserva el resultado más confiable y marca:

```json
{
  "needs_confirmation": true,
  "message": "Conflicting SET_SIZE commands detected: 72, 75"
}
```

Para revisar una decisión completa usa `/v1/commands/debug` en development:

```bash
curl -X POST http://localhost:8000/v1/commands/debug \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"Necesito que el monitor 2 esté en 75 pulgadas","language_hint":"es"}'
```

Campos útiles del debug:

* `completeness`: indica si el resultado base está completo y qué intención quedó sin cubrir.
* `llm`: indica modo, si debía llamarse, si fue llamada y la razón.
* `merge`: muestra deduplicación, comandos removidos y conflictos.
* `merge.conflicts`: lista conflictos como tamaños distintos, monitores distintos o movimientos opuestos.

Ejemplo esperado para la frase completa:

```json
{
  "completeness": {
    "is_complete": true
  },
  "llm": {
    "mode": "hybrid",
    "should_call": false,
    "called": false,
    "reason": null
  },
  "merge": {
    "deduplicated": true,
    "duplicates_removed": [],
    "conflicts": []
  }
}
```

### Ollama

Instala y levanta Ollama localmente:

```bash
ollama serve
ollama pull qwen2.5:3b
```

Variables principales:

```bash
ENABLE_OLLAMA_FALLBACK=true
LLM_COMMAND_MODE=hybrid
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT_SECONDS=8
LLM_ACCEPT_THRESHOLD=0.78
LLM_CONFIDENCE_CAP=0.90
ALLOW_DYNAMIC_SIZE_INCHES=true
MIN_SIZE_INCHES=40
MAX_SIZE_INCHES=150
```

En Docker Compose, el API apunta por defecto a `http://host.docker.internal:11434` para usar Ollama instalado en el host. También existe un profile opcional `ollama` si prefieres correrlo como contenedor.

### Ejemplo

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"Redimensiona a 72 pulgadas el monitor 1","language_hint":"es"}'
```

Respuesta esperada, resumida:

```json
{
  "commands": [
    {"command": "SELECT_MONITOR", "monitor": 1},
    {"command": "SET_SIZE", "size_inches": 72}
  ]
}
```

### Troubleshooting

* Si Ollama está apagado, el API sigue funcionando con reglas/fuzzy/semantic y omite la completación LLM.
* Si el modelo no está descargado, ejecuta `ollama pull qwen2.5:3b`.
* Si hay timeouts, sube `OLLAMA_TIMEOUT_SECONDS`.
* Si no se llama LLM, revisa `LLM_COMMAND_MODE`; `off` nunca llama LLM.
* Si no se llama LLM, revisa `ENABLE_OLLAMA_FALLBACK`; debe ser `true` salvo en modo `primary`.
* Si un tamaño no se acepta, revisa `ALLOW_DYNAMIC_SIZE_INCHES`, `MIN_SIZE_INCHES` y `MAX_SIZE_INCHES`.
* Usa `POST /v1/commands/debug` en development para ver `completeness` y decisión LLM.

### Seguridad

La LLM propone comandos, pero el API valida la salida antes de aceptarla:

* No acepta comandos fuera de `CommandName`.
* No acepta monitores fuera de `1` o `2`.
* No acepta layouts fuera de `1` o `2`.
* No acepta tamaños fuera del rango configurado.
* No ejecuta texto libre generado por la LLM.

---

## Recommended settings for real doctor testing

Para pruebas reales con doctores, usa un perfil más preciso que el perfil rápido de Docker desarrollo:

```bash
ENABLE_SEMANTIC_MATCHER=true
TRANSCRIPTION_MODEL_NAME=base
TRANSCRIPTION_COMPUTE_TYPE=int8
FUZZY_THRESHOLD=86
SEMANTIC_THRESHOLD=0.72
SEMANTIC_CONFIRMATION_THRESHOLD=0.62
MAX_AUDIO_DURATION_SECONDS=30
```

Si la máquina tiene CPU/RAM suficiente, puedes probar:

```bash
TRANSCRIPTION_MODEL_NAME=small
```

Notas prácticas:

* `tiny` es rápido y útil para desarrollo, pero comete más errores de transcripción.
* `base` es el recomendado inicial para prueba real porque mejora precisión sin ser demasiado pesado.
* `small` mejora precisión, pero consume más recursos y tarda más en cargar.
* `ENABLE_SEMANTIC_MATCHER=true` ayuda con frases naturales no vistas en reglas o fuzzy matching.
* Las reglas exactas y entidades siguen teniendo prioridad sobre fuzzy y semantic matcher; por ejemplo, `pantalla dos en 55` debe resolverse por entidad/regla antes que por embeddings.
* Revisa el estado efectivo con `GET /v1/audio/status`; devuelve modelo actual de transcripción, estado del semantic matcher, versión activa de catálogo y si hay cambios pendientes por publicar.

---

## Audio transcription

El API puede recibir archivos `.ogg`, `.mp3` o `.m4a`.

La transcripción usa `faster-whisper` de forma local/offline y carga el modelo de manera lazy: no se descarga ni se inicializa hasta que llamas un endpoint de audio o haces warmup manual.

Comportamiento actual:

* puede transcribir solamente
* puede transcribir y luego normalizar el texto transcrito con el pipeline existente
* no guarda el audio por defecto
* el archivo subido se guarda solo de forma temporal
* el audio temporal se borra después de procesarlo

### Variables de entorno de audio

```bash
ENABLE_AUDIO_TRANSCRIPTION=true
TRANSCRIPTION_ENGINE=faster_whisper
TRANSCRIPTION_MODEL_NAME=base
TRANSCRIPTION_DEVICE=cpu
TRANSCRIPTION_COMPUTE_TYPE=int8
TRANSCRIPTION_BEAM_SIZE=1
TRANSCRIPTION_VAD_FILTER=false
TRANSCRIPTION_LANGUAGE_DEFAULT=
MAX_AUDIO_FILE_MB=10
MAX_AUDIO_DURATION_SECONDS=30
ALLOWED_AUDIO_EXTENSIONS=.ogg,.mp3,.m4a
ALLOWED_AUDIO_MIME_TYPES=audio/ogg,audio/mpeg,audio/mp3,audio/mp4,audio/x-m4a,application/octet-stream
AUDIO_TEMP_DIR=/tmp/voice-command-audio
ENABLE_AUDIO_TRANSCRIPTION_LOGS=true
```

### Endpoints de audio

```text
GET  /v1/audio/status
POST /v1/audio/warmup
POST /v1/audio/transcribe
POST /v1/audio/normalize
```

### Ejemplo `status`

```bash
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer ${API_TOKEN}"
```

Campos relevantes:

* `model`: modelo efectivo de transcripción (`tiny`, `base`, `small`, etc.).
* `semantic_matcher_enabled`: indica si el semantic matcher está activo.
* `active_catalog_version`: versión activa publicada del catálogo, o `null` si todavía no se publicó.
* `catalog_dirty`: `true` si hay cambios pendientes de publicar desde el panel admin.

### Ejemplo `transcribe`

```bash
curl -X POST http://localhost:8000/v1/audio/transcribe \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -F "file=@sample.m4a" \
  -F "language_hint=es"
```

Respuesta de ejemplo:

```json
{
  "ok": true,
  "text": "monitor dos y acercalo",
  "language": "es",
  "duration_seconds": 1.84,
  "engine": "faster_whisper",
  "model": "base",
  "segments": [
    {
      "start": 0.0,
      "end": 1.84,
      "text": "monitor dos y acercalo"
    }
  ],
  "message": null
}
```

### Ejemplo `normalize`

```bash
curl -X POST http://localhost:8000/v1/audio/normalize \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -F "file=@sample.ogg" \
  -F "language_hint=es" \
  -F 'context_json={"selected_monitor":null}'
```

Respuesta de ejemplo:

```json
{
  "ok": true,
  "transcription": {
    "ok": true,
    "text": "monitor dos y acercalo",
    "language": "es",
    "duration_seconds": 1.84,
    "engine": "faster_whisper",
    "model": "base",
    "segments": [
      {
        "start": 0.0,
        "end": 1.84,
        "text": "monitor dos y acercalo"
      }
    ],
    "message": null
  },
  "normalization": {
    "ok": true,
    "raw_text": "monitor dos y acercalo",
    "normalized_text": "monitor dos y acercalo",
    "language": "es",
    "commands": [
      {
        "command": "SELECT_MONITOR",
        "confidence": 1.0,
        "method": "entity_rule",
        "monitor": 2,
        "layout": null,
        "size_inches": null,
        "value": null,
        "raw_fragment": "monitor dos"
      },
      {
        "command": "ZOOM_IN",
        "confidence": 1.0,
        "method": "exact_rule",
        "monitor": null,
        "layout": null,
        "size_inches": null,
        "value": null,
        "raw_fragment": "acercalo"
      }
    ],
    "needs_confirmation": false,
    "message": null
  },
  "message": null
}
```

### Recomendación de modelos

* `tiny`
  Más rápido, menor precisión. Bueno para desarrollo y pruebas locales rápidas.
* `base`
  Balance inicial recomendado para empezar.
* `small`
  Mejor precisión, pero más pesado en CPU/RAM y más lento al cargar.

### Notas de producción

* limita tamaño con `MAX_AUDIO_FILE_MB`
* limita duración con `MAX_AUDIO_DURATION_SECONDS`
* no guardes audio si no es estrictamente necesario
* usa HTTPS si recibes audio desde clientes externos
* considera colas o workers si vas a procesar audios largos o concurrencia alta
* no actives warmup automático si el servidor tiene poca RAM

En Docker Compose de desarrollo se usa por defecto:

* `TRANSCRIPTION_MODEL_NAME=tiny`
* `TRANSCRIPTION_DEVICE=cpu`
* `TRANSCRIPTION_COMPUTE_TYPE=int8`

Eso permite probar audio localmente sin forzar un modelo más pesado al arrancar el stack.

## Docker Audio

Con Docker Compose, la API monta dos volúmenes útiles para audio:

* `hf_cache:/root/.cache/huggingface`
  Persistencia del caché de modelos para evitar descargas repetidas.
* `audio_tmp:/tmp/voice-command-audio`
  Directorio temporal para uploads de audio mientras se procesan.

Flujo esperado:

```bash
docker compose up --build
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer ${API_TOKEN}"
```

El modelo de transcripción no se precarga al startup. Se carga la primera vez que uses:

* `POST /v1/audio/transcribe`
* `POST /v1/audio/normalize`
* `POST /v1/audio/warmup`

---

## Audio troubleshooting

Si la parte de audio no responde como esperas, revisa esto:

* La primera llamada puede ser lenta porque el modelo puede descargarse o inicializarse en el primer uso.
* Para desarrollo usa `TRANSCRIPTION_MODEL_NAME=tiny`; carga más rápido y consume menos recursos.
* Si quieres desactivar completamente audio, usa `ENABLE_AUDIO_TRANSCRIPTION=false`.
* Revisa el estado efectivo con:

```bash
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer ${API_TOKEN}"
```

* Si quieres cargar manualmente el modelo antes de la primera transcripción, usa:

```bash
curl -X POST http://localhost:8000/v1/audio/warmup \
  -H "Authorization: Bearer ${API_TOKEN}"
```

* No actives warmup automático si el servidor tiene poca RAM; es mejor mantener lazy loading.

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
GET  /v1/audio/status
GET  /v1/commands/catalog
GET  /v1/commands/examples
POST /v1/audio/warmup
POST /v1/audio/transcribe
POST /v1/audio/normalize
POST /v1/commands/normalize
POST /v1/commands/warmup
POST /v1/commands/debug
```

Notas:

* `POST /v1/audio/warmup` carga manualmente el modelo de transcripción sin procesar un archivo real.
* `POST /v1/audio/transcribe` solo transcribe audio y devuelve texto.
* `POST /v1/audio/normalize` transcribe audio y luego ejecuta el normalizer existente.
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

Para crear la primera versión activa del catálogo y evitar `Active Version: none` en el panel admin:

```bash
python -m app.db.publish_initial_catalog
```

Ese comando usa el catálogo sembrado en MySQL, crea una `CatalogVersion` activa, marca `CATALOG_DIRTY=false`, limpia cachés y reconstruye índices runtime si el semantic matcher está habilitado.

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
  -H "Authorization: Bearer ${API_TOKEN}" \
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
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"monitor one"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"selecciona monitor dos"}'
```

---

## Mover monitor

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"left"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"mueve el monitor a la derecha"}'
```

---

## Zoom

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"zoom in"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"acercalo"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"zoom out"}'
```

---

## Tamaño del monitor

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"increase"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"hazlo más grande"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"decrease"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"ponlo en 65 pulgadas"}'
```

---

## Layouts

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"layout one"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"layout dos"}'
```

---

## Seguimiento y posición

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"follow me"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"stop follow me"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"recenter objects"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"reset position"}'
```

---

## Paneles y UI

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"show aitrol"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"close aitrol"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"show voice commands"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"close voice commands"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"settings"}'
```

---

## Captura, stream y grabación

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"capture"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"stream"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"record"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"stop stream"}'
```

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"stop"}'
```

---

## Multi-comando

```bash
curl -X POST http://localhost:8000/v1/commands/normalize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
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
  -H "Authorization: Bearer ${API_TOKEN}" \
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
curl -X POST http://localhost:8000/v1/commands/warmup \
  -H "Authorization: Bearer ${API_TOKEN}"
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

Generar un reporte de cobertura NLU con frases críticas:

```bash
python scripts/nlu_coverage_report.py
```

Por defecto el reporte desactiva semantic matcher para evitar descargas de modelo durante diagnóstico local. Para incluir embeddings:

```bash
python scripts/nlu_coverage_report.py --semantic
```

## Production NLU coverage report

Ejecutar el reporte contra el fixture de frases naturales de producción:

```bash
python scripts/nlu_coverage_report.py --fixture tests/fixtures/production_natural_phrases.json
```

Exigir una cobertura mínima y fallar con código `1` si no se cumple:

```bash
python scripts/nlu_coverage_report.py \
  --fixture tests/fixtures/production_natural_phrases.json \
  --min-coverage 95
```

El reporte muestra total de frases, passed, failed, coverage, fallos por comando esperado, frases con `UNKNOWN`, frases con `needs_confirmation=true`, entidades faltantes y los 20 fallos más críticos.

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
* Definir `API_AUTH_TOKEN`; en producción es obligatorio para `/v1/*`.
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
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d '{"text":"ponlo como pantalla grande"}'
```

---

# Notas

* El API recibe texto ya transcrito y también puede recibir audio en `/v1/audio/transcribe` y `/v1/audio/normalize`.
* El audio no se guarda como archivo permanente.
* El idioma puede enviarse en `language_hint`, pero no es obligatorio.
* Los comandos internos deben mantenerse estables.
* Las frases de usuario se amplían en `catalog.yml`.
* No se necesita una LLM pagada para la primera versión.
* Ollama es opcional y solo se recomienda como fallback.
