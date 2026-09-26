## Changelog

### [Unreleased]

#### Added
- **Background jobs for long recordings, `/api/jobs`.** Upload up to 1 GB, get an id at once,
  fetch the result later: plain text, who said what, or who spoke when. The file is worked through
  in pieces of about a minute cut at pauses, and the model goes back to the pool between them, so
  short requests keep being answered: a 30-minute recording took 107 s on the deployment GPU
  while phone-call-sized requests alongside it took 10 s at worst. Speakers keep one number across
  the whole file. Jobs survive a restart and are removed after `JOB_RETENTION_HOURS`.
- **`GET /metrics` for Prometheus:** requests by route and status with durations, error
  responses by category, pool sizes and free instances, live sessions, segments dropped by the
  speech gate, live audio shed by a session that fell behind.
- **`GET /api/health?deep=1`** runs one second of silence through every loaded model and answers
  503 if one fails - the plain check only says the process is up.
- **The live stream under gunicorn.** `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker` with
  `stt_server:asgi_app` serves `/api/stream` from several workers; checked under load on the
  deployment GPU.
- **Docker images in CI and on GHCR.** CI builds the CPU and web UI images on every PR; a release
  tag pushes them to GHCR as `speech-to-text-cpu` and `speech-to-text-www`.
- **Who spoke when, on its own, in the web UI.** FILE gets a Turns mode that calls
  `/api/diarize` and draws the result as a timeline: a lane per speaker, a bar per turn, and the
  stretches where two people talk at once marked. Each source now keeps its last result while
  another screen is open, and a live session that falls behind shows how much it skipped.
- **Uploads up to 100 MB in the Docker setup** (`MAX_CONTENT_LENGTH_MB`, now read from `.env`).
- **`docs/DEPLOY.md`:** first deployment, what to rebuild or restart after an update, rolling
  back, going offline once the models are cached, the certificate, and what an open server
  exposes. `make tag-rollback` tags both images before a deploy.
- **A live session that falls behind catches up.** When its queued phrases hold more than two
  minutes of audio - a 24/7 source on a slower-than-realtime transcriber - it drops the oldest
  queued ones and says so in a new `skipped` message, instead of growing its memory and its lag
  without end.
- **Only spoken text is returned.** A voice detector (Silero VAD) now vets every transcript:
  a segment that lies mostly outside detected speech is dropped, and so is a whole-segment
  subtitle credit line. Before, Whisper answered a tone with a Russian "subtitles by
  DimaTorzok" credit, noise and even digital silence with "to be continued...", and music with
  both; on a
  corpus of nine such recordings every one of them came back as text on every endpoint, and
  now none does, while every phrase of the speech recordings is kept. Whisper's own
  `no_speech_prob` was 0.00 even on silence, which is why its confidence is not used. A live
  phrase with no speech in it is not sent to the model at all. `SPEECH_GATE=false` turns it off.
- **A live phrase is cut where the speaker changes.** With `diarize`, `/api/stream` no longer
  waits for a 0.6 s pause that a quick reply does not leave: it closes the phrase where the
  diarizer hears one speaker hand over to another.
- **A STREAM source in the web UI.** Beside FILE and DEVICE, STREAM takes the address of a
  stream or a remote file and has the server read it, so the UI shows every way the service
  takes audio.
- **Live transcription in the web UI, and from a URL.** TRANSCRIBE gets a FILE / DEVICE
  switch: DEVICE captures a microphone, a headset, a loopback source or a browser tab's sound
  and shows each phrase as soon as it is transcribed, as a block per phrase in Speakers mode. Browsers allow audio devices
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
- **A URL source ending as the client left** is logged as the client leaving, not as an abnormal end.
- **405 names the allowed methods** in an `Allow` header, as RFC 9110 requires.
- **An SRT listener could still get past the URL check.** ffmpeg reads SRT options from the
  first `?` anywhere in the address, while the check read urlsplit's query, which stops at `#`, so
  `srt://0.0.0.0:9000#?mode=listener` passed and made the server listen. Options are now read the
  way ffmpeg reads them. A live segment that Whisper placed wholly past the end of the audio is
  dropped instead of coming out with its end before its start. Both found by the new tests for
  the live stream.
- **URL sources, after a review.** RTSP works: ffmpeg was given `-rw_timeout`, which the RTSP
  demuxer does not take, and aborted every RTSP source. A source that keeps ffmpeg complaining
  no longer freezes the session: its stderr is read as it comes instead of after exit. A live
  source no longer runs 7-35 s behind: `-re` paced its backlog too, and an initial burst now takes
  it at once. A malformed address or an ffmpeg that cannot start ends in an `error` and a close
  instead of a dropped or silent socket, and the string that is checked is the one ffmpeg runs.
- **URL sources are fenced in.** A page on another site cannot start one (`Forbidden`), SRT
  listener and rendezvous modes and `listen` parameters are refused, at most four run at once,
  and the log no longer records credentials or query strings.
- **Live capture in the web UI, after the same review.** Switching source no longer loses a
  running upload, a file dropped on the live tabs no longer replaces the page, a quick
  START-STOP-START no longer leaves the microphone on, the remembered device is the one
  recorded, a device below 16 kHz is resampled instead of sent too fast, and a stopped session
  says it is finishing rather than "No speech recognised".
- **Gunicorn starts again.** Since the module split, `gu.py` bound the settings module to the
  name `config`, which is also a gunicorn setting; gunicorn read it as one and refused to start
  with `Invalid value for config`. The default `python3 stt_server.py` run was not affected.
  Gunicorn 26's control socket is turned off in the same file: it defaults to a path under
  `$HOME`, which the unprivileged server user cannot write, and nothing here uses it.
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
- **The voice detector takes its lock per 30 s window**, so a long file's detection no longer
  holds every short request's speech gate for its whole length.
- **Builds are reproducible.** Every install step runs with `-c constraints.txt`, the versions
  of the last verified image (`make constraints` refreshes it), and the uv image is pinned; a
  moving `uv:latest` had thrown away the layer cache and cost a 20-minute rebuild. The GPU image
  now also refuses a torch without kernels for NVIDIA GB10.
- **The server can run as the host user.** `STT_UID` / `STT_GID` make `models/`, `logs/` and
  `recs/` belong to the user who owns the checkout, instead of uid 1001.
- **An upload that is not audio is logged as one WARNING line**, not an ERROR with a traceback:
  it is the client's mistake and is answered with 400.
- **The CPU image is on Python 3.12**, like the GPU image and the project's target.
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
