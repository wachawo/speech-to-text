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
* **실시간 전사.** WebSocket으로 오디오를 스트리밍하면 말하는 대로 구절마다 결과를 돌려받으며, 화자 분리가 켜져 있으면 각 구절에 화자도 함께 지정됩니다.
* **웹 UI 포함.** 브라우저에서 파일을 업로드하고 텍스트나 누가 무엇을 말했는지를 읽을 수 있습니다. 서버 옆에서 동작하는 전용 nginx 컨테이너가 이를 제공합니다.

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

GPU 빌드는 호스트에 `nvidia-container-toolkit`가 필요합니다. 첫 실행 시 Whisper 모델을 `./models`로 내려받습니다. 서버에서의 운영(업데이트, 롤백, 인증서, 의존성)은 [docs/DEPLOY.md](DEPLOY.md)에서 다룹니다.

### 웹 UI

`docker compose up`은 `stt_www`도 함께 시작합니다. 이는 브라우저 UI를 제공하고 `/api/`를 서버로 넘겨 주는 nginx 컨테이너이므로, UI와 API가 하나의 주소를 공유합니다.

| 리스너 | 기본 포트 | 설정 변수          |
| ------ | --------- | ------------------ |
| http   | `8080`    | `STT_WWW_PORT`     |
| https  | `8443`    | `STT_WWW_TLS_PORT` |

`http://<host>:8080`을 엽니다. **TRANSCRIBE**에는 세 가지 소스가 있습니다. **FILE**은 오디오 파일을 업로드합니다. **DEVICE**는 오디오 입력에서 실시간으로 전사합니다. 입력으로는 마이크나 헤드셋, 스피커나 헤드폰으로 재생되는 모든 소리를 담는 Linux의 `Monitor of ...` 소스, 또는 Chromium 계열 브라우저에서는 브라우저 탭에서 재생되는 소리(운영 체제가 허용하면 시스템 전체)를 위한 `Tab or screen audio`를 쓸 수 있습니다. **STREAM**은 스트림이나 원격 파일의 주소(인터넷 라디오, HLS, RTMP, RTSP, SRT)를 받아 서버가 직접 읽습니다. 어느 경우든 결과는 폼 아래에 일반 텍스트로 나타나며, 화자 분리가 켜져 있으면 구절마다 화자와 시간이 붙은 블록으로 나타납니다. 화자마다 고유한 색이 붙고, 두 사람이 동시에 말한 구절은 따로 표시됩니다. 실시간 구절은 화자가 말을 멈춘 뒤 약 1초 후에 나타납니다. 결과는 복사하거나 TXT 또는 JSON으로 내려받을 수 있으며, 다른 화면을 보는 동안에도 각 소스는 마지막 결과를 유지합니다. FILE에는 **Turns** 모드도 있는데, 이는 `POST /api/diarize`만 단독으로 쓰는 것으로, 누가 언제 말했는지를 화자마다 레인이 하나씩 있는 타임라인으로 그리고 두 사람이 동시에 말하는 구간을 표시합니다. **MODELS**는 `GET /api/models`가 알려 주는 내용을 보여 줍니다. `STT_TOKENS`가 설정되어 있으면 UI는 토큰을 한 번만 묻고 브라우저에 보관합니다.

브라우저는 안전한 페이지에만 오디오 장치를 넘겨주므로, 네트워크를 통해서는 DEVICE가 https 리스너를 거쳐 동작합니다(`http://localhost`에서도 동작합니다). https 리스너는 컨테이너가 처음 시작할 때 `./data/certs`에 만드는 자체 서명 인증서를 사용합니다. 이를 교체하려면 실제 `stt.crt`와 `stt.key`를 그곳에 두십시오. UI에는 빌드 단계도 CDN도 없습니다. Vue 2와 그 라이브러리는 `www/vendor`에 함께 들어 있으므로, 인터넷에 연결되지 않은 기기에서도 동작합니다.

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
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`GET /api/health?deep=1`은 여기에 더해 로드된 모든 모델에 1초 분량의 무음을 통과시키고, 각 모델을 `ok`, `busy`(5초 안에 비는 인스턴스가 없음), `failed` 중 하나로 보고하며, 하나라도 실패하면 `503`을 반환합니다. GPU 작업이 들기 때문에 `STT_TOKENS`가 설정되어 있는 동안에는 토큰이 필요하며, 일반 검사는 컨테이너 헬스체크를 위해 열린 채로 둡니다.

`GET /metrics`는 Prometheus 메트릭을 제공합니다. 경로와 상태별 요청, 그 소요 시간, 범주별 오류 응답, 풀 크기와 빈 인스턴스 수, 실행 중이거나 시작된 실시간 세션, 음성 검출기가 버린 구간, 뒤처진 세션이 흘려 버린 실시간 오디오가 포함됩니다. 헬스체크와 마찬가지로 토큰이 필요 없으며, `stt_www`는 이를 프록시하지 않으므로 `STT_PORT`를 직접 수집하십시오. gunicorn에서는 워커마다 따로 집계합니다.

`POST /api/stt`는 `file`이라는 이름의 `multipart/form-data` 필드 또는 원시 `audio/*` 본문을 받습니다. 선택적인 `language`(쿼리 문자열 또는 폼 필드)는 해당 요청에 대해 서버 기본값을 덮어쓰며, `auto`는 자동으로 감지합니다. 성공하면 텍스트와 소요 시간(초)을 반환합니다.

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

언어는 코드(`ru`)로도, 영어 이름(`russian`)으로도 지정할 수 있습니다. 모델이 모르는 값은 전사 도중에 실패하는 대신 `400`으로 거부됩니다. `GET /api/models`가 아는 언어를 나열합니다. 이는 언어를 받는 백엔드(`accepts_language: true`)에만 해당합니다. Parakeet는 언어를 스스로 감지하고 값을 무시하며, 확신하지 못하는 음성을 알리지 않고 누락할 수 있습니다. 여러 언어가 섞인 녹음에서는 소수 언어에 대해 아무것도 반환하지 않을 수 있습니다.

`GET /api/models`는 이 서버가 무엇을 갖추고 있는지 알려 주므로, 클라이언트가 짐작할 필요가 없습니다. 각 백엔드는 자신의 언어 목록을 함께 제공합니다. 집합이 실제로 서로 다르기 때문에, 하나로 합친 목록은 개별 백엔드 어느 쪽에도 맞지 않습니다.

```bash
curl -H 'Authorization: Bearer <token>' localhost:5099/api/models
```

```json
{
  "default": "whisper",
  "models": [
    { "backend": "whisper", "model": "turbo", "aliases": ["large-v3-turbo"], "status": "loaded",
      "multilingual": true, "accepts_language": true, "languages_source": "derived",
      "languages": ["en", "zh", "de", "..."], "default_language": "en", "default": true },
    { "backend": "diarize", "model": "nvidia/Nemotron-3-Diarization", "status": "installed",
      "accepts_language": false, "languages": null, "max_speakers": 8, "default": false }
  ]
}
```

`status`는 풀에 인스턴스가 대기 중이면 `loaded`, 가중치는 디스크에 있지만 아직 로드된 것이 없으면 `installed`, 그 외에는 `absent`입니다. 설정은 되어 있지만 설치되지 않은 백엔드는 `absent`라고만 말하며, 그 이상은 알려 주지 않습니다. 이유는 로그로 들어갑니다. `accepts_language`는 해당 백엔드에서 `?language=`가 애초에 의미를 갖는지 여부를 나타냅니다. 화자 분리기는 빈 목록이 아니라 `null` 언어를 반환하는데, 어떤 언어로도 텍스트를 생성하지 않기 때문입니다.

CLI 클라이언트도 같은 엔드포인트를 읽습니다.

```bash
python3 stt_client.py --list
```

`POST /api/diarize`는 **누가 언제 말했는지**만 답하며, 그 외에는 아무것도 반환하지 않습니다. 화자 번호가 붙은 시간 구간을 돌려줄 뿐, 텍스트는 절대 반환하지 않습니다. `DIARIZE=true`로 빌드한 이미지에서 `DIARIZE_ENABLED`가 설정되어 있지 않으면 비활성 상태이며, 그 경우 `503`을 반환합니다.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

이 숫자들에 대해 두 가지를 알아 두어야 합니다. 먼저, 화자 채널마다 따로 점수를 매기기 때문에 구간이 서로 겹칠 수 있습니다. 두 사람이 동시에 말하면 같은 시간대를 덮는 구간이 두 개 생깁니다. 그리고 화자 번호는 이 녹음 하나 안에서의 순서이며, 먼저 말한 사람부터 매겨집니다. 신원이 아니므로 다음 요청에서는 같은 사람이 다른 번호를 받습니다. 화자에게 이름을 붙이려면 등록 단계가 필요한데, 이 서비스에는 그런 단계가 없습니다. 구분되는 화자는 최대 여덟 명입니다.

전사 백엔드는 두 가지를 쓸 수 있습니다. **Whisper**가 기본값이며 `language`를 받습니다. **Parakeet**(`nvidia/parakeet-tdt-0.6b-v3`)은 유럽 언어 25종을 다루고 언어를 스스로 감지하므로 `language` 인자를 아예 받지 않으며, `GET /api/models`는 이를 `accepts_language: false`로 알려 줍니다. `PARAKEET=true`로 빌드한 이미지에서 `STT_BACKEND=parakeet`으로 선택합니다. 요청마다 고르는 것이 아니라 배포 시점에 정하는 선택인데, 상주 모델이 하나 더 늘어난다는 것은 모든 워커에 가중치 한 벌이 더 올라간다는 뜻이기 때문입니다.

두 백엔드 모두 겹쳐 말하는 음성을 인식하지 못합니다. NVIDIA의 겹침 인식 모델은 NeMo 체크포인트로만 배포되는데, NeMo가 이 프로젝트의 CUDA 빌드와는 다른 PyTorch 버전을 고정하기 때문에 여기서는 설치할 수 없습니다.

`POST /api/transcript`는 **누가 무엇을 말했는지**에 답합니다. 같은 오디오에 대해 화자 분리와 전사를 모두 수행한 뒤 시간을 기준으로 둘을 결합합니다. 화자 분리가 활성화되어 있어야 하며, 그렇지 않으면 `503`을 반환합니다.

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
  "elapsed": 3.41
}
```

`turns`는 화자 분리기의 원본 출력이고 `segments`는 그 결합 결과입니다. 귀속 결과를 믿지 못하는 호출자도 화자 분리기가 무엇이라고 말했는지를 그대로 볼 수 있도록 둘을 따로 두었습니다. `text`는 일반 전사문이며, 같은 파일에 대해 `/api/stt`가 반환하는 것과 동일합니다. 어느 구간에도 덮이지 않는 구절은 가장 가까운 화자에게 넘겨지는 대신 `"speaker": null`을 유지합니다.

`overlap`은 다른 사람도 함께 말하고 있던 구절을 표시합니다. NVIDIA는 일반적인 단일 화자 모델을 화자 분리와 짝짓는 것이 겹쳐 말하는 음성을 위해 만들어진 모델과 동등하지 않다고 분명히 밝히고 있습니다. 잘라낸 시간 구간에는 그 구간과 겹치는 모든 목소리가 여전히 들어 있으므로, 그런 구절들은 서로 섞이거나 엉뚱한 화자의 말을 고를 수 있습니다. `overlap`이 표시된 구간은 전사문에서 가장 신뢰하기 어려운 지점으로 다루십시오.

**긴 녹음은 작업으로 처리합니다.** `POST /api/jobs`는 `/api/stt`와 같은 형태의 본문을 `JOB_MAX_CONTENT_LENGTH_MB`(1 GB)까지 받으며, 여기에 `mode`를 더합니다. `text`(기본값), `speakers`(`/api/transcript` 결과), `turns`(`/api/diarize` 결과) 중 하나입니다. 응답은 곧바로 `202`로 오며, 작업 id와 폴링할 `Location`이 함께 옵니다.

```bash
curl -F file=@meeting.mp3 'localhost:5099/api/jobs?mode=speakers&language=ru'
curl localhost:5099/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6 } }
```

`status`는 `queued`(`position` 포함), `running`을 거쳐 `result`가 담긴 `done`이 되거나, `error` 범주가 담긴 `failed`가 됩니다. `GET /api/jobs`는 작업 목록을 보여 주고, `DELETE /api/jobs/<id>`는 실행 중이 아닌 작업을 삭제합니다. 작업은 파일을 멈춤에서 자른 약 1분 길이의 조각으로 나누어 처리하고 조각 사이마다 모델을 돌려주므로, 작업이 도는 동안에도 짧은 요청은 계속 응답을 받습니다. 배포 환경의 GPU에서 30분짜리 녹음은 107초가 걸렸고, 그동안 보낸 전화 통화 요청은 길어야 10초가 걸렸습니다. 화자 분리는 모델의 스트리밍 모드로 파일 전체에 걸쳐 실행되므로, 한 화자는 첫 1분부터 마지막 1분까지 같은 번호를 유지합니다. 작업은 `JOBS_DIR` 아래의 파일이므로 재시작 후에도 남으며, 끝난 작업은 `JOB_RETENTION_HOURS`가 지나면 삭제됩니다.

`/api/stream`은 **실시간 전사**를 위한 WebSocket입니다. 오디오는 녹음되는 대로 들어가고, 각 구절은 화자가 말을 멈춘 뒤 약 1초 후에 돌아옵니다. JSON 텍스트 메시지는 제어를, 바이너리 메시지는 오디오를 전달합니다.

1. 클라이언트가 `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`을 보냅니다. `type`을 제외한 모든 필드는 선택 사항입니다. `token`은 브라우저가 인증하는 방법인데, 브라우저는 WebSocket에 헤더를 설정할 수 없기 때문입니다. 다른 클라이언트는 대신 핸드셰이크 때 `Authorization: Bearer <token>`을 보내도 됩니다.
2. 서버가 `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`로 응답합니다.
3. 클라이언트는 원시 PCM(부호 있는 16비트, 리틀 엔디언, 모노, 16 kHz)을 임의 크기의 바이너리 메시지로 녹음되는 속도에 맞춰 보내고, 끝나면 `{"type": "stop"}`을 보냅니다. 실시간보다 빠르게 보낸 파일은 설계상 뒤처지며 구절을 잃습니다(아래의 `skipped` 참고). 파일은 작업으로 보내십시오.
4. 서버는 구절마다 `segment`를, 약 1초마다 `progress`를 보내고, 세션이 2분 넘게 뒤처지는 일이 생기면 버린 오디오의 초 수와 함께 `skipped`를 보내며, 닫기 전에 `done`을 보냅니다.

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

오디오는 다른 곳에서 올 수도 있습니다. 시작 메시지에 `"source": "url", "url": "https://..."`를 넣으면 클라이언트는 오디오를 전혀 보내지 않습니다. 서버가 ffmpeg로 그 주소의 스트림을 읽으며, 스트림이 끝나거나 클라이언트가 `stop`을 보낼 때까지 계속합니다. 인터넷 라디오, HLS, RTMP, RTSP, SRT가 동작합니다. 스킴은 `http`, `https`, `rtmp`, `rtmps`, `rtsp`, `srt` 중 하나여야 합니다. 라이브 소스에 이미 쌓여 있는 분량은 한 번에 가져오고 나머지는 소스 자체의 속도대로 읽으므로, 원격 파일도 방송과 같은 방식으로 도착합니다.

이 기능은 클라이언트가 고른 주소를 서버가 가져오게 만들기 때문에 제한이 걸려 있습니다. ffmpeg는 네트워크 프로토콜만 쓸 수 있으므로 URL이든 재생 목록이든 로컬 파일을 읽게 만들 수 없고, 어떤 방법으로도 연결을 기다리는 상태로 만들 수 없습니다. SRT의 `listener`와 `rendezvous` 모드, 그리고 모든 `listen` 매개변수는 거부됩니다. 다른 사이트의 페이지는 이를 시작할 수 없습니다(`Forbidden`). 브라우저는 WebSocket에 CORS를 적용하지 않으므로, 소켓이 페이지의 오리진이 이 호스트인지, 또는 `CORS_ORIGINS`에 나열되어 있는지 확인합니다. URL 소스는 동시에 최대 네 개까지 실행되며(그 이상은 `Service Unavailable`), 로그에는 각 주소가 자격 증명과 쿼리를 뺀 채로 기록됩니다. 그래도 서버 자신의 네트워크에 있는 호스트에는 여전히 닿을 수 있는데, 카메라라면 바로 그것이 목적이고, 다른 사람이 접근할 수 있는 서버에 `STT_TOKENS`를 설정해야 하는 이유이기도 합니다.

실패는 `{"type": "error", "error": "<category>", "request_id": "..."}` 하나로 전달되고 그 뒤에 연결이 닫힙니다. 범주는 HTTP 오류 범주에 `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed`, `Forbidden`이 더해진 것입니다.

구절은 0.6초의 멈춤에서 끝나거나, 화자 분리기가 한 화자에서 다른 화자로 말이 넘어가는 것을 들은 지점에서 끝나거나(`diarize` 사용 시, 서로 대답을 주고받는 사람들은 흔히 0.6초보다 짧게 쉬기 때문), 15초를 넘기면 가장 조용한 지점에서 끝나며, 업로드와 같은 풀에서 빌린 모델로 따로 전사됩니다. 그래서 풀이 바쁘면 실시간 구절은 실패하지 않고 늦어질 뿐입니다. `diarize`를 쓰면 화자 분리기가 스트리밍 모드로 동작하며 청크에서 청크로 화자 캐시를 이어 가므로, 한 화자는 세션 내내 같은 번호를 유지합니다. 이 소켓은 서버가 uvicorn에서 실행될 때 존재합니다. 곧 `python3 stt_server.py`(Docker 기본값)이거나, `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker`로 `stt_server:asgi_app`을 제공하는 gunicorn입니다. Flask 디버그 서버나 gunicorn의 기본 sync 워커에서는 존재하지 않는데, 이들은 WebSocket을 지원하지 않기 때문입니다.

**실제로 말한 텍스트만 반환됩니다.** 음성이 없는 곳(신호음, 음악, 잡음, 연결음, 심지어 디지털 무음)에서 Whisper는 자신이 학습한 자막 영상의 크레딧으로 답하며(러시아어 "자막 제작: DimaTorzok" 크레딧, "다음 편에 계속...", "시청해 주셔서 감사합니다."), 그것도 완전한 확신을 가지고 그렇게 합니다. 테스트 코퍼스에서 Whisper 자신의 `no_speech_prob`는 무음에서조차 0.00이었습니다. 그래서 모든 엔드포인트는 오디오에 음성 검출기인 Silero VAD를 돌려, 검출된 음성 밖에 대부분 놓인 전사 구간과, 자막 크레딧 한 줄 전체로 이루어진 구간을 버립니다. 음성이 없는 녹음 아홉 개로 이루어진 코퍼스에서 이 방식은 그런 줄을 모두 없애면서도 음성 녹음의 구절은 하나도 잃지 않았습니다. 아무 말도 없는 녹음은 이제 빈 텍스트가 됩니다. 실시간 스트림에서는 음성이 검출되지 않은 구절은 아예 모델로 보내지지 않습니다. 검출기는 CPU에서 동작하며, 오디오 3분당 약 1초가 더 걸립니다. `SPEECH_GATE=false`로 이전 동작을 되돌릴 수 있습니다.

업로드는 `MAX_CONTENT_LENGTH_MB`(서버만 단독으로 실행하면 10 MB, Docker 구성에서는 100 MB)로 제한되며, 더 큰 본문은 `413`을 반환합니다.

오류는 형식이 일관됩니다. `error`는 일반적인 범주를 담고, `request_id`는 전체 예외가 기록된 서버 로그와 응답을 연결합니다.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

`STT_TOKENS`가 설정되어 있으면 `GET /api/health`를 제외한 모든 경로는 `Authorization: Bearer <token>`을 포함해야 합니다. `GET /api/health`는 헬스체크가 계속 동작하도록 열려 있습니다.

### CLI 클라이언트

`stt_client.py`는 서버를 다루고 테스트하기 위한 작은 클라이언트입니다. 서버 주소와 토큰을 `STT_URL`과 `STT_TOKEN`에서 읽어 옵니다.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

`--stream`은 파일 하나를 말하는 속도로 `/api/stream`에 흘려 보내고, 구절이 돌아올 때마다 출력합니다. `--speakers`를 붙이면 화자도 지정합니다.

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker`는 `/api/stream`을 추가(gunicorn 전용) |
| `LOG_LEVEL`             | `INFO`                  | 로깅 레벨                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn 액세스 로그 기록                           |
| `WHISPER_MODEL`         | `small.en`              | Whisper 모델 이름(예: `small.en`, `turbo`)         |
| `WHISPER_LANGUAGE`      | `en`                    | 기본 전사 언어                                     |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | 모델 캐시 디렉터리(Docker에서는 `/opt/models`)     |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, 또는 `auto`                         |
| `STT_BACKEND`           | `whisper`               | 전사 백엔드: `whisper` 또는 `parakeet`             |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet 모델 ID                             |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet 모델 캐시 디렉터리                        |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` 활성화(`DIARIZE=true` 이미지 필요) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | 화자 분리 모델 ID                          |
| `DIARIZE_POOL_SIZE`     | `1`                     | 미리 로드되는 화자 분리기 인스턴스 수              |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | 화자 분리 모델 캐시 디렉터리                       |
| `DIARIZE_THRESHOLD`     | `0.5`                   | 음성으로 간주하는 화자 활동 확률                   |
| `JOBS_DIR`              | `recs/jobs`             | 작업이 업로드, 기록, 결과를 보관하는 곳             |
| `JOB_MAX_CONTENT_LENGTH_MB` | `1024`              | 작업 하나의 최대 업로드 크기(MB)                    |
| `JOB_RETENTION_HOURS`   | `24`                    | 끝난 작업을 삭제하기까지의 시간 수                  |
| `SPEECH_GATE`           | `true`                  | 아무도 말하지 않은 전사 텍스트 제거(음성 검출기)    |
| `STT_UID`, `STT_GID`    | (이미지의 `stt`, 1001)  | `models/`, `logs/`, `recs/`를 소유하는 호스트 사용자(Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | 모델이 캐시된 뒤 `1`: 시작 시 허브 요청 없음        |
| `STT_WWW_PORT`          | `8080`                  | 웹 UI http 포트(compose)                            |
| `STT_WWW_TLS_PORT`      | `8443`                  | 웹 UI https 포트(compose)                           |
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
│   ├── model_pool.py    # pools of pre-loaded Whisper and diarizer instances
│   ├── catalog.py       # what the server can do, for GET /api/models
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
│   ├── backends.py      # which module transcribes, per STT_BACKEND
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

### 개발

시스템 패키지 `ffmpeg`와 `libsndfile1`이 설치되어 있어야 합니다. 런타임 및 개발 의존성을 설치하세요.

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

테스트 스위트는 Whisper 백엔드를 스텁으로 대체하므로 HTTP 계층(request_id, 오류 범주, 모델 풀 동작)을 다루며, 모델을 내려받거나 GPU가 필요하지 않고 몇 초 만에 실행됩니다.

### 라이선스

[MIT](../LICENSE)
