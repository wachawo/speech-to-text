# STT Server

`stt_server.py` is an HTTP speech-to-text service built with Flask and served by uvicorn.

Backend: **openai-whisper**.

## What the server does

- Loads a pool of Whisper model instances at startup (`STT_POOL_SIZE`)
- Accepts audio files via HTTP and returns transcription text
- Converts input audio to WAV before inference
- Exposes a health endpoint with model pool status

## Endpoints

### `GET /api/health`

Returns server status and model availability.

Example response:

```json
{
  "status": "ok",
  "pool_size": 4,
  "available": 3
}
```

### `POST /api/stt`

Transcribes uploaded audio.

- `multipart/form-data` with field `file`
- or raw binary body (`audio/*`)

Example response:

```json
{
  "text": "transcribed text",
  "elapsed": 1.23
}
```

## Environment variables

- `STT_HOST` (default: `0.0.0.0`)
- `STT_PORT` (default: `5099`)
- `STT_POOL_SIZE` (default: `8`)
- `STT_DEBUG` (default: `false`)
- `WHISPER_MODEL` (default: `small.en`)
- `WHISPER_LANGUAGE` (default: `en`)
- `WHISPER_DOWNLOAD_ROOT` (default: `models`; in Docker: `/opt/models`)

Model files are stored in `./models` on host via the `./models:/opt/models` mount in `docker-compose.yml`.

## Local server commands

```bash
make install
make start
make stop
make run
```

- `make start` — starts server in background, writes PID to `.stt_server.pid`, logs to `logs/stt_server.log`
- `make stop` — stops the background server by PID
- `make run` — runs server in foreground (console mode)
