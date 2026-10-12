## speech-to-text: a self-hosted Whisper transcription server

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

**[English](https://github.com/wachawo/speech-to-text/blob/main/README.md)** | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` turns audio into text with [openai-whisper](https://github.com/openai/whisper), wrapped in a small HTTP service you run yourself. You send an audio file, you get the transcription back. No external API, no per-minute billing, and your audio never leaves your machine.

The project fits local use, batch transcription, and running your own STT server on the network.

* **A ready-to-use HTTP server.** Flask served by uvicorn loads Whisper at startup and answers requests from other machines on your local network.
* **Safe under concurrency.** The server keeps a pool of pre-loaded Whisper instances, so several requests are transcribed in parallel without reloading the model.
* **CPU or GPU, same code.** The backend is selected by environment and which Docker image you build. A CUDA card speeds inference up, but everything also runs on CPU.
* **A CLI client is included.** `stt_client.py` posts local files to the server and prints the result.
* **Live transcription.** Stream audio over a websocket and get each phrase back as it is spoken, attributed to a speaker when diarization is on.
* **A web UI is included.** Upload a file in the browser and read the text, or who said what, served by its own nginx container beside the server.

### Models

The server carries three kinds of model. Which ones a running instance actually has, with their exact language lists, is answered by `GET /api/models` (or `python3 stt_client.py --list`); this section is the overview.

**Transcription** - one model chosen with `STT_BACKEND`, or several side by side listed in `STT_MODELS` (see [Several models](#several-models)).

Whisper (`STT_BACKEND=whisper`, the default) ships several sizes. Bigger models are more accurate and slower; smaller ones are fast and light.

| Model      | Parameters | VRAM    | Languages          | Good for                                      |
| ---------- | ---------- | ------- | ------------------ | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | 99                 | quick drafts on weak hardware                 |
| `base`     | 74M        | ~1 GB   | 99                 | a light general-purpose default               |
| `small`    | 244M       | ~2 GB   | 99                 | a good accuracy / speed balance               |
| `medium`   | 769M       | ~5 GB   | 99                 | higher accuracy when you can spare the memory |
| `turbo`    | 809M       | ~6 GB   | 100                | near-`large` accuracy, much faster            |
| `large`    | 1550M      | ~10 GB  | 100                | best quality, needs a GPU                     |

The large-v3 lineage (`large`, `turbo`) knows 100 languages, the others 99; the English-only variants (`tiny.en`, `base.en`, `small.en`, `medium.en`) know one and are a bit more accurate on English audio. `turbo` is stored on disk as `large-v3-turbo.pt`. Without `WHISPER_MODEL` set, the server loads `small.en`; `.env.example` sets `turbo`, the best all-round pick on a GPU.

Parakeet (`STT_BACKEND=parakeet`) is `nvidia/parakeet-tdt-0.6b-v3`: 600M parameters, about 2.4 GB of weights, 25 European languages. It detects the language itself and takes no `language` argument, which `GET /api/models` reports as `accepts_language: false`. It needs an image built with `PARAKEET=true`.

#### Several models

`STT_MODELS` loads several transcription models at startup, each with its own pool, and lets every request pick one with `model`. Entries are comma-separated `backend:model[@pool]`:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # the model a request without `model` gets; empty means the first entry
```

Models are chosen only among the ones loaded at startup: a request never triggers a download or a load, and a model that is not loaded is refused with `400`. Every listed model costs memory for as long as the server runs, roughly `workers x (pool x model size)` summed over the list, plus the diarizer. `turbo@2,small@1,parakeet@1` on a GPU is about 12 + 2 + 3 = 17 GB per process. Under gunicorn each sync worker handles one request at a time, so give every entry `@1` and scale with `GUNICORN_WORKERS`. An entry without `@pool` takes `STT_POOL_SIZE`, which is 8 outside Docker, so write `@N` explicitly. Loading several large models takes longer than one, so raise the healthcheck `start_period` in the compose file if the container is marked unhealthy while it starts.

With `STT_MODELS` empty, `STT_BACKEND`, `WHISPER_MODEL` and `PARAKEET_MODEL` choose the single model as before and the server loads exactly what it loaded before; responses only gain fields. With it set they no longer choose what is loaded. In Docker, put `STT_MODELS` and `STT_DEFAULT_MODEL` in `.env`, not in the compose `environment:` block, which overrides `.env`. A Parakeet entry still needs an image built with `PARAKEET=true`, and the server refuses to start on an unknown backend, on the same weights listed twice (`turbo` and `large-v3-turbo`) or on an `STT_DEFAULT_MODEL` that is not in the list. A model given as a file path is served under its file name without `.pt`, so the path never reaches a client. `STT_DEFAULT_MODEL` may name such an entry by that name or by the path exactly as written in `STT_MODELS`, and its languages are those of the checkpoint its file name names: `/models/large-v3.pt` knows what `large-v3` knows. Two entries that would be served under one name (`/a/model.pt` and `/b/model.pt`), or an entry that would be served under a backend name (`/models/parakeet.pt`), stop the server at startup.

**Diarization** - `nvidia/Nemotron-3-Diarization`, 100M parameters, about 400 MB of weights. It answers who spoke when for up to eight speakers and produces no text in any language. It needs an image built with `DIARIZE=true` and `DIARIZE_ENABLED=true` at run time, and is documented for NVIDIA GPUs only.

None of these is overlap-aware: where two people talk at once, the transcript marks the span rather than separating the voices. NVIDIA's model for that ships only as a NeMo checkpoint, which is not installable against this project's CUDA build of PyTorch.

### Quick start (Docker)

The easiest way to run the server is with Docker. Model files are cached in `./models` on the host, so they survive container rebuilds.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

The GPU build needs `nvidia-container-toolkit` on the host, and the compose file requests the GPU through CDI, so the host also needs a CDI spec. Generate it once, and again after every driver update:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

The GPU image is built on the multi-architecture CUDA base and runs on x86_64 and on aarch64, including NVIDIA GB10 (DGX Spark).

Diarization and Parakeet are optional and are built into the image only when asked for. Set the build switches and the run-time switches in `.env`:

```bash
DIARIZE=true            # build: install the diarization backend
DIARIZE_ENABLED=true    # run: serve /api/diarize and /api/transcript
PARAKEET=true           # build: install the Parakeet backend
STT_BACKEND=parakeet    # run: transcribe with Parakeet instead of Whisper
```

then rebuild with `docker compose up -d --build`. Running it on a server - updates, rollbacks, certificates, dependencies - is covered in [docs/DEPLOY.md](docs/DEPLOY.md). The two failures differ on purpose. Enabling diarization on an image built without it answers `503` for the diarization routes and keeps transcribing. Selecting `STT_BACKEND=parakeet` on an image built without it stops the server at startup with the missing dependency in the log: a transcription service that cannot transcribe should not report itself healthy, and quietly falling back to Whisper would serve a different model than the one configured. The first run downloads each model into `./models`: Whisper, and when enabled about 2.4 GB for Parakeet and 400 MB for the diarizer.

### Web UI

`docker compose up` also starts `stt_www`, an nginx container that serves the browser UI and passes `/api/` through to the server, so the UI and the API share one address.

| Listener | Default port | Set with           |
| -------- | ------------ | ------------------ |
| http     | `8080`       | `STT_WWW_PORT`     |
| https    | `8443`       | `STT_WWW_TLS_PORT` |

Open `http://<host>:8080`. **TRANSCRIBE** has three sources. **FILE** uploads an audio file. **DEVICE** transcribes live from an audio input: a microphone or a headset, a `Monitor of ...` source on Linux that carries whatever plays through the speakers or headphones, or, in Chromium browsers, `Tab or screen audio` for what plays in a browser tab, or in the whole system where the OS allows it. **STREAM** takes the address of a stream or a remote file - internet radio, HLS, RTMP, RTSP, SRT - and the server reads it itself. Either way the result appears under the form as plain text or, with diarization enabled, as one block per phrase with its speaker and time, each speaker in its own colour and the phrases where two people talked at once marked; a live phrase appears about a second after the speaker pauses. The result can be copied or downloaded as TXT or JSON, and each source keeps its last result while you look at another screen. FILE also has a **Turns** mode, `POST /api/diarize` on its own: who spoke when, drawn as a timeline with a lane per speaker and the stretches where two people talk at once marked. With several models loaded (`STT_MODELS`), a model select beside the mode and the language picks the model for every source - FILE, DEVICE and STREAM - fed from `GET /api/models`, and the language list follows the chosen model; Turns transcribes nothing and sends no model. **MODELS** shows what `GET /api/models` reports. When `STT_TOKENS` is set, the UI asks for a token once and keeps it in the browser.

Browsers hand audio devices only to a secure page, so over the network DEVICE works through the https listener (and on `http://localhost`). The https listener uses a self-signed certificate that the container creates in `./data/certs` on its first start; put a real `stt.crt` and `stt.key` there to replace it. The UI has no build step and no CDN: Vue 2 and its libraries are vendored under `www/vendor`, so it works on a machine with no route to the internet.

### HTTP API

Once the server is up, check its status and send an audio file for transcription.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` returns the pool status. The top-level `pool_size` and `available` describe the default model, the one a request without `model` waits for; `available` dropping to 0 means every instance of it is in flight. `models` reports every loaded model by id:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

With `STT_TOKENS` set, `default_model` and `models` are only included in the answer to a request carrying a valid token: like `GET /api/models`, they name the deployment's configuration. A healthcheck without the token still gets `status`, `pool_size`, `available` and `diarize`.

`GET /api/health?deep=1` also pushes one second of silence through every loaded model, one at a time, and reports each as `ok`, `busy` (no instance freed up within five seconds) or `failed`: every transcription model by its id under `deep.models`, `deep.transcriber` as the worst of them, and `deep.diarizer` when diarization is on. It answers `503` if any failed. It costs GPU work, so while `STT_TOKENS` is set it needs a token; the plain check stays open for container healthchecks.

`GET /metrics` serves Prometheus metrics: requests by route and status, their durations, error responses by category, pool sizes and free instances, live sessions running and started, segments dropped by the speech gate and live audio shed by a session that fell behind. The unlabelled `stt_pool_*` gauges describe the default model and the diarizer; `stt_model_pool_size` and `stt_model_pool_available` carry every loaded model, labelled `model` and `backend`. Per transcription model there are also two histograms and a counter: `stt_model_inference_seconds` (labelled `model` and `backend`) is how long each model call took to transcribe its audio, `stt_model_wait_seconds` (labelled `model`) how long each borrow waited for a free instance, and `stt_model_wait_timeouts_total` (labelled `model`) how many waits ran out - a 503 after `STT_QUEUE_TIMEOUT`, or a live session or a job that waited too long; the deep health check's probe is in neither. Both histograms use the buckets 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 2.5, 5, 10, 30, 60 and 120 seconds, fine below one second so that short phrases are told apart. Like health it needs no token, and `stt_www` does not proxy it: scrape `STT_PORT` directly. Also like health, with `STT_TOKENS` set the per-model series are only in a scrape that sends a valid token, since they name the models; without one, the two pool gauges are empty and the latency histograms and the timeout counter are left out altogether. Under gunicorn every worker counts for itself.

`POST /api/stt` accepts a `multipart/form-data` field named `file`, or a raw `audio/*` body. An optional `model` (query string or form field) picks one of the loaded models: its id, an alias (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), the `backend:model` form, or a bare backend name, which means the default model if it belongs to that backend and otherwise that backend's first model. Without `model` the default model serves. An optional `language` (query string or form field) overrides the server default for that request; `auto` autodetects. On success it returns the text, the elapsed seconds, the model that transcribed and the language: the code Whisper detected or used (always `en` for an English-only model), or `null` for Parakeet, which does not report it.

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

A language may be given as a code (`ru`) or as its English name (`russian`); anything the model does not know is refused with `400` instead of failing part-way through a transcription. `GET /api/models` lists what each model knows. How strictly `language` is checked depends on the model and on whether the request named it:

| Model                        | `language` it takes                     | Request without `model`                      | Request with `model`                  |
| ---------------------------- | --------------------------------------- | -------------------------------------------- | ------------------------------------- |
| multilingual Whisper         | a code or English name from its list    | `400 Unsupported language` outside the list  | the same                              |
| English-only Whisper (`.en`) | `en` and `auto`                         | another known code is transcribed as English | `400 Unsupported language`            |
| Parakeet                     | none, it detects the language itself    | any value is accepted and ignored            | a code from its list, or `400`        |

Parakeet accepts only codes, not English names, and it can drop speech it is unsure of without saying so: in a mixed-language recording it may return nothing at all for the minority language.

A Whisper file path whose name matches no known checkpoint, such as a fine-tune at `/models/my-large-v3-finetune.pt`, has a language list that is only guessed from that name, so a request without `model` hands it any known code, as it always did; a request that names it is still checked against the guessed list.

The `400` errors for these two options are `Invalid model` (no backend knows the name), `Model not loaded` (a real model this server did not load), `Invalid language` (not a language at all) and `Unsupported language` (a real language the chosen model does not take). All four are returned before the audio is decoded.

`GET /api/models` reports what this server carries, so a client does not have to guess. Each loaded model has its own row, and so does each transcriber with nothing loaded (`selectable: false`) and the diarizer. Every row brings its own language list, because the sets genuinely diverge and a merged list would be wrong for every model on its own.

```bash
curl -H 'Authorization: Bearer <token>' localhost:5099/api/models
```

```json
{
  "default": "whisper",
  "default_model": "turbo",
  "models": [
    { "id": "turbo", "backend": "whisper", "model": "turbo", "aliases": ["large-v3-turbo"], "status": "loaded",
      "selectable": true, "default": true, "pool_size": 2, "available": 2,
      "multilingual": true, "accepts_language": true, "languages_source": "derived",
      "languages": ["en", "zh", "de", "..."], "default_language": "en" },
    { "id": "small.en", "backend": "whisper", "model": "small.en", "aliases": [], "status": "loaded",
      "selectable": true, "default": false, "pool_size": 1, "available": 1,
      "multilingual": false, "accepts_language": true, "languages": ["en"], "default_language": "en" },
    { "id": "nvidia/Nemotron-3-Diarization", "backend": "diarize", "model": "nvidia/Nemotron-3-Diarization",
      "status": "installed", "selectable": false, "default": false, "pool_size": 1, "available": 0,
      "accepts_language": false, "languages": null, "max_speakers": 8 }
  ]
}
```

`id` is what a request passes as `model`, and exactly one row has `default: true`: its id is `default_model`, and its backend is the top-level `default`. `pool_size` and `available` are that model's pool. `status` is `loaded` when instances were loaded into its pool, free or busy, `installed` when the weights are on disk but nothing is loaded yet, and `absent` otherwise. A backend that is configured but not installed says `absent` and nothing more; the reason goes to the log. `accepts_language` says whether `?language=` means anything to that backend at all. The diarizer reports `null` languages rather than an empty list, because it produces no text in any language.

The CLI client reads the same endpoint:

```bash
python3 stt_client.py --list
```

`POST /api/diarize` answers **who spoke when**, and nothing else: it returns time ranges with a speaker number, never text. It is off unless `DIARIZE_ENABLED` is set on an image built with `DIARIZE=true`; otherwise it answers `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Two things about those numbers. Turns may overlap, because each speaker channel is scored on its own, so two people talking at once produce two turns covering the same seconds. And the labels are positions in this one recording, ordered by who spoke first: they are not identities, and the same person gets a different number in the next request. Naming a speaker needs an enrollment step that this service does not have. At most eight speakers are distinguished.

Two transcription backends are available. **Whisper** is the default and accepts a `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) covers 25 European languages, detects the language itself and therefore takes no `language` argument at all, which `GET /api/models` reports as `accepts_language: false`. It needs an image built with `PARAKEET=true`. Select it for the whole server with `STT_BACKEND=parakeet`, or load it beside Whisper through `STT_MODELS` and pick it per request with `model`. A request only ever chooses among the models loaded at startup, and every loaded model holds its weights in every worker, so the memory is the number of workers times the sum of the pools.

Neither backend is overlap-aware. NVIDIA's overlap-aware model ships only as a NeMo checkpoint, and NeMo pins a different PyTorch than this project's CUDA build, so it is not installable here.

`POST /api/transcript` answers **who said what**: it runs diarization and transcription over the same audio and joins them by time. It needs diarization enabled, and otherwise answers `503`. It takes the same `model` and `language` as `/api/stt` and names the model that transcribed in `model`.

```bash
curl -X POST localhost:5099/api/transcript -F file=@meeting.wav
```

```json
{
  "segments": [ { "speaker": 0, "start": 0.5, "end": 4.2, "text": "so where are we", "overlap": false },
                { "speaker": 1, "start": 4.0, "end": 9.8, "text": "green since this morning", "overlap": true } ],
  "turns": [ { "speaker": 0, "start": 0.51, "end": 4.24 }, { "speaker": 1, "start": 4.0, "end": 9.81 } ],
  "speakers": 2,
  "text": "so where are we green since this morning",
  "elapsed": 3.41,
  "model": "turbo"
}
```

`turns` is the diarizer's raw output and `segments` is the join, kept apart so a caller who distrusts the attribution can still see what the diarizer said. `text` is the plain transcript, identical to what `/api/stt` returns for the same file. A phrase no turn covers keeps `"speaker": null` rather than being handed to the nearest one.

`overlap` marks a phrase during which somebody else was also talking. NVIDIA is explicit that pairing a conventional single-speaker model with diarization is not equivalent to a model built for overlapping speech: an extracted time range still contains every voice that overlaps it, so those phrases may merge or select the wrong speaker's words. Treat a segment marked `overlap` as a place the transcript is least trustworthy.

**Long recordings go through a job.** `POST /api/jobs` takes the same body shapes as `/api/stt`, up to `JOB_MAX_CONTENT_LENGTH_MB` (1 GB), plus a `mode`: `text` (the default), `speakers` (the `/api/transcript` result) or `turns` (the `/api/diarize` result). It answers `202` at once with the job's id and a `Location` to poll:

```bash
curl -F file=@meeting.mp3 'localhost:5099/api/jobs?mode=speakers&language=ru'
curl localhost:5099/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "model": "turbo", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6, "model": "turbo" } }
```

`status` goes `queued` (with its `position`), `running`, then `done` with the `result`, or `failed` with an `error` category. `GET /api/jobs` lists them and `DELETE /api/jobs/<id>` removes one that is not running. A job works through the file in pieces of about a minute, cut at pauses, and gives the model back between them, so the short requests keep being answered while it runs: a 30-minute recording took 107 s on the deployment GPU, and phone-call requests sent during it took 10 s at worst. Diarization runs across the whole file in the model's streaming mode, so a speaker keeps one number from the first minute to the last. Jobs are files under `JOBS_DIR`, so they survive a restart, and finished ones are removed after `JOB_RETENTION_HOURS`. A `text` or `speakers` job takes `model` and `language` like `/api/stt` and keeps that model: the job and its result name it, and a job whose model a restart unloaded fails as `Model not loaded`. A `turns` job, like `/api/diarize`, takes no `model`.

`/api/stream` is a websocket for **live transcription**: audio goes in as it is recorded, and each phrase comes back about a second after the speaker pauses. JSON text messages carry control, binary messages carry audio:

1. The client sends `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}`. Every field but `type` is optional. `model` picks one of the loaded models the way `model` does on `/api/stt`, and the language is checked against that model; without it the default model serves and the language is only checked for being a language at all, as it always was, so a code the default model lacks fails when a phrase is transcribed. `token` is how a browser authenticates, since it cannot set headers on a websocket; other clients may send `Authorization: Bearer <token>` on the handshake instead.
2. The server answers `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}`.
3. The client sends raw PCM - signed 16-bit little-endian, mono, 16 kHz - as binary messages of any size, at the pace it is recorded, and `{"type": "stop"}` when it is done. A file sent faster than real time falls behind by design and loses phrases (see `skipped` below); a file belongs in a job.
4. The server sends a `segment` for every phrase, `progress` about once a second, `skipped` with the seconds of audio it dropped if the session ever falls more than two minutes behind, and `done` before it closes:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

The audio can also come from somewhere else. With `"source": "url", "url": "https://..."` in the start message the client sends no audio at all: the server reads the stream at that address through ffmpeg until it ends or the client sends `stop`. Internet radio, HLS, RTMP, RTSP and SRT work; the scheme must be `http`, `https`, `rtmp`, `rtmps`, `rtsp` or `srt`. A live source's backlog is taken at once and the rest at the source's own pace, so a remote file arrives the way a broadcast would.

Because this makes the server fetch an address a client chose, it is fenced in. ffmpeg may use network protocols only, so neither a URL nor a playlist can make it read a local file, and nothing may make it listen: SRT `listener` and `rendezvous` modes and any `listen` parameter are refused. An address that is or resolves to the server itself (loopback), a link-local address such as the cloud metadata service at `169.254.169.254`, or `0.0.0.0` is refused as `Invalid stream URL`; this is checked when the session starts, and ffmpeg still follows redirects and playlists. A page on another site cannot start one (`Forbidden`): browsers apply no CORS to websockets, so the socket checks that the page's origin is this host, or is listed in `CORS_ORIGINS`. At most four URL sources run at once in each server process (`Service Unavailable` beyond that), so gunicorn with several workers allows that many per worker, and the log records each address without its credentials or query. It can still reach hosts on the server's own network, which is the point for a camera and the reason to set `STT_TOKENS` on a server others can reach.

A failure is one `{"type": "error", "error": "<category>", "request_id": "..."}` followed by a close, with the HTTP error categories plus `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` and `Forbidden`.

A phrase ends at a pause of 0.6 s, where the diarizer hears one speaker hand over to another (with `diarize`, since people answering each other often leave less than 0.6 s), or at its quietest moment once it runs past 15 s, and is transcribed on its own with a model borrowed from the same pool as the uploads, so a busy pool delays live phrases rather than failing them. With `diarize`, the diarizer runs in its streaming mode and carries a speaker cache from chunk to chunk, so a speaker keeps the same number for the whole session. The socket exists when the server runs under uvicorn - `python3 stt_server.py`, the Docker default, or gunicorn with `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker` serving `stt_server:asgi_app` - and not under the Flask debug server or gunicorn's default sync workers, which do not speak websocket.

**Only spoken text is returned.** Where there is no speech - a tone, music, noise, a ringback, even digital silence - Whisper answers with the credits of the subtitled video it learned from - a Russian "subtitles by DimaTorzok" credit, "to be continued...", "Thank you for watching." - and it does so with full confidence: on the test corpus its own `no_speech_prob` was 0.00 even on silence. So every endpoint runs a voice detector, Silero VAD, over the audio and drops a transcribed segment that lies mostly outside detected speech, plus any segment that is a whole subtitle credit line. On a corpus of nine non-speech recordings this removed every such line while keeping every phrase of the speech recordings. A recording with nothing spoken in it now reads as empty text. In the live stream a phrase with no detected speech is not even sent to the model. The detector runs on the CPU and adds about a second per three minutes of audio. `SPEECH_GATE=false` restores the old behaviour.

Uploads are capped at `MAX_CONTENT_LENGTH_MB` (10 MB for the bare server, 100 MB in the Docker setup); a larger body returns `413`.

Errors are uniform: `error` carries a generic category and `request_id` correlates the response with the server log, where the full exception is recorded.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

When `STT_TOKENS` is set, every route except `GET /api/health` must carry `Authorization: Bearer <token>`; health stays open so healthchecks keep working.

### OpenAI-compatible API

`POST /v1/audio/transcriptions` and `GET /v1/models` follow OpenAI's audio API, so any OpenAI SDK works once its `base_url` points at `http://<host>:<port>/v1` and its API key is one of `STT_TOKENS` (any string while auth is off).

```bash
curl localhost:5099/v1/audio/transcriptions \
  -H 'Authorization: Bearer <token>' \
  -F file=@phrase.wav -F model=turbo -F language=en -F response_format=verbose_json
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5099/v1", api_key="<token>")
print(client.audio.transcriptions.create(model="turbo", file=open("phrase.wav", "rb")).text)
```

The request is `multipart/form-data` with `file` and goes through exactly what `/api/stt` does: the same token, size limit, conversion, speech gate and wait for a free instance (`STT_QUEUE_TIMEOUT`). A 16 kHz mono 16-bit PCM WAV is passed on without decoding; anything else is decoded and converted to 16 kHz mono through pydub, as on `/api/stt`.

- `model` is one of the ids `GET /v1/models` lists (the same ids as `/api/models`), an alias or a backend name, exactly as on `/api/stt`; absent or empty means the default model. OpenAI's own names such as `whisper-1` are refused as `Invalid model`.
- `language` is checked against the chosen model as on `/api/stt`; Parakeet accepts and ignores it.
- `prompt` becomes Whisper's initial prompt. openai-whisper keeps only its last 223 tokens and uses it for the first 30 s of audio. Parakeet takes no prompt and ignores it. A prompt holding a Whisper special token such as `<|endoftext|>` is refused with a 400, whatever the model. The prompt is never logged.
- `temperature` may only be absent or `0`: decoding is deterministic at temperature 0.
- `response_format` is `json` (the default, `{"text": ...}`), `text` (a plain-text body) or `verbose_json`; `srt` and `vtt` are refused. `timestamp_granularities[]` may only ask for `segment`.

`verbose_json` carries `task`, `language` (the full lower-case name Whisper reports, such as `english`, or `null` for Parakeet, which does not report one), `duration` in seconds, `text` and `segments`. Whisper's segments are its own, with `id`, `seek`, `start`, `end`, `text`, `tokens`, `temperature`, `avg_logprob`, `compression_ratio` and `no_speech_prob`. Parakeet gives one segment with `tokens` empty and the confidence fields `null`, because it produces none.

Errors on every `/v1` path, `401`, `404`, `405`, `413` and `500` included, take OpenAI's shape, with the same category as `message`; every `/v1` response also carries the request id in an `X-Request-Id` header. `/api/*` errors keep their own shape.

```json
{ "error": { "message": "Invalid language", "type": "invalid_request_error", "param": "language",
             "code": "invalid_language", "request_id": "a1b2c3d4e5f6" } }
```

### CLI client

`stt_client.py` is a small client for working with and testing the server. It reads the server address and token from `STT_URL` and `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` and `--language` (also as `--model=NAME`) are sent only when given, so the server default applies otherwise; each result line shows the model and language the server used. `--list` prints the default model and one line per model with its status, whether a request may select it, its pool and its languages.

`--stream` plays one file into `/api/stream` at the speed of speech and prints each phrase as it comes back, with `--speakers` for speaker attribution:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### Environment variables

`.env` is loaded by both the server and the client through `python-dotenv`.

| Variable                | Default                 | Purpose                                             |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | server bind address                                 |
| `STT_PORT`              | `5099`                  | server port                                         |
| `STT_POOL_SIZE`         | `8`                     | instances per model; the default for an `STT_MODELS` entry without `@pool` |
| `STT_QUEUE_TIMEOUT`     | `120`                   | seconds a synchronous request waits for a free instance of its model before `503` |
| `STT_KEEPALIVE_SECONDS` | `5`                     | seconds an idle HTTP connection stays open (uvicorn; gunicorn `keepalive`) |
| `STT_TOKENS`            | (empty)                 | comma-separated valid tokens; empty disables auth   |
| `STT_DEBUG`             | `false`                 | Flask debug mode                                     |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | max upload size in MB; a larger body returns `413`  |
| `CORS_ORIGINS`          | `*`                     | allowed CORS origins: `*` or a comma-separated list |
| `GUNICORN_WORKERS`      | `4`                     | worker processes (gunicorn only)                    |
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` adds `/api/stream` (gunicorn only) |
| `LOG_LEVEL`             | `INFO`                  | logging level                                       |
| `LOG_ACCESS`            | `false`                 | log uvicorn access lines                            |
| `WHISPER_MODEL`         | `small.en`              | Whisper model name (e.g. `small.en`, `turbo`) when `STT_MODELS` is empty |
| `WHISPER_LANGUAGE`      | `en`                    | default language of every Whisper model             |
| `WHISPER_BEAM_SIZE`     | `1`                     | Whisper beam width; `1` is greedy, a wider beam is slower and slightly more accurate |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | model cache directory (`/opt/models` in Docker)     |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, or `auto`                             |
| `STT_BACKEND`           | `whisper`               | transcription backend when `STT_MODELS` is empty: `whisper` or `parakeet` |
| `STT_MODELS`            | (empty)                 | several models side by side: `backend:model[@pool]`, comma-separated |
| `STT_DEFAULT_MODEL`     | (empty)                 | model a request without `model` gets; empty means the first `STT_MODELS` entry |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet model id                             |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet model cache directory                      |
| `DIARIZE_ENABLED`       | `false`                 | enable `POST /api/diarize` (needs a `DIARIZE=true` image) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | diarization model id                        |
| `DIARIZE_POOL_SIZE`     | `1`                     | pre-loaded diarizer instances                       |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | diarization model cache directory                   |
| `DIARIZE_THRESHOLD`     | `0.5`                   | speaker activity probability counted as speech      |
| `JOBS_DIR`              | `recs/jobs`             | where jobs keep their upload, record and result     |
| `JOB_MAX_CONTENT_LENGTH_MB` | `1024`              | max upload size of a job in MB                      |
| `JOB_RETENTION_HOURS`   | `24`                    | finished jobs older than this are removed           |
| `SPEECH_GATE`           | `true`                  | drop transcribed text nobody spoke (voice detector) |
| `STT_UID`, `STT_GID`    | (image's `stt`, 1001)   | host user that owns `models/`, `logs/`, `recs/` (Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | `1` once the models are cached: no hub requests on start |
| `STT_WWW_PORT`          | `8080`                  | web UI http port (compose)                          |
| `STT_WWW_TLS_PORT`      | `8443`                  | web UI https port (compose)                         |
| `STT_URL`               | `http://localhost:5099` | client: server base URL                             |
| `STT_TOKEN`             | (empty)                 | client: bearer token sent to the server             |

### Project structure

```text
speech-to-text/
├── stt_server.py        # Flask app wiring, routes, entry point
├── stt_client.py        # CLI client that posts files to the server
├── gu.py                # Gunicorn config and hooks
├── libs/
│   ├── config.py        # every environment variable, read once
│   ├── logs.py          # logging format shared by the app, uvicorn and the CLIs
│   ├── errors.py        # uniform JSON error responses and Flask error handlers
│   ├── auth.py          # optional static-token authentication
│   ├── audio.py         # upload -> 16 kHz mono WAV conversion
│   ├── model_pool.py    # a pool per transcription model, and one for the diarizer
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── openai_api.py    # the OpenAI-compatible /v1 API: its options, answers and model list
│   ├── align.py         # joins transcription segments to speaker turns
│   ├── live.py          # the /api/stream websocket: protocol and sessions
│   ├── stream.py        # live transcription core: pauses, phrases, per-phrase transcription
│   ├── url_source.py    # URL sources for /api/stream: vetting the address, running ffmpeg
│   ├── speech_gate.py   # voice detector that drops text nobody spoke
│   ├── metrics.py       # Prometheus metrics for GET /metrics
│   ├── jobs.py          # background jobs: stored on disk, claimed with a lock, run by a worker thread
│   ├── longform.py      # a long recording in pieces: one borrowed model per piece, speakers across the file
│   ├── stt.py           # Whisper wrapper
│   ├── parakeet.py      # NVIDIA Parakeet wrapper, the second transcriber
│   ├── backends.py      # backend name -> transcriber module (STT_BACKEND or an STT_MODELS entry)
│   ├── registry.py      # which models are loaded and what a request may select
│   └── diarize.py       # speaker diarization (who spoke when, no text)
├── Dockerfile           # GPU build (CUDA 13.0)
├── Dockerfile-cpu       # CPU build
├── Dockerfile-www       # web UI image (nginx)
├── nginx/               # stt_www config: static UI, /api/ proxy, self-signed TLS
├── www/                 # web UI: Vue 2 without a build step, libraries vendored
├── constraints.txt      # every dependency version the tested image resolved
├── docs/                # DEPLOY.md and the README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### Development

System packages `ffmpeg` and `libsndfile1` must be present. Install the runtime and dev dependencies:

```bash
pip install -e ".[dev]"
pre-commit install
```

The Makefile wraps the common tasks:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
make typecheck      # mypy
```

The test suite stubs the Whisper backend, so it covers the HTTP layer (request_id, error categories, model pool semantics) and runs in seconds without downloading a model or needing a GPU.

### License

[MIT](LICENSE)
