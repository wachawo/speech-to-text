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

### Avvio rapido (Docker)

Il modo più semplice per eseguire il server è con Docker. I file dei modelli vengono memorizzati nella cache in `./models` sull'host, così sopravvivono alle ricostruzioni del container.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La build GPU richiede `nvidia-container-toolkit` sull'host. La prima esecuzione scarica il modello Whisper in `./models`. L'esercizio su un server - aggiornamenti, rollback, certificati, dipendenze - è descritto in [docs/DEPLOY.md](DEPLOY.md).

### Interfaccia web

`docker compose up` avvia anche `stt_www`, un container nginx che serve l'interfaccia del browser e inoltra `/api/` al server, così interfaccia e API condividono un unico indirizzo.

| Protocollo | Porta predefinita | Impostata con      |
| ---------- | ----------------- | ------------------ |
| http       | `8080`            | `STT_WWW_PORT`     |
| https      | `8443`            | `STT_WWW_TLS_PORT` |

Apri `http://<host>:8080`. **TRANSCRIBE** ha tre sorgenti. **FILE** carica un file audio. **DEVICE** trascrive in tempo reale da un ingresso audio: un microfono o delle cuffie con microfono, una sorgente `Monitor of ...` su Linux che porta tutto ciò che viene riprodotto da altoparlanti o cuffie, oppure, nei browser Chromium, `Tab or screen audio` per ciò che viene riprodotto in una scheda del browser, o nell'intero sistema dove il sistema operativo lo consente. **STREAM** accetta l'indirizzo di uno stream o di un file remoto - radio via internet, HLS, RTMP, RTSP, SRT - e il server lo legge da sé. In ogni caso il risultato compare sotto il modulo come testo semplice oppure, con la diarizzazione abilitata, come un blocco per frase con il suo parlante e il suo tempo, ogni parlante nel proprio colore e contrassegnate le frasi in cui due persone hanno parlato insieme; una frase in tempo reale compare circa un secondo dopo che il parlante fa una pausa. Il risultato può essere copiato o scaricato come TXT o JSON, e ogni sorgente conserva il suo ultimo risultato mentre guardi un'altra schermata. FILE ha anche una modalità **Turns**, `POST /api/diarize` da solo: chi ha parlato e quando, disegnato come una timeline con una corsia per parlante e contrassegnati i tratti in cui due persone parlano insieme. **MODELS** mostra ciò che riporta `GET /api/models`. Quando `STT_TOKENS` è impostato, l'interfaccia chiede un token una sola volta e lo conserva nel browser.

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

`GET /api/health` restituisce lo stato del pool. `available` che scende a 0 significa che tutti i modelli sono attualmente in uso:

```json
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`GET /api/health?deep=1` fa inoltre passare un secondo di silenzio attraverso ogni modello caricato e riporta ciascuno come `ok`, `busy` (nessuna istanza si è liberata entro cinque secondi) o `failed`, rispondendo `503` se qualcuno è fallito. Costa lavoro di GPU, quindi finché `STT_TOKENS` è impostato richiede un token; il controllo semplice resta aperto per i controlli di integrità dei container.

`GET /metrics` espone metriche Prometheus: richieste per rotta e stato, la loro durata, risposte di errore per categoria, dimensioni dei pool e istanze libere, sessioni in tempo reale attive e avviate, segmenti scartati dal rilevatore di voce e audio in tempo reale abbandonato da una sessione rimasta indietro. Come health non richiede token, e `stt_www` non lo inoltra: interroga direttamente `STT_PORT`. Sotto gunicorn ogni worker conta per sé.

`POST /api/stt` accetta un campo `multipart/form-data` chiamato `file`, oppure un corpo grezzo `audio/*`. Un parametro opzionale `language` (query string o campo del form) sovrascrive il valore predefinito del server per quella richiesta; `auto` esegue il riconoscimento automatico. In caso di successo restituisce il testo e i secondi trascorsi:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

La lingua può essere indicata come codice (`ru`) o con il suo nome inglese (`russian`); qualsiasi valore che il modello non conosca viene rifiutato con `400` invece di fallire a metà trascrizione. `GET /api/models` elenca quelle che conosce. Questo vale per i backend che accettano una lingua (`accepts_language: true`). Parakeet rileva la lingua da solo e ignora il valore, e può tralasciare senza segnalarlo il parlato di cui non è sicuro: in una registrazione multilingue può non restituire nulla per la lingua minoritaria.

`GET /api/models` indica ciò che questo server offre, così un client non deve tirare a indovinare. Ogni backend porta il proprio elenco di lingue, perché gli insiemi divergono realmente e un elenco unificato sarebbe errato per ogni singolo backend.

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

`status` è `loaded` quando un'istanza è in attesa in un pool, `installed` quando i pesi sono sul disco ma non è ancora stato caricato nulla, e `absent` negli altri casi. Un backend configurato ma non installato risponde `absent` e nient'altro; il motivo finisce nel log. `accepts_language` indica se `?language=` abbia un qualche significato per quel backend. Il diarizzatore riporta `null` come lingue anziché un elenco vuoto, perché non produce testo in nessuna lingua.

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

Sono disponibili due backend di trascrizione. **Whisper** è quello predefinito e accetta un `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) copre 25 lingue europee, rileva da sé la lingua e di conseguenza non accetta alcun argomento `language`, cosa che `GET /api/models` riporta come `accepts_language: false`. Selezionalo con `STT_BACKEND=parakeet` su un'immagine costruita con `PARAKEET=true`; è una scelta in fase di deploy, non per singola richiesta, perché un secondo modello residente significherebbe un secondo insieme di pesi in ogni worker.

Nessuno dei due backend tiene conto delle sovrapposizioni. Il modello di NVIDIA che gestisce il parlato sovrapposto viene distribuito solo come checkpoint NeMo, e NeMo vincola una versione di PyTorch diversa da quella della build CUDA di questo progetto, quindi qui non è installabile.

`POST /api/transcript` risponde a **chi ha detto cosa**: esegue la diarizzazione e la trascrizione sullo stesso audio e le unisce in base al tempo. Richiede che la diarizzazione sia abilitata, altrimenti risponde `503`.

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

`turns` è l'output grezzo del diarizzatore e `segments` è la giunzione dei due, tenuti separati così che un client che non si fida dell'attribuzione possa comunque vedere ciò che ha detto il diarizzatore. `text` è la trascrizione semplice, identica a quella che `/api/stt` restituisce per lo stesso file. Una frase che nessun turno copre mantiene `"speaker": null` invece di essere assegnata a quello più vicino.

`overlap` contrassegna una frase durante la quale stava parlando anche qualcun altro. NVIDIA afferma esplicitamente che abbinare un modello convenzionale a parlante singolo alla diarizzazione non equivale a un modello costruito per il parlato sovrapposto: un intervallo temporale estratto contiene comunque ogni voce che vi si sovrappone, quindi quelle frasi possono fondersi tra loro oppure selezionare le parole del parlante sbagliato. Considera un segmento contrassegnato con `overlap` come il punto in cui la trascrizione è meno affidabile.

**Le registrazioni lunghe passano da un job.** `POST /api/jobs` accetta le stesse forme di corpo di `/api/stt`, fino a `JOB_MAX_CONTENT_LENGTH_MB` (1 GB), più un `mode`: `text` (il predefinito), `speakers` (il risultato di `/api/transcript`) o `turns` (il risultato di `/api/diarize`). Risponde subito `202` con l'id del job e una `Location` da interrogare:

```bash
curl -F file=@meeting.mp3 'localhost:5099/api/jobs?mode=speakers&language=ru'
curl localhost:5099/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6 } }
```

`status` passa per `queued` (con la sua `position`), `running`, poi `done` con il `result`, oppure `failed` con una categoria `error`. `GET /api/jobs` li elenca e `DELETE /api/jobs/<id>` ne rimuove uno che non è in esecuzione. Un job elabora il file a pezzi di circa un minuto, tagliati sulle pause, e restituisce il modello tra un pezzo e l'altro, così le richieste brevi continuano a ricevere risposta mentre è in corso: una registrazione di 30 minuti ha richiesto 107 s sulla GPU del deploy, e le richieste di telefonate inviate nel frattempo hanno richiesto al massimo 10 s. La diarizzazione percorre l'intero file nella modalità streaming del modello, così un parlante mantiene lo stesso numero dal primo all'ultimo minuto. I job sono file sotto `JOBS_DIR`, quindi sopravvivono a un riavvio, e quelli terminati vengono rimossi dopo `JOB_RETENTION_HOURS`.

`/api/stream` è un WebSocket per la **trascrizione in tempo reale**: l'audio entra man mano che viene registrato, e ogni frase torna circa un secondo dopo che il parlante fa una pausa. I messaggi di testo JSON trasportano il controllo, i messaggi binari trasportano l'audio:

1. Il client invia `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`. Tutti i campi tranne `type` sono opzionali. `token` è il modo in cui un browser si autentica, dato che non può impostare header su un WebSocket; gli altri client possono invece inviare `Authorization: Bearer <token>` durante l'handshake.
2. Il server risponde `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`.
3. Il client invia PCM grezzo - 16 bit con segno, little-endian, mono, 16 kHz - come messaggi binari di qualsiasi dimensione, al ritmo con cui viene registrato, e `{"type": "stop"}` quando ha finito. Un file inviato più velocemente del tempo reale resta indietro per scelta progettuale e perde frasi (vedi `skipped` più sotto); un file va in un job.
4. Il server invia un `segment` per ogni frase, `progress` circa una volta al secondo, `skipped` con i secondi di audio scartati se la sessione accumula più di due minuti di ritardo, e `done` prima di chiudere:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

L'audio può anche arrivare da altrove. Con `"source": "url", "url": "https://..."` nel messaggio di avvio il client non invia alcun audio: il server legge lo stream a quell'indirizzo tramite ffmpeg finché non termina o il client invia `stop`. Funzionano radio via internet, HLS, RTMP, RTSP e SRT; lo schema deve essere `http`, `https`, `rtmp`, `rtmps`, `rtsp` o `srt`. Ciò che una sorgente dal vivo ha già accumulato viene preso subito, e il resto al ritmo proprio della sorgente, così un file remoto arriva come arriverebbe una trasmissione.

Poiché così il server va a leggere un indirizzo scelto da un client, la funzione è delimitata. ffmpeg può usare solo protocolli di rete, quindi né un URL né una playlist possono fargli leggere un file locale, e nulla può metterlo in ascolto: le modalità SRT `listener` e `rendezvous` e qualsiasi parametro `listen` vengono rifiutati. Una pagina di un altro sito non può avviarne una (`Forbidden`): i browser non applicano CORS ai WebSocket, quindi il socket verifica che l'origine della pagina sia questo host o compaia in `CORS_ORIGINS`. Al massimo quattro sorgenti URL girano contemporaneamente (`Service Unavailable` oltre questo limite), e il log registra ogni indirizzo senza credenziali né query string. Può comunque raggiungere host sulla rete del server stesso, ed è proprio questo lo scopo per una telecamera e il motivo per impostare `STT_TOKENS` su un server raggiungibile da altri.

Un errore è un singolo `{"type": "error", "error": "<category>", "request_id": "..."}` seguito da una chiusura, con le categorie di errore HTTP più `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` e `Forbidden`.

Una frase termina a una pausa di 0,6 s, dove il diarizzatore sente un parlante passare la parola a un altro (con `diarize`, perché le persone che si rispondono lasciano spesso meno di 0,6 s), oppure nel suo punto più silenzioso una volta superati i 15 s, e viene trascritta da sola con un modello preso in prestito dallo stesso pool degli upload, così un pool occupato ritarda le frasi in tempo reale invece di farle fallire. Con `diarize`, il diarizzatore funziona in modalità streaming e porta con sé una cache dei parlanti da un blocco all'altro, così un parlante mantiene lo stesso numero per tutta la sessione. Il socket esiste quando il server gira sotto uvicorn - `python3 stt_server.py`, il predefinito in Docker, oppure gunicorn con `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker` che serve `stt_server:asgi_app` - e non con il server di debug di Flask né con i worker sync predefiniti di gunicorn, che non parlano WebSocket.

**Viene restituito solo il testo parlato.** Dove non c'è parlato - un bip, musica, rumore, il tono di libero, persino silenzio digitale - Whisper risponde con i titoli di coda dei video sottotitolati da cui ha imparato (un credito russo "sottotitoli a cura di DimaTorzok", "continua...", "Grazie per la visione."), e lo fa con piena sicurezza: sul corpus di test il suo stesso `no_speech_prob` era 0,00 anche sul silenzio. Per questo ogni endpoint fa passare sull'audio un rilevatore di voce, Silero VAD, e scarta un segmento trascritto che cade per lo più fuori dal parlato rilevato, oltre a qualsiasi segmento che sia un'intera riga di titoli dei sottotitoli. Su un corpus di nove registrazioni senza parlato questo ha eliminato ogni riga del genere mantenendo ogni frase delle registrazioni con parlato. Una registrazione in cui non si dice nulla ora risulta come testo vuoto. Nello stream in tempo reale una frase senza parlato rilevato non viene nemmeno inviata al modello. Il rilevatore gira sulla CPU e aggiunge circa un secondo ogni tre minuti di audio. `SPEECH_GATE=false` ripristina il comportamento precedente.

Gli upload sono limitati a `MAX_CONTENT_LENGTH_MB` (10 MB per il server da solo, 100 MB nella configurazione Docker); un corpo più grande restituisce `413`.

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
```

`--stream` riproduce un file verso `/api/stream` alla velocità del parlato e stampa ogni frase man mano che torna, con `--speakers` per l'attribuzione dei parlanti:

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` aggiunge `/api/stream` (solo gunicorn) |
| `LOG_LEVEL`             | `INFO`                  | livello di logging                                 |
| `LOG_ACCESS`            | `false`                 | registra le righe di access di uvicorn             |
| `WHISPER_MODEL`         | `small.en`              | nome del modello Whisper (es. `small.en`, `turbo`) |
| `WHISPER_LANGUAGE`      | `en`                    | lingua di trascrizione predefinita                 |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | directory della cache dei modelli (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, oppure `auto`                       |
| `STT_BACKEND`           | `whisper`               | backend di trascrizione: `whisper` o `parakeet`    |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | id del modello Parakeet                       |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | directory della cache del modello Parakeet         |
| `DIARIZE_ENABLED`       | `false`                 | abilita `POST /api/diarize` (richiede un'immagine `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | id del modello di diarizzazione                    |
| `DIARIZE_POOL_SIZE`     | `1`                     | istanze di diarizzazione precaricate               |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | directory della cache del modello di diarizzazione |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilità di attività del parlante contata come voce |
| `JOBS_DIR`              | `recs/jobs`             | dove i job tengono upload, record e risultato       |
| `JOB_MAX_CONTENT_LENGTH_MB` | `1024`              | dimensione massima dell'upload di un job in MB      |
| `JOB_RETENTION_HOURS`   | `24`                    | ore dopo le quali i job terminati vengono rimossi   |
| `SPEECH_GATE`           | `true`                  | scarta il testo trascritto che nessuno ha pronunciato (rilevatore di voce) |
| `STT_UID`, `STT_GID`    | (`stt` dell'immagine, 1001) | utente dell'host proprietario di `models/`, `logs/`, `recs/` (Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | `1` una volta messi in cache i modelli: nessuna richiesta all'hub all'avvio |
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
