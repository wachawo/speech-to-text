## Changelog

### [Unreleased]

#### Added
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

#### Changed
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
