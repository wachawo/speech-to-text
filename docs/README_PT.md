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

#### Vários modelos

O `STT_MODELS` carrega vários modelos de transcrição na inicialização, cada um com seu próprio pool, e deixa cada requisição escolher um com `model`. As entradas são separadas por vírgula no formato `backend:model[@pool]`:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # o modelo de uma requisição sem `model`; vazio significa a primeira entrada
```

A escolha acontece apenas entre os modelos carregados na inicialização: uma requisição nunca dispara um download nem um carregamento, e um modelo que não está carregado é recusado com `400`. Cada modelo da lista ocupa memória enquanto o servidor estiver rodando, aproximadamente `workers x (pool x tamanho do modelo)` somado sobre a lista, mais o diarizador. `turbo@2,small@1,parakeet@1` em uma GPU ocupa cerca de 12 + 2 + 3 = 17 GB por processo. No gunicorn, cada worker sync atende uma requisição por vez, então dê `@1` a cada entrada e escale com `GUNICORN_WORKERS`. Uma entrada sem `@pool` recebe `STT_POOL_SIZE`, que fora do Docker vale 8, então escreva `@N` explicitamente. Carregar vários modelos grandes demora mais do que carregar um, então aumente o `start_period` do healthcheck no arquivo compose se o contêiner for marcado como unhealthy durante a inicialização.

Com `STT_MODELS` vazio, `STT_BACKEND`, `WHISPER_MODEL` e `PARAKEET_MODEL` escolhem o modelo único como antes, e o servidor carrega exatamente o que carregava antes; as respostas apenas ganham campos. Quando ele está definido, essas variáveis deixam de decidir o que é carregado. No Docker, coloque `STT_MODELS` e `STT_DEFAULT_MODEL` no `.env`, não no bloco `environment:` do compose, que sobrescreve o `.env`. Uma entrada do Parakeet continua exigindo uma imagem construída com `PARAKEET=true`, e o servidor se recusa a iniciar com um backend desconhecido, com os mesmos pesos listados duas vezes (`turbo` e `large-v3-turbo`) ou com um `STT_DEFAULT_MODEL` que não está na lista. Um modelo informado como caminho de arquivo é servido pelo nome do arquivo sem `.pt`, de modo que o caminho nunca chega a um cliente. `STT_DEFAULT_MODEL` pode indicar uma entrada assim por esse nome ou pelo caminho exatamente como está escrito em `STT_MODELS`, e os idiomas dela são os do checkpoint que o nome do arquivo indica: `/models/large-v3.pt` conhece o que `large-v3` conhece. Duas entradas que seriam servidas com o mesmo nome (`/a/model.pt` e `/b/model.pt`), ou uma entrada servida com o nome de um backend (`/models/parakeet.pt`), impedem o servidor de iniciar.

### Início rápido (Docker)

A maneira mais fácil de rodar o servidor é com o Docker. Os arquivos de modelo ficam em cache em `./models` no host, então sobrevivem às reconstruções do contêiner.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
docker compose -f docker-compose-p40.yml up --build    # Pascal GPU such as Tesla P40 (CUDA 12.6), no web UI
```

A build com GPU precisa do `nvidia-container-toolkit` no host. A primeira execução baixa o modelo do Whisper para `./models`. A operação em um servidor - atualizações, rollbacks, certificados, dependências - é descrita em [docs/DEPLOY.md](DEPLOY.md).

### Interface web

O `docker compose up` também inicia o `stt_www`, um contêiner nginx que serve a interface do navegador e repassa `/api/` para o servidor, de modo que a interface e a API compartilham um único endereço. Ele escuta em uma única porta, `STT_WWW_PORT` (padrão `5053`), por https, a menos que `STT_WWW_SCHEME=http` esteja definido.

Abra `https://<host>:5053`. **TRANSCRIBE** tem três fontes. **FILE** envia um arquivo de áudio. **DEVICE** transcreve ao vivo a partir de uma entrada de áudio: um microfone ou um headset, uma fonte `Monitor of ...` no Linux que carrega tudo o que toca pelos alto-falantes ou fones de ouvido, ou, em navegadores Chromium, `Tab or screen audio` para o que toca em uma aba do navegador, ou no sistema inteiro quando o sistema operacional permite. **STREAM** recebe o endereço de um stream ou de um arquivo remoto - rádio pela internet, HLS, RTMP, RTSP, SRT - e o próprio servidor o lê. Em qualquer caso, o resultado aparece abaixo do formulário como texto simples ou, com a diarização ativada, como um bloco por frase com o seu locutor e o seu tempo, cada locutor com a sua própria cor e as frases em que duas pessoas falaram ao mesmo tempo marcadas; uma frase ao vivo aparece cerca de um segundo depois que o locutor faz uma pausa. O resultado pode ser copiado ou baixado como TXT ou JSON, e cada fonte guarda o seu último resultado enquanto você olha outra tela. O FILE também tem um modo **Turns**, o `POST /api/diarize` sozinho: quem falou quando, desenhado como uma linha do tempo com uma faixa por locutor e marcados os trechos em que duas pessoas falam ao mesmo tempo. Com vários modelos carregados (`STT_MODELS`), um seletor de modelo ao lado do modo e do idioma escolhe o modelo para as três fontes, FILE, DEVICE e STREAM, alimentado por `GET /api/models`, e a lista de idiomas acompanha o modelo escolhido; o Turns não transcreve nada e não envia modelo. **MODELS** mostra o que o `GET /api/models` informa. Quando `STT_TOKENS` está definido, a interface pede um token uma única vez e o guarda no navegador.

Os navegadores só entregam dispositivos de áudio a uma página segura, então, pela rede, o DEVICE precisa do esquema https; com http ele só funciona em `http://localhost`. Com https, uma requisição `http://` simples para essa porta é redirecionada para https, e o contêiner cria um certificado autoassinado em `./data/certs` na primeira inicialização; coloque ali um `stt.crt` e um `stt.key` reais para substituí-lo. A interface não tem etapa de build nem CDN: o Vue 2 e as suas bibliotecas ficam incluídos em `www/vendor`, então ela funciona em uma máquina sem acesso à internet.

### API HTTP

Assim que o servidor estiver no ar, verifique o seu status e envie um arquivo de áudio para transcrição.

```bash
curl localhost:5051/api/health

curl -X POST localhost:5051/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5051/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

O `GET /api/health` retorna o status dos pools. Os campos `pool_size` e `available` do nível superior descrevem o modelo padrão, aquele que uma requisição sem `model` aguarda; o `available` chegando a 0 significa que todas as instâncias dele estão em uso. `models` informa cada modelo carregado pelo seu id:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

Quando `STT_TOKENS` está definido, `default_model` e `models` só aparecem na resposta a uma requisição com um token válido: assim como `GET /api/models`, eles descrevem a configuração do servidor. Um healthcheck sem token continua recebendo `status`, `pool_size`, `available` e `diarize`.

O `GET /api/health?deep=1` também passa um segundo de silêncio por cada modelo carregado, um de cada vez, e informa cada um como `ok`, `busy` (nenhuma instância ficou livre em cinco segundos) ou `failed`: cada modelo de transcrição pelo seu id em `deep.models`, `deep.transcriber` como o pior deles e `deep.diarizer` quando a diarização está ativada. Ele responde `503` se algum falhar. Isso custa trabalho de GPU, então, enquanto `STT_TOKENS` estiver definido, ele exige um token; a verificação simples continua aberta para os healthchecks dos contêineres.

O `GET /metrics` expõe métricas do Prometheus: requisições por rota e status, suas durações, respostas de erro por categoria, tamanhos dos pools e instâncias livres, sessões ao vivo em andamento e iniciadas, segmentos descartados pelo detector de voz e áudio ao vivo abandonado por uma sessão que ficou para trás. Os gauges `stt_pool_*` sem rótulos descrevem o modelo padrão e o diarizador; `stt_model_pool_size` e `stt_model_pool_available` trazem cada modelo carregado, com os rótulos `model` e `backend`. Por modelo de transcrição há ainda dois histogramas e um contador: `stt_model_inference_seconds` (rótulos `model` e `backend`) mede quanto cada chamada ao modelo levou para transcrever seu áudio, `stt_model_wait_seconds` (rótulo `model`) quanto cada empréstimo esperou por uma instância livre, e `stt_model_wait_timeouts_total` (rótulo `model`) conta as esperas que se esgotaram - um 503 após `STT_QUEUE_TIMEOUT`, ou uma sessão ao vivo ou um job que esperou demais; a sonda da verificação de saúde profunda não entra em nenhum dos dois. Os dois histogramas usam os buckets 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 2.5, 5, 10, 30, 60 e 120 segundos, finos abaixo de um segundo para distinguir frases curtas. Assim como o health, ele não exige token, e o `stt_www` não faz proxy dele: consulte `STT_PORT` diretamente. Também como no health, com `STT_TOKENS` definido as séries por modelo só aparecem em uma coleta que envia um token válido, porque nomeiam os modelos; sem ele, os dois gauges dos pools ficam vazios e os histogramas de latência e o contador de esperas esgotadas nem aparecem. No gunicorn, cada worker conta por si.

O `POST /api/stt` aceita um campo `multipart/form-data` chamado `file` ou um corpo `audio/*` bruto. Um `model` opcional (na query string ou como campo de formulário) escolhe um dos modelos carregados: seu id, um alias (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), a forma `backend:model` ou apenas o nome de um backend, que significa o modelo padrão se ele pertencer a esse backend e, caso contrário, o primeiro modelo desse backend. Sem `model`, responde o modelo padrão. Um `language` opcional (na query string ou como campo de formulário) substitui o padrão do servidor para aquela requisição; `auto` ativa a detecção automática. Em caso de sucesso, retorna o texto, os segundos decorridos, o modelo que transcreveu e o idioma: o código que o Whisper detectou ou usou (sempre `en` em um modelo só de inglês), ou `null` no Parakeet, que não o informa.

```bash
curl -X POST 'localhost:5051/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

O idioma pode ser informado como código (`ru`) ou pelo seu nome em inglês (`russian`); qualquer valor que o modelo não conheça é recusado com `400` em vez de falhar no meio da transcrição. O `GET /api/models` lista o que cada modelo conhece. O rigor da verificação de `language` depende do modelo e de a requisição tê-lo nomeado ou não:

| Modelo | `language` que aceita | Requisição sem `model` | Requisição com `model` |
| --- | --- | --- | --- |
| Whisper multilíngue | um código ou nome em inglês da sua lista | `400 Unsupported language` fora da lista | o mesmo |
| Whisper só de inglês (`.en`) | `en` e `auto` | outro código conhecido é transcrito como inglês | `400 Unsupported language` |
| Parakeet | nenhum, ele detecta o idioma sozinho | qualquer valor é aceito e ignorado | um código da sua lista, ou `400` |

O Parakeet aceita apenas códigos, não nomes em inglês, e pode omitir sem avisar a fala da qual não tem certeza: em uma gravação com vários idiomas, pode não retornar nada para o idioma minoritário.

Um caminho de arquivo do Whisper cujo nome não corresponde a nenhum checkpoint conhecido, como um fine-tune em `/models/my-large-v3-finetune.pt`, tem uma lista de idiomas apenas deduzida desse nome, então uma requisição sem `model` repassa a ele qualquer código conhecido, como sempre; uma requisição que o nomeia continua sendo verificada contra a lista deduzida.

Os erros `400` dessas duas opções são `Invalid model` (nenhum backend conhece o nome), `Model not loaded` (um modelo real que este servidor não carregou), `Invalid language` (não é um idioma) e `Unsupported language` (um idioma real que o modelo escolhido não aceita). Os quatro são retornados antes de o áudio ser decodificado.

O `GET /api/models` informa o que este servidor oferece, para que um cliente não precise adivinhar. Cada modelo carregado tem sua própria linha, assim como cada transcritor sem nada carregado (`selectable: false`) e o diarizador. Cada linha traz sua própria lista de idiomas, porque os conjuntos realmente divergem e uma lista combinada estaria errada para cada modelo isoladamente.

```bash
curl -H 'Authorization: Bearer <token>' localhost:5051/api/models
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

O `id` é o que uma requisição passa como `model`, e exatamente uma linha tem `default: true`: seu id é o `default_model` e seu backend é o `default` do nível superior. `pool_size` e `available` descrevem o pool desse modelo. O `status` é `loaded` quando instâncias foram carregadas no pool dele, livres ou ocupadas, `installed` quando os pesos estão no disco mas nada foi carregado ainda, e `absent` nos demais casos. Um backend configurado mas não instalado informa `absent` e nada mais; o motivo vai para o log. `accepts_language` diz se `?language=` significa alguma coisa para aquele backend. O diarizador informa `null` em vez de uma lista de idiomas vazia, porque ele não produz texto em nenhum idioma.

O cliente CLI lê o mesmo endpoint:

```bash
python3 stt_client.py --list
```

O `POST /api/diarize` responde **quem falou quando**, e nada além disso: ele retorna intervalos de tempo com um número de locutor, nunca texto. Ele fica desativado a menos que `DIARIZE_ENABLED` esteja definido em uma imagem construída com `DIARIZE=true`; caso contrário, ele responde `503`.

```bash
curl -X POST localhost:5051/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Duas observações sobre esses números. Os turnos podem se sobrepor, porque cada canal de locutor é pontuado por conta própria, de modo que duas pessoas falando ao mesmo tempo produzem dois turnos cobrindo os mesmos segundos. E os rótulos são posições nesta gravação específica, ordenados por quem falou primeiro: eles não são identidades, e a mesma pessoa recebe um número diferente na próxima requisição. Dar nome a um locutor exigiria uma etapa de cadastro que este serviço não possui. No máximo oito locutores são distinguidos.

Dois backends de transcrição estão disponíveis. O **Whisper** é o padrão e aceita um `language`. O **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) cobre 25 idiomas europeus, detecta o idioma sozinho e por isso não aceita nenhum argumento `language`, o que o `GET /api/models` informa como `accepts_language: false`. Ele precisa de uma imagem construída com `PARAKEET=true`. Escolha-o para o servidor inteiro com `STT_BACKEND=parakeet`, ou carregue-o ao lado do Whisper via `STT_MODELS` e escolha-o por requisição com `model`. Uma requisição só escolhe entre os modelos carregados na inicialização, e cada modelo carregado mantém seus pesos em cada worker, então a memória é o número de workers vezes a soma dos pools.

Nenhum dos dois backends lida com sobreposição. O modelo da NVIDIA que lida com sobreposição é distribuído apenas como um checkpoint do NeMo, e o NeMo fixa uma versão do PyTorch diferente da build CUDA deste projeto, de modo que não é instalável aqui.

O `POST /api/transcript` responde **quem disse o quê**: ele executa a diarização e a transcrição sobre o mesmo áudio e as une pelo tempo. Ele precisa que a diarização esteja ativada; caso contrário, responde `503`. Ele aceita os mesmos `model` e `language` do `/api/stt` e informa em `model` o modelo que transcreveu.

```bash
curl -X POST localhost:5051/api/transcript -F file=@meeting.wav
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

`turns` é a saída bruta do diarizador e `segments` é a junção, mantidos separados para que um chamador que desconfie da atribuição ainda possa ver o que o diarizador disse. `text` é a transcrição simples, idêntica à que o `/api/stt` retorna para o mesmo arquivo. Uma frase que nenhum turno cobre mantém `"speaker": null` em vez de ser entregue ao turno mais próximo.

`overlap` marca uma frase durante a qual outra pessoa também estava falando. A NVIDIA afirma explicitamente que combinar um modelo convencional de locutor único com a diarização não equivale a um modelo construído para fala sobreposta: um intervalo de tempo extraído ainda contém todas as vozes que se sobrepõem a ele, de modo que essas frases podem se misturar ou selecionar as palavras do locutor errado. Trate um segmento marcado com `overlap` como o ponto em que a transcrição é menos confiável.

**Gravações longas passam por um job.** O `POST /api/jobs` aceita os mesmos formatos de corpo que o `/api/stt`, até `JOB_MAX_CONTENT_LENGTH_MB` (1 GB), além de um `mode`: `text` (o padrão), `speakers` (o resultado do `/api/transcript`) ou `turns` (o resultado do `/api/diarize`). Ele responde `202` na hora, com o id do job e um `Location` para consultar:

```bash
curl -F file=@meeting.mp3 'localhost:5051/api/jobs?mode=speakers&language=ru'
curl localhost:5051/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "model": "turbo", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6, "model": "turbo" } }
```

O `status` passa por `queued` (com a sua `position`), `running` e depois `done` com o `result`, ou `failed` com uma categoria em `error`. O `GET /api/jobs` lista os jobs e o `DELETE /api/jobs/<id>` remove um que não esteja rodando. Um job percorre o arquivo em pedaços de cerca de um minuto, cortados nas pausas, e devolve o modelo entre um pedaço e outro, de modo que as requisições curtas continuam sendo respondidas enquanto ele roda: uma gravação de 30 minutos levou 107 s na GPU do deploy, e requisições de chamadas telefônicas enviadas nesse meio-tempo levaram no máximo 10 s. A diarização percorre o arquivo inteiro no modo de streaming do modelo, de modo que um locutor mantém o mesmo número do primeiro ao último minuto. Jobs são arquivos em `JOBS_DIR`, então sobrevivem a uma reinicialização, e os concluídos são removidos depois de `JOB_RETENTION_HOURS`. Um job `text` ou `speakers` recebe `model` e `language` como o `/api/stt` e mantém esse modelo: o job e o seu resultado o informam, e um job cujo modelo deixou de estar carregado após uma reinicialização falha com `Model not loaded`. Um job `turns`, como o `/api/diarize`, não recebe `model`.

O `/api/stream` é um WebSocket para **transcrição ao vivo**: o áudio entra à medida que é gravado, e cada frase volta cerca de um segundo depois que o locutor faz uma pausa. Mensagens de texto JSON carregam o controle, mensagens binárias carregam o áudio:

1. O cliente envia `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}`. Todos os campos, exceto `type`, são opcionais. `model` escolhe um dos modelos carregados da mesma forma que `model` em `/api/stt`, e o idioma é verificado em relação a esse modelo; sem ele, atende o modelo padrão e o idioma só é verificado quanto a ser um idioma, como sempre, então um código que o modelo padrão não conhece falha ao transcrever uma frase. O `token` é a forma de um navegador se autenticar, já que ele não consegue definir cabeçalhos em um WebSocket; outros clientes podem, em vez disso, enviar `Authorization: Bearer <token>` no handshake.
2. O servidor responde `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}`.
3. O cliente envia PCM bruto - 16 bits com sinal, little-endian, mono, 16 kHz - como mensagens binárias de qualquer tamanho, no ritmo em que é gravado, e `{"type": "stop"}` quando termina. Um arquivo enviado mais rápido que o tempo real fica para trás por design e perde frases (veja `skipped` abaixo); um arquivo deve ir para um job.
4. O servidor envia um `segment` para cada frase, `progress` cerca de uma vez por segundo, `skipped` com os segundos de áudio descartados se a sessão chegar a ficar mais de dois minutos atrasada, e `done` antes de fechar:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

O áudio também pode vir de outro lugar. Com `"source": "url", "url": "https://..."` na mensagem de início, o cliente não envia áudio nenhum: o servidor lê o stream naquele endereço através do ffmpeg até que ele termine ou o cliente envie `stop`. Rádio pela internet, HLS, RTMP, RTSP e SRT funcionam; o esquema precisa ser `http`, `https`, `rtmp`, `rtmps`, `rtsp` ou `srt`. O que uma fonte ao vivo já tem acumulado é lido de uma vez, e o resto no ritmo da própria fonte, de modo que um arquivo remoto chega do jeito que uma transmissão chegaria.

Como isso faz o servidor buscar um endereço escolhido por um cliente, o recurso é cercado de limites. O ffmpeg só pode usar protocolos de rede, de modo que nem uma URL nem uma playlist conseguem fazê-lo ler um arquivo local, e nada pode fazê-lo escutar conexões: os modos SRT `listener` e `rendezvous` e qualquer parâmetro `listen` são recusados. Um endereço que seja o próprio servidor ou que resolva para ele (loopback), um endereço link-local como o serviço de metadados da nuvem em `169.254.169.254`, ou `0.0.0.0` é recusado com `Invalid stream URL`; isso é verificado quando a sessão começa, e o ffmpeg ainda segue redirecionamentos e playlists. Uma página de outro site não consegue iniciar uma fonte assim (`Forbidden`): os navegadores não aplicam CORS a WebSockets, então o socket verifica se a origem da página é este host ou está listada em `CORS_ORIGINS`. No máximo quatro fontes URL rodam ao mesmo tempo em cada processo do servidor (`Service Unavailable` além disso), então o gunicorn com vários workers permite essa quantidade por worker, e o log registra cada endereço sem as suas credenciais nem a query string. Ainda assim, ele consegue alcançar hosts da própria rede do servidor, o que é justamente o objetivo no caso de uma câmera e o motivo para definir `STT_TOKENS` em um servidor que outras pessoas consigam alcançar.

Uma falha é um único `{"type": "error", "error": "<category>", "request_id": "..."}` seguido de um fechamento, com as categorias de erro HTTP mais `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` e `Forbidden`.

Uma frase termina em uma pausa de 0,6 s, onde o diarizador percebe que um locutor passa a vez para outro (com `diarize`, já que pessoas que respondem umas às outras costumam deixar menos de 0,6 s), ou no seu momento mais silencioso quando passa de 15 s, e é transcrita sozinha com um modelo emprestado do mesmo pool dos uploads, de modo que um pool ocupado atrasa as frases ao vivo em vez de fazê-las falhar. Com `diarize`, o diarizador roda no seu modo de streaming e carrega um cache de locutores de um trecho para o outro, de modo que um locutor mantém o mesmo número durante toda a sessão. O socket existe quando o servidor roda sob o uvicorn - `python3 stt_server.py`, o padrão no Docker, ou o gunicorn com `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker` servindo `stt_server:asgi_app` - e não sob o servidor de depuração do Flask nem com os workers sync padrão do gunicorn, que não falam WebSocket.

**Só o texto falado é retornado.** Onde não há fala - um bipe, música, ruído, um tom de chamada, até silêncio digital - o Whisper responde com os créditos dos vídeos legendados com que aprendeu (um crédito em russo "legendas por DimaTorzok", "continua...", "Obrigado por assistir."), e faz isso com total confiança: no corpus de teste, o seu próprio `no_speech_prob` foi 0,00 mesmo em silêncio. Por isso, todo endpoint passa um detector de voz, o Silero VAD, sobre o áudio e descarta um segmento transcrito que fica majoritariamente fora da fala detectada, além de qualquer segmento que seja inteiramente uma linha de créditos de legenda. Com o Parakeet, cujos segmentos são palavras isoladas, mantém-se uma palavra que se sobrepõe à fala detectada ou fica a no máximo 0,3 s dela. Em um corpus de nove gravações sem fala, isso removeu todas essas linhas e manteve cada frase das gravações com fala. Uma gravação sem nada falado agora resulta em texto vazio. No stream ao vivo, uma frase sem fala detectada nem chega a ser enviada ao modelo. O detector roda na CPU e acrescenta cerca de um segundo a cada três minutos de áudio. `SPEECH_GATE=false` restaura o comportamento antigo.

Os uploads são limitados a `MAX_CONTENT_LENGTH_MB` (10 MB no servidor puro, 100 MB na configuração com Docker); um corpo maior retorna `413`.

Os erros são uniformes: `error` carrega uma categoria genérica e `request_id` correlaciona a resposta com o log do servidor, onde a exceção completa é registrada.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Quando `STT_TOKENS` está definido, toda rota exceto `GET /api/health` precisa enviar `Authorization: Bearer <token>`; ela permanece aberta para que os healthchecks continuem funcionando.

### API compatível com a OpenAI

`POST /v1/audio/transcriptions` e `GET /v1/models` seguem a API de áudio da OpenAI, então qualquer SDK da OpenAI funciona assim que seu `base_url` aponta para `http://<host>:<port>/v1` e sua chave de API é um dos `STT_TOKENS` (qualquer string com a autenticação desligada).

```bash
curl localhost:5051/v1/audio/transcriptions \
  -H 'Authorization: Bearer <token>' \
  -F file=@phrase.wav -F model=turbo -F language=en -F response_format=verbose_json
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5051/v1", api_key="<token>")
print(client.audio.transcriptions.create(model="turbo", file=open("phrase.wav", "rb")).text)
```

A requisição é `multipart/form-data` com `file` e passa exatamente pelo mesmo caminho de `/api/stt`: o mesmo token, o mesmo limite de tamanho, a mesma conversão, o mesmo filtro de fala e a mesma espera por uma instância livre (`STT_QUEUE_TIMEOUT`). Um WAV PCM de 16 bits, mono, 16 kHz é repassado sem decodificação, todo o resto é decodificado e convertido para 16 kHz mono pelo pydub, como em `/api/stt`.

- `model` é um dos ids listados por `GET /v1/models` (os mesmos de `/api/models`), um alias ou um nome de backend, exatamente como em `/api/stt`; ausente ou vazio, vale o modelo padrão. Os nomes próprios da OpenAI, como `whisper-1`, são recusados com `Invalid model`.
- `language` é verificado contra o modelo escolhido como em `/api/stt`; o Parakeet o aceita e o ignora.
- `prompt` vira o prompt inicial do Whisper. O openai-whisper mantém apenas os últimos 223 tokens e o usa nos primeiros 30 s de áudio. O Parakeet não aceita prompt e o ignora. Um prompt com um token especial do Whisper como `<|endoftext|>` é recusado com um 400, qualquer que seja o modelo. O prompt nunca é registrado no log.
- `temperature` só pode estar ausente ou valer `0`: a decodificação é determinística na temperatura 0.
- `response_format` é `json` (o padrão, `{"text": ...}`), `text` (um corpo de texto puro) ou `verbose_json`; `srt` e `vtt` são recusados. `timestamp_granularities[]` só pode pedir `segment`.

`verbose_json` traz `task`, `language` (o nome completo em minúsculas que o Whisper informa, como `english`, ou `null` para o Parakeet, que não informa nenhum), `duration` em segundos, `text` e `segments`. Os segmentos do Whisper são os dele, com `id`, `seek`, `start`, `end`, `text`, `tokens`, `temperature`, `avg_logprob`, `compression_ratio` e `no_speech_prob`. O Parakeet devolve um segmento com `tokens` vazio e os campos de confiança em `null`, porque não produz nenhum.

Os erros em qualquer caminho `/v1`, incluindo `401`, `404`, `405`, `413` e `500`, seguem o formato da OpenAI, com a mesma categoria em `message`; toda resposta de `/v1` também traz o id da requisição no cabeçalho `X-Request-Id`. Os erros de `/api/*` mantêm o próprio formato.

```json
{ "error": { "message": "Invalid language", "type": "invalid_request_error", "param": "language",
             "code": "invalid_language", "request_id": "a1b2c3d4e5f6" } }
```

### Cliente CLI

O `stt_client.py` é um pequeno cliente para trabalhar com o servidor e testá-lo. Ele lê o endereço do servidor e o token de `STT_URL` e `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` e `--language` (também como `--model=NOME`) só são enviados quando informados, e caso contrário vale o padrão do servidor; cada linha de resultado mostra o modelo e o idioma que o servidor usou. `--list` mostra o modelo padrão e uma linha por modelo com seu status, se uma requisição pode escolhê-lo, seu pool e seus idiomas.

O `--stream` toca um arquivo em `/api/stream` na velocidade da fala e imprime cada frase à medida que ela volta, com `--speakers` para a atribuição de locutores:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### Variáveis de ambiente

O `.env` é carregado tanto pelo servidor quanto pelo cliente através do `python-dotenv`.

| Variável                | Padrão                  | Finalidade                                          |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | endereço de bind do servidor                        |
| `STT_PORT`              | `5051`                  | porta do servidor                                   |
| `STT_POOL_SIZE`         | `8`                     | instâncias por modelo; padrão de uma entrada de `STT_MODELS` sem `@pool` |
| `STT_QUEUE_TIMEOUT`     | `120`                   | segundos que uma requisição síncrona espera por uma instância livre do seu modelo antes de `503` |
| `STT_KEEPALIVE_SECONDS` | `5`                     | segundos que uma conexão HTTP ociosa fica aberta (uvicorn; `keepalive` do gunicorn) |
| `STT_TOKENS`            | (vazio)                 | tokens válidos separados por vírgula; vazio desativa a autenticação |
| `STT_DEBUG`             | `false`                 | modo de depuração do Flask                          |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | tamanho máximo de upload em MB; um corpo maior retorna `413` |
| `CORS_ORIGINS`          | `*`                     | origens CORS permitidas: `*` ou uma lista separada por vírgulas |
| `GUNICORN_WORKERS`      | `4`                     | processos worker (apenas gunicorn)                  |
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` acrescenta `/api/stream` (apenas gunicorn) |
| `LOG_LEVEL`             | `INFO`                  | nível de log                                        |
| `LOG_ACCESS`            | `false`                 | registrar as linhas de acesso do uvicorn           |
| `WHISPER_MODEL`         | `small.en`              | nome do modelo Whisper (ex.: `small.en`, `turbo`) quando `STT_MODELS` está vazio |
| `WHISPER_LANGUAGE`      | `en`                    | idioma padrão de todos os modelos Whisper |
| `WHISPER_BEAM_SIZE`     | `1`                     | largura do beam do Whisper; `1` é guloso, um beam mais largo é mais lento e um pouco mais preciso |
| `WHISPER_FP16`          | `true`                  | meia precisão em CUDA; `false` em placas Pascal (Tesla P40), que executam fp16 a 1/64 da velocidade |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | diretório de cache de modelos (`/opt/models` no Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` ou `auto`                             |
| `STT_BACKEND`           | `whisper`               | backend de transcrição: `whisper` ou `parakeet` quando `STT_MODELS` está vazio |
| `STT_MODELS`            | (vazio)                 | vários modelos lado a lado: `backend:model[@pool]`, separados por vírgula |
| `STT_DEFAULT_MODEL`     | (vazio)                 | modelo de uma requisição sem `model`; vazio significa a primeira entrada de `STT_MODELS` |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | id do modelo Parakeet                               |
| `PARAKEET_DOWNLOAD_ROOT` | `models`                | diretório de cache do modelo Parakeet               |
| `DIARIZE_ENABLED`       | `false`                 | ativar `POST /api/diarize` (requer uma imagem `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | id do modelo de diarização                          |
| `DIARIZE_POOL_SIZE`     | `1`                     | instâncias do diarizador pré-carregadas             |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | diretório de cache do modelo de diarização          |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilidade de atividade do locutor contada como fala |
| `JOBS_DIR`              | `recs/jobs`             | onde os jobs guardam o upload, o registro e o resultado |
| `JOB_MAX_CONTENT_LENGTH_MB` | `1024`              | tamanho máximo do upload de um job em MB            |
| `JOB_RETENTION_HOURS`   | `24`                    | horas após as quais os jobs concluídos são removidos |
| `SPEECH_GATE`           | `true`                  | descarta o texto transcrito que ninguém falou (detector de voz) |
| `STT_UID`, `STT_GID`    | (`stt` da imagem, 1001) | usuário do host dono de `models/`, `logs/`, `recs/` (Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | `1` depois que os modelos estão em cache: nenhuma requisição ao hub na inicialização |
| `STT_WWW_PORT`          | `5053`                  | porta da interface web (compose)                    |
| `STT_WWW_SCHEME`        | `https`                 | esquema da interface web, `https` ou `http` (compose) |
| `STT_URL`               | `http://localhost:5051` | cliente: URL base do servidor                       |
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
│   ├── model_pool.py    # a pool per transcription model, and one for the diarizer
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── openai_api.py    # the OpenAI-compatible /v1 API: its options, answers and model list
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
│   ├── backends.py      # backend name -> transcriber module (STT_BACKEND or an STT_MODELS entry)
│   ├── registry.py      # which models are loaded and what a request may select
│   └── diarize.py       # speaker diarization (who spoke when, no text)
├── Dockerfile           # GPU build (CUDA 13.0)
├── Dockerfile-cpu       # CPU build
├── Dockerfile-p40       # Pascal GPU build (CUDA 12.6, Tesla P40)
├── Dockerfile-www       # web UI image (nginx)
├── nginx/               # stt_www config: static UI, /api/ proxy, self-signed TLS
├── www/                 # web UI: Vue 2 without a build step, libraries vendored
├── constraints.txt      # every dependency version the tested image resolved
├── docs/                # DEPLOY.md and the README translations
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
