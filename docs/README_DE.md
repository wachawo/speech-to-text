## speech-to-text: ein selbst gehosteter Whisper-Transkriptionsserver

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | **[Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md)** | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` wandelt Audio mit [openai-whisper](https://github.com/openai/whisper) in Text um, eingebettet in einen kleinen HTTP-Dienst, den Sie selbst betreiben. Sie senden eine Audiodatei und erhalten die Transkription zurück. Keine externe API, keine Abrechnung pro Minute, und Ihre Audiodaten verlassen niemals Ihre Maschine.

Das Projekt eignet sich für die lokale Nutzung, für die Stapeltranskription und für den Betrieb eines eigenen STT-Servers im Netzwerk.

* **Ein einsatzbereiter HTTP-Server.** Flask, ausgeliefert über uvicorn, lädt Whisper beim Start und beantwortet Anfragen von anderen Maschinen in Ihrem lokalen Netzwerk.
* **Sicher bei Nebenläufigkeit.** Der Server hält einen Pool vorab geladener Whisper-Instanzen bereit, sodass mehrere Anfragen parallel transkribiert werden, ohne das Modell neu zu laden.
* **CPU oder GPU, derselbe Code.** Das Backend wird über die Umgebung und über das gebaute Docker-Image ausgewählt. Eine CUDA-Karte beschleunigt die Inferenz, aber alles läuft auch auf der CPU.
* **Ein CLI-Client ist enthalten.** `stt_client.py` sendet lokale Dateien an den Server und gibt das Ergebnis aus.

### Modelle

Whisper liefert mehrere Modellgrößen. Größere Modelle sind genauer und langsamer; kleinere sind schnell und leichtgewichtig.

| Model      | Parameters | VRAM    | Languages       | Good for                                      |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | mehrsprachig    | schnelle Entwürfe auf schwacher Hardware      |
| `base`     | 74M        | ~1 GB   | mehrsprachig    | ein leichter Allzweck-Standard                |
| `small`    | 244M       | ~2 GB   | mehrsprachig    | eine gute Balance aus Genauigkeit und Tempo   |
| `medium`   | 769M       | ~5 GB   | mehrsprachig    | höhere Genauigkeit, wenn Speicher verfügbar ist |
| `turbo`    | 809M       | ~6 GB   | mehrsprachig    | nahezu `large`-Genauigkeit, deutlich schneller |
| `large`    | 1550M      | ~10 GB  | mehrsprachig    | beste Qualität, benötigt eine GPU             |

Die rein englischen Varianten (`tiny.en`, `base.en`, `small.en`, `medium.en`) sind bei englischem Audio etwas genauer. Der Standard ist `turbo`, die beste Allround-Wahl für Englisch auf einer GPU.

### Schnellstart (Docker)

Am einfachsten lässt sich der Server mit Docker betreiben. Modelldateien werden auf dem Host in `./models` zwischengespeichert, sodass sie Neuaufbauten der Container überstehen.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

Der GPU-Build benötigt `nvidia-container-toolkit` auf dem Host. Beim ersten Lauf wird das Whisper-Modell nach `./models` heruntergeladen.

### HTTP-API

Sobald der Server läuft, prüfen Sie seinen Status und senden eine Audiodatei zur Transkription.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` gibt den Status des Pools zurück. Wenn `available` auf 0 fällt, sind gerade alle Modelle in Verwendung:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` akzeptiert ein `multipart/form-data`-Feld namens `file` oder einen rohen `audio/*`-Body. Ein optionales `language` (Query-String oder Formularfeld) überschreibt für diese Anfrage den Server-Standard; `auto` erkennt die Sprache automatisch. Bei Erfolg werden der Text und die verstrichenen Sekunden zurückgegeben:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Uploads sind auf `MAX_CONTENT_LENGTH_MB` begrenzt (standardmäßig 10 MB); ein größerer Body gibt `413` zurück.

Fehler sind einheitlich: `error` trägt eine generische Kategorie, und `request_id` verknüpft die Antwort mit dem Server-Log, in dem die vollständige Ausnahme festgehalten wird.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Wenn `STT_TOKENS` gesetzt ist, muss jede `POST /api/stt`-Anfrage `Authorization: Bearer <token>` mitführen; `GET /api/health` bleibt offen, damit Healthchecks weiterhin funktionieren.

### CLI-Client

`stt_client.py` ist ein kleiner Client zum Arbeiten mit dem Server und zum Testen. Er liest die Server-Adresse und das Token aus `STT_URL` und `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### Umgebungsvariablen

`.env` wird sowohl vom Server als auch vom Client über `python-dotenv` geladen.

| Variable                | Default                 | Zweck                                               |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | Bind-Adresse des Servers                            |
| `STT_PORT`              | `5099`                  | Server-Port                                         |
| `STT_POOL_SIZE`         | `8`                     | Anzahl vorab geladener Whisper-Instanzen            |
| `STT_TOKENS`            | (empty)                 | kommagetrennte gültige Tokens; leer deaktiviert Auth |
| `STT_DEBUG`             | `false`                 | Flask-Debug-Modus                                   |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | maximale Upload-Größe in MB; ein größerer Body gibt `413` zurück |
| `CORS_ORIGINS`          | `*`                     | erlaubte CORS-Ursprünge: `*` oder eine kommagetrennte Liste |
| `GUNICORN_WORKERS`      | `4`                     | Worker-Prozesse (nur gunicorn)                      |
| `LOG_LEVEL`             | `INFO`                  | Logging-Level                                       |
| `LOG_ACCESS`            | `false`                 | uvicorn-Access-Zeilen protokollieren                |
| `WHISPER_MODEL`         | `turbo`                 | Whisper-Modellname (z. B. `small.en`, `turbo`)      |
| `WHISPER_LANGUAGE`      | `en`                    | Standardsprache der Transkription                   |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | Verzeichnis des Modell-Caches (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` oder `auto`                            |
| `STT_URL`               | `http://localhost:5099` | Client: Basis-URL des Servers                       |
| `STT_TOKEN`             | (empty)                 | Client: an den Server gesendetes Bearer-Token       |

### Projektstruktur

```text
speech-to-text/
├── stt_server.py        # Flask-App-Verdrahtung, Routen, Einstiegspunkt
├── stt_client.py        # CLI-Client, der Dateien an den Server sendet
├── gu.py                # Gunicorn-Konfiguration und Hooks
├── libs/
│   ├── config.py        # alle Umgebungsvariablen, einmalig gelesen
│   ├── logs.py          # Logging-Format für App, uvicorn und die CLIs
│   ├── errors.py        # einheitliche JSON-Fehlerantworten und Flask-Error-Handler
│   ├── auth.py          # optionale Authentifizierung per statischem Token
│   ├── audio.py         # Upload -> Konvertierung nach 16 kHz Mono-WAV
│   ├── model_pool.py    # Pool vorgeladener Whisper-Instanzen
│   └── stt.py           # Whisper-Wrapper
├── Dockerfile           # GPU-Build (CUDA 13.0)
├── Dockerfile-cpu       # CPU-Build
├── docs/                # README-Übersetzungen
└── tests/               # pytest-Tests, keine Modell-Downloads und keine GPU
```

### Entwicklung

Die Systempakete `ffmpeg` und `libsndfile1` müssen vorhanden sein. Installieren Sie die Laufzeit- und Entwicklungsabhängigkeiten:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Das Makefile fasst die gängigen Aufgaben zusammen:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

Die Testsuite ersetzt das Whisper-Backend durch einen Stub, deckt also die HTTP-Schicht ab (request_id, Fehlerkategorien, Semantik des Modell-Pools) und läuft in Sekunden, ohne ein Modell herunterzuladen oder eine GPU zu benötigen.

### Lizenz

[MIT](../LICENSE)
