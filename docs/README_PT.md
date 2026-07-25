## speech-to-text: um servidor de transcrição Whisper auto-hospedado

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | **[Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md)** | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

O `speech-to-text` converte áudio em texto com o [openai-whisper](https://github.com/openai/whisper), envolvido em um pequeno serviço HTTP que você mesmo executa. Você envia um arquivo de áudio e recebe a transcrição de volta. Sem API externa, sem cobrança por minuto, e o seu áudio nunca sai da sua máquina.

O projeto serve para uso local, transcrição em lote e para rodar o seu próprio servidor de STT na rede.

* **Um servidor HTTP pronto para uso.** O Flask servido pelo uvicorn carrega o Whisper na inicialização e responde a requisições de outras máquinas na sua rede local.
* **Seguro sob concorrência.** O servidor mantém um pool de instâncias do Whisper pré-carregadas, de modo que várias requisições são transcritas em paralelo sem recarregar o modelo.
* **CPU ou GPU, o mesmo código.** O backend é selecionado pelo ambiente e pela imagem Docker que você constrói. Uma placa CUDA acelera a inferência, mas tudo também roda em CPU.
* **Um cliente CLI está incluído.** O `stt_client.py` envia arquivos locais para o servidor e imprime o resultado.

### Modelos

O Whisper traz vários tamanhos de modelo. Modelos maiores são mais precisos e mais lentos; os menores são rápidos e leves.

| Modelo     | Parâmetros | VRAM    | Idiomas         | Bom para                                          |
| ---------- | ---------- | ------- | --------------- | ------------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | multilíngue     | rascunhos rápidos em hardware fraco               |
| `base`     | 74M        | ~1 GB   | multilíngue     | um padrão leve de uso geral                       |
| `small`    | 244M       | ~2 GB   | multilíngue     | um bom equilíbrio entre precisão e velocidade     |
| `medium`   | 769M       | ~5 GB   | multilíngue     | maior precisão quando há memória disponível       |
| `turbo`    | 809M       | ~6 GB   | multilíngue     | precisão próxima do `large`, muito mais rápido    |
| `large`    | 1550M      | ~10 GB  | multilíngue     | melhor qualidade, requer uma GPU                  |

As variantes apenas em inglês (`tiny.en`, `base.en`, `small.en`, `medium.en`) são um pouco mais precisas em áudio em inglês. O padrão é `turbo`, que é a melhor escolha geral para inglês em uma GPU.

### Início rápido (Docker)

A maneira mais fácil de rodar o servidor é com o Docker. Os arquivos de modelo ficam em cache em `./models` no host, então sobrevivem às reconstruções do contêiner.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

A build com GPU precisa do `nvidia-container-toolkit` no host. A primeira execução baixa o modelo do Whisper para `./models`.

### API HTTP

Assim que o servidor estiver no ar, verifique o seu status e envie um arquivo de áudio para transcrição.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

O `GET /api/health` retorna o status do pool. O `available` chegando a 0 significa que todos os modelos estão em uso no momento:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

O `POST /api/stt` aceita um campo `multipart/form-data` chamado `file`, ou um corpo bruto `audio/*`. Um `language` opcional (na query string ou como campo do formulário) sobrescreve o padrão do servidor para aquela requisição; `auto` detecta automaticamente. Em caso de sucesso, ele retorna o texto e os segundos decorridos:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Os uploads são limitados a `MAX_CONTENT_LENGTH_MB` (10 MB por padrão); um corpo maior retorna `413`.

Os erros são uniformes: `error` carrega uma categoria genérica e `request_id` correlaciona a resposta com o log do servidor, onde a exceção completa é registrada.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Quando `STT_TOKENS` está definido, todo `POST /api/stt` precisa enviar `Authorization: Bearer <token>`; o `GET /api/health` permanece aberto para que os healthchecks continuem funcionando.

### Cliente CLI

O `stt_client.py` é um pequeno cliente para trabalhar com o servidor e testá-lo. Ele lê o endereço do servidor e o token de `STT_URL` e `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### Variáveis de ambiente

O `.env` é carregado tanto pelo servidor quanto pelo cliente através do `python-dotenv`.

| Variável                | Padrão                  | Finalidade                                          |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | endereço de bind do servidor                        |
| `STT_PORT`              | `5099`                  | porta do servidor                                   |
| `STT_POOL_SIZE`         | `8`                     | número de instâncias do Whisper pré-carregadas      |
| `STT_TOKENS`            | (vazio)                 | tokens válidos separados por vírgula; vazio desativa a autenticação |
| `STT_DEBUG`             | `false`                 | modo de depuração do Flask                          |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | tamanho máximo de upload em MB; um corpo maior retorna `413` |
| `CORS_ORIGINS`          | `*`                     | origens CORS permitidas: `*` ou uma lista separada por vírgulas |
| `GUNICORN_WORKERS`      | `4`                     | processos worker (apenas gunicorn)                  |
| `LOG_LEVEL`             | `INFO`                  | nível de log                                        |
| `LOG_ACCESS`            | `false`                 | registrar as linhas de acesso do uvicorn           |
| `WHISPER_MODEL`         | `turbo`                 | nome do modelo Whisper (ex.: `small.en`, `turbo`)   |
| `WHISPER_LANGUAGE`      | `en`                    | idioma de transcrição padrão                        |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | diretório de cache de modelos (`/opt/models` no Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` ou `auto`                             |
| `STT_URL`               | `http://localhost:5099` | cliente: URL base do servidor                       |
| `STT_TOKEN`             | (vazio)                 | cliente: token bearer enviado ao servidor           |

### Estrutura do projeto

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

### Desenvolvimento

Os pacotes de sistema `ffmpeg` e `libsndfile1` precisam estar presentes. Instale as dependências de runtime e de desenvolvimento:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

O Makefile encapsula as tarefas comuns:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

A suíte de testes substitui o backend do Whisper por um stub, de modo que cobre a camada HTTP (request_id, categorias de erro, semântica do pool de modelos) e roda em segundos sem baixar um modelo nem precisar de uma GPU.

### Licença

[MIT](../LICENSE)
