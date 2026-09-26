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
* **Transcrição ao vivo.** Envie áudio em streaming por um WebSocket e receba cada frase de volta enquanto ela é falada, atribuída a um locutor quando a diarização está ativada.
* **Uma interface web está incluída.** Envie um arquivo pelo navegador e leia o texto, ou quem disse o quê; ela é servida pelo seu próprio contêiner nginx ao lado do servidor.

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

### Interface web

O `docker compose up` também inicia o `stt_www`, um contêiner nginx que serve a interface do navegador e repassa `/api/` para o servidor, de modo que a interface e a API compartilham um único endereço.

| Protocolo | Porta padrão | Definida com       |
| --------- | ------------ | ------------------ |
| http      | `8080`       | `STT_WWW_PORT`     |
| https     | `8443`       | `STT_WWW_TLS_PORT` |

Abra `http://<host>:8080`. **TRANSCRIBE** tem três fontes. **FILE** envia um arquivo de áudio. **DEVICE** transcreve ao vivo a partir de uma entrada de áudio: um microfone ou um headset, uma fonte `Monitor of ...` no Linux que carrega tudo o que toca pelos alto-falantes ou fones de ouvido, ou, em navegadores Chromium, `Tab or screen audio` para o que toca em uma aba do navegador, ou no sistema inteiro quando o sistema operacional permite. **STREAM** recebe o endereço de um stream ou de um arquivo remoto - rádio pela internet, HLS, RTMP, RTSP, SRT - e o próprio servidor o lê. Em qualquer caso, o resultado aparece abaixo do formulário como texto simples ou, com a diarização ativada, como um bloco por frase com o seu locutor e o seu tempo, cada locutor com a sua própria cor e as frases em que duas pessoas falaram ao mesmo tempo marcadas; uma frase ao vivo aparece cerca de um segundo depois que o locutor faz uma pausa. O resultado pode ser copiado ou baixado como TXT ou JSON. **MODELS** mostra o que o `GET /api/models` informa. Quando `STT_TOKENS` está definido, a interface pede um token uma única vez e o guarda no navegador.

Os navegadores só entregam dispositivos de áudio a uma página segura, então, pela rede, o DEVICE funciona pela porta https (e em `http://localhost`). A porta https usa um certificado autoassinado que o contêiner cria em `./data/certs` na primeira inicialização; coloque ali um `stt.crt` e um `stt.key` reais para substituí-lo. A interface não tem etapa de build nem CDN: o Vue 2 e as suas bibliotecas ficam incluídos em `www/vendor`, então ela funciona em uma máquina sem acesso à internet.

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
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

O `POST /api/stt` aceita um campo `multipart/form-data` chamado `file`, ou um corpo bruto `audio/*`. Um `language` opcional (na query string ou como campo do formulário) sobrescreve o padrão do servidor para aquela requisição; `auto` detecta automaticamente. Em caso de sucesso, ele retorna o texto e os segundos decorridos:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

O idioma pode ser informado como código (`ru`) ou pelo seu nome em inglês (`russian`); qualquer valor que o modelo não conheça é recusado com `400` em vez de falhar no meio de uma transcrição. `GET /api/models` lista os que ele conhece. Isso vale para os backends que aceitam um idioma (`accepts_language: true`). O Parakeet detecta o idioma sozinho e ignora o valor, e pode omitir falas de que não tem certeza sem avisar: em uma gravação com vários idiomas, pode não retornar nada para o idioma minoritário.

O `GET /api/models` informa o que este servidor oferece, para que um cliente não precise adivinhar. Cada backend traz a sua própria lista de idiomas, porque os conjuntos realmente divergem e uma lista mesclada estaria errada para cada backend por si só.

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

O `status` é `loaded` quando uma instância está aguardando em um pool, `installed` quando os pesos estão em disco mas nada foi carregado ainda, e `absent` caso contrário. Um backend que está configurado mas não instalado responde `absent` e nada mais; o motivo vai para o log. O `accepts_language` diz se `?language=` significa alguma coisa para aquele backend. O diarizador informa `languages` como `null` em vez de uma lista vazia, porque ele não produz texto em nenhum idioma.

O cliente CLI lê o mesmo endpoint:

```bash
python3 stt_client.py --list
```

O `POST /api/diarize` responde **quem falou quando**, e nada além disso: ele retorna intervalos de tempo com um número de locutor, nunca texto. Ele fica desativado a menos que `DIARIZE_ENABLED` esteja definido em uma imagem construída com `DIARIZE=true`; caso contrário, ele responde `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Duas observações sobre esses números. Os turnos podem se sobrepor, porque cada canal de locutor é pontuado por conta própria, de modo que duas pessoas falando ao mesmo tempo produzem dois turnos cobrindo os mesmos segundos. E os rótulos são posições nesta gravação específica, ordenados por quem falou primeiro: eles não são identidades, e a mesma pessoa recebe um número diferente na próxima requisição. Dar nome a um locutor exigiria uma etapa de cadastro que este serviço não possui. No máximo oito locutores são distinguidos.

Dois backends de transcrição estão disponíveis. O **Whisper** é o padrão e aceita um `language`. O **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) cobre 25 idiomas europeus, detecta o idioma sozinho e, portanto, não recebe nenhum argumento `language`, o que o `GET /api/models` informa como `accepts_language: false`. Selecione-o com `STT_BACKEND=parakeet` em uma imagem construída com `PARAKEET=true`; é uma escolha de deploy, não uma escolha por requisição, porque um segundo modelo residente significaria um segundo conjunto de pesos em cada worker.

Nenhum dos dois backends lida com sobreposição. O modelo da NVIDIA que lida com sobreposição é distribuído apenas como um checkpoint do NeMo, e o NeMo fixa uma versão do PyTorch diferente da build CUDA deste projeto, de modo que não é instalável aqui.

O `POST /api/transcript` responde **quem disse o quê**: ele executa a diarização e a transcrição sobre o mesmo áudio e as une pelo tempo. Ele precisa que a diarização esteja ativada; caso contrário, responde `503`.

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

`turns` é a saída bruta do diarizador e `segments` é a junção, mantidos separados para que um chamador que desconfie da atribuição ainda possa ver o que o diarizador disse. `text` é a transcrição simples, idêntica à que o `/api/stt` retorna para o mesmo arquivo. Uma frase que nenhum turno cobre mantém `"speaker": null` em vez de ser entregue ao turno mais próximo.

`overlap` marca uma frase durante a qual outra pessoa também estava falando. A NVIDIA afirma explicitamente que combinar um modelo convencional de locutor único com a diarização não equivale a um modelo construído para fala sobreposta: um intervalo de tempo extraído ainda contém todas as vozes que se sobrepõem a ele, de modo que essas frases podem se misturar ou selecionar as palavras do locutor errado. Trate um segmento marcado com `overlap` como o ponto em que a transcrição é menos confiável.

O `/api/stream` é um WebSocket para **transcrição ao vivo**: o áudio entra à medida que é gravado, e cada frase volta cerca de um segundo depois que o locutor faz uma pausa. Mensagens de texto JSON carregam o controle, mensagens binárias carregam o áudio:

1. O cliente envia `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`. Todos os campos, exceto `type`, são opcionais. O `token` é a forma de um navegador se autenticar, já que ele não consegue definir cabeçalhos em um WebSocket; outros clientes podem, em vez disso, enviar `Authorization: Bearer <token>` no handshake.
2. O servidor responde `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`.
3. O cliente envia PCM bruto - 16 bits com sinal, little-endian, mono, 16 kHz - como mensagens binárias de qualquer tamanho, e `{"type": "stop"}` quando termina.
4. O servidor envia um `segment` para cada frase, `progress` cerca de uma vez por segundo e `done` antes de fechar:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

O áudio também pode vir de outro lugar. Com `"source": "url", "url": "https://..."` na mensagem de início, o cliente não envia áudio nenhum: o servidor lê o stream naquele endereço através do ffmpeg até que ele termine ou o cliente envie `stop`. Rádio pela internet, HLS, RTMP, RTSP e SRT funcionam; o esquema precisa ser `http`, `https`, `rtmp`, `rtmps`, `rtsp` ou `srt`. O que uma fonte ao vivo já tem acumulado é lido de uma vez, e o resto no ritmo da própria fonte, de modo que um arquivo remoto chega do jeito que uma transmissão chegaria.

Como isso faz o servidor buscar um endereço escolhido por um cliente, o recurso é cercado de limites. O ffmpeg só pode usar protocolos de rede, de modo que nem uma URL nem uma playlist conseguem fazê-lo ler um arquivo local, e nada pode fazê-lo escutar conexões: os modos SRT `listener` e `rendezvous` e qualquer parâmetro `listen` são recusados. Uma página de outro site não consegue iniciar uma fonte assim (`Forbidden`): os navegadores não aplicam CORS a WebSockets, então o socket verifica se a origem da página é este host ou está listada em `CORS_ORIGINS`. No máximo quatro fontes URL rodam ao mesmo tempo (`Service Unavailable` além disso), e o log registra cada endereço sem as suas credenciais nem a query string. Ainda assim, ele consegue alcançar hosts da própria rede do servidor, o que é justamente o objetivo no caso de uma câmera e o motivo para definir `STT_TOKENS` em um servidor que outras pessoas consigam alcançar.

Uma falha é um único `{"type": "error", "error": "<category>", "request_id": "..."}` seguido de um fechamento, com as categorias de erro HTTP mais `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` e `Forbidden`.

Uma frase termina em uma pausa de 0,6 s, ou no seu momento mais silencioso quando passa de 15 s, e é transcrita sozinha com um modelo emprestado do mesmo pool dos uploads, de modo que um pool ocupado atrasa as frases ao vivo em vez de fazê-las falhar. Com `diarize`, o diarizador roda no seu modo de streaming e carrega um cache de locutores de um trecho para o outro, de modo que um locutor mantém o mesmo número durante toda a sessão. O socket só existe quando o servidor roda sob o uvicorn (`python3 stt_server.py`, o padrão no Docker): o servidor de depuração do Flask e os workers sync do gunicorn não falam WebSocket.

Os uploads são limitados a `MAX_CONTENT_LENGTH_MB` (10 MB por padrão); um corpo maior retorna `413`.

Os erros são uniformes: `error` carrega uma categoria genérica e `request_id` correlaciona a resposta com o log do servidor, onde a exceção completa é registrada.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Quando `STT_TOKENS` está definido, toda rota exceto `GET /api/health` precisa enviar `Authorization: Bearer <token>`; ela permanece aberta para que os healthchecks continuem funcionando.

### Cliente CLI

O `stt_client.py` é um pequeno cliente para trabalhar com o servidor e testá-lo. Ele lê o endereço do servidor e o token de `STT_URL` e `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

O `--stream` toca um arquivo em `/api/stream` na velocidade da fala e imprime cada frase à medida que ela volta, com `--speakers` para a atribuição de locutores:

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `WHISPER_MODEL`         | `small.en`              | nome do modelo Whisper (ex.: `small.en`, `turbo`)   |
| `WHISPER_LANGUAGE`      | `en`                    | idioma de transcrição padrão                        |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | diretório de cache de modelos (`/opt/models` no Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` ou `auto`                             |
| `STT_BACKEND`           | `whisper`               | backend de transcrição: `whisper` ou `parakeet`     |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | id do modelo Parakeet                               |
| `PARAKEET_DOWNLOAD_ROOT` | `models`                | diretório de cache do modelo Parakeet               |
| `DIARIZE_ENABLED`       | `false`                 | ativar `POST /api/diarize` (requer uma imagem `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | id do modelo de diarização                          |
| `DIARIZE_POOL_SIZE`     | `1`                     | instâncias do diarizador pré-carregadas             |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | diretório de cache do modelo de diarização          |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilidade de atividade do locutor contada como fala |
| `STT_WWW_PORT`          | `8080`                  | porta http da interface web (compose)               |
| `STT_WWW_TLS_PORT`      | `8443`                  | porta https da interface web (compose)              |
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
│   ├── model_pool.py    # pools of pre-loaded Whisper and diarizer instances
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── align.py         # joins transcription segments to speaker turns
│   ├── live.py          # the /api/stream websocket: protocol and sessions
│   ├── stream.py        # live transcription core: pauses, phrases, per-phrase transcription
│   ├── url_source.py    # URL sources for /api/stream: vetting the address, running ffmpeg
│   ├── stt.py           # Whisper wrapper
│   ├── parakeet.py      # NVIDIA Parakeet wrapper, the second transcriber
│   ├── backends.py      # which module transcribes, per STT_BACKEND
│   └── diarize.py       # speaker diarization (who spoke when, no text)
├── Dockerfile           # GPU build (CUDA 13.0)
├── Dockerfile-cpu       # CPU build
├── Dockerfile-www       # web UI image (nginx)
├── nginx/               # stt_www config: static UI, /api/ proxy, self-signed TLS
├── www/                 # web UI: Vue 2 without a build step, libraries vendored
├── docs/                # README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### Desenvolvimento

Os pacotes de sistema `ffmpeg` e `libsndfile1` precisam estar presentes. Instale as dependências de runtime e de desenvolvimento:

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

A suíte de testes substitui o backend do Whisper por um stub, de modo que cobre a camada HTTP (request_id, categorias de erro, semântica do pool de modelos) e roda em segundos sem baixar um modelo nem precisar de uma GPU.

### Licença

[MIT](../LICENSE)
