## Changelog

### [Unreleased]

#### Added
- **Several pre-loaded transcription models, chosen per request.** `STT_MODELS` lists
  them as `backend:model[@pool]` entries, for example
  `whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1`, each with
  its own pool; `STT_DEFAULT_MODEL` names the one a request without `model` gets, else the
  first entry serves. Every model still loads at startup and nothing is ever loaded
  lazily. An entry without `@pool` takes `STT_POOL_SIZE`. With `STT_MODELS` empty the
  server loads exactly what `STT_BACKEND` / `WHISPER_MODEL` / `PARAKEET_MODEL` chose
  before. A malformed list, an unknown backend, the same weights listed twice (`turbo`
  and `large-v3-turbo`) or a default that is not in the list stops the server at startup.
  A file path is served under its basename without `.pt`, so the host's layout never
  reaches a client, and its languages are those of the checkpoint that name names
  (`/models/large-v3.pt` knows what `large-v3` knows). `STT_DEFAULT_MODEL` accepts a path
  entry by that name or as written in `STT_MODELS`. Two entries one name would select, or
  an entry served under a backend name, stop startup; a pool size must be plain digits, and
  an entry without `@pool` stops startup when `STT_POOL_SIZE` is below 1. A path entry's
  name is judged case-insensitively, so `/models/Tiny.EN.pt` is English-only like `tiny.en`.
- **`model` on `POST /api/stt` and `POST /api/transcript`**, as a query parameter or a form
  field: an id, an alias, `backend:model` or a bare backend name. A name nobody knows is
  `400 Invalid model`; a real model this server did not load is `400 Model not loaded`.
  Both are checked before the audio is decoded or an instance is borrowed.
- **`/api/stt` says which model transcribed and in which language.** The response gains
  `model` (the canonical id) and `language` (the code Whisper detected or used, always `en`
  for an English-only checkpoint, `null` for Parakeet, which does not report it).
  `/api/transcript` gains `model`.
- **`GET /api/models` has one row per loaded model**, each with `id`, `selectable`,
  `pool_size` and `available`, and the body gains `default_model`. A transcriber with
  nothing loaded keeps its single row, with `selectable: false`. `default` is still the
  default model's backend.
- **`stt_client.py --model NAME --language CODE`.** Both flags accept `--flag VALUE` and
  `--flag=VALUE` and are sent as form fields only when given; each result line shows the
  model and language the server used, and `--list` prints one line per model with its
  selectability and pool.
- **`GET /api/health` reports every pool.** `default_model` and `models` (per id: backend,
  pool size, available) join the top-level `pool_size` and `available`, which now describe
  the default model and are unchanged for a single-model deployment. With `STT_TOKENS`
  set, the model list is only included for a request carrying a valid token: it is
  configuration, like `/api/models`, and health itself stays open.
- **A model select in the web UI.** With several models loaded, TRANSCRIBE offers the
  selectable rows of `GET /api/models` beside the mode and the language, for the FILE and
  DEVICE sources alike: FILE sends it as the `model` form field, DEVICE in the stream's
  start message. The language list is the chosen model's own, the choice is remembered in
  the browser, and the line above a transcript names the model that produced it. The
  MODELS screen keys its rows by model id, so two Whisper models no longer collide. A
  server with one model shows no select and gets no `model`, exactly as before.
- **`model` in the `/api/stream` start message.** A live session names one of the loaded
  models the way `/api/stt` does, and every phrase borrows an instance from that model's
  pool; without it the default model serves. The language is checked against the chosen
  model, an unknown or unloaded model is one `error` message (`Invalid model` /
  `Model not loaded`) and a close, and `ready` names the model. `stt_client.py --stream`
  takes `--model`.
- **Live transcription in the web UI, and from a URL.** TRANSCRIBE gets a FILE / DEVICE
  switch: DEVICE captures a microphone, a headset, a loopback source or a browser tab's sound
  and shows each phrase as a block as soon as it is transcribed. Browsers allow audio devices
  only on a secure page, so over the network this works through the https listener.
  `/api/stream` also takes `"source": "url"`: the server reads internet radio, HLS, RTMP, RTSP
  or SRT itself through ffmpeg, which is held to network protocols so a URL or a playlist
  cannot make it read a local file.
- **Live transcription over a websocket, `/api/stream`.** The client sends raw 16 kHz PCM and
  gets each phrase back as soon as the speaker pauses - a median of 0.9 s after the end of the
  phrase on the deployment GPU. With `diarize` the diarizer runs in its streaming mode and
  keeps a speaker cache for the whole session, so speaker numbers hold for as long as it runs.
  Every phrase borrows a model from the same pool as the uploads and gives it back, so a live
  session delays under load instead of starving the uploads. `stt_client.py --stream` plays a
  file into it in real time.
- **A web UI.** `stt_www`, an nginx container beside the server, serves a Vue 2 UI with no
  build step and passes `/api/` through, so the browser and the API share one address.
  TRANSCRIBE uploads a file and shows plain text or, with diarization on, who said what with
  overlapping speech marked, ready to copy or download as TXT or JSON; MODELS shows the
  catalogue; a token screen appears only when the server asks for one. http on `STT_WWW_PORT`
  (8080), https with a self-signed certificate on `STT_WWW_TLS_PORT` (8443). It looks and is
  laid out like the text-to-speech project's UI, and its libraries are vendored, not fetched
  from a CDN.
- **NVIDIA Parakeet as a second transcription backend.** `STT_BACKEND=parakeet` serves
  `nvidia/parakeet-tdt-0.6b-v3`: 25 European languages, self-detected, with native
  token-level timestamps. Opt-in at build time (`--build-arg PARAKEET=true`) and needs no
  git pin, unlike the diarizer: `parakeet_tdt` ships in released transformers. It takes no
  `language` argument at all, and `GET /api/models` reports that rather than leaving a
  caller to discover it. The variant most write-ups name, v2, ships only as a NeMo
  checkpoint and is not installable against this project's pinned CUDA build of PyTorch;
  neither is the overlap-aware Multitalker model.
- **`POST /api/transcript`: who said what.** Diarization and transcription over the
  same audio, joined by time. Returns the attributed `segments`, the diarizer's raw
  `turns` beside them, the plain `text` and the speaker count. A phrase no turn covers
  keeps `"speaker": null` instead of being handed to the nearest speaker, and `overlap`
  marks a phrase somebody else was talking across. NVIDIA is explicit that this pairing
  is not equivalent to a model built for overlapping speech, and the README says so.
  The join is a pure function in `libs/align.py`, tested without any model.
- **`GET /api/models`: what this server actually carries.** One row per backend with its
  own language list, its model id and aliases, and a three-valued `status` -
  `loaded` when an instance waits in a pool, `installed` when the weights are on disk,
  `absent` otherwise. Language lists are per backend and never merged: Whisper knows 99
  or 100 codes depending on the checkpoint and the diarizer knows none, so a union would
  be wrong for both. `python3 stt_client.py --list` prints the same catalogue.
- **`POST /api/diarize`: who spoke when.** An optional second model,
  `nvidia/Nemotron-3-Diarization`, returns `{segments, speakers, elapsed}` where each
  segment is `{speaker, start, end}`. It produces no text; Whisper remains the only
  source of words. Turns may overlap, because each speaker channel is scored
  independently, and speaker numbers are arrival-order positions in one recording, not
  identities. Eight speakers is the ceiling.
- **Diarization is opt-in twice over.** `DIARIZE` is a compose build arg deciding
  whether the backend is installed into the image at all; `DIARIZE_ENABLED` is the
  runtime switch. Turning the second on without the first returns
  `503 Diarization unavailable` and logs why, rather than failing to start. With both
  off, no model is loaded and no diarization dependency is installed; the image itself
  differs only by an `HF_HOME` setting and the torch assertion below. The CPU image
  leaves it off: the model card names four NVIDIA GPU architectures and never mentions
  CPU.
- **A second pool.** `DIARIZER_POOL` sits beside `MODEL_POOL` as its own queue, with
  `init_diarizer_pool`, `acquire_diarizer` and `release_diarizer`. Both pools fill inside
  the single `flock` in `post_fork`, because both models download on first run.
  `GET /api/health` reports the diarization mode and, when it is on, the pool counters.
- **Build-time assertion on the CUDA wheel.** The GPU image installs `torch==2.10.0+cu130`
  and then runs further unconstrained dependency resolutions, any of which can replace it;
  the failure used to surface much later as cuBLAS and cuDNN errors that read like a driver
  problem. The build now fails instead, and a `DIARIZE=true` build additionally asserts that
  the installed transformers really carries the model.
- **The project is an installable package.** `pyproject.toml` gained a `[project]`
  table, entry points `stt-server` and `stt-client`, and a `whisper` extra that
  holds the model backend, so `pip install speech-to-text` no longer drags in
  torch for someone who only wants the client.
- **Release workflow.** Pushing a `1.2.3` tag builds the wheel and sdist and cuts
  a GitHub Release whose notes come from the matching `### [1.2.3]` section of
  this file.
- **Type checking.** `mypy` runs over `libs/`, `stt_server.py`, `stt_client.py`
  and `gu.py`, in CI and behind `make typecheck`.
- **Repository furniture.** Issue forms for bugs and feature requests, a pull
  request template with the project checklist, and a Dependabot configuration
  for pip and GitHub Actions. `torch` and `torchaudio` are excluded from it
  because their CUDA build is pinned per Docker image.
- **Per-request language for `/api/stt`.** An optional `language` (query string
  `?language=ru` or a multipart form field) overrides the server
  `WHISPER_LANGUAGE` default for a single request; `auto` autodetects. Invalid
  values return `400 {"error": "Invalid language"}`.
- **Static token auth.** `STT_TOKENS` holds a comma-separated list of valid
  tokens. When set, every `POST /api/stt` must carry `Authorization: Bearer
  <token>`; missing or invalid tokens return `401`. `GET /api/health` stays open
  so docker-compose healthchecks keep working. The client sends `STT_TOKEN`.
- **Configurable `STT_PORT`.** Both docker-compose files honor `STT_PORT`, so the
  published port follows the server port without editing the compose files.
- **Multilingual README.** Translations live in `docs/README_<LANG>.md` and are
  linked from the language switcher at the top of each README.

#### Fixed
- **Gunicorn starts again.** Since the module split, `gu.py` bound the settings module to the
  name `config`, which is also a gunicorn setting; gunicorn read it as one and refused to start
  with `Invalid value for config`. The default `python3 stt_server.py` run was not affected.
  Gunicorn 26's control socket is turned off in the same file: it defaults to a path under
  `$HOME`, which the unprivileged server user cannot write, and nothing here uses it.
- **A bearer token with non-ASCII characters is a 401, not a 500.** `hmac.compare_digest`
  raised `TypeError` on such a string, so such a header failed `/api/stt`
  with a 500 and, now that health reads the token for its detailed body, made the open
  `GET /api/health` fail too. Tokens are compared as UTF-8 bytes; health answers 200 with
  the non-detailed body. A `token` in the `/api/stream` start message holding a lone
  surrogate (`"\ud800"`), which UTF-8 cannot encode, is `Unauthorized` too, instead of an
  internal close with a traceback.
- **A known language outside the model's slice is a 400, not a 500.** `?language=yue` on a
  99-language checkpoint passed the check and raised inside Whisper; it is now
  `400 Unsupported language` before any audio is decoded, and on `/api/stream` whose start
  message names the model an `Unsupported language` error before the session starts; a start
  message without `model` is checked exactly as before. Only a checkpoint whose list is
  certain refuses it: a file path whose name matches no known checkpoint (a fine-tune at
  `/models/my-large-v3-finetune.pt`) still has any known code passed on when the request
  names no model, because its list is only guessed from the name.
- **A busy model is still `loaded` in the catalogue.** With every instance in flight the
  pool was empty and the row fell back to `installed`.
- **The container stops cleanly.** `entrypoint.sh` ran the server under `/bin/sh -c` without
  `exec`, so the shell stayed PID 1, never forwarded SIGTERM, and every stop and redeploy
  waited out Docker's 10 s grace period and then SIGKILLed the server with requests in flight
  (seen on the deployment host as exit 137 on every restart).
- **No empty segments in a speaker transcript.** A whitespace-only token became a segment of
  its own, `{"speaker": null, "text": ""}`.
- **The README no longer promises a 400 for an unknown language under Parakeet.** That holds
  only for a backend with `accepts_language: true`; Parakeet accepts and ignores the value,
  and the README and its translations now also say that it can drop speech it is unsure of
  without signalling it.
- **A speaker-attributed transcript no longer merges across another speaker's turn.**
  Found on the deployment host: when the transcriber produced no words for one voice, the
  other voice's two phrases merged into one run that claimed a single person spoke straight
  through the other's turn. A run now continues only if nobody else held a turn in the gap.
- **Parakeet's timestamps are joined word by word.** They were grouped into phrases on a
  0.6 s silence, and speakers hand over faster than that, so a phrase could swallow the
  handover and be attributed whole to whoever spoke longer.
- **Docker builds survive a slow network.** A GPU build on aarch64 failed partway through
  the 2.5 GB of CUDA wheels on uv's default 30 s read timeout; both images now allow 300 s.
  PyTorch also moved into a layer of its own ahead of `requirements.txt`, so editing the
  requirements no longer discards the cached wheels and sends the build back for all of them.
- **The README named the wrong default model.** It said `turbo`; without `WHISPER_MODEL`
  set, the server loads `small.en`, and only `.env.example` selects `turbo`. The README and
  its translations now say so, and the Models section lists the real language counts
  (99, or 100 for the large-v3 lineage) instead of "multilingual".
- **`language` is checked against what the model knows, not against a regex.** The old
  shape check was wrong in both directions: `?language=zz` has the shape of a code, so it
  passed, reached Whisper, raised there and surfaced as a `500`; `?language=russian` was
  refused with `400` although Whisper accepts that spelling. Both now behave: an unknown
  language is a `400` before any audio is decoded, and a name resolves to its code.
- **First-run model download into bind-mounted `./models`.** The container
  runs as the unprivileged `stt` user while the host-owned bind mounts stayed
  root-owned, so `whisper.load_model` died with `PermissionError` (same trap
  for `./logs` and `./recs`). A root entrypoint now fixes ownership of the
  mounted dirs and drops privileges via `setpriv` before starting the server.

#### Changed
- **`libs.model_pool` keeps one pool per model.** The module attribute `MODEL_POOL` is
  replaced by `MODEL_POOLS`, a dict of queues keyed by model id, and `init_model_pool()`
  no longer takes a `size` argument: each model's size comes from its `STT_MODELS` entry
  or `STT_POOL_SIZE`. `catalog.describe_transcriber` is replaced by
  `describe_configured_model` (one loaded model) and `describe_unconfigured_backend` (a
  transcriber with nothing loaded), and `backends.transcriber()` is gone: every caller
  resolves `backends.transcriber_for_backend(spec["backend"])` for the model it serves.
  Code importing `libs` directly needs these new names.
- **A request that names its model has its `language` checked against that model's own
  list.** An English-only Whisper given `ru`, or Parakeet given a code outside its 25, is
  `400 Unsupported language`. A request without `model` keeps the old leniency: an
  English-only default still quietly transcribes English, and Parakeet still accepts and
  ignores any value.
- **The transcriber modules take the model to work on.** `get_model` and `describe_backend`
  accept `model_name`, and both modules gained `get_stt_result`, `list_aliases`,
  `list_known_models` and (Parakeet) `resolve_languages`; `get_stt_bio` is now a thin
  wrapper. Parakeet's catalogue row lists its short name as an alias.
- **A model backend that fails to load no longer stops the server.** The failure is
  logged and its pool left empty, so `/api/diarize` answers 503 while `/api/stt` keeps
  serving. Previously the exception surfaced inside the Gunicorn `post_fork` hook and
  every worker boot-looped.
- **Pool sizes are read when a pool is initialised**, not bound as default arguments at
  import time, so changing `MODEL_POOL_SIZE` or `DIARIZE_POOL_SIZE` is actually obeyed.
- **The upload-to-WAV step is shared** by both endpoints instead of duplicated.
- **CI mirrors the sibling text-to-speech project.** Actions are pinned by commit
  SHA, dependencies install through `pip install -e ".[dev]"`, and the lint job
  runs `mypy` after `pre-commit`.
- **Formatting widened to 128 columns**, and black and ruff moved to current
  releases. Throwaway names use an `unused_` prefix, which ruff is configured to
  accept, because the project style forbids a leading underscore.
- **`stt_server.py` split into focused modules.** The entry point now holds only
  the app wiring, the two routes and `main()`. Configuration, logging setup,
  error handling, auth, audio conversion and the model pool moved to
  `libs/config.py`, `libs/logs.py`, `libs/errors.py`, `libs/auth.py`,
  `libs/audio.py` and `libs/model_pool.py`. The WSGI target
  (`stt_server:app`) and the HTTP contract are unchanged.
- **Environment read in one place.** `libs/config.py` is the only module that
  calls `os.getenv` and `load_dotenv`; everything else imports the constants
  from it. This removes the import-ordering workaround that forced
  `import libs.stt` to sit below `load_dotenv()` in the entry point.
- **`libs/stt.py` is no longer treated as vendored.** It follows the same rules
  as the rest of the code and is covered by `black` and `ruff`, which are now
  applied to the whole repository.
- **Whisper wrapper cleanups.** The library no longer calls
  `logging.basicConfig`, so `LOG_LEVEL` set by the server finally takes effect.
  The shared mutable default `bio=io.BytesIO()` is gone, device resolution is
  no longer duplicated, waveform decoding and language normalization are
  separate named functions, and the unused `convert_to_wav()` helper was
  removed. The CLI entry point is now `python3 -m libs.stt <file>`, logs its
  usage line and reports failures with a traceback instead of exiting silently.
- **Gunicorn hooks log again.** `gu.py` configures logging on load; previously
  its `logger.info` calls were dropped because nothing had configured the root
  logger in the master process.
- **Docker images are self-contained.** Both Dockerfiles now copy `gu.py` and
  the real `libs/` package instead of creating an empty `libs/__init__.py`, so
  an image works without the compose bind mounts.
- **Uniform error responses.** Every error carries a generic `error` category and
  a `request_id` that correlates the response with the full exception in the
  server log.
- **Simplified request log.** Request lines log elapsed seconds with a plain
  separator instead of milliseconds and a duplicated status code.
