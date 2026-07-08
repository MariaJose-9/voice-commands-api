# Voice To Commands Usage

Guía práctica para usar el endpoint principal del sistema: recibir un audio de voz y devolver comandos canónicos.

## Endpoint Principal

```http
POST /v1/audio/normalize
```

Este endpoint hace todo el flujo:

```text
audio .ogg/.mp3/.m4a/.mp4/.wav/.webm/.aac/.flac
  -> transcripción local
  -> normalización de comandos
  -> JSON con comandos canónicos
```

URL local:

```text
http://localhost:8000/v1/audio/normalize
```

## Documentación Interactiva

FastAPI ya genera documentación automática. No hace falta agregar otra librería:

```text
http://localhost:8000/docs
http://localhost:8000/openapi.json
```

## Autenticación

En `development`, el token puede estar vacío.

En `production`, `API_AUTH_TOKEN` es obligatorio para `/v1/*`.

Header recomendado:

```http
Authorization: Bearer <API_AUTH_TOKEN>
```

También se acepta:

```http
X-API-Token: <API_AUTH_TOKEN>
```

## Request

El endpoint recibe `multipart/form-data`.

Campos:

* `file`: requerido. Archivo de audio `.ogg`, `.mp3`, `.m4a`, `.mp4`, `.wav`, `.webm`, `.aac` o `.flac`.
* `language_hint`: opcional. Ejemplo: `es`, `en`.
* `context_json`: opcional. JSON string con contexto del cliente.

Ejemplo:

```bash
curl -X POST http://localhost:8000/v1/audio/normalize \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@sample.mp3" \
  -F "language_hint=es"
```

Con token:

```bash
curl -X POST http://localhost:8000/v1/audio/normalize \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@sample.mp3" \
  -F "language_hint=es"
```

Con contexto:

```bash
curl -X POST http://localhost:8000/v1/audio/normalize \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@sample.ogg" \
  -F "language_hint=es" \
  -F 'context_json={"selected_monitor":null}'
```

## Response

Respuesta resumida:

```json
{
  "ok": true,
  "transcription": {
    "ok": true,
    "text": "redimensiona a 72 pulgadas el monitor 1",
    "language": "es",
    "duration_seconds": 3.2,
    "engine": "faster_whisper",
    "model": "base",
    "segments": [
      {
        "start": 0.0,
        "end": 3.2,
        "text": "redimensiona a 72 pulgadas el monitor 1"
      }
    ],
    "message": null
  },
  "normalization": {
    "ok": true,
    "raw_text": "redimensiona a 72 pulgadas el monitor 1",
    "normalized_text": "redimensiona a 72 pulgadas el monitor 1",
    "language": "es",
    "commands": [
      {
        "command": "SELECT_MONITOR",
        "confidence": 1.0,
        "method": "entity_rule",
        "monitor": 1,
        "layout": null,
        "size_inches": null,
        "value": null,
        "raw_fragment": "monitor 1"
      },
      {
        "command": "SET_SIZE",
        "confidence": 0.9,
        "method": "llm",
        "monitor": null,
        "layout": null,
        "size_inches": 72,
        "value": null,
        "raw_fragment": "redimensiona a 72 pulgadas"
      }
    ],
    "needs_confirmation": false,
    "message": "LLM used: incomplete_result; Completed with LLM"
  },
  "message": null
}
```

## Comandos Esperados

Ejemplos de audio/transcripción y salida esperada:

```text
"monitor 1" -> SELECT_MONITOR monitor=1
"pantalla dos a la derecha" -> SELECT_MONITOR monitor=2 + MOVE_RIGHT
"pon pantalla 2 en 55" -> SELECT_MONITOR monitor=2 + SET_SIZE size_inches=55
"redimensiona a 72 pulgadas el monitor 1" -> SELECT_MONITOR monitor=1 + SET_SIZE size_inches=72
"haz mas grande el monitor uno" -> SELECT_MONITOR monitor=1 + INCREASE_SIZE
"reduce el monitor dos" -> SELECT_MONITOR monitor=2 + DECREASE_SIZE
"abre comandos de voz" -> SHOW_VOICE_COMMANDS
"deten stream" -> STOP_STREAM
```

## Formatos De Audio

Permitidos por defecto:

```text
.ogg
.mp3
.m4a
.mp4
.wav
.webm
.aac
.flac
```

Límites por defecto:

```text
MAX_AUDIO_FILE_MB=10
MAX_AUDIO_DURATION_SECONDS=30
```

## No Se Guarda El Audio

El archivo se guarda temporalmente solo para procesarlo y luego se borra.

El sistema puede guardar logs de metadata/transcripción si `ENABLE_AUDIO_TRANSCRIPTION_LOGS=true`, pero no guarda el archivo de audio.

Si el decodificador directo falla para un formato permitido, el servicio intenta convertir el archivo a WAV mono 16 kHz con `ffmpeg` y reintenta la transcripción.

## Probar Estado De Audio

```bash
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer your-secret-token"
```

Con token en producción:

```bash
curl http://localhost:8000/v1/audio/status \
  -H "Authorization: Bearer your-secret-token"
```

## Warmup Opcional

El modelo se carga lazy en la primera llamada. Para cargarlo manualmente:

```bash
curl -X POST http://localhost:8000/v1/audio/warmup \
  -H "Authorization: Bearer your-secret-token"
```

Con token:

```bash
curl -X POST http://localhost:8000/v1/audio/warmup \
  -H "Authorization: Bearer your-secret-token"
```

## Errores Comunes

Token faltante o inválido:

```json
{
  "detail": "Invalid or missing API token."
}
```

Token no configurado en producción:

```json
{
  "detail": "API_AUTH_TOKEN must be configured in production."
}
```

Archivo inválido:

```json
{
  "detail": "Invalid audio file extension."
}
```

Audio demasiado grande o largo:

```json
{
  "detail": "Audio file is too large."
}
```

Fallo de transcripción de `.mp4`:

```json
{
  "detail": "Failed to transcribe audio file: ..."
}
```

`.mp4` es un contenedor. Si viene desde móvil, puede tener una pista de audio o codec no decodificable por el runtime actual. Revisa logs y codec:

```bash
docker compose logs -f api
docker compose exec api ffmpeg -i /tmp/voice-command-audio/archivo.mp4
```

## Configuración Recomendada

Para desarrollo rápido:

```env
TRANSCRIPTION_MODEL_NAME=tiny
ENABLE_SEMANTIC_MATCHER=false
```

Para prueba real:

```env
TRANSCRIPTION_MODEL_NAME=base
TRANSCRIPTION_COMPUTE_TYPE=int8
ENABLE_OLLAMA_FALLBACK=true
LLM_COMMAND_MODE=hybrid
ALLOW_DYNAMIC_SIZE_INCHES=true
```

Para producción:

```env
ENV=production
API_AUTH_TOKEN=replace-with-a-long-random-token
ALLOWED_ORIGINS=https://your-app.example.com
```

## Resumen

El endpoint principal para clientes externos es:

```http
POST /v1/audio/normalize
```

Ese es el flujo recomendado para integrar voz a comandos.
