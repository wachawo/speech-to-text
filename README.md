# STT Server

`stt_server.py` is an HTTP speech-to-text service built with Flask and served by uvicorn.
The BEST Server model for English is `turbo`

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

Example success response:

```json
{
  "text": "transcribed text",
  "elapsed": 1.23
}
```

Error responses are uniform — `error` carries a generic category, `request_id`
correlates the response to log entries (search the server log by it for full
exception details):

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

## Environment variables

Server:

- `STT_HOST` (default: `0.0.0.0`)
- `STT_PORT` (default: `5099`)
- `STT_POOL_SIZE` (default: `8`)
- `STT_DEBUG` (default: `false`)
- `WHISPER_MODEL` (default: `turbo`)
- `WHISPER_LANGUAGE` (default: `en`)
- `WHISPER_DOWNLOAD_ROOT` (default: `models`; in Docker: `/opt/models`)
- `STT_TOKENS` (default: empty) — comma-separated list of valid static tokens.
  When empty, **auth is disabled** and all requests are accepted. When set, every
  `POST /api/stt` must carry `Authorization: Bearer <token>`; missing or invalid
  token returns `401 {"error": "Unauthorized", "request_id": "..."}`.
  `GET /api/health` is always reachable without a token (so docker-compose
  healthchecks keep working).

Client (`stt_client.py`):

- `STT_URL` (default: `http://localhost:5099`)
- `STT_TOKEN` (default: empty) — single token sent as `Authorization: Bearer
  <token>` to the server. Leave empty when the server has no `STT_TOKENS`.

Model files are stored in `./models` on host via the `./models:/opt/models` mount in `docker-compose.yml`.

## Local commands

Install Python dependencies into whichever environment you prefer
(`requirements.txt` for runtime, `requirements-dev.txt` for runtime + dev/test
tools). System packages `ffmpeg` and `libsndfile1` must be present. The
Makefile invokes `python3`, `gunicorn`, `pytest` and `pre-commit` from `PATH`.

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

`requirements-dev.txt` references `requirements.txt` and adds `pytest`,
`pre-commit`, `black`, `ruff`. There is no separate `requirements-test.txt`.

To install pre-commit hooks (so `git commit` runs black + ruff):

```bash
pre-commit install
```

## Docker

Both Dockerfiles use `uv` to install Python dependencies (much faster than pip).

```bash
docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU
```

GPU build needs `nvidia-container-toolkit` on the host.

## Continuous integration

`.github/workflows/ci.yml` runs two jobs on `push` and `pull_request` to `main`:

- **lint** — `pre-commit run --all-files` (black + ruff).
- **test** — installs `requirements-dev.txt` via `uv` and runs `pytest`.

Test suite stubs `libs.stt` so it doesn't exercise the actual Whisper backend —
it covers the HTTP layer (request_id, error categories, leak regression, model
pool semantics) and runs in seconds.
