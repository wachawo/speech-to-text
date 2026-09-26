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

Öffnen Sie `http://<host>:8080`. **TRANSCRIBE** hat drei Quellen. **FILE** lädt eine Audiodatei hoch. **DEVICE** transkribiert live von einem Audioeingang: einem Mikrofon oder Headset, einer `Monitor of ...`-Quelle unter Linux, die alles führt, was über Lautsprecher oder Kopfhörer wiedergegeben wird, oder, in Chromium-Browsern, `Tab or screen audio` für das, was in einem Browser-Tab läuft, oder im ganzen System, wo das Betriebssystem es zulässt. **STREAM** nimmt die Adresse eines Streams oder einer entfernten Datei entgegen - Internetradio, HLS, RTMP, RTSP, SRT - und der Server liest sie selbst. In jedem Fall erscheint das Ergebnis unter dem Formular als schlichter Text oder, bei aktivierter Diarisierung, als ein Block pro Phrase mit Sprecher und Zeit, jeder Sprecher in einer eigenen Farbe und die Phrasen markiert, in denen zwei Personen gleichzeitig gesprochen haben; eine Live-Phrase erscheint etwa eine Sekunde, nachdem der Sprecher eine Pause macht. Das Ergebnis lässt sich kopieren oder als TXT oder JSON herunterladen, und jede Quelle behält ihr letztes Ergebnis, während Sie sich einen anderen Bildschirm ansehen. FILE hat außerdem einen Modus **Turns**, `POST /api/diarize` für sich allein: wer wann gesprochen hat, gezeichnet als Zeitleiste mit einer Spur pro Sprecher, in der die Abschnitte markiert sind, in denen zwei Personen gleichzeitig sprechen. **MODELS** zeigt, was `GET /api/models` meldet. Wenn `STT_TOKENS` gesetzt ist, fragt die Oberfläche einmal nach einem Token und speichert es im Browser.

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

`GET /api/health` gibt den Status des Pools zurück. Wenn `available` auf 0 fällt, sind gerade alle Modelle in Verwendung:

```json
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`GET /api/health?deep=1` schickt zusätzlich eine Sekunde Stille durch jedes geladene Modell und meldet jedes als `ok`, `busy` (innerhalb von fünf Sekunden wurde keine Instanz frei) oder `failed`; ist eines gescheitert, antwortet der Endpunkt mit `503`. Das kostet GPU-Arbeit, daher braucht er ein Token, solange `STT_TOKENS` gesetzt ist; der einfache Check bleibt für Container-Healthchecks offen.

`GET /metrics` liefert Prometheus-Metriken: Anfragen nach Route und Status, ihre Dauer, Fehlerantworten nach Kategorie, Pool-Größen und freie Instanzen, laufende und gestartete Live-Sitzungen, von der Sprachaktivitätserkennung verworfene Segmente und Live-Audio, das eine in Rückstand geratene Sitzung abgeworfen hat. Wie der Health-Endpunkt braucht er kein Token, und `stt_www` leitet ihn nicht weiter: Fragen Sie `STT_PORT` direkt ab. Unter gunicorn zählt jeder Worker für sich.

`POST /api/stt` akzeptiert ein `multipart/form-data`-Feld namens `file` oder einen rohen `audio/*`-Body. Ein optionales `language` (Query-String oder Formularfeld) überschreibt für diese Anfrage den Server-Standard; `auto` erkennt die Sprache automatisch. Bei Erfolg werden der Text und die verstrichenen Sekunden zurückgegeben:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Die Sprache kann als Code (`ru`) oder mit ihrem englischen Namen (`russian`) angegeben werden; was das Modell nicht kennt, wird mit `400` abgelehnt, statt mitten in einer Transkription zu scheitern. `GET /api/models` listet auf, was es kennt. Das gilt für Backends, die eine Sprache annehmen (`accepts_language: true`). Parakeet erkennt die Sprache selbst und ignoriert den Wert, und es kann Sprache, bei der es unsicher ist, ohne Hinweis auslassen: In einer mehrsprachigen Aufnahme liefert es für die Minderheitensprache unter Umständen gar nichts.

`GET /api/models` gibt an, was dieser Server mitbringt, sodass ein Client nicht raten muss. Jedes Backend bringt seine eigene Sprachliste mit, denn die Mengen weichen tatsächlich voneinander ab, und eine zusammengeführte Liste wäre für jedes Backend einzeln falsch.

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

`status` ist `loaded`, wenn eine Instanz in einem Pool wartet, `installed`, wenn die Gewichte auf der Platte liegen, aber noch nichts geladen ist, und andernfalls `absent`. Ein Backend, das konfiguriert, aber nicht installiert ist, meldet `absent` und nichts weiter; der Grund geht ins Log. `accepts_language` sagt, ob `?language=` für dieses Backend überhaupt eine Bedeutung hat. Der Diarisierer meldet `null` als Sprachen statt einer leeren Liste, denn er erzeugt in keiner Sprache Text.

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

Es stehen zwei Transkriptions-Backends zur Verfügung. **Whisper** ist der Standard und akzeptiert ein `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) deckt 25 europäische Sprachen ab, erkennt die Sprache selbst und nimmt daher überhaupt kein `language`-Argument entgegen, was `GET /api/models` als `accepts_language: false` meldet. Wählen Sie es mit `STT_BACKEND=parakeet` auf einem mit `PARAKEET=true` gebauten Image; das ist eine Entscheidung zur Deployment-Zeit und keine pro Anfrage, denn ein zweites dauerhaft geladenes Modell würde einen zweiten Satz Gewichte in jedem Worker bedeuten.

Keines der beiden Backends ist auf überlappende Sprache ausgelegt. NVIDIAs Modell für überlappende Sprache wird ausschließlich als NeMo-Checkpoint ausgeliefert, und NeMo legt eine andere PyTorch-Version fest als der CUDA-Build dieses Projekts, sodass es sich hier nicht installieren lässt.

`POST /api/transcript` beantwortet **wer was gesagt hat**: Der Endpunkt führt Diarisierung und Transkription über demselben Audio aus und verbindet beides über die Zeit. Er benötigt eine aktivierte Diarisierung und antwortet andernfalls mit `503`.

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

`turns` ist die Rohausgabe des Diarisierers und `segments` ist die Verknüpfung; beides bleibt getrennt, damit ein Client, der der Zuordnung misstraut, weiterhin sehen kann, was der Diarisierer gemeldet hat. `text` ist die schlichte Transkription, identisch mit dem, was `/api/stt` für dieselbe Datei zurückgibt. Eine Phrase, die von keinem Sprechbeitrag abgedeckt wird, behält `"speaker": null`, statt dem nächstgelegenen zugeschlagen zu werden.

`overlap` markiert eine Phrase, während der auch jemand anderes gesprochen hat. NVIDIA sagt ausdrücklich, dass die Kombination eines herkömmlichen Einzelsprecher-Modells mit Diarisierung nicht einem Modell entspricht, das für überlappende Sprache gebaut wurde: Ein herausgeschnittener Zeitbereich enthält weiterhin jede Stimme, die ihn überlappt, sodass diese Phrasen verschmelzen oder die Worte des falschen Sprechers auswählen können. Behandeln Sie ein mit `overlap` markiertes Segment als die Stelle, an der die Transkription am wenigsten vertrauenswürdig ist.

**Lange Aufnahmen laufen über einen Job.** `POST /api/jobs` akzeptiert dieselben Body-Formen wie `/api/stt`, bis zu `JOB_MAX_CONTENT_LENGTH_MB` (1 GB), dazu einen `mode`: `text` (der Standard), `speakers` (das Ergebnis von `/api/transcript`) oder `turns` (das Ergebnis von `/api/diarize`). Der Endpunkt antwortet sofort mit `202`, der ID des Jobs und einer `Location`, die abgefragt werden kann:

```bash
curl -F file=@meeting.mp3 'localhost:5099/api/jobs?mode=speakers&language=ru'
curl localhost:5099/api/jobs/1f0c3a9e7d2b4c85
```

```json
{ "id": "1f0c3a9e7d2b4c85", "status": "done", "mode": "speakers", "position": null, "seconds": 1801.6,
  "result": { "segments": ["..."], "turns": ["..."], "speakers": 4, "text": "...", "seconds": 1801.6 } }
```

`status` durchläuft `queued` (mit seiner `position`), `running` und dann `done` mit dem `result` oder `failed` mit einer `error`-Kategorie. `GET /api/jobs` listet die Jobs auf, und `DELETE /api/jobs/<id>` entfernt einen, der gerade nicht läuft. Ein Job arbeitet die Datei in Stücken von etwa einer Minute ab, die an Pausen geschnitten werden, und gibt das Modell zwischen ihnen zurück, sodass die kurzen Anfragen weiter beantwortet werden, während er läuft: Eine 30-minütige Aufnahme brauchte auf der GPU des Deployments 107 s, und Anfragen mit Telefongesprächen, die währenddessen gesendet wurden, höchstens 10 s. Die Diarisierung läuft im Streaming-Modus des Modells über die gesamte Datei, sodass ein Sprecher von der ersten bis zur letzten Minute dieselbe Nummer behält. Jobs sind Dateien unter `JOBS_DIR`, überstehen also einen Neustart, und abgeschlossene Jobs werden nach `JOB_RETENTION_HOURS` entfernt.

`/api/stream` ist ein WebSocket für **Live-Transkription**: Audio geht hinein, während es aufgenommen wird, und jede Phrase kommt etwa eine Sekunde, nachdem der Sprecher eine Pause macht, zurück. JSON-Textnachrichten tragen die Steuerung, Binärnachrichten das Audio:

1. Der Client sendet `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`. Alle Felder außer `type` sind optional. Über `token` authentifiziert sich ein Browser, da er bei einem WebSocket keine Header setzen kann; andere Clients können stattdessen beim Handshake `Authorization: Bearer <token>` senden.
2. Der Server antwortet mit `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`.
3. Der Client sendet rohes PCM - vorzeichenbehaftet, 16 Bit, Little-Endian, mono, 16 kHz - als Binärnachrichten beliebiger Größe im Tempo der Aufnahme und `{"type": "stop"}`, wenn er fertig ist. Eine Datei, die schneller als in Echtzeit gesendet wird, gerät konstruktionsbedingt in Rückstand und verliert Phrasen (siehe `skipped` unten); eine Datei gehört in einen Job.
4. Der Server sendet für jede Phrase ein `segment`, etwa einmal pro Sekunde `progress`, `skipped` mit den Sekunden verworfenen Audios, falls die Sitzung einmal mehr als zwei Minuten in Rückstand gerät, und vor dem Schließen `done`:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

Das Audio kann auch von woanders kommen. Mit `"source": "url", "url": "https://..."` in der Startnachricht sendet der Client überhaupt kein Audio: Der Server liest den Stream unter dieser Adresse über ffmpeg, bis er endet oder der Client `stop` sendet. Internetradio, HLS, RTMP, RTSP und SRT funktionieren; das Schema muss `http`, `https`, `rtmp`, `rtmps`, `rtsp` oder `srt` sein. Was eine Live-Quelle bereits vorhält, übernimmt der Server sofort, den Rest im eigenen Tempo der Quelle, sodass eine entfernte Datei so ankommt, wie es eine Sendung täte.

Weil der Server damit eine Adresse abruft, die ein Client gewählt hat, ist das eng eingegrenzt. ffmpeg darf nur Netzwerkprotokolle verwenden, sodass weder eine URL noch eine Playlist es dazu bringen kann, eine lokale Datei zu lesen, und nichts darf es dazu bringen, auf Verbindungen zu lauschen: Die SRT-Modi `listener` und `rendezvous` sowie jeder `listen`-Parameter werden abgelehnt. Eine Seite auf einer anderen Website kann keine solche Quelle starten (`Forbidden`): Browser wenden auf WebSockets kein CORS an, daher prüft der Socket, dass der Origin der Seite dieser Host ist oder in `CORS_ORIGINS` steht. Höchstens vier URL-Quellen laufen gleichzeitig (darüber hinaus `Service Unavailable`), und das Log verzeichnet jede Adresse ohne Zugangsdaten und ohne Query. Hosts im eigenen Netzwerk des Servers bleiben erreichbar, was bei einer Kamera gerade der Sinn ist und der Grund, `STT_TOKENS` auf einem Server zu setzen, den andere erreichen können.

Ein Fehler ist ein einzelnes `{"type": "error", "error": "<category>", "request_id": "..."}`, gefolgt vom Schließen der Verbindung, mit den Fehlerkategorien der HTTP-API sowie `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` und `Forbidden`.

Eine Phrase endet bei einer Pause von 0,6 s, an der Stelle, an der der Diarisierer einen Sprecher an einen anderen übergeben hört (mit `diarize`, da Menschen, die einander antworten, oft weniger als 0,6 s Pause lassen), oder, sobald sie länger als 15 s dauert, an ihrer leisesten Stelle und wird für sich allein mit einem Modell transkribiert, das aus demselben Pool geliehen wird wie für Uploads, sodass ein ausgelasteter Pool Live-Phrasen verzögert, statt sie scheitern zu lassen. Mit `diarize` läuft der Diarisierer in seinem Streaming-Modus und führt einen Sprecher-Cache von Abschnitt zu Abschnitt mit, sodass ein Sprecher für die ganze Sitzung dieselbe Nummer behält. Der Socket existiert, wenn der Server unter uvicorn läuft - `python3 stt_server.py`, der Docker-Standard, oder gunicorn mit `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker`, das `stt_server:asgi_app` ausliefert -, und nicht unter dem Flask-Debug-Server oder den standardmäßigen Sync-Workern von gunicorn, die kein WebSocket sprechen.

**Zurückgegeben wird nur gesprochener Text.** Wo keine Sprache vorkommt - ein Ton, Musik, Rauschen, ein Freizeichen, sogar digitale Stille -, antwortet Whisper mit dem Abspann der untertitelten Videos, aus denen es gelernt hat (eine russische Zeile "Untertitel von DimaTorzok", "Fortsetzung folgt...", "Danke fürs Zuschauen."), und zwar mit voller Zuversicht: Im Testkorpus lag sein eigenes `no_speech_prob` selbst bei Stille bei 0,00. Deshalb lässt jeder Endpunkt eine Sprachaktivitätserkennung, Silero VAD, über das Audio laufen und verwirft ein transkribiertes Segment, das größtenteils außerhalb erkannter Sprache liegt, sowie jedes Segment, das eine vollständige Abspannzeile aus Untertiteln ist. Auf einem Korpus aus neun Aufnahmen ohne Sprache entfernte das jede solche Zeile, während jede Phrase der Sprachaufnahmen erhalten blieb. Eine Aufnahme, in der nichts gesprochen wird, ergibt jetzt leeren Text. Im Live-Stream wird eine Phrase ohne erkannte Sprache gar nicht erst an das Modell geschickt. Die Erkennung läuft auf der CPU und kostet etwa eine Sekunde pro drei Minuten Audio. `SPEECH_GATE=false` stellt das alte Verhalten wieder her.

Uploads sind auf `MAX_CONTENT_LENGTH_MB` begrenzt (10 MB beim reinen Server, 100 MB im Docker-Setup); ein größerer Body gibt `413` zurück.

Fehler sind einheitlich: `error` trägt eine generische Kategorie, und `request_id` verknüpft die Antwort mit dem Server-Log, in dem die vollständige Ausnahme festgehalten wird.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Wenn `STT_TOKENS` gesetzt ist, muss jede Route außer `GET /api/health` `Authorization: Bearer <token>` mitführen; dieser Endpunkt bleibt offen, damit Healthchecks weiterhin funktionieren.

### CLI-Client

`stt_client.py` ist ein kleiner Client zum Arbeiten mit dem Server und zum Testen. Er liest die Server-Adresse und das Token aus `STT_URL` und `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

`--stream` spielt eine Datei in Sprechgeschwindigkeit in `/api/stream` ein und gibt jede Phrase aus, sobald sie zurückkommt, mit `--speakers` für die Sprecherzuordnung:

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` ergänzt `/api/stream` (nur gunicorn) |
| `LOG_LEVEL`             | `INFO`                  | Logging-Level                                       |
| `LOG_ACCESS`            | `false`                 | uvicorn-Access-Zeilen protokollieren                |
| `WHISPER_MODEL`         | `small.en`              | Whisper-Modellname (z. B. `small.en`, `turbo`)      |
| `WHISPER_LANGUAGE`      | `en`                    | Standardsprache der Transkription                   |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | Verzeichnis des Modell-Caches (`/opt/models` in Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` oder `auto`                            |
| `STT_BACKEND`           | `whisper`               | Transkriptions-Backend: `whisper` oder `parakeet`   |
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
│   ├── model_pool.py    # Pools vorgeladener Whisper- und Diarisierungs-Instanzen
│   ├── catalog.py       # was dieser Server kann, für GET /api/models
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
│   ├── backends.py      # welches Modul transkribiert, je nach STT_BACKEND
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
