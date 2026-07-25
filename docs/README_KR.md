## speech-to-text: 직접 호스팅하는 Whisper 음성 인식 서버

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | **[한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)**

`speech-to-text`는 [openai-whisper](https://github.com/openai/whisper)를 사용해 오디오를 텍스트로 변환하며, 직접 운영하는 작은 HTTP 서비스로 감싸져 있습니다. 오디오 파일을 보내면 전사 결과를 돌려받습니다. 외부 API도, 분당 과금도 없으며, 오디오는 절대 사용자의 기기를 벗어나지 않습니다.

이 프로젝트는 로컬 사용, 일괄 전사, 그리고 네트워크에서 자체 STT 서버를 운영하는 데 적합합니다.

* **바로 사용할 수 있는 HTTP 서버.** uvicorn으로 구동되는 Flask가 시작 시 Whisper를 로드하고, 로컬 네트워크의 다른 기기에서 오는 요청에 응답합니다.
* **동시성에 안전함.** 서버는 미리 로드된 Whisper 인스턴스 풀을 유지하므로, 모델을 다시 로드하지 않고도 여러 요청을 병렬로 전사합니다.
* **CPU 또는 GPU, 동일한 코드.** 백엔드는 환경 변수와 빌드하는 Docker 이미지에 따라 선택됩니다. CUDA 카드는 추론 속도를 높여 주지만, 모든 기능은 CPU에서도 동작합니다.
* **CLI 클라이언트 포함.** `stt_client.py`는 로컬 파일을 서버로 전송하고 결과를 출력합니다.

### 모델

Whisper는 여러 크기의 모델을 제공합니다. 큰 모델은 더 정확하지만 느리고, 작은 모델은 빠르고 가볍습니다.

| 모델       | 매개변수    | VRAM    | 언어            | 적합한 용도                                   |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | 다국어          | 성능이 낮은 하드웨어에서의 빠른 초안 작성     |
| `base`     | 74M        | ~1 GB   | 다국어          | 가벼운 범용 기본값                            |
| `small`    | 244M       | ~2 GB   | 다국어          | 정확도와 속도의 좋은 균형                     |
| `medium`   | 769M       | ~5 GB   | 다국어          | 메모리 여유가 있을 때의 더 높은 정확도        |
| `turbo`    | 809M       | ~6 GB   | 다국어          | `large`에 가까운 정확도, 훨씬 빠름            |
| `large`    | 1550M      | ~10 GB  | 다국어          | 최고 품질, GPU 필요                           |

영어 전용 변형(`tiny.en`, `base.en`, `small.en`, `medium.en`)은 영어 오디오에서 조금 더 정확합니다. 기본값은 `turbo`이며, GPU에서 영어를 처리할 때 가장 무난한 선택입니다.

### 빠른 시작 (Docker)

서버를 실행하는 가장 쉬운 방법은 Docker를 사용하는 것입니다. 모델 파일은 호스트의 `./models`에 캐시되므로 컨테이너를 다시 빌드해도 유지됩니다.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU 빌드는 호스트에 `nvidia-container-toolkit`가 필요합니다. 첫 실행 시 Whisper 모델을 `./models`로 내려받습니다.

### HTTP API

서버가 올라오면 상태를 확인하고 전사할 오디오 파일을 보냅니다.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health`는 풀 상태를 반환합니다. `available`이 0으로 떨어지면 모든 모델이 현재 사용 중이라는 뜻입니다.

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt`는 `file`이라는 이름의 `multipart/form-data` 필드 또는 원시 `audio/*` 본문을 받습니다. 선택적인 `language`(쿼리 문자열 또는 폼 필드)는 해당 요청에 대해 서버 기본값을 덮어쓰며, `auto`는 자동으로 감지합니다. 성공하면 텍스트와 소요 시간(초)을 반환합니다.

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

업로드는 `MAX_CONTENT_LENGTH_MB`(기본 10 MB)로 제한되며, 더 큰 본문은 `413`을 반환합니다.

오류는 형식이 일관됩니다. `error`는 일반적인 범주를 담고, `request_id`는 전체 예외가 기록된 서버 로그와 응답을 연결합니다.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

`STT_TOKENS`가 설정되어 있으면 모든 `POST /api/stt`는 `Authorization: Bearer <token>`을 포함해야 합니다. `GET /api/health`는 헬스체크가 계속 동작하도록 열려 있습니다.

### CLI 클라이언트

`stt_client.py`는 서버를 다루고 테스트하기 위한 작은 클라이언트입니다. 서버 주소와 토큰을 `STT_URL`과 `STT_TOKEN`에서 읽어 옵니다.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### 환경 변수

`.env`는 `python-dotenv`를 통해 서버와 클라이언트 양쪽에서 로드됩니다.

| 변수                    | 기본값                  | 용도                                               |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | 서버 바인드 주소                                   |
| `STT_PORT`              | `5099`                  | 서버 포트                                          |
| `STT_POOL_SIZE`         | `8`                     | 미리 로드되는 Whisper 인스턴스 수                  |
| `STT_TOKENS`            | (비어 있음)             | 쉼표로 구분된 유효 토큰, 비어 있으면 인증 비활성화 |
| `STT_DEBUG`             | `false`                 | Flask 디버그 모드                                  |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | 최대 업로드 크기(MB), 더 큰 본문은 `413` 반환      |
| `CORS_ORIGINS`          | `*`                     | 허용되는 CORS 출처: `*` 또는 쉼표로 구분된 목록    |
| `GUNICORN_WORKERS`      | `4`                     | 워커 프로세스 수(gunicorn 전용)                    |
| `LOG_LEVEL`             | `INFO`                  | 로깅 레벨                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn 액세스 로그 기록                           |
| `WHISPER_MODEL`         | `turbo`                 | Whisper 모델 이름(예: `small.en`, `turbo`)         |
| `WHISPER_LANGUAGE`      | `en`                    | 기본 전사 언어                                     |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | 모델 캐시 디렉터리(Docker에서는 `/opt/models`)     |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, 또는 `auto`                         |
| `STT_URL`               | `http://localhost:5099` | 클라이언트: 서버 기본 URL                          |
| `STT_TOKEN`             | (비어 있음)             | 클라이언트: 서버로 전송되는 베어러 토큰            |

### 프로젝트 구조

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
│   ├── model_pool.py    # pool of pre-loaded Whisper instances
│   └── stt.py           # Whisper wrapper
├── Dockerfile           # GPU build (CUDA 13.0)
├── Dockerfile-cpu       # CPU build
├── docs/                # README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### 개발

시스템 패키지 `ffmpeg`와 `libsndfile1`이 설치되어 있어야 합니다. 런타임 및 개발 의존성을 설치하세요.

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Makefile은 자주 쓰는 작업들을 감싸 줍니다.

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

테스트 스위트는 Whisper 백엔드를 스텁으로 대체하므로 HTTP 계층(request_id, 오류 범주, 모델 풀 동작)을 다루며, 모델을 내려받거나 GPU가 필요하지 않고 몇 초 만에 실행됩니다.

### 라이선스

[MIT](../LICENSE)
