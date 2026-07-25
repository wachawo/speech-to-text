## speech-to-text: un servidor de transcripción Whisper autoalojado

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | **[Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md)** | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` convierte audio en texto con [openai-whisper](https://github.com/openai/whisper), envuelto en un pequeño servicio HTTP que tú mismo ejecutas. Envías un archivo de audio y recibes la transcripción de vuelta. Sin API externa, sin facturación por minuto, y tu audio nunca sale de tu máquina.

El proyecto encaja para uso local, transcripción por lotes y para ejecutar tu propio servidor STT en la red.

* **Un servidor HTTP listo para usar.** Flask servido por uvicorn carga Whisper al arrancar y responde a las solicitudes de otras máquinas en tu red local.
* **Seguro bajo concurrencia.** El servidor mantiene un grupo de instancias de Whisper precargadas, de modo que varias solicitudes se transcriben en paralelo sin recargar el modelo.
* **CPU o GPU, el mismo código.** El backend se selecciona según el entorno y según qué imagen de Docker compiles. Una tarjeta CUDA acelera la inferencia, pero todo funciona también en CPU.
* **Se incluye un cliente CLI.** `stt_client.py` envía archivos locales al servidor e imprime el resultado.

### Modelos

Whisper ofrece varios tamaños de modelo. Los modelos más grandes son más precisos y lentos; los más pequeños son rápidos y ligeros.

| Modelo     | Parámetros | VRAM    | Idiomas         | Recomendado para                              |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | multilingüe     | borradores rápidos en hardware modesto        |
| `base`     | 74M        | ~1 GB   | multilingüe     | un valor por defecto ligero y general         |
| `small`    | 244M       | ~2 GB   | multilingüe     | un buen equilibrio entre precisión y velocidad|
| `medium`   | 769M       | ~5 GB   | multilingüe     | mayor precisión cuando puedes ceder memoria   |
| `turbo`    | 809M       | ~6 GB   | multilingüe     | precisión cercana a `large`, mucho más rápido |
| `large`    | 1550M      | ~10 GB  | multilingüe     | mejor calidad, necesita una GPU               |

Las variantes solo para inglés (`tiny.en`, `base.en`, `small.en`, `medium.en`) son algo más precisas con audio en inglés. El valor por defecto es `turbo`, que es la mejor opción global para inglés en una GPU.

### Inicio rápido (Docker)

La forma más fácil de ejecutar el servidor es con Docker. Los archivos del modelo se almacenan en caché en `./models` en el host, de modo que sobreviven a las recompilaciones del contenedor.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La compilación para GPU necesita `nvidia-container-toolkit` en el host. La primera ejecución descarga el modelo Whisper en `./models`.

### API HTTP

Una vez que el servidor esté en marcha, comprueba su estado y envía un archivo de audio para transcribir.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` devuelve el estado del grupo. Que `available` baje a 0 significa que todos los modelos están actualmente en uso:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` acepta un campo `multipart/form-data` llamado `file`, o un cuerpo en bruto `audio/*`. Un parámetro opcional `language` (en la cadena de consulta o como campo del formulario) anula el valor por defecto del servidor para esa solicitud; `auto` detecta automáticamente. En caso de éxito devuelve el texto y los segundos transcurridos:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Las subidas están limitadas a `MAX_CONTENT_LENGTH_MB` (10 MB por defecto); un cuerpo mayor devuelve `413`.

Los errores son uniformes: `error` lleva una categoría genérica y `request_id` correlaciona la respuesta con el registro del servidor, donde se anota la excepción completa.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Cuando `STT_TOKENS` está configurado, cada `POST /api/stt` debe llevar `Authorization: Bearer <token>`; `GET /api/health` permanece abierto para que los healthchecks sigan funcionando.

### Cliente CLI

`stt_client.py` es un pequeño cliente para trabajar con el servidor y probarlo. Lee la dirección del servidor y el token de `STT_URL` y `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### Variables de entorno

`.env` es cargado tanto por el servidor como por el cliente mediante `python-dotenv`.

| Variable                | Por defecto             | Propósito                                          |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | dirección de escucha del servidor                  |
| `STT_PORT`              | `5099`                  | puerto del servidor                                |
| `STT_POOL_SIZE`         | `8`                     | número de instancias de Whisper precargadas        |
| `STT_TOKENS`            | (vacío)                 | tokens válidos separados por comas; vacío desactiva la autenticación |
| `STT_DEBUG`             | `false`                 | modo de depuración de Flask                        |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | tamaño máximo de subida en MB; un cuerpo mayor devuelve `413` |
| `CORS_ORIGINS`          | `*`                     | orígenes CORS permitidos: `*` o una lista separada por comas |
| `GUNICORN_WORKERS`      | `4`                     | procesos de trabajo (solo gunicorn)                |
| `LOG_LEVEL`             | `INFO`                  | nivel de registro                                  |
| `LOG_ACCESS`            | `false`                 | registrar las líneas de acceso de uvicorn          |
| `WHISPER_MODEL`         | `turbo`                 | nombre del modelo Whisper (p. ej. `small.en`, `turbo`) |
| `WHISPER_LANGUAGE`      | `en`                    | idioma de transcripción por defecto                |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | directorio de caché del modelo (`/opt/models` en Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` o `auto`                             |
| `STT_URL`               | `http://localhost:5099` | cliente: URL base del servidor                     |
| `STT_TOKEN`             | (vacío)                 | cliente: token bearer enviado al servidor          |

### Estructura del proyecto

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

### Desarrollo

Los paquetes del sistema `ffmpeg` y `libsndfile1` deben estar presentes. Instala las dependencias de ejecución y de desarrollo:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

El Makefile envuelve las tareas comunes:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

La suite de pruebas sustituye el backend de Whisper, de modo que cubre la capa HTTP (request_id, categorías de error, semántica del grupo de modelos) y se ejecuta en segundos sin descargar un modelo ni necesitar una GPU.

### Licencia

[MIT](../LICENSE)
