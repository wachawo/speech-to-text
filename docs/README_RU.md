## speech-to-text: самостоятельно размещаемый сервер транскрипции на базе Whisper

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | **[Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md)** | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` превращает аудио в текст с помощью [openai-whisper](https://github.com/openai/whisper), обёрнутого в небольшой HTTP-сервис, который вы запускаете сами. Вы отправляете аудиофайл и получаете обратно его транскрипцию. Никакого внешнего API, никакой оплаты за минуты, и ваше аудио никогда не покидает вашу машину.

Проект подходит для локального использования, пакетной транскрипции и запуска собственного STT-сервера в сети.

* **Готовый к работе HTTP-сервер.** Flask под управлением uvicorn загружает Whisper при старте и отвечает на запросы с других машин в вашей локальной сети.
* **Безопасность при параллельных запросах.** Сервер держит пул предварительно загруженных экземпляров Whisper, поэтому несколько запросов транскрибируются параллельно без повторной загрузки модели.
* **CPU или GPU, один и тот же код.** Бэкенд выбирается окружением и тем, какой Docker-образ вы собираете. Видеокарта с CUDA ускоряет инференс, но всё работает и на CPU.
* **В комплекте идёт CLI-клиент.** `stt_client.py` отправляет локальные файлы на сервер и выводит результат.

### Модели

Whisper поставляется в нескольких размерах моделей. Более крупные модели точнее и медленнее, более мелкие быстрые и лёгкие.

| Модель     | Параметры  | VRAM    | Языки           | Подходит для                                  |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | многоязычная    | быстрые черновики на слабом железе            |
| `base`     | 74M        | ~1 GB   | многоязычная    | лёгкий универсальный вариант по умолчанию     |
| `small`    | 244M       | ~2 GB   | многоязычная    | хороший баланс точности и скорости            |
| `medium`   | 769M       | ~5 GB   | многоязычная    | выше точность, если можно выделить память     |
| `turbo`    | 809M       | ~6 GB   | многоязычная    | точность близкая к `large`, намного быстрее   |
| `large`    | 1550M      | ~10 GB  | многоязычная    | лучшее качество, требуется GPU                |

Англоязычные варианты (`tiny.en`, `base.en`, `small.en`, `medium.en`) чуть точнее на английском аудио. По умолчанию используется `turbo`, лучший универсальный выбор для английского на GPU.

### Быстрый старт (Docker)

Проще всего запустить сервер через Docker. Файлы моделей кешируются в `./models` на хосте, поэтому они переживают пересборку контейнера.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

Для сборки под GPU на хосте нужен `nvidia-container-toolkit`. При первом запуске модель Whisper скачивается в `./models`.

### HTTP API

Когда сервер запущен, проверьте его статус и отправьте аудиофайл на транскрипцию.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` возвращает статус пула. Падение `available` до 0 означает, что все модели сейчас заняты:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` принимает поле `file` в формате `multipart/form-data` либо сырое тело `audio/*`. Необязательный параметр `language` (в строке запроса или как поле формы) переопределяет язык сервера по умолчанию для конкретного запроса; значение `auto` включает автоопределение. При успехе возвращаются текст и затраченное время в секундах:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Размер загрузки ограничен значением `MAX_CONTENT_LENGTH_MB` (по умолчанию 10 МБ); большее тело возвращает `413`.

Ошибки единообразны: `error` несёт обобщённую категорию, а `request_id` связывает ответ с записью в логе сервера, где зафиксировано полное исключение.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Если задана переменная `STT_TOKENS`, каждый `POST /api/stt` должен содержать `Authorization: Bearer <token>`; `GET /api/health` остаётся открытым, чтобы продолжали работать проверки состояния.

### CLI-клиент

`stt_client.py` это небольшой клиент для работы с сервером и его тестирования. Он читает адрес сервера и токен из `STT_URL` и `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### Переменные окружения

`.env` загружается и сервером, и клиентом через `python-dotenv`.

| Переменная              | По умолчанию            | Назначение                                          |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | адрес привязки сервера                              |
| `STT_PORT`              | `5099`                  | порт сервера                                        |
| `STT_POOL_SIZE`         | `8`                     | число предварительно загруженных экземпляров Whisper|
| `STT_TOKENS`            | (пусто)                 | допустимые токены через запятую; пусто отключает авторизацию |
| `STT_DEBUG`             | `false`                 | режим отладки Flask                                 |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | максимальный размер загрузки в МБ; большее тело возвращает `413` |
| `CORS_ORIGINS`          | `*`                     | разрешённые источники CORS: `*` или список через запятую |
| `GUNICORN_WORKERS`      | `4`                     | рабочие процессы (только gunicorn)                  |
| `LOG_LEVEL`             | `INFO`                  | уровень логирования                                 |
| `LOG_ACCESS`            | `false`                 | логировать строки доступа uvicorn                   |
| `WHISPER_MODEL`         | `turbo`                 | имя модели Whisper (например, `small.en`, `turbo`)  |
| `WHISPER_LANGUAGE`      | `en`                    | язык транскрипции по умолчанию                      |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | каталог кеша моделей (`/opt/models` в Docker)       |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` или `auto`                             |
| `STT_URL`               | `http://localhost:5099` | клиент: базовый URL сервера                         |
| `STT_TOKEN`             | (пусто)                 | клиент: bearer-токен, отправляемый на сервер        |

### Структура проекта

```text
speech-to-text/
├── stt_server.py        # сборка Flask-приложения, роуты, точка входа
├── stt_client.py        # CLI-клиент, отправляющий файлы на сервер
├── gu.py                # конфигурация и хуки Gunicorn
├── libs/
│   ├── config.py        # все переменные окружения, читаются один раз
│   ├── logs.py          # формат логов для приложения, uvicorn и CLI
│   ├── errors.py        # единообразные JSON-ответы об ошибках и хендлеры Flask
│   ├── auth.py          # опциональная авторизация по статическому токену
│   ├── audio.py         # конвертация загруженного файла в моно-WAV 16 кГц
│   ├── model_pool.py    # пул предзагруженных экземпляров Whisper
│   └── stt.py           # обёртка над Whisper
├── Dockerfile           # сборка под GPU (CUDA 13.0)
├── Dockerfile-cpu       # сборка под CPU
├── docs/                # переводы README
└── tests/               # тесты pytest, без скачивания моделей и без GPU
```

### Разработка

Должны присутствовать системные пакеты `ffmpeg` и `libsndfile1`. Установите рантайм- и dev-зависимости:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Makefile оборачивает типовые задачи:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

Набор тестов подменяет бэкенд Whisper заглушкой, поэтому он покрывает HTTP-слой (request_id, категории ошибок, семантику пула моделей) и выполняется за секунды без скачивания модели и без GPU.

### Лицензия

[MIT](../LICENSE)
