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
* **Live-Transkription.** Streamen Sie Audio über einen WebSocket und erhalten Sie jede Phrase zurück, während sie gesprochen wird, bei aktivierter Diarisierung einem Sprecher zugeordnet.
* **Eine Web-Oberfläche ist enthalten.** Laden Sie im Browser eine Datei hoch und lesen Sie den Text oder wer was gesagt hat; ausgeliefert wird sie von einem eigenen nginx-Container neben dem Server.

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

#### Mehrere Modelle

`STT_MODELS` lädt beim Start mehrere Transkriptionsmodelle, jedes mit einem eigenen Pool, und lässt jede Anfrage mit `model` eines davon wählen. Die Einträge sind kommagetrennt und haben die Form `backend:model[@pool]`:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # Modell für Anfragen ohne `model`; leer bedeutet der erste Eintrag
```

Gewählt wird nur unter den Modellen, die beim Start geladen wurden: Eine Anfrage löst nie einen Download oder ein Laden aus, und ein nicht geladenes Modell wird mit `400` abgelehnt. Jedes aufgeführte Modell belegt Speicher, solange der Server läuft, grob `Worker x (Pool x Modellgröße)` über die Liste summiert, dazu der Diarisierer. `turbo@2,small@1,parakeet@1` braucht auf einer GPU etwa 12 + 2 + 3 = 17 GB pro Prozess. Unter gunicorn bearbeitet jeder sync-Worker eine Anfrage nach der anderen; geben Sie daher jedem Eintrag `@1` und skalieren Sie über `GUNICORN_WORKERS`. Ein Eintrag ohne `@pool` erhält `STT_POOL_SIZE`, außerhalb von Docker also 8; schreiben Sie `@N` deshalb ausdrücklich. Mehrere große Modelle laden länger als eines; erhöhen Sie die `start_period` des Healthchecks in der Compose-Datei, falls der Container beim Start als unhealthy markiert wird.

Ist `STT_MODELS` leer, wählen `STT_BACKEND`, `WHISPER_MODEL` und `PARAKEET_MODEL` wie bisher das eine Modell, und der Server lädt genau das, was er bisher geladen hat; die Antworten erhalten nur neue Felder. Ist es gesetzt, bestimmen diese Variablen nicht mehr, was geladen wird. Unter Docker gehören `STT_MODELS` und `STT_DEFAULT_MODEL` in die `.env`, nicht in den `environment:`-Block der Compose-Datei, der die `.env` überschreibt. Ein Parakeet-Eintrag braucht weiterhin ein mit `PARAKEET=true` gebautes Image, und der Server startet nicht bei einem unbekannten Backend, bei denselben Gewichten in zwei Einträgen (`turbo` und `large-v3-turbo`) oder bei einem `STT_DEFAULT_MODEL`, das nicht in der Liste steht. Ein als Dateipfad angegebenes Modell wird unter seinem Dateinamen ohne `.pt` angeboten, sodass der Pfad nie bei einem Client ankommt. `STT_DEFAULT_MODEL` darf einen solchen Eintrag mit diesem Namen oder mit dem Pfad genau so nennen, wie er in `STT_MODELS` steht, und seine Sprachen sind die des Checkpoints, den der Dateiname nennt: `/models/large-v3.pt` kennt, was `large-v3` kennt. Zwei Einträge, die unter demselben Namen bereitgestellt würden (`/a/model.pt` und `/b/model.pt`), oder ein Eintrag, der unter einem Backend-Namen bereitgestellt würde (`/models/parakeet.pt`), stoppen den Server beim Start.

### Schnellstart (Docker)

Am einfachsten lässt sich der Server mit Docker betreiben. Modelldateien werden auf dem Host in `./models` zwischengespeichert, sodass sie Neuaufbauten der Container überstehen.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

Der GPU-Build benötigt `nvidia-container-toolkit` auf dem Host. Beim ersten Lauf wird das Whisper-Modell nach `./models` heruntergeladen. Den Betrieb auf einem Server - Updates, Rollbacks, Zertifikate, Abhängigkeiten - behandelt [docs/DEPLOY.md](DEPLOY.md).

### Web-Oberfläche

`docker compose up` startet außerdem `stt_www`, einen nginx-Container, der die Browser-Oberfläche ausliefert und `/api/` an den Server durchreicht, sodass Oberfläche und API unter derselben Adresse erreichbar sind.

| Listener | Standard-Port | Gesetzt über       |
| -------- | ------------- | ------------------ |
| http     | `8080`        | `STT_WWW_PORT`     |
| https    | `8443`        | `STT_WWW_TLS_PORT` |

Öffnen Sie `http://<host>:8080`. **TRANSCRIBE** hat drei Quellen. **FILE** lädt eine Audiodatei hoch. **DEVICE** transkribiert live von einem Audioeingang: einem Mikrofon oder Headset, einer `Monitor of ...`-Quelle unter Linux, die alles führt, was über Lautsprecher oder Kopfhörer wiedergegeben wird, oder, in Chromium-Browsern, `Tab or screen audio` für das, was in einem Browser-Tab läuft, oder im ganzen System, wo das Betriebssystem es zulässt. **STREAM** nimmt die Adresse eines Streams oder einer entfernten Datei entgegen - Internetradio, HLS, RTMP, RTSP, SRT - und der Server liest sie selbst. In jedem Fall erscheint das Ergebnis unter dem Formular als schlichter Text oder, bei aktivierter Diarisierung, als ein Block pro Phrase mit Sprecher und Zeit, jeder Sprecher in einer eigenen Farbe und die Phrasen markiert, in denen zwei Personen gleichzeitig gesprochen haben; eine Live-Phrase erscheint etwa eine Sekunde, nachdem der Sprecher eine Pause macht. Das Ergebnis lässt sich kopieren oder als TXT oder JSON herunterladen, und jede Quelle behält ihr letztes Ergebnis, während Sie sich einen anderen Bildschirm ansehen. FILE hat außerdem einen Modus **Turns**, `POST /api/diarize` für sich allein: wer wann gesprochen hat, gezeichnet als Zeitleiste mit einer Spur pro Sprecher, in der die Abschnitte markiert sind, in denen zwei Personen gleichzeitig sprechen. Sind mehrere Modelle geladen (`STT_MODELS`), wählt eine Modellauswahl neben Modus und Sprache das Modell für alle drei Quellen, FILE, DEVICE und STREAM, gespeist aus `GET /api/models`, und die Sprachliste folgt dem gewählten Modell; Turns transkribiert nichts und sendet kein Modell. **MODELS** zeigt, was `GET /api/models` meldet. Wenn `STT_TOKENS` gesetzt ist, fragt die Oberfläche einmal nach einem Token und speichert es im Browser.

Browser geben Audiogeräte nur an eine sichere Seite heraus, daher funktioniert DEVICE über das Netzwerk über den https-Listener (und unter `http://localhost`). Der https-Listener verwendet ein selbstsigniertes Zertifikat, das der Container beim ersten Start in `./data/certs` anlegt; legen Sie dort ein echtes `stt.crt` und `stt.key` ab, um es zu ersetzen. Die Oberfläche hat keinen Build-Schritt und kein CDN: Vue 2 und seine Bibliotheken werden unter `www/vendor` mitgeliefert, sodass sie auch auf einer Maschine ohne Verbindung zum Internet funktioniert.

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

`GET /api/health` gibt den Status der Pools zurück. Die obersten `pool_size` und `available` beschreiben das Standardmodell, auf das eine Anfrage ohne `model` wartet; fällt `available` auf 0, sind gerade alle seine Instanzen in Arbeit. `models` meldet jedes geladene Modell nach seiner ID:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

Ist `STT_TOKENS` gesetzt, erscheinen `default_model` und `models` nur in der Antwort auf eine Anfrage mit gültigem Token: Wie `GET /api/models` verraten sie die Konfiguration des Servers. Ein Healthcheck ohne Token erhält weiterhin `status`, `pool_size`, `available` und `diarize`.

`GET /api/health?deep=1` schickt zusätzlich eine Sekunde Stille durch jedes geladene Modell, eines nach dem anderen, und meldet jedes als `ok`, `busy` (innerhalb von fünf Sekunden wurde keine Instanz frei) oder `failed`: jedes Transkriptionsmodell unter seiner ID in `deep.models`, `deep.transcriber` als das schlechteste davon und `deep.diarizer`, wenn die Diarisierung eingeschaltet ist. Ist eines gescheitert, antwortet der Endpunkt mit `503`. Das kostet GPU-Arbeit, daher braucht er ein Token, solange `STT_TOKENS` gesetzt ist; der einfache Check bleibt für Container-Healthchecks offen.

`GET /metrics` liefert Prometheus-Metriken: Anfragen nach Route und Status, ihre Dauer, Fehlerantworten nach Kategorie, Pool-Größen und freie Instanzen, laufende und gestartete Live-Sitzungen, von der Sprachaktivitätserkennung verworfene Segmente und Live-Audio, das eine in Rückstand geratene Sitzung abgeworfen hat. Die Gauges `stt_pool_*` ohne Labels beschreiben das Standardmodell und den Diarisierer; `stt_model_pool_size` und `stt_model_pool_available` führen jedes geladene Modell, mit den Labels `model` und `backend`. Pro Modell gibt es außerdem zwei Histogramme und einen Zähler: `stt_model_inference_seconds` (Labels `model` und `backend`) misst, wie lange jeder Modellaufruf für die Transkription seines Audios brauchte, `stt_model_wait_seconds` (Label `model`), wie lange jede Ausleihe auf eine freie Instanz wartete, und `stt_model_wait_timeouts_total` (Label `model`) zählt die abgelaufenen Wartezeiten - ein 503 nach `STT_QUEUE_TIMEOUT`, eine Live-Sitzung oder ein Job, der zu lange wartete, oder ein tiefer Health-Check, der das Modell belegt vorfand. Beide Histogramme verwenden die Buckets 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 2.5, 5, 10, 30, 60 und 120 Sekunden, fein unterhalb einer Sekunde, damit kurze Phrasen unterscheidbar bleiben. Wie der Health-Endpunkt braucht er kein Token, und `stt_www` leitet ihn nicht weiter: Fragen Sie `STT_PORT` direkt ab. Ebenfalls wie beim Health-Endpunkt enthalten die Serien pro Modell bei gesetztem `STT_TOKENS` nur dann Werte, wenn die Abfrage ein gültiges Token mitsendet, da sie die Modelle benennen; ohne Token bleiben die beiden Pool-Gauges leer, und die Latenz-Histogramme und der Timeout-Zähler fehlen ganz. Unter gunicorn zählt jeder Worker für sich.

`POST /api/stt` akzeptiert ein `multipart/form-data`-Feld namens `file` oder einen rohen `audio/*`-Body. Ein optionales `model` (Query-String oder Formularfeld) wählt eines der geladenen Modelle: seine ID, einen Alias (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), die Form `backend:model` oder den bloßen Backend-Namen, der das Standardmodell meint, wenn es zu diesem Backend gehört, und sonst dessen erstes Modell. Ohne `model` antwortet das Standardmodell. Ein optionales `language` (Query-String oder Formularfeld) überschreibt für diese Anfrage die Server-Voreinstellung; `auto` erkennt die Sprache automatisch. Bei Erfolg kommen der Text, die verstrichenen Sekunden, das Modell, das transkribiert hat, und die Sprache zurück: der Code, den Whisper erkannt oder verwendet hat (bei einem rein englischen Modell immer `en`), oder `null` bei Parakeet, das ihn nicht meldet.

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

Die Sprache kann als Code (`ru`) oder mit ihrem englischen Namen (`russian`) angegeben werden; was das Modell nicht kennt, wird mit `400` abgelehnt, statt mitten in der Transkription zu scheitern. `GET /api/models` listet auf, was jedes Modell kennt. Wie streng `language` geprüft wird, hängt vom Modell ab und davon, ob die Anfrage es benannt hat:

| Modell | akzeptiertes `language` | Anfrage ohne `model` | Anfrage mit `model` |
| --- | --- | --- | --- |
| mehrsprachiges Whisper | ein Code oder englischer Name aus seiner Liste | `400 Unsupported language` außerhalb der Liste | genauso |
| rein englisches Whisper (`.en`) | `en` und `auto` | ein anderer bekannter Code wird als Englisch transkribiert | `400 Unsupported language` |
| Parakeet | keines, es erkennt die Sprache selbst | jeder Wert wird angenommen und ignoriert | ein Code aus seiner Liste, sonst `400` |

Parakeet akzeptiert nur Codes, keine englischen Namen, und es kann Sprache, bei der es unsicher ist, stillschweigend auslassen: In einer mehrsprachigen Aufnahme liefert es für die Minderheitensprache womöglich gar nichts.

Ein Whisper-Dateipfad, dessen Name zu keinem bekannten Checkpoint passt, etwa ein Fine-Tune unter `/models/my-large-v3-finetune.pt`, hat eine Sprachliste, die aus diesem Namen nur geraten ist. Eine Anfrage ohne `model` reicht ihm deshalb wie bisher jeden bekannten Code weiter; eine Anfrage, die ihn nennt, wird weiterhin gegen die geratene Liste geprüft.

Die `400`-Fehler dieser beiden Optionen sind `Invalid model` (kein Backend kennt den Namen), `Model not loaded` (ein echtes Modell, das dieser Server nicht geladen hat), `Invalid language` (überhaupt keine Sprache) und `Unsupported language` (eine echte Sprache, die das gewählte Modell nicht annimmt). Alle vier kommen, bevor das Audio dekodiert wird.

`GET /api/models` gibt an, was dieser Server mitbringt, sodass ein Client nicht raten muss. Jedes geladene Modell hat eine eigene Zeile, ebenso jeder Transkriptor ohne geladenes Modell (`selectable: false`) und der Diarisierer. Jede Zeile bringt ihre eigene Sprachliste mit, denn die Mengen unterscheiden sich tatsächlich, und eine zusammengeführte Liste wäre für jedes Modell für sich genommen falsch.

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

`id` ist das, was eine Anfrage als `model` übergibt, und genau eine Zeile hat `default: true`: Ihre ID ist `default_model`, ihr Backend das oberste `default`. `pool_size` und `available` beschreiben den Pool dieses Modells. `status` ist `loaded`, wenn Instanzen in seinen Pool geladen wurden, frei oder belegt, `installed`, wenn die Gewichte auf der Platte liegen, aber noch nichts geladen ist, und sonst `absent`. Ein Backend, das konfiguriert, aber nicht installiert ist, meldet `absent` und nichts weiter; der Grund steht im Log. `accepts_language` sagt, ob `?language=` für dieses Backend überhaupt etwas bedeutet. Der Diarisierer meldet `null` statt einer leeren Sprachliste, weil er in keiner Sprache Text erzeugt.

Der CLI-Client liest denselben Endpunkt:

```bash
python3 stt_client.py --list
```

`POST /api/diarize` beantwortet **wer wann gesprochen hat**, und sonst nichts: Der Endpunkt gibt Zeitbereiche mit einer Sprechernummer zurück, niemals Text. Er ist deaktiviert, sofern nicht `DIARIZE_ENABLED` auf einem mit `DIARIZE=true` gebauten Image gesetzt ist; andernfalls antwortet er mit `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Zwei Hinweise zu diesen Zahlen. Die Sprechbeiträge dürfen sich überlappen, denn jeder Sprecherkanal wird für sich bewertet, sodass zwei gleichzeitig sprechende Personen zwei Beiträge über dieselben Sekunden erzeugen. Und die Nummern sind Positionen innerhalb dieser einen Aufnahme, geordnet danach, wer zuerst gesprochen hat: Sie sind keine Identitäten, und dieselbe Person erhält bei der nächsten Anfrage eine andere Nummer. Einen Sprecher zu benennen erfordert einen Enrollment-Schritt, den dieser Dienst nicht hat. Es werden höchstens acht Sprecher unterschieden.

Es stehen zwei Transkriptions-Backends zur Verfügung. **Whisper** ist der Standard und akzeptiert ein `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) deckt 25 europäische Sprachen ab, erkennt die Sprache selbst und nimmt daher überhaupt kein `language`-Argument an, was `GET /api/models` als `accepts_language: false` meldet. Es braucht ein mit `PARAKEET=true` gebautes Image. Sie wählen es für den ganzen Server mit `STT_BACKEND=parakeet` oder laden es über `STT_MODELS` neben Whisper und wählen es pro Anfrage mit `model`. Eine Anfrage wählt immer nur unter den beim Start geladenen Modellen, und jedes geladene Modell hält seine Gewichte in jedem Worker, der Speicher ist also die Zahl der Worker mal die Summe der Pools.

Keines der beiden Backends ist auf überlappende Sprache ausgelegt. NVIDIAs Modell für überlappende Sprache wird ausschließlich als NeMo-Checkpoint ausgeliefert, und NeMo legt eine andere PyTorch-Version fest als der CUDA-Build dieses Projekts, sodass es sich hier nicht installieren lässt.

`POST /api/transcript` beantwortet **wer was gesagt hat**: Der Endpunkt führt Diarisierung und Transkription über demselben Audio aus und verbindet beides über die Zeit. Er benötigt eine aktivierte Diarisierung und antwortet andernfalls mit `503`. Er nimmt dieselben `model` und `language` an wie `/api/stt` und nennt in `model` das Modell, das transkribiert hat.

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

`turns` ist die Rohausgabe des Diarisierers und `segments` ist die Verknüpfung; beides bleibt getrennt, damit ein Client, der der Zuordnung misstraut, weiterhin sehen kann, was der Diarisierer gemeldet hat. `text` ist die schlichte Transkription, identisch mit dem, was `/api/stt` für dieselbe Datei zurückgibt. Eine Phrase, die von keinem Sprechbeitrag abgedeckt wird, behält `"speaker": null`, statt dem nächstgelegenen zugeschlagen zu werden.

`overlap` markiert eine Phrase, während der auch jemand anderes gesprochen hat. NVIDIA sagt ausdrücklich, dass die Kombination eines herkömmlichen Einzelsprecher-Modells mit Diarisierung nicht einem Modell entspricht, das für überlappende Sprache gebaut wurde: Ein herausgeschnittener Zeitbereich enthält weiterhin jede Stimme, die ihn überlappt, sodass diese Phrasen verschmelzen oder die Worte des falschen Sprechers auswählen können. Behandeln Sie ein mit `overlap` markiertes Segment als die Stelle, an der die Transkription am wenigsten vertrauenswürdig ist.

**Lange Aufnahmen laufen über einen Job.** `POST /api/jobs` akzeptiert dieselben Body-Formen wie `/api/stt`, bis zu `JOB_MAX_CONTENT_LENGTH_MB` (1 GB), dazu einen `mode`: `text` (der Standard), `speakers` (das Ergebnis von `/api/transcript`) oder `turns` (das Ergebnis von `/api/diarize`). Der Endpunkt antwortet sofort mit `202`, der ID des Jobs und einer `Location`, die abgefragt werden kann:

```bash
curl -F file=@meeting.mp3 'localhost:5099/api/jobs?mode=speakers&language=ru'
curl localhost:5099/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "model": "turbo", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6, "model": "turbo" } }
```

`status` durchläuft `queued` (mit seiner `position`), `running` und dann `done` mit dem `result` oder `failed` mit einer `error`-Kategorie. `GET /api/jobs` listet die Jobs auf, und `DELETE /api/jobs/<id>` entfernt einen, der gerade nicht läuft. Ein Job arbeitet die Datei in Stücken von etwa einer Minute ab, die an Pausen geschnitten werden, und gibt das Modell zwischen ihnen zurück, sodass die kurzen Anfragen weiter beantwortet werden, während er läuft: Eine 30-minütige Aufnahme brauchte auf der GPU des Deployments 107 s, und Anfragen mit Telefongesprächen, die währenddessen gesendet wurden, höchstens 10 s. Die Diarisierung läuft im Streaming-Modus des Modells über die gesamte Datei, sodass ein Sprecher von der ersten bis zur letzten Minute dieselbe Nummer behält. Jobs sind Dateien unter `JOBS_DIR`, überstehen also einen Neustart, und abgeschlossene Jobs werden nach `JOB_RETENTION_HOURS` entfernt. Ein `text`- oder `speakers`-Job nimmt `model` und `language` wie `/api/stt` und behält dieses Modell: Der Job und sein Ergebnis nennen es, und ein Job, dessen Modell ein Neustart entladen hat, schlägt mit `Model not loaded` fehl. Ein `turns`-Job nimmt wie `/api/diarize` kein `model`.

`/api/stream` ist ein WebSocket für **Live-Transkription**: Audio geht hinein, während es aufgenommen wird, und jede Phrase kommt etwa eine Sekunde, nachdem der Sprecher eine Pause macht, zurück. JSON-Textnachrichten tragen die Steuerung, Binärnachrichten das Audio:

1. Der Client sendet `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}`. Alle Felder außer `type` sind optional. `model` wählt eines der geladenen Modelle so, wie es `model` bei `/api/stt` tut, und die Sprache wird gegen dieses Modell geprüft; ohne das Feld arbeitet das Standardmodell, und die Sprache wird wie bisher nur darauf geprüft, ob sie überhaupt eine Sprache ist; ein Code, den das Standardmodell nicht kennt, scheitert erst beim Transkribieren einer Phrase. Über `token` authentifiziert sich ein Browser, da er bei einem WebSocket keine Header setzen kann; andere Clients können stattdessen beim Handshake `Authorization: Bearer <token>` senden.
2. Der Server antwortet mit `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}`.
3. Der Client sendet rohes PCM - vorzeichenbehaftet, 16 Bit, Little-Endian, mono, 16 kHz - als Binärnachrichten beliebiger Größe im Tempo der Aufnahme und `{"type": "stop"}`, wenn er fertig ist. Eine Datei, die schneller als in Echtzeit gesendet wird, gerät konstruktionsbedingt in Rückstand und verliert Phrasen (siehe `skipped` unten); eine Datei gehört in einen Job.
4. Der Server sendet für jede Phrase ein `segment`, etwa einmal pro Sekunde `progress`, `skipped` mit den Sekunden verworfenen Audios, falls die Sitzung einmal mehr als zwei Minuten in Rückstand gerät, und vor dem Schließen `done`:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

Das Audio kann auch von woanders kommen. Mit `"source": "url", "url": "https://..."` in der Startnachricht sendet der Client überhaupt kein Audio: Der Server liest den Stream unter dieser Adresse über ffmpeg, bis er endet oder der Client `stop` sendet. Internetradio, HLS, RTMP, RTSP und SRT funktionieren; das Schema muss `http`, `https`, `rtmp`, `rtmps`, `rtsp` oder `srt` sein. Was eine Live-Quelle bereits vorhält, übernimmt der Server sofort, den Rest im eigenen Tempo der Quelle, sodass eine entfernte Datei so ankommt, wie es eine Sendung täte.

Weil der Server damit eine Adresse abruft, die ein Client gewählt hat, ist das eng eingegrenzt. ffmpeg darf nur Netzwerkprotokolle verwenden, sodass weder eine URL noch eine Playlist es dazu bringen kann, eine lokale Datei zu lesen, und nichts darf es dazu bringen, auf Verbindungen zu lauschen: Die SRT-Modi `listener` und `rendezvous` sowie jeder `listen`-Parameter werden abgelehnt. Eine Adresse, die der Server selbst ist oder dorthin auflöst (Loopback), eine Link-Local-Adresse wie der Cloud-Metadatendienst unter `169.254.169.254` oder `0.0.0.0` wird als `Invalid stream URL` abgelehnt; geprüft wird beim Start der Sitzung, und ffmpeg folgt weiterhin Weiterleitungen und Playlists. Eine Seite auf einer anderen Website kann keine solche Quelle starten (`Forbidden`): Browser wenden auf WebSockets kein CORS an, daher prüft der Socket, dass der Origin der Seite dieser Host ist oder in `CORS_ORIGINS` steht. Höchstens vier URL-Quellen laufen gleichzeitig in jedem Serverprozess (darüber hinaus `Service Unavailable`), gunicorn mit mehreren Workern erlaubt also so viele pro Worker, und das Log verzeichnet jede Adresse ohne Zugangsdaten und ohne Query. Hosts im eigenen Netzwerk des Servers bleiben erreichbar, was bei einer Kamera gerade der Sinn ist und der Grund, `STT_TOKENS` auf einem Server zu setzen, den andere erreichen können.

Ein Fehler ist ein einzelnes `{"type": "error", "error": "<category>", "request_id": "..."}`, gefolgt vom Schließen der Verbindung, mit den Fehlerkategorien der HTTP-API sowie `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` und `Forbidden`.

Eine Phrase endet bei einer Pause von 0,6 s, an der Stelle, an der der Diarisierer einen Sprecher an einen anderen übergeben hört (mit `diarize`, da Menschen, die einander antworten, oft weniger als 0,6 s Pause lassen), oder, sobald sie länger als 15 s dauert, an ihrer leisesten Stelle und wird für sich allein mit einem Modell transkribiert, das aus demselben Pool geliehen wird wie für Uploads, sodass ein ausgelasteter Pool Live-Phrasen verzögert, statt sie scheitern zu lassen. Mit `diarize` läuft der Diarisierer in seinem Streaming-Modus und führt einen Sprecher-Cache von Abschnitt zu Abschnitt mit, sodass ein Sprecher für die ganze Sitzung dieselbe Nummer behält. Der Socket existiert, wenn der Server unter uvicorn läuft - `python3 stt_server.py`, der Docker-Standard, oder gunicorn mit `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker`, das `stt_server:asgi_app` ausliefert -, und nicht unter dem Flask-Debug-Server oder den standardmäßigen Sync-Workern von gunicorn, die kein WebSocket sprechen.

**Zurückgegeben wird nur gesprochener Text.** Wo keine Sprache vorkommt - ein Ton, Musik, Rauschen, ein Freizeichen, sogar digitale Stille -, antwortet Whisper mit dem Abspann der untertitelten Videos, aus denen es gelernt hat (eine russische Zeile "Untertitel von DimaTorzok", "Fortsetzung folgt...", "Danke fürs Zuschauen."), und zwar mit voller Zuversicht: Im Testkorpus lag sein eigenes `no_speech_prob` selbst bei Stille bei 0,00. Deshalb lässt jeder Endpunkt eine Sprachaktivitätserkennung, Silero VAD, über das Audio laufen und verwirft ein transkribiertes Segment, das größtenteils außerhalb erkannter Sprache liegt, sowie jedes Segment, das eine vollständige Abspannzeile aus Untertiteln ist. Auf einem Korpus aus neun Aufnahmen ohne Sprache entfernte das jede solche Zeile, während jede Phrase der Sprachaufnahmen erhalten blieb. Eine Aufnahme, in der nichts gesprochen wird, ergibt jetzt leeren Text. Im Live-Stream wird eine Phrase ohne erkannte Sprache gar nicht erst an das Modell geschickt. Die Erkennung läuft auf der CPU und kostet etwa eine Sekunde pro drei Minuten Audio. `SPEECH_GATE=false` stellt das alte Verhalten wieder her.

Uploads sind auf `MAX_CONTENT_LENGTH_MB` begrenzt (10 MB beim reinen Server, 100 MB im Docker-Setup); ein größerer Body gibt `413` zurück.

Fehler sind einheitlich: `error` trägt eine generische Kategorie, und `request_id` verknüpft die Antwort mit dem Server-Log, in dem die vollständige Ausnahme festgehalten wird.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Wenn `STT_TOKENS` gesetzt ist, muss jede Route außer `GET /api/health` `Authorization: Bearer <token>` mitführen; dieser Endpunkt bleibt offen, damit Healthchecks weiterhin funktionieren.

### OpenAI-kompatible API

`POST /v1/audio/transcriptions` und `GET /v1/models` folgen der Audio-API von OpenAI, daher funktioniert jedes OpenAI-SDK, sobald seine `base_url` auf `http://<host>:<port>/v1` zeigt und sein API-Key einer der `STT_TOKENS` ist (bei ausgeschalteter Authentifizierung ein beliebiger String).

```bash
curl localhost:5099/v1/audio/transcriptions \
  -H 'Authorization: Bearer <token>' \
  -F file=@phrase.wav -F model=turbo -F language=en -F response_format=verbose_json
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:5099/v1", api_key="<token>")
print(client.audio.transcriptions.create(model="turbo", file=open("phrase.wav", "rb")).text)
```

Die Anfrage ist `multipart/form-data` mit `file` und durchläuft genau das, was `/api/stt` tut: dasselbe Token, dieselbe Größengrenze, dieselbe Konvertierung, denselben Sprachfilter und dieselbe Wartezeit auf eine freie Instanz (`STT_QUEUE_TIMEOUT`). Ein 16-kHz-Mono-WAV mit 16-Bit-PCM wird ohne Dekodierung weitergereicht, alles andere wird wie bei `/api/stt` über pydub dekodiert und auf 16 kHz mono konvertiert.

- `model` ist eine der IDs, die `GET /v1/models` auflistet (dieselben IDs wie `/api/models`), ein Alias oder ein Backend-Name, genau wie bei `/api/stt`; fehlt er oder ist er leer, gilt das Standardmodell. OpenAIs eigene Namen wie `whisper-1` werden als `Invalid model` abgelehnt.
- `language` wird wie bei `/api/stt` gegen das gewählte Modell geprüft; Parakeet nimmt es an und ignoriert es.
- `prompt` wird zu Whispers Initial Prompt. openai-whisper behält nur dessen letzte 223 Tokens und nutzt ihn für die ersten 30 s Audio. Parakeet nimmt keinen Prompt und ignoriert ihn. Ein Prompt mit einem Whisper-Sondertoken wie `<|endoftext|>` wird unabhängig vom Modell mit 400 abgelehnt. Der Prompt wird nie geloggt.
- `temperature` darf nur fehlen oder `0` sein: Dekodiert wird deterministisch bei Temperatur 0.
- `response_format` ist `json` (Standard, `{"text": ...}`), `text` (ein Klartext-Body) oder `verbose_json`; `srt` und `vtt` werden abgelehnt. `timestamp_granularities[]` darf nur `segment` anfordern.

`verbose_json` enthält `task`, `language` (den vollen kleingeschriebenen Namen, den Whisper meldet, etwa `english`, oder `null` für Parakeet, das keinen meldet), `duration` in Sekunden, `text` und `segments`. Whispers Segmente sind seine eigenen, mit `id`, `seek`, `start`, `end`, `text`, `tokens`, `temperature`, `avg_logprob`, `compression_ratio` und `no_speech_prob`. Parakeet liefert ein Segment mit leeren `tokens` und den Konfidenzfeldern als `null`, weil es keine erzeugt.

Fehler auf jedem `/v1`-Pfad, `401`, `404`, `405`, `413` und `500` eingeschlossen, haben die Form von OpenAI, mit derselben Kategorie als `message`; jede `/v1`-Antwort trägt außerdem die Request-ID im Header `X-Request-Id`. Fehler unter `/api/*` behalten ihre eigene Form.

```json
{ "error": { "message": "Invalid language", "type": "invalid_request_error", "param": "language",
             "code": "invalid_language", "request_id": "a1b2c3d4e5f6" } }
```

### CLI-Client

`stt_client.py` ist ein kleiner Client zum Arbeiten mit dem Server und zum Testen. Er liest die Server-Adresse und das Token aus `STT_URL` und `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` und `--language` (auch als `--model=NAME`) werden nur gesendet, wenn sie angegeben sind, sonst gilt die Server-Voreinstellung; jede Ergebniszeile zeigt Modell und Sprache, die der Server verwendet hat. `--list` gibt das Standardmodell aus und je Modell eine Zeile mit Status, Wählbarkeit, Pool und Sprachen.

`--stream` spielt eine Datei in Sprechgeschwindigkeit in `/api/stream` ein und gibt jede Phrase aus, sobald sie zurückkommt, mit `--speakers` für die Sprecherzuordnung:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### Umgebungsvariablen

`.env` wird sowohl vom Server als auch vom Client über `python-dotenv` geladen.

| Variable                | Default                 | Zweck                                               |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | Bind-Adresse des Servers                            |
| `STT_PORT`              | `5099`                  | Server-Port                                         |
| `STT_POOL_SIZE`         | `8`                     | Instanzen pro Modell; Standard für einen `STT_MODELS`-Eintrag ohne `@pool` |
| `STT_QUEUE_TIMEOUT`     | `120`                   | Sekunden, die eine synchrone Anfrage auf eine freie Instanz ihres Modells wartet, bevor `503` kommt |
| `STT_KEEPALIVE_SECONDS` | `5`                     | Sekunden, die eine ungenutzte HTTP-Verbindung offen bleibt (uvicorn; gunicorn `keepalive`) |
| `STT_TOKENS`            | (empty)                 | kommagetrennte gültige Tokens; leer deaktiviert Auth |
| `STT_DEBUG`             | `false`                 | Flask-Debug-Modus                                   |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | maximale Upload-Größe in MB; ein größerer Body gibt `413` zurück |
| `CORS_ORIGINS`          | `*`                     | erlaubte CORS-Ursprünge: `*` oder eine kommagetrennte Liste |
| `GUNICORN_WORKERS`      | `4`                     | Worker-Prozesse (nur gunicorn)                      |
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` ergänzt `/api/stream` (nur gunicorn) |
| `LOG_LEVEL`             | `INFO`                  | Logging-Level                                       |
| `LOG_ACCESS`            | `false`                 | uvicorn-Access-Zeilen protokollieren                |
| `WHISPER_MODEL`         | `small.en`              | Whisper-Modellname (z. B. `small.en`, `turbo`), wenn `STT_MODELS` leer ist |
| `WHISPER_LANGUAGE`      | `en`                    | Standardsprache jedes Whisper-Modells |
| `WHISPER_BEAM_SIZE`     | `1`                     | Beam-Breite von Whisper; `1` ist greedy, ein breiterer Beam ist langsamer und etwas genauer |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | Verzeichnis des Modell-Caches (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` oder `auto`                            |
| `STT_BACKEND`           | `whisper`               | Transkriptions-Backend: `whisper` oder `parakeet`, wenn `STT_MODELS` leer ist |
| `STT_MODELS`            | (empty)                 | mehrere Modelle nebeneinander: `backend:model[@pool]`, kommagetrennt |
| `STT_DEFAULT_MODEL`     | (empty)                 | Modell für Anfragen ohne `model`; leer bedeutet der erste `STT_MODELS`-Eintrag |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | ID des Parakeet-Modells                             |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Verzeichnis des Parakeet-Modell-Caches              |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` aktivieren (erfordert ein `DIARIZE=true`-Image) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | ID des Diarisierungsmodells                         |
| `DIARIZE_POOL_SIZE`     | `1`                     | Anzahl vorab geladener Diarisierungs-Instanzen      |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | Verzeichnis des Diarisierungsmodell-Caches          |
| `DIARIZE_THRESHOLD`     | `0.5`                   | Sprecheraktivitäts-Wahrscheinlichkeit, die als Sprache zählt |
| `JOBS_DIR`              | `recs/jobs`             | wo Jobs ihren Upload, ihren Datensatz und ihr Ergebnis ablegen |
| `JOB_MAX_CONTENT_LENGTH_MB` | `1024`              | maximale Upload-Größe eines Jobs in MB              |
| `JOB_RETENTION_HOURS`   | `24`                    | Stunden, nach denen abgeschlossene Jobs entfernt werden |
| `SPEECH_GATE`           | `true`                  | verwirft Text, den niemand gesprochen hat (Sprachaktivitätserkennung) |
| `STT_UID`, `STT_GID`    | (`stt` aus dem Image, 1001) | Host-Benutzer, dem `models/`, `logs/`, `recs/` gehören (Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | `1`, sobald die Modelle im Cache liegen: keine Hub-Anfragen beim Start |
| `STT_WWW_PORT`          | `8080`                  | http-Port der Web-Oberfläche (compose)              |
| `STT_WWW_TLS_PORT`      | `8443`                  | https-Port der Web-Oberfläche (compose)             |
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
│   ├── model_pool.py    # ein Pool pro Transkriptionsmodell und einer für den Diarisierer
│   ├── catalog.py       # was dieser Server kann, für GET /api/models
│   ├── openai_api.py    # die OpenAI-kompatible /v1-API: ihre Optionen, Antworten und Modellliste
│   ├── align.py         # verbindet Transkriptionssegmente mit Sprechbeiträgen
│   ├── live.py          # der WebSocket /api/stream: Protokoll und Sitzungen
│   ├── stream.py        # Kern der Live-Transkription: Pausen, Phrasen, Transkription je Phrase
│   ├── url_source.py    # URL-Quellen für /api/stream: Prüfung der Adresse, Start von ffmpeg
│   ├── speech_gate.py   # Sprachaktivitätserkennung, die Text verwirft, den niemand gesprochen hat
│   ├── metrics.py       # Prometheus-Metriken für GET /metrics
│   ├── jobs.py          # Hintergrund-Jobs: auf der Platte gespeichert, per Sperre übernommen, von einem Worker-Thread ausgeführt
│   ├── longform.py      # eine lange Aufnahme in Stücken: ein geliehenes Modell pro Stück, Sprecher über die ganze Datei
│   ├── stt.py           # Whisper-Wrapper
│   ├── parakeet.py      # NVIDIA-Parakeet-Wrapper, der zweite Transkribierer
│   ├── backends.py      # Backend-Name -> Transkriptionsmodul (STT_BACKEND oder ein STT_MODELS-Eintrag)
│   ├── registry.py      # welche Modelle geladen sind und was eine Anfrage wählen darf
│   └── diarize.py       # Sprecherdiarisierung (wer wann gesprochen hat, kein Text)
├── Dockerfile           # GPU-Build (CUDA 13.0)
├── Dockerfile-cpu       # CPU-Build
├── Dockerfile-www       # Image der Web-Oberfläche (nginx)
├── nginx/               # stt_www-Konfiguration: statische Oberfläche, /api/-Proxy, selbstsigniertes TLS
├── www/                 # Web-Oberfläche: Vue 2 ohne Build-Schritt, Bibliotheken mitgeliefert
├── constraints.txt      # jede Abhängigkeitsversion, die das getestete Image aufgelöst hat
├── docs/                # DEPLOY.md und die README-Übersetzungen
└── tests/               # pytest-Tests, keine Modell-Downloads und keine GPU
```

### Entwicklung

Die Systempakete `ffmpeg` und `libsndfile1` müssen vorhanden sein. Installieren Sie die Laufzeit- und Entwicklungsabhängigkeiten:

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

Die Testsuite ersetzt das Whisper-Backend durch einen Stub, deckt also die HTTP-Schicht ab (request_id, Fehlerkategorien, Semantik des Modell-Pools) und läuft in Sekunden, ohne ein Modell herunterzuladen oder eine GPU zu benötigen.

### Lizenz

[MIT](../LICENSE)
