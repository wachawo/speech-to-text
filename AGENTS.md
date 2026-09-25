# AGENTS.md

Conventions and context for anyone working in this repository, human or tooling.

## What this is

A single-process Flask + uvicorn HTTP service wrapping `openai-whisper` for speech-to-text, with a browser UI in `www/` served by its own nginx container. No database, no background worker - just `stt_server.py` (app wiring, routes, entry point), `stt_client.py` (a CLI that POSTs files to it), `gu.py` (Gunicorn config and hooks) and the `libs/` package holding everything else: `config.py`, `logs.py`, `errors.py`, `auth.py`, `audio.py`, `model_pool.py`, `stt.py`, `diarize.py`.

## Architecture

- **One module, one job.** `libs/config.py` is the only place `os.getenv` is called and the only place `load_dotenv` runs - enforced, nothing else in the repo calls either. Import it as `from libs import config` and read `config.X` at call time, never `from libs.config import X`: the tests monkeypatch `config` attributes and a copied name would not see the patch. The one exception is `gu.py`, which imports it as `stt_config`: gunicorn treats every module-level name in its config file that matches a setting as that setting, and `config` is one.
- **Model pool, not a model singleton.** `libs/model_pool.py::init_model_pool()` pre-loads `STT_POOL_SIZE` Whisper instances into a `queue.Queue`. Each `/api/stt` request calls `acquire_model()`, runs `stt.get_stt_bio()`, and `release_model()`s it in `finally`. Pool exhaustion returns 503. This is what makes the server safe under concurrency, because Whisper itself is not thread-safe.
- **Each backend describes itself.** `libs/catalog.py` assembles `GET /api/models` from a `describe_backend()` in each backend module, then upgrades `status` to `loaded` by looking at the pools. The catalogue must keep working when a backend cannot describe itself, so the failure is logged and that row is skipped. `libs/catalog.py` must never import `whisper` or `transformers` directly: CI installs only `.[dev]`, which has neither, and the backend modules are what the tests replace.
- **Whisper's language list is derived from the checkpoint NAME, not by loading it.** The large-v3 lineage knows 100 codes, every other multilingual checkpoint the first 99, a `.en` checkpoint one. And the name is not the filename: `turbo` downloads as `large-v3-turbo.pt`, so an installed check that compares the configured name against the directory listing reports a running model as missing. Resolve through `whisper._MODELS`.
- **Two transcribers, one at a time.** `libs/backends.py` maps `STT_BACKEND` to a module, and every transcriber module exports the same four names with the same signatures: `get_model`, `get_stt_bio`, `get_stt_segments`, `describe_backend`. Callers resolve the **module** and then call it by name - `backends.transcriber().get_stt_bio(...)`. A dispatcher that resolved the function instead would leave three tests patching `stt.get_stt_bio` intercepting nothing, and they would keep passing while testing nothing. An unknown `STT_BACKEND` logs and falls back rather than failing to start.
- **Parakeet takes no language.** It detects it, so `normalize_language_code` deliberately does not exist on that module and `resolve_language` accepts the value and ignores it rather than checking it against a foreign table. The catalogue says `accepts_language: false`. Its 25 language codes are in no config file the runtime can read, so they are a constant in `libs/parakeet.py` carrying the date and the model id they were read for, and an id outside that table reports `null` rather than a guess.
- **The join merges runs only when nobody else spoke in between.** Two segments of one speaker with another speaker's diarized turn in the gap stay separate, even when the transcriber produced no words for that turn - otherwise the output claims one person talked through the other. Parakeet feeds the join **words**, not phrases: a silence threshold long enough to keep one person's sentence together is longer than a normal handover.
- **Parakeet can drop speech silently.** It detects the language once per file, and on the deployment host it produced no tokens at all for an English voice inside a Russian recording - about half the English in a three-minute mixed meeting - and also skipped fragments of the main language it was unsure of. The response is a 200 with no sign anything was lost. A mixed-language conversation may lose its minority language under this backend; Whisper with an explicit `language` does not have this failure mode.
- **Nothing installable here solves overlapping speech.** The join in `libs/align.py` attributes each transcription segment to the speaker turn it overlaps most, and NVIDIA states plainly that this is not equivalent to a model built for overlap: the range still contains every voice inside it. The overlap-aware model, Multitalker Parakeet, ships only as a NeMo checkpoint and NeMo is ruled out by the torch pin. Say this rather than approximating it.
- **`word_timestamps=True` is not used and must not be added casually.** It rewrites `seek` from the end of the last word and clears zero-length segments whose tokens then never reach the text, so it can change the transcription the decoding settings fix on purpose. Segment times come free from the same unmodified call.
- **Diarization is a second model, and it produces no text.** `libs/diarize.py` wraps `nvidia/Nemotron-3-Diarization`, which emits a `[T, 8]` per-frame activity tensor that becomes `{speaker, start, end}` turns. Whisper is what produces words; pairing the two is what would produce a speaker-attributed transcript. Turns may overlap (each speaker channel is scored independently) and the labels are arrival-order positions in one recording, never identities, so nothing may present them as named people. Eight speakers is the ceiling.
- **Two pools, not one queue with two kinds.** `MODEL_POOL` and `DIARIZER_POOL` are separate queues in `libs/model_pool.py`. A queue hands out whatever is at its head and has no notion of kind, so mixing them would make every caller check what it got. `init_diarizer_pool()` is a no-op unless `DIARIZE_ENABLED`, and both pools fill inside the one `flock` in `gu.py::post_fork` because both models download on first run.
- **The diarizer needs transformers from git.** The model declares `transformers_version 5.18.0.dev0`; the newest PyPI release is 5.17.0 and answers `AutoConfig` with "model type `nemotron3_diarization` but Transformers does not recognize this architecture", and the repository ships no custom modeling code, so `trust_remote_code` is not a way around it. The pin is a commit SHA in `requirements-diarize.txt` and the `diarize` extra. Replace it with a version pin once 5.18.0 ships.
- **The GPU image asserts its own torch.** `Dockerfile` installs a `+cu130` wheel and then runs further unconstrained resolutions; anything depending on torch can replace it, and the failure surfaces much later as cuBLAS and cuDNN errors that read like a driver problem. A `RUN python3 -c "assert '+cu130' in torch.__version__"` turns that into a build failure. Do not remove it, and add the same shape of check for any new pin that matters.
- **Two run modes, two pool semantics:**
  - **Direct (`python3 stt_server.py`)** - one process; the pool lives in it and `STT_POOL_SIZE` is the real concurrency limit.
  - **Gunicorn (`gunicorn --config gu.py stt_server:app`)** - `worker_class = "sync"`, `GUNICORN_WORKERS` processes; each worker calls `init_model_pool` from `post_fork` under an `flock` on `/tmp/.stt_model_init.lock` so only one downloads the model. With sync workers `STT_POOL_SIZE=1` per worker is intentional - concurrency comes from worker count. **Do not switch to `gthread`**: PyTorch's MKL/OpenBLAS thread pools deadlock with Gunicorn threads.
- **Torch must never load before `fork()`.** `libs/stt.py`, and therefore `libs/model_pool.py`, pulls in torch and whisper. `gu.py` imports `init_model_pool` inside `post_fork`, not at module scope. The tests rely on the same boundary - `tests/conftest.py` replaces `sys.modules["libs.stt"]` with a stub before importing `stt_server`, so the suite needs neither torch nor whisper.
- **Audio path.** `libs/audio.py::convert_to_wav()` decodes the upload through pydub and exports 16 kHz mono 16-bit WAV to a `BytesIO` before `stt.get_stt_bio()` sees it. The server does the resampling so `libs/stt.py` skips its torchaudio resample branch on the hot path. Changing one side means keeping this contract intact.
- **Determinism is deliberate.** `get_stt_bio` seeds torch + numpy and decodes with `temperature=0.0, beam_size=1, best_of=1, condition_on_previous_text=False`. Don't relax these without a reason - the goal is stable output for repeated identical inputs.
- **CPU vs GPU is environment-only.** The same Python code runs both; `COMPUTE_TYPE` (`cpu` / `cuda` / `auto`) plus the chosen Dockerfile/compose file select the backend. `Dockerfile` + `docker-compose.yml` (CUDA 13.0, `torch+cu130`) and `Dockerfile-cpu` + `docker-compose-cpu.yml` are the two parallel images.
- **The web UI is static files behind nginx.** `stt_www` (`Dockerfile-www`, `nginx/`) serves `www/` and proxies `/api/` to `stt_server`, so the browser and the API share one origin and CORS never comes into it. It follows the sibling text-to-speech project's UI file for file - vendored libraries under `www/vendor` and no CDN, `.vue` screens loaded by httpVueLoader, the same palette and shell - and the two should keep looking alike. `www/` is bind-mounted, so a UI change needs a browser reload, not a rebuild. The UI learns whether a token is needed from a `401` on `GET /api/models`: health is open and says nothing about auth.
- **One ASGI app, dispatched by path.** `stt_server.build_asgi_app()` sends the `/api/stream` websocket to `libs/live.py` and everything else to Flask through uvicorn's WSGI middleware. Dispatched, not mounted: mounting strips the prefix, and Flask would then answer its own 404 for `/health`. The socket exists only under uvicorn; gunicorn's sync workers and the Flask debug server serve Flask alone.
- **A live session borrows models per phrase.** `libs/stream.py` cuts phrases at pauses with an energy detector and transcribes each one with a model taken from `MODEL_POOL` for that phrase only, so a stream waits for uploads instead of starving them. The diarizer runs in its streaming mode (`libs/diarize.py::advance_stream`, the model card's loop) with the model's speaker cache kept in the session, which is what keeps speaker numbers stable for hours; it too borrows from its pool per call. Blocking calls go through `asyncio.to_thread`, and the event loop only moves audio.
- **A long silence must not grow the buffer.** With nothing to transcribe for a second, the worker catches the diarizer up and trims every sample nothing needs any more (`libs/live.py::find_keep_from`). Without it a quiet hour keeps an hour of audio in memory and leaves the diarizer an hour behind when speech resumes.
- **Containers start as root, then drop.** `entrypoint.sh` runs as root, chowns the bind-mounted `/opt/models`, `/opt/logs`, `/opt/recs` (host-owned mounts the build-time chown cannot reach) and `exec`s the command as `stt` via `setpriv`. Without it the first `whisper.load_model` dies with `PermissionError`.
- **The GPU is requested through CDI** (`devices: [nvidia.com/gpu=all]`), not `deploy.resources.reservations.devices`: with the latter a `systemctl daemon-reload` silently revokes device access on cgroup v2, and the failure surfaces as misleading cuDNN/cuBLAS errors. CDI needs `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` on the host, regenerated after driver updates.

## Commands

```bash
make run           # foreground: python3 stt_server.py
make start         # background via nohup; PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop          # kills the PID from .stt_server.pid (SIGTERM, then SIGKILL after 1s)
make gunicorn      # gunicorn --config gu.py stt_server:app

make test          # pytest with coverage (stubs Whisper; no model download, no GPU)
make lint          # pre-commit: black + ruff over the whole repo
make typecheck     # mypy

docker compose up --build                            # GPU build (default)
docker compose -f docker-compose-cpu.yml up --build   # CPU build

python3 stt_client.py file.mp3 [file2 ...]   # respects STT_URL (default http://localhost:5099)
python3 stt_client.py --stream file.wav --speakers   # play a file into /api/stream in real time
python3 -m libs.stt file.wav                 # transcribe one file without the server
python3 -m libs.diarize file.wav             # speaker turns for one 16 kHz mono file

DIARIZE=true docker compose up --build       # GPU image WITH the diarization backend
```

Dev install is `pip install -e ".[dev]"`, which is also what CI runs. CI has two jobs: **lint** (`pre-commit run --all-files` plus `mypy`) and **test** (`pytest`). Both must pass before a PR is mergeable. A tag of the form `1.2.3` triggers **release**, which builds the wheel and sdist and cuts a GitHub Release from the matching `### [1.2.3]` section of `CHANGELOG.md` - so that section must exist before the tag is pushed. Docker images are **not** built in CI - changing a `COPY` line or `entrypoint.sh` needs a local `docker compose ... up --build`.

The project is an installable package. `pip install speech-to-text` gives the HTTP layer, the error handling and the CLI client; the transcription backend is the `whisper` extra, because `openai-whisper` pulls torch and that is the wrong default for someone who only wants to talk to a server. `requirements.txt` is the server's install, which does include the backend, and is what the Docker images use. Entry points: `stt-server` and `stt-client`.

## Environment

`.env` is loaded once, by `libs/config.py`. Variables actually consumed by the code:

- Server: `STT_HOST`, `STT_PORT`, `STT_POOL_SIZE`, `STT_DEBUG`, `LOG_LEVEL`, `LOG_ACCESS`
- Auth / limits / CORS: `STT_TOKENS` (comma-separated; empty disables auth), `MAX_CONTENT_LENGTH_MB`, `CORS_ORIGINS`
- Whisper: `WHISPER_MODEL`, `WHISPER_LANGUAGE`, `WHISPER_DOWNLOAD_ROOT` (host `models`, container `/opt/models`), `COMPUTE_TYPE`
- Transcription backend: `STT_BACKEND` (`whisper` or `parakeet`), `PARAKEET_MODEL`, `PARAKEET_DOWNLOAD_ROOT`. Parakeet only exists in an image built with `--build-arg PARAKEET=true`.
- Diarization: `DIARIZE_ENABLED`, `DIARIZE_MODEL`, `DIARIZE_POOL_SIZE`, `DIARIZE_DOWNLOAD_ROOT`, `DIARIZE_THRESHOLD`. Two knobs, deliberately separate: `DIARIZE` is a compose **build** arg deciding whether the backend is installed at all, `DIARIZE_ENABLED` is the **runtime** switch. Never pin `DIARIZE_ENABLED` in a compose `environment:` block, which overrides `env_file:` and would silently ignore `.env`.
- Gunicorn: `GUNICORN_WORKERS`
- Client: `STT_URL`, `STT_TOKEN`
- Web UI (compose only, never read by the Python code): `STT_WWW_PORT`, `STT_WWW_TLS_PORT`

Model `.pt` files live in `./models/` and are mounted at `/opt/models`, so the cache survives rebuilds.

## Endpoints

- `GET /api/health` - `{status, pool_size, available, diarize}`, plus `diarize_pool_size` and `diarize_available` when diarization is on. `available` at 0 means every model is in flight. Open, no token required, so healthchecks keep working.
- `POST /api/stt` - multipart field `file` or a raw `audio/*` body, optional `language` as a code (`ru`), an English name (`russian`) or `auto`. The value is resolved against the backend's own table, never against a regex: a shape check passes `zz`, which then raises inside the model and surfaces as a 500, and it refuses `russian`, which the model accepts. Returns `{text, elapsed}`. 400 on missing/bad audio, or on a language the backend does not know when that backend has `accepts_language: true` (Parakeet accepts and ignores any value), 401 without a valid token when `STT_TOKENS` is set, 413 over the size limit, 503 when the pool stays exhausted for 120s, 500 on Whisper errors.
- `GET /api/models` - the capability catalogue: `{default, models: [...]}`, one row per backend with its own `languages` list, `accepts_language`, and a three-valued `status` (`loaded` / `installed` / `absent`). Token-protected like everything except health. **Never merge the language lists into a top-level union**: Whisper knows 99 or 100 codes depending on the checkpoint, the diarizer knows none, and a union is wrong for each of them taken alone.
- `POST /api/transcript` - same body shapes, returns `{segments, turns, speakers, text, elapsed}`. Diarization runs first and its instance is **released before** a transcription model is borrowed: no request ever holds one of each, because the two pools have different sizes and different timeouts and holding both is how a deadlock starts. A segment no turn covers keeps `"speaker": null`. `overlap` marks contested speech and must stay visible in every surface that shows a transcript.
- `/api/stream` (websocket) - live transcription: a JSON `start` message, then raw 16 kHz mono PCM16 as binary messages, then `stop`; the server answers `ready`, a `segment` per phrase (`{id, start, end, text, speaker, overlap}`), `progress`, and `done`. Errors are one `{"type": "error", "error", "request_id"}` and a close. A browser sends its token in the start message, other clients may use the `Authorization` header.
- `POST /api/diarize` - same body shapes, returns `{segments, speakers, elapsed}` where each segment is `{speaker, start, end}`. 503 with `Diarization disabled` when `DIARIZE_ENABLED` is false, which is the default and the only thing a CPU build ever answers.
- Every error body is exactly `{"error": <category>, "request_id": <12 hex>}` (413 adds `limit_mb`). Details never reach the client - the full exception goes to the log under the same `request_id`. Build them with `libs/errors.py::build_error_response`, never by hand.

## Code conventions

Beyond PEP 8 and Python 3.12 defaults:

- **File header:** `#!/usr/bin/env python3`, `# -*- coding: utf-8 -*-`, then a one-line module docstring. Every file.
- **Every function has a docstring** - nested functions, Flask handlers, Gunicorn hooks and test helpers included.
- **No name starts with `_`.** Not for "private", not for callbacks, not for unused arguments (write `exception`, not `_exception`). Dunder methods are the only exception.
- **Function names are verb + noun** (`get_pool_status`, `build_error_response`, `convert_to_wav`).
- **Imports:** stdlib, then third-party, then a `# Local imports` block, then UPPER_CASE constants. No imports buried inside functions, except the deliberate torch-after-fork ones described above.
- **Every message goes through `logging`** - never `print`. Module-level `logger = logging.getLogger(__name__)`; `libs/logs.py::setup_logging()` configures the root logger, and only entry points call it. Log calls use lazy `%`-style formatting, not f-strings.
- **Exceptions log `type(exc).__name__`, `str(exc)` and `traceback.format_exc()`**, then return a generic body.
- **Every runnable file ends with `main()` + `if __name__ == "__main__": main()`**; module-only files get an empty `main()`.
- **No decorative comment banners** (`# ----`, `# ====`).
- **Functional style over classes.** Classes only for ORM models and framework subclasses; there are none here.
- **Do not add tests unless asked.** When behaviour changes, update the existing suite so it keeps passing.
- **A deliberately unused name is spelled `unused_something`**, never `_something`; ruff's `dummy-variable-rgx` is configured to accept exactly that prefix.
- `black` and `ruff` cover the whole repo (line length 128, target py312, rules `E,F,I,UP,B`, ignoring `E501,UP009`). Nothing is excluded except `models/`.
- **`mypy` must pass.** It runs over `libs/`, `stt_server.py`, `stt_client.py` and `gu.py` with `ignore_missing_imports`, so untyped third-party packages are fine; a real type error is not.

## Repo etiquette

- **English only** in everything that lands in the repo: code, comments, docstrings, log messages, commit messages, PR titles and bodies, README, CHANGELOG. The sole exception is `docs/README_<LANG>.md`, which are translations.
- **No em dash and no middle dot.** Use a spaced hyphen (` - `) as a separator, in prose, in UI strings and in log messages alike.
- **Branch per change**, PR into `main`. Never force-push to `main`.
- **`CHANGELOG.md` follows Keep a Changelog**; user-visible changes get an entry under `## [Unreleased]`. Release tags are a manual step, never automatic.
- **The ten `docs/README_<LANG>.md` translations mirror `README.md`.** A change to its Project structure or environment table belongs in all of them. Only three carry a translated file tree today (DE, FR, RU); the rest keep the English one.
- `.gitignore` applies a default-deny to root `*.md`: only `README.md`, `CHANGELOG.md`, `AGENTS.md` and `docs/*.md` are tracked.

## Local overlay

`CLAUDE.local.md` sits beside this file, is gitignored, and holds whatever is specific to one machine or one operator: deployment targets, host addresses, personal workflow rules. It is optional - a clone without it works fine, and the import below is simply skipped.

@CLAUDE.local.md
