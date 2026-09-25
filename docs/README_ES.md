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
* **Transcripción en directo.** Envía audio en streaming por un WebSocket y recibe cada frase a medida que se pronuncia, atribuida a un hablante cuando la diarización está activada.
* **Se incluye una interfaz web.** Sube un archivo desde el navegador y lee el texto, o quién dijo qué; la sirve su propio contenedor nginx junto al servidor.

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

#### Varios modelos

`STT_MODELS` carga varios modelos de transcripción al arrancar, cada uno con su propio pool, y deja que cada petición elija uno con `model`. Las entradas van separadas por comas con la forma `backend:model[@pool]`:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # el modelo de una petición sin `model`; vacío significa la primera entrada
```

Solo se elige entre los modelos cargados al arrancar: una petición nunca provoca una descarga ni una carga, y un modelo que no está cargado se rechaza con `400`. Cada modelo de la lista ocupa memoria mientras el servidor esté en marcha, aproximadamente `workers x (pool x tamaño del modelo)` sumado sobre la lista, más el diarizador. `turbo@2,small@1,parakeet@1` en una GPU son unos 12 + 2 + 3 = 17 GB por proceso. Con gunicorn cada worker sync atiende una petición a la vez, así que pon `@1` en cada entrada y escala con `GUNICORN_WORKERS`. Una entrada sin `@pool` recibe `STT_POOL_SIZE`, que fuera de Docker vale 8, así que escribe `@N` de forma explícita. Cargar varios modelos grandes tarda más que cargar uno, así que aumenta el `start_period` del healthcheck en el archivo compose si el contenedor se marca como unhealthy mientras arranca.

Con `STT_MODELS` vacío, `STT_BACKEND`, `WHISPER_MODEL` y `PARAKEET_MODEL` eligen el único modelo como antes y el servidor carga exactamente lo mismo que antes; las respuestas solo ganan campos. Si está definido, esas variables ya no deciden qué se carga. En Docker, pon `STT_MODELS` y `STT_DEFAULT_MODEL` en `.env`, no en el bloque `environment:` del compose, que sobrescribe `.env`. Una entrada de Parakeet sigue necesitando una imagen construida con `PARAKEET=true`, y el servidor se niega a arrancar ante un backend desconocido, ante los mismos pesos listados dos veces (`turbo` y `large-v3-turbo`) o ante un `STT_DEFAULT_MODEL` que no esté en la lista. Un modelo indicado como ruta de archivo se sirve con su nombre de archivo sin `.pt`, de modo que la ruta nunca llega a un cliente. `STT_DEFAULT_MODEL` puede nombrar una entrada así por ese nombre o por la ruta tal como está escrita en `STT_MODELS`, y sus idiomas son los del checkpoint que nombra el archivo: `/models/large-v3.pt` conoce lo que conoce `large-v3`. Dos entradas que se servirían con el mismo nombre (`/a/model.pt` y `/b/model.pt`), o una entrada que se serviría con el nombre de un backend (`/models/parakeet.pt`), detienen el servidor al arrancar.

### Inicio rápido (Docker)

La forma más fácil de ejecutar el servidor es con Docker. Los archivos del modelo se almacenan en caché en `./models` en el host, de modo que sobreviven a las recompilaciones del contenedor.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La compilación para GPU necesita `nvidia-container-toolkit` en el host. La primera ejecución descarga el modelo Whisper en `./models`.

### Interfaz web

`docker compose up` también arranca `stt_www`, un contenedor nginx que sirve la interfaz del navegador y reenvía `/api/` al servidor, de modo que la interfaz y la API comparten una misma dirección.

| Protocolo | Puerto por defecto | Se define con      |
| --------- | ------------------ | ------------------ |
| http      | `8080`             | `STT_WWW_PORT`     |
| https     | `8443`             | `STT_WWW_TLS_PORT` |

Abre `http://<host>:8080`. **TRANSCRIBE** tiene dos fuentes. **FILE** sube un archivo de audio. **DEVICE** transcribe en directo desde una entrada de audio: un micrófono o unos auriculares con micrófono, una fuente `Monitor of ...` en Linux que lleva todo lo que suena por los altavoces o los auriculares, o `Tab or screen audio` para lo que suena en una pestaña del navegador, o en todo el sistema cuando el sistema operativo lo permite. En ambos casos el resultado aparece bajo el formulario como texto plano o, con la diarización activada, como un bloque por frase con su hablante y su tiempo, cada hablante en su propio color y marcadas las frases en las que dos personas hablaron a la vez; una frase en directo aparece alrededor de un segundo después de que el hablante hace una pausa. El resultado se puede copiar o descargar como TXT o JSON. Con varios modelos cargados (`STT_MODELS`), un selector de modelo junto al modo y el idioma elige el modelo para cualquiera de las dos fuentes, alimentado desde `GET /api/models`, y la lista de idiomas sigue al modelo elegido. **MODELS** muestra lo que informa `GET /api/models`. Cuando `STT_TOKENS` está configurado, la interfaz pide un token una sola vez y lo guarda en el navegador.

Los navegadores solo entregan los dispositivos de audio a una página segura, así que a través de la red DEVICE funciona por el puerto https (y en `http://localhost`). El puerto https usa un certificado autofirmado que el contenedor crea en `./data/certs` en su primer arranque; coloca ahí un `stt.crt` y un `stt.key` reales para sustituirlo. La interfaz no tiene paso de compilación ni CDN: Vue 2 y sus bibliotecas van incluidas en `www/vendor`, así que funciona en una máquina sin salida a internet.

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

`GET /api/health` devuelve el estado de los grupos. Los `pool_size` y `available` de primer nivel describen el modelo por defecto, el que espera una petición sin `model`; que `available` baje a 0 significa que todas sus instancias están ocupadas. `models` informa de cada modelo cargado por su id:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

Cuando `STT_TOKENS` está configurado, `default_model` y `models` solo aparecen en la respuesta a una petición con un token válido: igual que `GET /api/models`, describen la configuración del servidor. Un healthcheck sin token sigue recibiendo `status`, `pool_size`, `available` y `diarize`.

`POST /api/stt` acepta un campo `multipart/form-data` llamado `file` o un cuerpo `audio/*` sin procesar. Un `model` opcional (en la query string o como campo de formulario) elige uno de los modelos cargados: su id, un alias (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), la forma `backend:model` o el nombre del backend a secas, que significa el modelo por defecto si pertenece a ese backend y, si no, el primer modelo de ese backend. Sin `model` responde el modelo por defecto. Un `language` opcional (en la query string o como campo de formulario) sustituye el valor por defecto del servidor para esa petición; `auto` lo detecta automáticamente. Si todo va bien, devuelve el texto, los segundos transcurridos, el modelo que transcribió y el idioma: el código que Whisper detectó o usó (siempre `en` en un modelo solo en inglés), o `null` en Parakeet, que no lo informa.

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

El idioma puede indicarse como código (`ru`) o con su nombre en inglés (`russian`); cualquier valor que el modelo no conozca se rechaza con `400` en lugar de fallar a mitad de la transcripción. `GET /api/models` enumera lo que conoce cada modelo. Lo estricta que sea la comprobación de `language` depende del modelo y de si la petición lo nombró:

| Modelo | `language` que acepta | Petición sin `model` | Petición con `model` |
| --- | --- | --- | --- |
| Whisper multilingüe | un código o nombre en inglés de su lista | `400 Unsupported language` fuera de la lista | lo mismo |
| Whisper solo inglés (`.en`) | `en` y `auto` | otro código conocido se transcribe como inglés | `400 Unsupported language` |
| Parakeet | ninguno, detecta el idioma por sí mismo | cualquier valor se acepta y se ignora | un código de su lista, o `400` |

Parakeet solo acepta códigos, no nombres en inglés, y puede omitir en silencio el habla de la que no está seguro: en una grabación con varios idiomas puede no devolver nada para el idioma minoritario.

Una ruta de archivo de Whisper cuyo nombre no coincide con ningún checkpoint conocido, como un fine-tune en `/models/my-large-v3-finetune.pt`, tiene una lista de idiomas que solo se deduce de ese nombre, así que una petición sin `model` le pasa cualquier código conocido, como siempre; una petición que lo nombra se sigue comprobando contra la lista deducida.

Los errores `400` de estas dos opciones son `Invalid model` (ningún backend conoce el nombre), `Model not loaded` (un modelo real que este servidor no cargó), `Invalid language` (no es un idioma en absoluto) y `Unsupported language` (un idioma real que el modelo elegido no acepta). Los cuatro se devuelven antes de decodificar el audio.

`GET /api/models` informa de lo que lleva este servidor, para que un cliente no tenga que adivinarlo. Cada modelo cargado tiene su propia fila, igual que cada transcriptor sin nada cargado (`selectable: false`) y el diarizador. Cada fila trae su propia lista de idiomas, porque los conjuntos realmente difieren y una lista combinada sería incorrecta para cada modelo por separado.

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

`id` es lo que una petición pasa como `model`, y exactamente una fila tiene `default: true`: su id es `default_model` y su backend es el `default` de primer nivel. `pool_size` y `available` son el pool de ese modelo. `status` es `loaded` cuando existen instancias del modelo, libres u ocupadas, `installed` cuando los pesos están en disco pero todavía no hay nada cargado, y `absent` en otro caso. Un backend configurado pero no instalado dice `absent` y nada más; el motivo va al log. `accepts_language` indica si `?language=` significa algo para ese backend. El diarizador informa `null` en lugar de una lista vacía de idiomas, porque no produce texto en ningún idioma.

El cliente CLI lee el mismo endpoint:

```bash
python3 stt_client.py --list
```

`POST /api/diarize` responde **quién habló y cuándo**, y nada más: devuelve intervalos de tiempo con un número de hablante, nunca texto. Está desactivado salvo que `DIARIZE_ENABLED` esté configurado en una imagen compilada con `DIARIZE=true`; en caso contrario responde `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Dos cosas sobre esos números. Los turnos pueden solaparse, porque cada canal de hablante se evalúa por separado, de modo que dos personas hablando a la vez producen dos turnos que cubren los mismos segundos. Y las etiquetas son posiciones dentro de esta única grabación, ordenadas según quién habló primero: no son identidades, y la misma persona recibe un número distinto en la siguiente solicitud. Poner nombre a un hablante requiere un paso de registro previo que este servicio no tiene. Se distinguen como máximo ocho hablantes.

Hay dos backends de transcripción disponibles. **Whisper** es el que viene por defecto y acepta un `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) cubre 25 idiomas europeos, detecta el idioma por sí mismo y por eso no acepta ningún argumento `language`, lo que `GET /api/models` indica como `accepts_language: false`. Necesita una imagen construida con `PARAKEET=true`. Elígelo para todo el servidor con `STT_BACKEND=parakeet`, o cárgalo junto a Whisper mediante `STT_MODELS` y elígelo en cada petición con `model`. Una petición solo elige entre los modelos cargados al arrancar, y cada modelo cargado mantiene sus pesos en cada worker, así que la memoria es el número de workers por la suma de los pools.

Ninguno de los dos backends maneja el habla solapada. El modelo de NVIDIA que sí la maneja se distribuye únicamente como un checkpoint de NeMo, y NeMo fija una versión de PyTorch distinta de la que usa la compilación CUDA de este proyecto, así que aquí no se puede instalar.

`POST /api/transcript` responde **quién dijo qué**: ejecuta la diarización y la transcripción sobre el mismo audio y las une por tiempo. Necesita que la diarización esté activada; en caso contrario responde `503`. Acepta los mismos `model` y `language` que `/api/stt` e indica en `model` el modelo que transcribió.

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

`turns` es la salida en bruto del diarizador y `segments` es la unión, mantenidos aparte para que quien desconfíe de la atribución pueda ver igualmente lo que dijo el diarizador. `text` es la transcripción simple, idéntica a la que devuelve `/api/stt` para el mismo archivo. Una frase que ningún turno cubre conserva `"speaker": null` en lugar de entregarse al turno más cercano.

`overlap` marca una frase durante la cual alguien más estaba hablando también. NVIDIA es explícita en que combinar un modelo convencional de un solo hablante con la diarización no equivale a un modelo construido para habla solapada: un intervalo de tiempo extraído sigue conteniendo todas las voces que se solapan con él, de modo que esas frases pueden fusionarse o seleccionar las palabras del hablante equivocado. Trata un segmento marcado con `overlap` como el lugar donde la transcripción es menos fiable.

`/api/stream` es un WebSocket para la **transcripción en directo**: el audio entra a medida que se graba, y cada frase vuelve alrededor de un segundo después de que el hablante hace una pausa. Los mensajes de texto JSON llevan el control y los mensajes binarios llevan el audio:

1. El cliente envía `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}`. Todos los campos salvo `type` son opcionales. `model` elige uno de los modelos cargados igual que `model` en `/api/stt`, y el idioma se comprueba contra ese modelo; sin él, sirve el modelo predeterminado y el idioma solo se comprueba para ver si es un idioma, como siempre, así que un código que el modelo predeterminado no conoce falla al transcribir una frase. `token` es la forma en que se autentica un navegador, ya que no puede establecer cabeceras en un WebSocket; otros clientes pueden enviar en su lugar `Authorization: Bearer <token>` en el handshake.
2. El servidor responde `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}`.
3. El cliente envía PCM en bruto - 16 bits con signo, little-endian, mono, 16 kHz - como mensajes binarios de cualquier tamaño, y `{"type": "stop"}` cuando termina.
4. El servidor envía un `segment` por cada frase, `progress` aproximadamente una vez por segundo y `done` antes de cerrar:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

El audio también puede venir de otro sitio. Con `"source": "url", "url": "https://..."` en el mensaje de inicio el cliente no envía ningún audio: el servidor lee el flujo de esa dirección mediante ffmpeg, al ritmo propio de la fuente, hasta que termina o el cliente envía `stop`. Funcionan la radio por internet, HLS, RTMP, RTSP y SRT; el esquema debe ser `http`, `https`, `rtmp`, `rtmps`, `rtsp` o `srt`, y ffmpeg está limitado a protocolos de red, de modo que una URL o una lista de reproducción no pueden hacer que lea un archivo local. Aun así, hace que el servidor acceda a una dirección elegida por un cliente, incluidas direcciones de su propia red: configura `STT_TOKENS` en cualquier servidor al que otros puedan llegar.

Un fallo es un único `{"type": "error", "error": "<category>", "request_id": "..."}` seguido de un cierre, con las categorías de error de HTTP más `Invalid start message`, `Invalid audio frame`, `Invalid stream URL` y `Stream source failed`.

Una frase termina en una pausa de 0,6 s, o en su momento más silencioso una vez que supera los 15 s, y se transcribe por separado con un modelo tomado del mismo grupo que las subidas, de modo que un grupo ocupado retrasa las frases en directo en lugar de hacerlas fallar. Con `diarize`, el diarizador funciona en su modo de streaming y mantiene una caché de hablantes de un fragmento a otro, de modo que un hablante conserva el mismo número durante toda la sesión. El socket solo existe cuando el servidor se ejecuta bajo uvicorn (`python3 stt_server.py`, el modo por defecto en Docker): el servidor de depuración de Flask y los procesos de trabajo sync de gunicorn no hablan WebSocket.

Las subidas están limitadas a `MAX_CONTENT_LENGTH_MB` (10 MB por defecto); un cuerpo mayor devuelve `413`.

Los errores son uniformes: `error` lleva una categoría genérica y `request_id` correlaciona la respuesta con el registro del servidor, donde se anota la excepción completa.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Cuando `STT_TOKENS` está configurado, cada ruta debe llevar `Authorization: Bearer <token>`, excepto `GET /api/health`, que permanece abierto para que los healthchecks sigan funcionando.

### Cliente CLI

`stt_client.py` es un pequeño cliente para trabajar con el servidor y probarlo. Lee la dirección del servidor y el token de `STT_URL` y `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` y `--language` (también como `--model=NOMBRE`) solo se envían si se indican, de modo que en otro caso se aplica el valor por defecto del servidor; cada línea de resultado muestra el modelo y el idioma que usó el servidor. `--list` muestra el modelo por defecto y una línea por modelo con su estado, si una petición puede elegirlo, su pool y sus idiomas.

`--stream` reproduce un archivo en `/api/stream` a la velocidad del habla e imprime cada frase según va llegando, con `--speakers` para atribuir hablantes:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### Variables de entorno

`.env` es cargado tanto por el servidor como por el cliente mediante `python-dotenv`.

| Variable                | Por defecto             | Propósito                                          |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | dirección de escucha del servidor                  |
| `STT_PORT`              | `5099`                  | puerto del servidor                                |
| `STT_POOL_SIZE`         | `8`                     | instancias por modelo; valor por defecto de una entrada de `STT_MODELS` sin `@pool` |
| `STT_TOKENS`            | (vacío)                 | tokens válidos separados por comas; vacío desactiva la autenticación |
| `STT_DEBUG`             | `false`                 | modo de depuración de Flask                        |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | tamaño máximo de subida en MB; un cuerpo mayor devuelve `413` |
| `CORS_ORIGINS`          | `*`                     | orígenes CORS permitidos: `*` o una lista separada por comas |
| `GUNICORN_WORKERS`      | `4`                     | procesos de trabajo (solo gunicorn)                |
| `LOG_LEVEL`             | `INFO`                  | nivel de registro                                  |
| `LOG_ACCESS`            | `false`                 | registrar las líneas de acceso de uvicorn          |
| `WHISPER_MODEL`         | `small.en`              | nombre del modelo Whisper (p. ej. `small.en`, `turbo`) cuando `STT_MODELS` está vacío |
| `WHISPER_LANGUAGE`      | `en`                    | idioma por defecto de todos los modelos Whisper |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | directorio de caché del modelo (`/opt/models` en Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` o `auto`                             |
| `STT_BACKEND`           | `whisper`               | backend de transcripción: `whisper` o `parakeet` cuando `STT_MODELS` está vacío |
| `STT_MODELS`            | (vacío)                 | varios modelos a la vez: `backend:model[@pool]`, separados por comas |
| `STT_DEFAULT_MODEL`     | (vacío)                 | modelo de una petición sin `model`; vacío significa la primera entrada de `STT_MODELS` |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | identificador del modelo Parakeet                  |
| `PARAKEET_DOWNLOAD_ROOT` | `models`                | directorio de caché del modelo Parakeet            |
| `DIARIZE_ENABLED`       | `false`                 | activar `POST /api/diarize` (requiere una imagen `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | identificador del modelo de diarización            |
| `DIARIZE_POOL_SIZE`     | `1`                     | instancias de diarizador precargadas               |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | directorio de caché del modelo de diarización      |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilidad de actividad del hablante contada como habla |
| `STT_WWW_PORT`          | `8080`                  | puerto http de la interfaz web (compose)            |
| `STT_WWW_TLS_PORT`      | `8443`                  | puerto https de la interfaz web (compose)           |
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
│   ├── model_pool.py    # a pool per transcription model, and one for the diarizer
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── align.py         # joins transcription segments to speaker turns
│   ├── live.py          # the /api/stream websocket: protocol and sessions
│   ├── stream.py        # live transcription core: pauses, phrases, per-phrase transcription
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
├── docs/                # README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### Desarrollo

Los paquetes del sistema `ffmpeg` y `libsndfile1` deben estar presentes. Instala las dependencias de ejecución y de desarrollo:

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

La suite de pruebas sustituye el backend de Whisper, de modo que cubre la capa HTTP (request_id, categorías de error, semántica del grupo de modelos) y se ejecuta en segundos sin descargar un modelo ni necesitar una GPU.

### Licencia

[MIT](../LICENSE)
