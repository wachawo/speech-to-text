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

`POST /api/jobs` stores each job under `JOBS_DIR`, which compose puts in `./recs/jobs` on the host. The directory holds the upload until the job has run, then only the record and the result. Finished jobs are removed after `JOB_RETENTION_HOURS` (24). Jobs survive a restart: one that was running when the server stopped runs again from the start.

Leave `OMP_NUM_THREADS=1` as the compose file sets it. The voice detector runs on the CPU, and with torch's default thread count it ran eight times slower on the GB10 host.

### Monitoring

- `GET /api/health` is what the container healthcheck calls: the process is up and how many model instances are free.
- `GET /api/health?deep=1` runs one second of silence through every loaded model and answers `503` when one fails. It needs a token when `STT_TOKENS` is set.
- `GET /metrics` on `STT_PORT` is the Prometheus endpoint (`stt_www` does not proxy it). The metrics to alert on:
  - `stt_pool_available` at 0 for long;
  - `stt_errors_total` growing in any category;
  - `stt_stream_skipped_seconds_total` growing, which means live sessions fall behind.
  - `stt_jobs_total{status="failed"}` growing.

### Several workers

`python3 stt_server.py` is one process with `STT_POOL_SIZE` models. For several processes, run gunicorn instead (`command:` in the compose file):

```bash
GUNICORN_WORKERS=2 GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker gunicorn --config gu.py stt_server:asgi_app
```

- **The live stream needs `UvicornWorker`.** The default `sync` workers serve the HTTP API only.
- **Each worker loads its own models.** Two workers need twice the GPU memory.
- **Every worker keeps its own metrics,** so a scrape sees one worker at a time.

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
  - at most four URL sources run at once;
  - a browser page from another site cannot start one.

  None of that stops a client on the network from pointing the server at an internal address.
- **The web UI asks for the token itself** and keeps it in the browser. nginx adds none of its own.
