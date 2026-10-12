## Deploying speech-to-text

How to run the service on a GPU host with Docker, update it, and roll it back. The README covers what the service does; this is the operator's side.

### What runs

| Container    | Image            | Port (default)  | Role                                                     |
| ------------ | ---------------- | --------------- | -------------------------------------------------------- |
| `stt_server` | `stt_server_gpu` | `STT_PORT` 5099 | the API: `/api/*`, the `/api/stream` websocket, models   |
| `stt_www`    | `stt_www`        | 8080, 8443      | nginx: the web UI, `/api/` passed through, https for devices |

Both come from `docker-compose.yml` (GPU) or `docker-compose-cpu.yml`. `libs/`, `stt_server.py`, `stt_client.py`, `gu.py` and `www/` are bind-mounted, so a change to the code or the UI does not need a rebuild.

### First deployment

1. **Host prerequisites:**
   - Docker with the compose plugin;
   - `nvidia-container-toolkit`;
   - a CDI spec, regenerated after every driver update: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`.

   The GPU image runs on x86_64 and aarch64, NVIDIA GB10 included.

2. **Get the code and create the `.env`:**

   ```bash
   git clone https://github.com/wachawo/speech-to-text.git /opt/speech-to-text
   cd /opt/speech-to-text
   cp .env.example .env
   ```

3. **Edit `.env`.** The settings that matter for a deployment:

   | Variable                          | Why                                                                   |
   | --------------------------------- | --------------------------------------------------------------------- |
   | `STT_PORT`                        | the API port on the host                                              |
   | `STT_TOKENS`                      | set it on any server others can reach (see Security below)            |
   | `WHISPER_MODEL`                   | `turbo` is the best all-round choice on a GPU                         |
   | `DIARIZE`, `DIARIZE_ENABLED`      | build and run switches for diarization                                |
   | `PARAKEET`, `STT_BACKEND`         | build and run switches for Parakeet                                   |
   | `STT_MODELS`, `STT_DEFAULT_MODEL` | several models side by side, each request picking one; give every entry an explicit `@N`, and count on the GPU memory of every worker times the sum of the pools |
   | `STT_WWW_PORT`, `STT_WWW_TLS_PORT`| the web UI ports                                                      |
   | `STT_UID`, `STT_GID`              | the host user that should own `models/`, `logs/`, `recs/` (`id -u`, `id -g`) |

   Without `STT_UID` those directories belong to uid 1001 inside the image, and the host user can only write to them with sudo.

4. **Build and start:**

   ```bash
   docker compose up -d --build
   ```

   The first start downloads the models into `./models`: Whisper, and when enabled about 2.4 GB for Parakeet and 400 MB for the diarizer. The service is healthy once `curl localhost:$STT_PORT/api/health` answers. With the weights cached, a start takes about 20 s.

5. **Once `./models` is complete, set `HF_HUB_OFFLINE=1` in `.env` and recreate the container.** Otherwise the diarizer and Parakeet ask the Hugging Face hub on every start, and a host without internet access starts slowly or not at all.

### The web UI and its certificate

`stt_www` serves http on `STT_WWW_PORT` and https on `STT_WWW_TLS_PORT`. Browsers give a page an audio device only over https or on `localhost`, so live capture from a device (the DEVICE tab) needs the https port.

On the first start the container creates a self-signed certificate in `./data/certs` (`stt.crt`, `stt.key`), and browsers ask to accept it once. To use a real certificate, put it there under the same two names and restart `stt_www`.

### Updating

Tag the running images first, so there is something to roll back to:

```bash
make tag-rollback          # stt_server_gpu:rollback-<rev> and stt_www:rollback-<rev>
cp -p .env .env.bak-$(date +%Y%m%d-%H%M%S)
git pull --ff-only
```

What to do next depends on what the pull changed:

| Changed                                                                          | Do                                                                      |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| only `libs/`, `stt_server.py`, `gu.py`                                           | `docker compose restart stt_server`                                     |
| only `www/`                                                                      | nothing: it is bind-mounted, and a browser reload picks it up           |
| `requirements*.txt`, `constraints.txt`, `Dockerfile`, `entrypoint.sh`            | `docker compose build stt_server && docker compose up -d --no-build`    |
| `nginx/`, `Dockerfile-www`                                                       | `docker compose build stt_www && docker compose up -d --no-build`       |
| `docker-compose.yml`, `.env`                                                     | `docker compose up -d --no-build`                                       |

Two traps apply:
- **`pull_policy: build` is set,** so a plain `docker compose up -d` rebuilds the images. `--no-build` reuses the ones already built.
- **Only `stt_server` is interrupted by a restart,** for about 13 to 20 s. The container stops cleanly: the server gets SIGTERM, finishes what it can and exits within about a second.

### Rolling back

```bash
git checkout <rev>                                   # the commit the rollback images were built from
docker tag stt_server_gpu:rollback-<rev> stt_server_gpu:latest
docker tag stt_www:rollback-<rev> stt_www:latest
cp -p .env.bak-<stamp> .env                          # if .env changed since
docker compose up -d --no-build
```

A version from before the web UI has no `stt_www` service in its compose file, so stop that container by hand: `docker compose stop stt_www`.

### Checking a deployment

```bash
curl -s localhost:$STT_PORT/api/health
curl -s localhost:$STT_PORT/api/models | python3 -m json.tool | head
curl -s -F file=@speech.wav "localhost:$STT_PORT/api/stt?language=en"
python3 stt_client.py --stream speech.wav --speakers        # the live websocket, with STT_URL set
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:$STT_WWW_PORT/
```

`docker compose logs stt_server` should have no `[ERROR]` line after start. The diarizer's loader prints one `image_like_kwargs` line in the same format, which comes from transformers and is harmless.

### Jobs

`POST /api/jobs` stores each job under `JOBS_DIR`, which compose puts in `./recs/jobs` on the host. The directory holds the upload until the job has run, then only the record and the result. Finished jobs are removed after `JOB_RETENTION_HOURS` (24). Jobs survive a restart: one that was running when the server stopped runs again from the start. A job keeps the model it was accepted for, so one whose model the restart unloaded - after a change to `STT_MODELS`, `STT_BACKEND`, `WHISPER_MODEL` or `PARAKEET_MODEL` - fails as `Model not loaded` and has to be sent again.

Leave `OMP_NUM_THREADS=1` as the compose file sets it. The voice detector runs on the CPU, and with torch's default thread count it ran eight times slower on the GB10 host.

### Monitoring

- `GET /api/health` is what the container healthcheck calls: the process is up and how many model instances are free.
- `GET /api/health?deep=1` runs one second of silence through every loaded model, one at a time, reports each one by its id under `deep.models` and answers `503` when one fails. It needs a token when `STT_TOKENS` is set.
- `GET /metrics` on `STT_PORT` is the Prometheus endpoint (`stt_www` does not proxy it). The metrics to alert on:
  - `stt_pool_available` (the default model) at 0 for long, or `stt_model_pool_available` for any one model, labelled with its id and backend; with `STT_TOKENS` set, only a scrape that sends a token (`authorization` in the Prometheus scrape config) gets those series;
  - `stt_errors_total` growing in any category;
  - `stt_stream_skipped_seconds_total` growing, which means live sessions fall behind.
  - `stt_jobs_total{status="failed"}` growing.

### Several workers

`python3 stt_server.py` is one process with each model's pool: `STT_POOL_SIZE` instances of the single model, or the `@N` of every `STT_MODELS` entry. For several processes, run gunicorn instead (`command:` in the compose file):

```bash
GUNICORN_WORKERS=2 GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker gunicorn --config gu.py stt_server:asgi_app
```

- **The live stream needs `UvicornWorker`.** The default `sync` workers serve the HTTP API only.
- **Each worker loads its own models.** Two workers need twice the GPU memory.
- **Every worker keeps its own metrics,** so a scrape sees one worker at a time.

### A second instance for short phrases

A client that sends short phrases - 1 to 3 s of 16 kHz mono 16-bit PCM WAV, one multipart request each, waiting for every answer - is best served by a second `stt_server` with settings of its own: one instance per model, a short wait for a busy model, connections kept open. It runs from the image the main compose file built, on another port, and the main instance is not touched: other container, other compose project, other port, other jobs directory.

1. **Its env file,** `.env.short` next to `.env`. `.gitignore` already covers it, and it is not loaded by the main instance:

   ```bash
   STT_PORT=5061
   STT_TOKENS=<a token of its own>
   # One instance per model: a second one of the same model adds no throughput (see below).
   # The Parakeet entry needs an image built with PARAKEET=true.
   STT_MODELS=whisper:turbo@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
   STT_DEFAULT_MODEL=
   WHISPER_LANGUAGE=en
   WHISPER_BEAM_SIZE=1
   # A busy model answers 503 after this long instead of queueing the phrase for two minutes.
   STT_QUEUE_TIMEOUT=0.3
   # Longer than the client's longest pause between phrases, so it keeps one connection.
   STT_KEEPALIVE_SECONDS=30
   SPEECH_GATE=false
   DIARIZE_ENABLED=false
   # Its own jobs: two servers sharing a directory would claim each other's jobs.
   JOBS_DIR=/opt/recs/jobs-short
   HF_HUB_OFFLINE=1
   # The same values as in .env: the entrypoint chowns the shared models/, logs/ and recs/ to them.
   STT_UID=1000
   STT_GID=1000
   ```

   `SPEECH_GATE=false` is a setting of this instance only; the code default stays on. Without the gate Whisper answers "Thank you." on silence and on noise, while Parakeet returns empty text on non-speech, so a client of this instance has to expect that.

2. **Its compose file,** `docker-compose.short.yml` next to `docker-compose.yml`. It is kept on the host and is not part of the repository, so `git status` lists it as untracked:

   ```yaml
   name: stt_short

   services:
     stt_short:
       image: stt_server_gpu         # built by docker-compose.yml; this file builds nothing
       pull_policy: never
       container_name: stt_short
       hostname: stt_short
       restart: unless-stopped
       env_file:
         - .env.short
       environment:
         TZ: America/New_York
         WHISPER_DOWNLOAD_ROOT: "/opt/models"
         PARAKEET_DOWNLOAD_ROOT: "/opt/models"
         DIARIZE_DOWNLOAD_ROOT: "/opt/models"
         OMP_NUM_THREADS: "1"
         MKL_NUM_THREADS: "1"
         NVIDIA_VISIBLE_DEVICES: "all"
         NVIDIA_DRIVER_CAPABILITIES: "compute,utility"
         COMPUTE_TYPE: "cuda"
       ports:
         - "5061:5061"
       volumes:
         - /etc/localtime:/etc/localtime:ro
         - /etc/timezone:/etc/timezone:ro
         - ./stt_server.py:/opt/stt_server.py:ro
         - ./gu.py:/opt/gu.py:ro
         - ./libs:/opt/libs:ro
         - ./models:/opt/models
         - ./logs:/opt/logs
         - ./recs:/opt/recs
       devices:
         - "nvidia.com/gpu=all"
       logging:
         driver: "json-file"
         options:
           max-size: "128m"
           max-file: "3"
       entrypoint: ["/opt/entrypoint.sh"]
       healthcheck:
         test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5061/api/health')"]
         interval: 30s
         timeout: 10s
         retries: 3
         start_period: 120s
       command:
         - "python3 stt_server.py"
   ```

   The top-level `name` makes it a compose project of its own, so `docker compose up -d` in the main project neither recreates nor removes it as an orphan.

3. **Start it,** and after each update of the main instance restart it too, since it runs the same code and image:

   ```bash
   docker compose -f docker-compose.short.yml up -d
   docker compose -f docker-compose.short.yml restart stt_short    # after a code-only update
   curl -s -H "Authorization: Bearer <token>" "localhost:5061/api/health"
   curl -s -H "Authorization: Bearer <token>" -F file=@phrase.wav -F model=parakeet "localhost:5061/api/stt"
   ```

Why these settings:

- **`python3 stt_server.py`, not gunicorn sync workers.** One process holds one instance of each model and serves requests from a thread pool. Sync workers load the models once per worker and close the connection after every response, so a client would open a new connection for every phrase.
- **16 kHz mono 16-bit PCM WAV is passed straight to the model.** The server reads its header and skips decoding; any other format or rate goes through pydub and ffmpeg, which cost 70 ms per phrase (81 ms p95): over a third of Whisper turbo's model time and nearly all of Parakeet's. The server does no resampling of its own for this path: the client sends 16 kHz.
- **One instance per model.** A second instance of the same model on the same GPU added no throughput and doubled the time of every phrase: the two take turns on the same GPU.
- **`STT_QUEUE_TIMEOUT` well under a second.** With one instance, a phrase that finds the model busy waits for at most that long and then gets `503`, which the client can retry or count, instead of waiting behind a burst. 0.3 s is one or two phrases of Whisper turbo at beam 1.

Measured on 2026-10-12 on one NVIDIA GB10 with 240 phrases of LibriSpeech read speech, 1.3 to 3.5 s each; latency is model time only, without HTTP and without audio conversion:

| Model             | Beam | p50     | p95     | WER  | GPU memory |
| ----------------- | ---- | ------- | ------- | ---- | ---------- |
| Whisper turbo     | 1    | 0.189 s | 0.219 s | 4.8% | 3.3 GB     |
| Whisper turbo     | 5    | 0.252 s | 0.305 s | 4.6% | 3.3 GB     |
| Whisper large-v3  | 1    | 0.453 s | 0.589 s | 6.5% | 6.3 GB     |
| Whisper large-v3  | 5    | 0.848 s | 1.191 s | 6.1% | 6.3 GB     |
| Parakeet v3       | -    | 0.078 s | 0.098 s | 3.2% | 2.5 GB     |

| Two instances of one model instead of one | Throughput, two vs one  | Per-phrase latency |
| ----------------------------------------- | ----------------------- | ------------------ |
| Whisper turbo, beam 5                     | 3.9 vs 4.0 phrases/s    | doubled            |
| Parakeet v3                               | 12.7 vs 12.5 phrases/s  | doubled            |

Read speech is the easy case: phone audio, accents and noise are likely to raise every error rate, and the ranking between the models may differ on them. The GPU memory adds to that of the main instance and of every other model on the same GPU.

### Dependencies

`constraints.txt` holds every package version the GPU image resolved. All `pip install` steps in the Dockerfiles run with `-c constraints.txt`, so a rebuild installs the versions that were tested instead of whatever PyPI has that day. After a dependency change has been built and verified, freeze it with `make constraints` and commit the result.

The GPU Dockerfile also checks what it built:
- the CUDA 13.0 torch is still the one installed;
- torch carries kernels for NVIDIA GB10;
- the diarizer and Parakeet architectures are present when they were requested.

A failed check stops the build instead of producing an image that fails at its first request.

### Security

- **`STT_TOKENS` empty means open.** Anyone who can reach the ports can transcribe, and can make the server open a stream URL of their choice with `"source": "url"`, including addresses on the server's own network. Set a token on any host others can reach.
- **URL sources are fenced in.** The fence:
  - ffmpeg is held to network protocols;
  - it never listens;
  - the address may not be a loopback one, a link-local one (the cloud metadata service at `169.254.169.254` among them) or `0.0.0.0`, checked when the session starts;
  - at most four URL sources run at once in each worker process;
  - a browser page from another site cannot start one, unless DNS rebinding makes it look like this one, which only a token stops.

  None of that stops a client on the network from pointing the server at another host on the local network, which is allowed on purpose for cameras and encoders, at the server's own LAN or container address, or at an address a redirect or a playlist leads to.
- **The web UI asks for the token itself** and keeps it in the browser. nginx adds none of its own.
