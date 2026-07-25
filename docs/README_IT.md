## speech-to-text: un server di trascrizione Whisper self-hosted

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | **[Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md)** | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` trasforma l'audio in testo con [openai-whisper](https://github.com/openai/whisper), racchiuso in un piccolo servizio HTTP che esegui tu stesso. Invii un file audio e ricevi la trascrizione. Nessuna API esterna, nessuna fatturazione al minuto, e il tuo audio non lascia mai la tua macchina.

Il progetto si adatta all'uso locale, alla trascrizione in batch e all'esecuzione di un proprio server STT sulla rete.

* **Un server HTTP pronto all'uso.** Flask servito da uvicorn carica Whisper all'avvio e risponde alle richieste di altre macchine sulla tua rete locale.
* **Sicuro in condizioni di concorrenza.** Il server mantiene un pool di istanze Whisper precaricate, così diverse richieste vengono trascritte in parallelo senza ricaricare il modello.
* **CPU o GPU, stesso codice.** Il backend viene selezionato in base all'ambiente e all'immagine Docker che costruisci. Una scheda CUDA accelera l'inferenza, ma tutto funziona anche su CPU.
* **È incluso un client a riga di comando.** `stt_client.py` invia file locali al server e stampa il risultato.

### Modelli

Whisper offre diverse dimensioni di modello. I modelli più grandi sono più accurati e più lenti; quelli più piccoli sono veloci e leggeri.

| Model      | Parameters | VRAM    | Languages       | Adatto a                                          |
| ---------- | ---------- | ------- | --------------- | ------------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | multilingual    | bozze rapide su hardware modesto                  |
| `base`     | 74M        | ~1 GB   | multilingual    | un'impostazione predefinita leggera e versatile   |
| `small`    | 244M       | ~2 GB   | multilingual    | un buon equilibrio tra accuratezza e velocità     |
| `medium`   | 769M       | ~5 GB   | multilingual    | maggiore accuratezza quando puoi dedicare memoria |
| `turbo`    | 809M       | ~6 GB   | multilingual    | accuratezza quasi `large`, molto più veloce       |
| `large`    | 1550M      | ~10 GB  | multilingual    | qualità migliore, richiede una GPU                |

Le varianti solo inglese (`tiny.en`, `base.en`, `small.en`, `medium.en`) sono un po' più accurate sull'audio in inglese. Il valore predefinito è `turbo`, la scelta più equilibrata per l'inglese su GPU.

### Avvio rapido (Docker)

Il modo più semplice per eseguire il server è con Docker. I file dei modelli vengono memorizzati nella cache in `./models` sull'host, così sopravvivono alle ricostruzioni del container.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La build GPU richiede `nvidia-container-toolkit` sull'host. La prima esecuzione scarica il modello Whisper in `./models`.

### API HTTP

Una volta che il server è attivo, controlla il suo stato e invia un file audio per la trascrizione.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` restituisce lo stato del pool. `available` che scende a 0 significa che tutti i modelli sono attualmente in uso:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` accetta un campo `multipart/form-data` chiamato `file`, oppure un corpo grezzo `audio/*`. Un parametro opzionale `language` (query string o campo del form) sovrascrive il valore predefinito del server per quella richiesta; `auto` esegue il riconoscimento automatico. In caso di successo restituisce il testo e i secondi trascorsi:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Gli upload sono limitati a `MAX_CONTENT_LENGTH_MB` (10 MB per impostazione predefinita); un corpo più grande restituisce `413`.

Gli errori sono uniformi: `error` riporta una categoria generica e `request_id` correla la risposta con il log del server, dove viene registrata l'eccezione completa.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Quando `STT_TOKENS` è impostato, ogni `POST /api/stt` deve includere `Authorization: Bearer <token>`; `GET /api/health` resta aperto, così i controlli di integrità continuano a funzionare.

### Client a riga di comando

`stt_client.py` è un piccolo client per lavorare con il server e testarlo. Legge l'indirizzo del server e il token da `STT_URL` e `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### Variabili d'ambiente

`.env` viene caricato sia dal server sia dal client tramite `python-dotenv`.

| Variable                | Default                 | Scopo                                              |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | indirizzo di bind del server                       |
| `STT_PORT`              | `5099`                  | porta del server                                   |
| `STT_POOL_SIZE`         | `8`                     | numero di istanze Whisper precaricate              |
| `STT_TOKENS`            | (vuoto)                 | token validi separati da virgola; vuoto disabilita l'autenticazione |
| `STT_DEBUG`             | `false`                 | modalità debug di Flask                            |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | dimensione massima dell'upload in MB; un corpo più grande restituisce `413` |
| `CORS_ORIGINS`          | `*`                     | origini CORS consentite: `*` o un elenco separato da virgole |
| `GUNICORN_WORKERS`      | `4`                     | processi worker (solo gunicorn)                    |
| `LOG_LEVEL`             | `INFO`                  | livello di logging                                 |
| `LOG_ACCESS`            | `false`                 | registra le righe di access di uvicorn             |
| `WHISPER_MODEL`         | `turbo`                 | nome del modello Whisper (es. `small.en`, `turbo`) |
| `WHISPER_LANGUAGE`      | `en`                    | lingua di trascrizione predefinita                 |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | directory della cache dei modelli (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, oppure `auto`                       |
| `STT_URL`               | `http://localhost:5099` | client: URL base del server                        |
| `STT_TOKEN`             | (vuoto)                 | client: bearer token inviato al server             |

### Struttura del progetto

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

### Sviluppo

Devono essere presenti i pacchetti di sistema `ffmpeg` e `libsndfile1`. Installa le dipendenze di runtime e di sviluppo:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Il Makefile racchiude le attività comuni:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

La suite di test sostituisce il backend Whisper con uno stub, quindi copre il livello HTTP (request_id, categorie di errore, semantica del pool di modelli) e viene eseguita in pochi secondi senza scaricare un modello né richiedere una GPU.

### Licenza

[MIT](../LICENSE)
