# TikTok Lives

Herramienta local para grabar, transcribir y explorar clips de TikTok Lives. Graba streams en vivo, transcribe el audio, indexa sesiones con embeddings y permite busqueda semantica de momentos interesantes.

## Estructura

```
apps/
  recorder/     Grabacion de lives + monitoreo de chat, batallas y regalos
  cli/          Transcripcion, indexacion y busqueda semantica de clips
  backend/      API REST (FastAPI) para explorar clips y sesiones
  app-backoffice/  Dashboard web (Astro + Tailwind)
```

## Requisitos

- Python 3.12+
- [uv](https://docs.astro.build/en/install-and-setup/) para gestionar entornos Python
- [ffmpeg](https://ffmpeg.org/) en PATH (o configurado en `.env`)
- Node.js 18+ (solo para el backoffice)

## Setup

Cada app tiene su propio `pyproject.toml` y venv. Se ejecutan siempre con `uv run`:

```bash
# Instalar dependencias de cada app
cd apps/recorder && uv sync
cd apps/cli && uv sync
cd apps/backend && uv sync

# Backoffice
cd apps/app-backoffice && npm install
```

Crear un `.env` en la raiz con:

```
HF_HUB_CACHE=D:\files\models
PYTHONIOENCODING=utf-8
```

## Uso

### 1. Grabar un live

```bash
cd apps/recorder
uv run src/record_tiktok_live.py <username>
```

Genera `material/{user}/{date}/live_full.ts` (reproducible en VLC en tiempo real).

### 2. Extraer audio

```bash
ffmpeg -i live_full.ts -vn -acodec libopus -b:a 64k live_audio.opus
```

### 3. Transcribir

```bash
cd apps/cli

# Local con faster-whisper
uv run src/transcribe.py <audio_file> [model]

# Via Groq API
uv run src/transcribe_groq.py <audio_file>
```

Genera archivos `.srt` y `.txt` junto al audio.

### 4. Indexar sesion

```bash
cd apps/cli
uv run src/index_session.py <session_dir> --srt <file.srt>
```

### 5. Buscar clips

```bash
cd apps/cli
uv run src/find_clips.py "<query>"
```

### 6. Levantar el backend + backoffice

```bash
# API
cd apps/backend
uv run uvicorn src.main:app --reload --port 8000

# Dashboard
cd apps/app-backoffice
npm run dev
```

## Monitoreo en tiempo real

El recorder incluye spies que capturan eventos durante la grabacion:

- **chat_spy** — mensajes del chat
- **battle_spy** — batallas entre streamers
- **treasure_spy** — regalos y cofres
- **ventanilla_spy** — eventos de ventanilla
- **profile_checker** — verificacion de perfiles
- **watchdog** — monitoreo de salud del proceso

## Stack

| Componente | Tecnologia |
|---|---|
| Grabacion | yt-dlp + ffmpeg + TikTokLive |
| Transcripcion | faster-whisper, Groq API, AssemblyAI |
| Embeddings | sentence-transformers |
| Base de datos | SQLite (via better-sqlite3 / sqlite3) |
| Backend API | FastAPI + uvicorn |
| Frontend | Astro + Tailwind CSS |
