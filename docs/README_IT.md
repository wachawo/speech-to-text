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
* **Trascrizione in tempo reale.** Invia l'audio in streaming su un WebSocket e ricevi ogni frase mentre viene pronunciata, attribuita a un parlante quando la diarizzazione è attiva.
* **È inclusa un'interfaccia web.** Carica un file dal browser e leggi il testo, o chi ha detto cosa; la serve un container nginx dedicato accanto al server.

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

#### Più modelli

`STT_MODELS` carica all'avvio più modelli di trascrizione, ciascuno con il proprio pool, e lascia che ogni richiesta ne scelga uno con `model`. Le voci sono separate da virgole nella forma `backend:model[@pool]`:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # il modello di una richiesta senza `model`; vuoto significa la prima voce
```

La scelta avviene solo tra i modelli caricati all'avvio: una richiesta non provoca mai un download né un caricamento, e un modello non caricato viene rifiutato con `400`. Ogni modello in elenco occupa memoria finché il server resta attivo, all'incirca `worker x (pool x dimensione del modello)` sommato sull'elenco, più il diarizzatore. `turbo@2,small@1,parakeet@1` su una GPU richiede circa 12 + 2 + 3 = 17 GB per processo. Con gunicorn ogni worker sync gestisce una richiesta alla volta, quindi assegna `@1` a ogni voce e scala con `GUNICORN_WORKERS`. Una voce senza `@pool` riceve `STT_POOL_SIZE`, che fuori da Docker vale 8, quindi scrivi `@N` in modo esplicito. Caricare più modelli grandi richiede più tempo che caricarne uno, quindi aumenta lo `start_period` dell'healthcheck nel file compose se il container viene segnato come unhealthy durante l'avvio.

Con `STT_MODELS` vuoto, `STT_BACKEND`, `WHISPER_MODEL` e `PARAKEET_MODEL` scelgono l'unico modello come prima e il server carica esattamente ciò che caricava prima; le risposte guadagnano solo dei campi. Quando è impostato, queste variabili non decidono più cosa viene caricato. In Docker, metti `STT_MODELS` e `STT_DEFAULT_MODEL` nel `.env`, non nel blocco `environment:` del compose, che sovrascrive il `.env`. Una voce Parakeet richiede comunque un'immagine costruita con `PARAKEET=true`, e il server si rifiuta di avviarsi con un backend sconosciuto, con gli stessi pesi elencati due volte (`turbo` e `large-v3-turbo`) o con un `STT_DEFAULT_MODEL` che non è nell'elenco. Un modello indicato come percorso di file viene servito con il nome del file senza `.pt`, così il percorso non arriva mai a un client. `STT_DEFAULT_MODEL` può indicare una voce del genere con quel nome o con il percorso esattamente come è scritto in `STT_MODELS`, e le sue lingue sono quelle del checkpoint indicato dal nome del file: `/models/large-v3.pt` conosce ciò che conosce `large-v3`. Due voci che verrebbero servite con lo stesso nome (`/a/model.pt` e `/b/model.pt`), o una voce servita con il nome di un backend (`/models/parakeet.pt`), fermano il server all'avvio.

### Avvio rapido (Docker)

Il modo più semplice per eseguire il server è con Docker. I file dei modelli vengono memorizzati nella cache in `./models` sull'host, così sopravvivono alle ricostruzioni del container.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La build GPU richiede `nvidia-container-toolkit` sull'host. La prima esecuzione scarica il modello Whisper in `./models`.

### Interfaccia web

`docker compose up` avvia anche `stt_www`, un container nginx che serve l'interfaccia del browser e inoltra `/api/` al server, così interfaccia e API condividono un unico indirizzo.

| Protocollo | Porta predefinita | Impostata con      |
| ---------- | ----------------- | ------------------ |
| http       | `8080`            | `STT_WWW_PORT`     |
| https      | `8443`            | `STT_WWW_TLS_PORT` |

Apri `http://<host>:8080`. **TRANSCRIBE** ha due sorgenti. **FILE** carica un file audio. **DEVICE** trascrive in tempo reale da un ingresso audio: un microfono o delle cuffie con microfono, una sorgente `Monitor of ...` su Linux che porta tutto ciò che viene riprodotto da altoparlanti o cuffie, oppure `Tab or screen audio` per ciò che viene riprodotto in una scheda del browser, o nell'intero sistema dove il sistema operativo lo consente. In entrambi i casi il risultato compare sotto il modulo come testo semplice oppure, con la diarizzazione abilitata, come un blocco per frase con il suo parlante e il suo tempo, ogni parlante nel proprio colore e contrassegnate le frasi in cui due persone hanno parlato insieme; una frase in tempo reale compare circa un secondo dopo che il parlante fa una pausa. Il risultato può essere copiato o scaricato come TXT o JSON. Con più modelli caricati (`STT_MODELS`), un selettore del modello accanto a modalità e lingua sceglie il modello per entrambe le sorgenti, alimentato da `GET /api/models`, e l'elenco delle lingue segue il modello scelto. **MODELS** mostra ciò che riporta `GET /api/models`. Quando `STT_TOKENS` è impostato, l'interfaccia chiede un token una sola volta e lo conserva nel browser.

I browser concedono i dispositivi audio solo a una pagina sicura, quindi attraverso la rete DEVICE funziona tramite la porta https (e su `http://localhost`). La porta https usa un certificato autofirmato che il container crea in `./data/certs` al primo avvio; mettici un vero `stt.crt` e un vero `stt.key` per sostituirlo. L'interfaccia non ha fase di build né CDN: Vue 2 e le sue librerie sono incluse in `www/vendor`, così funziona anche su una macchina senza accesso a internet.

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

`GET /api/health` restituisce lo stato dei pool. I campi `pool_size` e `available` di primo livello descrivono il modello predefinito, quello che attende una richiesta senza `model`; `available` che scende a 0 significa che tutte le sue istanze sono occupate. `models` riporta ogni modello caricato per id:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

Quando `STT_TOKENS` è impostato, `default_model` e `models` compaiono solo nella risposta a una richiesta con un token valido: come `GET /api/models`, descrivono la configurazione del server. Un healthcheck senza token riceve comunque `status`, `pool_size`, `available` e `diarize`.

`POST /api/stt` accetta un campo `multipart/form-data` chiamato `file`, oppure un body `audio/*` grezzo. Un `model` facoltativo (query string o campo del modulo) sceglie uno dei modelli caricati: il suo id, un alias (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), la forma `backend:model` o il solo nome di un backend, che indica il modello predefinito se appartiene a quel backend e altrimenti il primo modello di quel backend. Senza `model` risponde il modello predefinito. Un `language` facoltativo (query string o campo del modulo) sostituisce il valore predefinito del server per quella richiesta; `auto` attiva il rilevamento automatico. In caso di successo restituisce il testo, i secondi trascorsi, il modello che ha trascritto e la lingua: il codice che Whisper ha rilevato o usato (sempre `en` per un modello solo inglese), oppure `null` per Parakeet, che non lo riporta.

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

La lingua può essere indicata come codice (`ru`) o con il suo nome inglese (`russian`); qualsiasi valore che il modello non conosce viene rifiutato con `400` invece di fallire a metà trascrizione. `GET /api/models` elenca ciò che conosce ogni modello. Quanto sia rigoroso il controllo di `language` dipende dal modello e dal fatto che la richiesta lo abbia nominato:

| Modello | `language` accettato | Richiesta senza `model` | Richiesta con `model` |
| --- | --- | --- | --- |
| Whisper multilingue | un codice o nome inglese del suo elenco | `400 Unsupported language` fuori dall'elenco | lo stesso |
| Whisper solo inglese (`.en`) | `en` e `auto` | un altro codice noto viene trascritto come inglese | `400 Unsupported language` |
| Parakeet | nessuno, rileva la lingua da solo | qualsiasi valore viene accettato e ignorato | un codice del suo elenco, altrimenti `400` |

Parakeet accetta solo codici, non nomi inglesi, e può tralasciare senza segnalarlo il parlato di cui non è sicuro: in una registrazione multilingue può non restituire nulla per la lingua minoritaria.

Un percorso di file Whisper il cui nome non corrisponde a nessun checkpoint noto, come un fine-tune in `/models/my-large-v3-finetune.pt`, ha un elenco di lingue soltanto dedotto da quel nome, quindi una richiesta senza `model` gli passa qualsiasi codice noto, come sempre; una richiesta che lo nomina viene ancora verificata sull'elenco dedotto.

Gli errori `400` di queste due opzioni sono `Invalid model` (nessun backend conosce il nome), `Model not loaded` (un modello reale che questo server non ha caricato), `Invalid language` (non è affatto una lingua) e `Unsupported language` (una lingua reale che il modello scelto non accetta). Tutti e quattro arrivano prima che l'audio venga decodificato.

`GET /api/models` indica ciò che questo server offre, così un client non deve tirare a indovinare. Ogni modello caricato ha una propria riga, così come ogni trascrittore senza nulla di caricato (`selectable: false`) e il diarizzatore. Ogni riga porta il proprio elenco di lingue, perché gli insiemi divergono davvero e un elenco unito sarebbe sbagliato per ciascun modello preso singolarmente.

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

`id` è ciò che una richiesta passa come `model`, ed esattamente una riga ha `default: true`: il suo id è `default_model` e il suo backend è il `default` di primo livello. `pool_size` e `available` descrivono il pool di quel modello. `status` è `loaded` quando esistono istanze del modello, libere o occupate, `installed` quando i pesi sono sul disco ma non è ancora stato caricato nulla, e `absent` altrimenti. Un backend configurato ma non installato risponde `absent` e nient'altro; il motivo finisce nel log. `accepts_language` dice se `?language=` ha un significato per quel backend. Il diarizzatore riporta `null` invece di un elenco di lingue vuoto, perché non produce testo in nessuna lingua.

Il client a riga di comando legge lo stesso endpoint:

```bash
python3 stt_client.py --list
```

`POST /api/diarize` risponde a **chi ha parlato e quando**, e a nient'altro: restituisce intervalli temporali con un numero di parlante, mai il testo. È disattivato a meno che `DIARIZE_ENABLED` non sia impostato su un'immagine costruita con `DIARIZE=true`; in caso contrario risponde `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Due precisazioni su questi numeri. I turni possono sovrapporsi, perché ogni canale di parlante viene valutato in modo indipendente, quindi due persone che parlano contemporaneamente producono due turni che coprono gli stessi secondi. E le etichette sono posizioni all'interno di questa singola registrazione, ordinate in base a chi ha parlato per primo: non sono identità, e la stessa persona riceve un numero diverso nella richiesta successiva. Dare un nome a un parlante richiede una fase di registrazione vocale che questo servizio non prevede. Vengono distinti al massimo otto parlanti.

Sono disponibili due backend di trascrizione. **Whisper** è quello predefinito e accetta un `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) copre 25 lingue europee, rileva la lingua da solo e quindi non accetta alcun argomento `language`, cosa che `GET /api/models` segnala come `accepts_language: false`. Richiede un'immagine costruita con `PARAKEET=true`. Sceglilo per l'intero server con `STT_BACKEND=parakeet`, oppure caricalo accanto a Whisper tramite `STT_MODELS` e sceglilo per ogni richiesta con `model`. Una richiesta sceglie sempre e solo tra i modelli caricati all'avvio, e ogni modello caricato tiene i propri pesi in ogni worker, quindi la memoria è il numero di worker moltiplicato per la somma dei pool.

Nessuno dei due backend tiene conto delle sovrapposizioni. Il modello di NVIDIA che gestisce il parlato sovrapposto viene distribuito solo come checkpoint NeMo, e NeMo vincola una versione di PyTorch diversa da quella della build CUDA di questo progetto, quindi qui non è installabile.

`POST /api/transcript` risponde a **chi ha detto cosa**: esegue la diarizzazione e la trascrizione sullo stesso audio e le unisce in base al tempo. Richiede che la diarizzazione sia abilitata, altrimenti risponde `503`. Accetta gli stessi `model` e `language` di `/api/stt` e indica in `model` il modello che ha trascritto.

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

`turns` è l'output grezzo del diarizzatore e `segments` è la giunzione dei due, tenuti separati così che un client che non si fida dell'attribuzione possa comunque vedere ciò che ha detto il diarizzatore. `text` è la trascrizione semplice, identica a quella che `/api/stt` restituisce per lo stesso file. Una frase che nessun turno copre mantiene `"speaker": null` invece di essere assegnata a quello più vicino.

`overlap` contrassegna una frase durante la quale stava parlando anche qualcun altro. NVIDIA afferma esplicitamente che abbinare un modello convenzionale a parlante singolo alla diarizzazione non equivale a un modello costruito per il parlato sovrapposto: un intervallo temporale estratto contiene comunque ogni voce che vi si sovrappone, quindi quelle frasi possono fondersi tra loro oppure selezionare le parole del parlante sbagliato. Considera un segmento contrassegnato con `overlap` come il punto in cui la trascrizione è meno affidabile.

`/api/stream` è un WebSocket per la **trascrizione in tempo reale**: l'audio entra man mano che viene registrato, e ogni frase torna circa un secondo dopo che il parlante fa una pausa. I messaggi di testo JSON trasportano il controllo, i messaggi binari trasportano l'audio:

1. Il client invia `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}`. Tutti i campi tranne `type` sono opzionali. `model` sceglie uno dei modelli caricati come fa `model` su `/api/stt`, e la lingua viene verificata rispetto a quel modello; senza di esso serve il modello predefinito e la lingua viene verificata soltanto per capire se è una lingua, come sempre, quindi un codice che il modello predefinito non conosce fallisce quando si trascrive una frase. `token` è il modo in cui un browser si autentica, dato che non può impostare header su un WebSocket; gli altri client possono invece inviare `Authorization: Bearer <token>` durante l'handshake.
2. Il server risponde `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}`.
3. Il client invia PCM grezzo - 16 bit con segno, little-endian, mono, 16 kHz - come messaggi binari di qualsiasi dimensione, e `{"type": "stop"}` quando ha finito.
4. Il server invia un `segment` per ogni frase, `progress` circa una volta al secondo e `done` prima di chiudere:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

L'audio può anche arrivare da altrove. Con `"source": "url", "url": "https://..."` nel messaggio di avvio il client non invia alcun audio: il server legge lo stream a quell'indirizzo tramite ffmpeg, al ritmo proprio della sorgente, finché non termina o il client invia `stop`. Funzionano radio via internet, HLS, RTMP, RTSP e SRT; lo schema deve essere `http`, `https`, `rtmp`, `rtmps`, `rtsp` o `srt`, e ffmpeg è limitato ai soli protocolli di rete, così un URL o una playlist non possono fargli leggere un file locale. Resta il fatto che il server va a leggere un indirizzo scelto da un client, compresi indirizzi della sua stessa rete: imposta `STT_TOKENS` su qualsiasi server raggiungibile da altri.

Un errore è un singolo `{"type": "error", "error": "<category>", "request_id": "..."}` seguito da una chiusura, con le categorie di errore HTTP più `Invalid start message`, `Invalid audio frame`, `Invalid stream URL` e `Stream source failed`.

Una frase termina a una pausa di 0,6 s, oppure nel suo punto più silenzioso una volta superati i 15 s, e viene trascritta da sola con un modello preso in prestito dallo stesso pool degli upload, così un pool occupato ritarda le frasi in tempo reale invece di farle fallire. Con `diarize`, il diarizzatore funziona in modalità streaming e porta con sé una cache dei parlanti da un blocco all'altro, così un parlante mantiene lo stesso numero per tutta la sessione. Il socket esiste solo quando il server gira sotto uvicorn (`python3 stt_server.py`, il predefinito in Docker): il server di debug di Flask e i worker sync di gunicorn non parlano WebSocket.

Gli upload sono limitati a `MAX_CONTENT_LENGTH_MB` (10 MB per impostazione predefinita); un corpo più grande restituisce `413`.

Gli errori sono uniformi: `error` riporta una categoria generica e `request_id` correla la risposta con il log del server, dove viene registrata l'eccezione completa.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Quando `STT_TOKENS` è impostato, ogni rotta tranne `GET /api/health` deve includere `Authorization: Bearer <token>`; `GET /api/health` resta aperto, così i controlli di integrità continuano a funzionare.

### Client a riga di comando

`stt_client.py` è un piccolo client per lavorare con il server e testarlo. Legge l'indirizzo del server e il token da `STT_URL` e `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` e `--language` (anche come `--model=NOME`) vengono inviati solo se indicati, altrimenti vale il valore predefinito del server; ogni riga di risultato mostra il modello e la lingua usati dal server. `--list` stampa il modello predefinito e una riga per modello con lo stato, se una richiesta può sceglierlo, il pool e le lingue.

`--stream` riproduce un file verso `/api/stream` alla velocità del parlato e stampa ogni frase man mano che torna, con `--speakers` per l'attribuzione dei parlanti:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### Variabili d'ambiente

`.env` viene caricato sia dal server sia dal client tramite `python-dotenv`.

| Variable                | Default                 | Scopo                                              |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | indirizzo di bind del server                       |
| `STT_PORT`              | `5099`                  | porta del server                                   |
| `STT_POOL_SIZE`         | `8`                     | istanze per modello; valore predefinito di una voce di `STT_MODELS` senza `@pool` |
| `STT_TOKENS`            | (vuoto)                 | token validi separati da virgola; vuoto disabilita l'autenticazione |
| `STT_DEBUG`             | `false`                 | modalità debug di Flask                            |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | dimensione massima dell'upload in MB; un corpo più grande restituisce `413` |
| `CORS_ORIGINS`          | `*`                     | origini CORS consentite: `*` o un elenco separato da virgole |
| `GUNICORN_WORKERS`      | `4`                     | processi worker (solo gunicorn)                    |
| `LOG_LEVEL`             | `INFO`                  | livello di logging                                 |
| `LOG_ACCESS`            | `false`                 | registra le righe di access di uvicorn             |
| `WHISPER_MODEL`         | `small.en`              | nome del modello Whisper (es. `small.en`, `turbo`) quando `STT_MODELS` è vuoto |
| `WHISPER_LANGUAGE`      | `en`                    | lingua predefinita di ogni modello Whisper |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | directory della cache dei modelli (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, oppure `auto`                       |
| `STT_BACKEND`           | `whisper`               | backend di trascrizione: `whisper` o `parakeet` quando `STT_MODELS` è vuoto |
| `STT_MODELS`            | (vuoto)                 | più modelli affiancati: `backend:model[@pool]`, separati da virgole |
| `STT_DEFAULT_MODEL`     | (vuoto)                 | modello di una richiesta senza `model`; vuoto significa la prima voce di `STT_MODELS` |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | id del modello Parakeet                       |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | directory della cache del modello Parakeet         |
| `DIARIZE_ENABLED`       | `false`                 | abilita `POST /api/diarize` (richiede un'immagine `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | id del modello di diarizzazione                    |
| `DIARIZE_POOL_SIZE`     | `1`                     | istanze di diarizzazione precaricate               |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | directory della cache del modello di diarizzazione |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilità di attività del parlante contata come voce |
| `STT_WWW_PORT`          | `8080`                  | porta http dell'interfaccia web (compose)           |
| `STT_WWW_TLS_PORT`      | `8443`                  | porta https dell'interfaccia web (compose)          |
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

### Sviluppo

Devono essere presenti i pacchetti di sistema `ffmpeg` e `libsndfile1`. Installa le dipendenze di runtime e di sviluppo:

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

La suite di test sostituisce il backend Whisper con uno stub, quindi copre il livello HTTP (request_id, categorie di errore, semantica del pool di modelli) e viene eseguita in pochi secondi senza scaricare un modello né richiedere una GPU.

### Licenza

[MIT](../LICENSE)
