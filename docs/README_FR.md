## speech-to-text: un serveur de transcription Whisper auto-hébergé

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | **[Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md)** | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` convertit l'audio en texte avec [openai-whisper](https://github.com/openai/whisper), enveloppé dans un petit service HTTP que vous exécutez vous-même. Vous envoyez un fichier audio, vous récupérez la transcription. Aucune API externe, aucune facturation à la minute, et votre audio ne quitte jamais votre machine.

Le projet convient à l'usage local, à la transcription par lots et à l'exploitation de votre propre serveur STT sur le réseau.

* **Un serveur HTTP prêt à l'emploi.** Flask servi par uvicorn charge Whisper au démarrage et répond aux requêtes des autres machines de votre réseau local.
* **Sûr en cas de concurrence.** Le serveur conserve un pool d'instances Whisper préchargées, de sorte que plusieurs requêtes sont transcrites en parallèle sans recharger le modèle.
* **CPU ou GPU, le même code.** Le backend est sélectionné par l'environnement et par l'image Docker que vous construisez. Une carte CUDA accélère l'inférence, mais tout fonctionne aussi sur CPU.
* **Un client en ligne de commande est inclus.** `stt_client.py` envoie des fichiers locaux au serveur et affiche le résultat.
* **Transcription en direct.** Diffusez l'audio via un WebSocket et recevez chaque phrase au fil de la parole, attribuée à un locuteur lorsque la diarisation est activée.
* **Une interface web est incluse.** Envoyez un fichier depuis le navigateur et lisez le texte, ou qui a dit quoi ; elle est servie par son propre conteneur nginx à côté du serveur.

### Modèles

Whisper propose plusieurs tailles de modèles. Les modèles plus grands sont plus précis et plus lents ; les plus petits sont rapides et légers.

| Modèle     | Paramètres | VRAM    | Langues         | Adapté à                                      |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | multilingue     | brouillons rapides sur matériel modeste       |
| `base`     | 74M        | ~1 GB   | multilingue     | une option polyvalente légère par défaut      |
| `small`    | 244M       | ~2 GB   | multilingue     | un bon équilibre précision / vitesse          |
| `medium`   | 769M       | ~5 GB   | multilingue     | meilleure précision quand la mémoire le permet |
| `turbo`    | 809M       | ~6 GB   | multilingue     | précision proche de `large`, bien plus rapide |
| `large`    | 1550M      | ~10 GB  | multilingue     | meilleure qualité, nécessite un GPU           |

Les variantes uniquement anglaises (`tiny.en`, `base.en`, `small.en`, `medium.en`) sont un peu plus précises sur l'audio en anglais. La valeur par défaut est `turbo`, qui constitue le meilleur choix tout-terrain pour l'anglais sur un GPU.

### Démarrage rapide (Docker)

La façon la plus simple d'exécuter le serveur est avec Docker. Les fichiers de modèle sont mis en cache dans `./models` sur l'hôte, ils survivent donc aux reconstructions de conteneurs.

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

La construction GPU nécessite `nvidia-container-toolkit` sur l'hôte. Le premier lancement télécharge le modèle Whisper dans `./models`.

### Interface web

`docker compose up` démarre aussi `stt_www`, un conteneur nginx qui sert l'interface du navigateur et transmet `/api/` au serveur, de sorte que l'interface et l'API partagent une même adresse.

| Point d'écoute | Port par défaut | Défini par         |
| -------------- | --------------- | ------------------ |
| http           | `8080`          | `STT_WWW_PORT`     |
| https          | `8443`          | `STT_WWW_TLS_PORT` |

Ouvrez `http://<host>:8080`. **TRANSCRIBE** propose deux sources. **FILE** envoie un fichier audio. **DEVICE** transcrit en direct depuis une entrée audio : un microphone ou un micro-casque, une source `Monitor of ...` sous Linux qui transporte tout ce qui est joué par les haut-parleurs ou les écouteurs, ou `Tab or screen audio` pour ce qui est joué dans un onglet du navigateur, ou dans tout le système lorsque le système d'exploitation le permet. Dans les deux cas, le résultat apparaît sous le formulaire en texte brut ou, avec la diarisation activée, sous forme d'un bloc par phrase avec son locuteur et son horodatage, chaque locuteur dans sa propre couleur et les phrases où deux personnes ont parlé en même temps signalées ; une phrase en direct apparaît environ une seconde après que le locuteur a marqué une pause. Le résultat peut être copié ou téléchargé en TXT ou en JSON. **MODELS** affiche ce que renvoie `GET /api/models`. Lorsque `STT_TOKENS` est défini, l'interface demande un jeton une seule fois et le conserve dans le navigateur.

Les navigateurs ne confient les périphériques audio qu'à une page sécurisée : à travers le réseau, DEVICE fonctionne donc via le point d'écoute https (et sur `http://localhost`). Le point d'écoute https utilise un certificat auto-signé que le conteneur crée dans `./data/certs` à son premier démarrage ; placez-y un vrai `stt.crt` et un vrai `stt.key` pour le remplacer. L'interface n'a ni étape de build ni CDN : Vue 2 et ses bibliothèques sont embarquées dans `www/vendor`, elle fonctionne donc sur une machine sans accès à Internet.

### API HTTP

Une fois le serveur démarré, vérifiez son état et envoyez un fichier audio pour transcription.

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` renvoie l'état du pool. La chute de `available` à 0 signifie que tous les modèles sont actuellement en cours d'utilisation :

```json
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`POST /api/stt` accepte un champ `multipart/form-data` nommé `file`, ou un corps brut `audio/*`. Un paramètre optionnel `language` (chaîne de requête ou champ de formulaire) remplace la valeur par défaut du serveur pour cette requête ; `auto` détecte automatiquement. En cas de succès, il renvoie le texte et les secondes écoulées :

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

La langue peut être donnée sous forme de code (`ru`) ou par son nom anglais (`russian`) ; toute valeur inconnue du modèle est refusée avec `400` plutôt que d'échouer au milieu d'une transcription. `GET /api/models` énumère celles qu'il connaît. Cela s'applique aux backends qui acceptent une langue (`accepts_language: true`). Parakeet détecte lui-même la langue et ignore la valeur, et il peut omettre sans le signaler la parole dont il n'est pas sûr : dans un enregistrement multilingue, il peut ne rien renvoyer pour la langue minoritaire.

`GET /api/models` indique ce que ce serveur embarque, afin qu'un client n'ait pas à le deviner. Chaque backend apporte sa propre liste de langues, car les ensembles divergent réellement et une liste fusionnée serait fausse pour chaque backend pris isolément.

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

`status` vaut `loaded` lorsqu'une instance attend dans un pool, `installed` lorsque les poids sont présents sur le disque mais que rien n'est encore chargé, et `absent` sinon. Un backend configuré mais non installé répond `absent` et rien de plus ; la raison part dans le journal. `accepts_language` indique si `?language=` a le moindre sens pour ce backend. Le diariseur signale des langues `null` plutôt qu'une liste vide, car il ne produit de texte dans aucune langue.

Le client en ligne de commande lit la même route :

```bash
python3 stt_client.py --list
```

`POST /api/diarize` répond à la question **qui a parlé et quand**, et à rien d'autre : il renvoie des plages temporelles assorties d'un numéro de locuteur, jamais du texte. Il est désactivé sauf si `DIARIZE_ENABLED` est défini sur une image construite avec `DIARIZE=true` ; sinon il répond `503`.

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

Deux remarques sur ces nombres. Les tours de parole peuvent se chevaucher, car chaque canal de locuteur est évalué indépendamment : deux personnes qui parlent en même temps produisent donc deux tours couvrant les mêmes secondes. Et les étiquettes sont des positions dans cet enregistrement précis, ordonnées selon qui a parlé en premier : ce ne sont pas des identités, et la même personne recevra un numéro différent à la requête suivante. Nommer un locuteur exigerait une étape d'enrôlement dont ce service ne dispose pas. Huit locuteurs au maximum sont distingués.

Deux backends de transcription sont disponibles. **Whisper** est celui par défaut et accepte un paramètre `language`. **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) couvre 25 langues européennes, détecte lui-même la langue et ne prend donc aucun argument `language`, ce que `GET /api/models` signale par `accepts_language: false`. Sélectionnez-le avec `STT_BACKEND=parakeet` sur une image construite avec `PARAKEET=true` ; c'est un choix fait au déploiement, et non requête par requête, car un second modèle résident signifierait un second jeu de poids dans chaque worker.

Aucun des deux backends ne gère la parole superposée. Le modèle de NVIDIA conçu pour la parole superposée n'est distribué que sous forme de checkpoint NeMo, et NeMo impose une version de PyTorch différente de celle de la construction CUDA de ce projet : il n'est donc pas installable ici.

`POST /api/transcript` répond à la question **qui a dit quoi** : il exécute la diarisation et la transcription sur le même audio et les joint par le temps. Il exige que la diarisation soit activée, sinon il répond `503`.

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

`turns` est la sortie brute du diariseur et `segments` est la jointure, tenus séparés afin qu'un client qui se méfie de l'attribution puisse tout de même voir ce que le diariseur a dit. `text` est la transcription simple, identique à ce que renvoie `/api/stt` pour le même fichier. Une phrase qu'aucun tour de parole ne couvre conserve `"speaker": null` plutôt que d'être attribuée au tour le plus proche.

`overlap` signale une phrase pendant laquelle quelqu'un d'autre parlait également. NVIDIA est explicite sur ce point : associer un modèle classique mono-locuteur à la diarisation n'équivaut pas à un modèle conçu pour la parole superposée. Une plage temporelle extraite contient toujours toutes les voix qui la chevauchent, de sorte que ces phrases peuvent fusionner ou retenir les mots du mauvais locuteur. Considérez un segment marqué `overlap` comme l'endroit où la transcription est la moins fiable.

`/api/stream` est un WebSocket de **transcription en direct** : l'audio entre au fur et à mesure de l'enregistrement, et chaque phrase revient environ une seconde après que le locuteur a marqué une pause. Les messages texte JSON portent le contrôle, les messages binaires portent l'audio :

1. Le client envoie `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`. Tous les champs sauf `type` sont optionnels. `token` est le moyen pour un navigateur de s'authentifier, puisqu'il ne peut pas définir d'en-têtes sur un WebSocket ; les autres clients peuvent envoyer à la place `Authorization: Bearer <token>` lors de la poignée de main.
2. Le serveur répond `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`.
3. Le client envoie du PCM brut - 16 bits signés little-endian, mono, 16 kHz - sous forme de messages binaires de taille quelconque, puis `{"type": "stop"}` lorsqu'il a terminé.
4. Le serveur envoie un `segment` pour chaque phrase, `progress` environ une fois par seconde, et `done` avant de fermer :

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

L'audio peut aussi venir d'ailleurs. Avec `"source": "url", "url": "https://..."` dans le message de démarrage, le client n'envoie aucun audio : le serveur lit le flux à cette adresse via ffmpeg, au rythme propre de la source, jusqu'à ce qu'il se termine ou que le client envoie `stop`. La radio sur Internet, HLS, RTMP, RTSP et SRT fonctionnent ; le schéma doit être `http`, `https`, `rtmp`, `rtmps`, `rtsp` ou `srt`, et ffmpeg est limité aux protocoles réseau, de sorte qu'une URL ou une playlist ne peut pas lui faire lire un fichier local. Cela amène tout de même le serveur à récupérer une adresse choisie par un client, y compris des adresses de son propre réseau : définissez `STT_TOKENS` sur tout serveur que d'autres peuvent atteindre.

Un échec se traduit par un unique `{"type": "error", "error": "<category>", "request_id": "..."}` suivi d'une fermeture, avec les catégories d'erreur HTTP plus `Invalid start message`, `Invalid audio frame`, `Invalid stream URL` et `Stream source failed`.

Une phrase se termine à une pause de 0,6 s, ou à son moment le plus calme dès qu'elle dépasse 15 s, et elle est transcrite seule avec un modèle emprunté au même pool que les envois, de sorte qu'un pool occupé retarde les phrases en direct au lieu de les faire échouer. Avec `diarize`, le diariseur fonctionne en mode streaming et conserve un cache de locuteurs d'un bloc à l'autre, si bien qu'un locuteur garde le même numéro pendant toute la session. Le socket n'existe que lorsque le serveur tourne sous uvicorn (`python3 stt_server.py`, le mode par défaut de Docker) : le serveur de débogage de Flask et les workers sync de gunicorn ne parlent pas WebSocket.

Les envois sont limités à `MAX_CONTENT_LENGTH_MB` (10 Mo par défaut) ; un corps plus grand renvoie `413`.

Les erreurs sont uniformes : `error` porte une catégorie générique et `request_id` met en corrélation la réponse avec le journal du serveur, où l'exception complète est enregistrée.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Lorsque `STT_TOKENS` est défini, chaque route à l'exception de `GET /api/health` doit comporter `Authorization: Bearer <token>` ; l'état de santé reste ouvert afin que les contrôles de santé continuent de fonctionner.

### Client en ligne de commande

`stt_client.py` est un petit client pour travailler avec le serveur et le tester. Il lit l'adresse du serveur et le jeton depuis `STT_URL` et `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

`--stream` joue un fichier dans `/api/stream` au rythme de la parole et affiche chaque phrase dès son retour, avec `--speakers` pour l'attribution des locuteurs :

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
```

### Variables d'environnement

`.env` est chargé à la fois par le serveur et par le client via `python-dotenv`.

| Variable                | Défaut                  | Rôle                                                |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | adresse d'écoute du serveur                          |
| `STT_PORT`              | `5099`                  | port du serveur                                      |
| `STT_POOL_SIZE`         | `8`                     | nombre d'instances Whisper préchargées               |
| `STT_TOKENS`            | (vide)                  | jetons valides séparés par des virgules ; vide désactive l'authentification |
| `STT_DEBUG`             | `false`                 | mode debug de Flask                                  |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | taille maximale d'envoi en Mo ; un corps plus grand renvoie `413` |
| `CORS_ORIGINS`          | `*`                     | origines CORS autorisées : `*` ou une liste séparée par des virgules |
| `GUNICORN_WORKERS`      | `4`                     | processus de travail (gunicorn uniquement)           |
| `LOG_LEVEL`             | `INFO`                  | niveau de journalisation                             |
| `LOG_ACCESS`            | `false`                 | journaliser les lignes d'accès uvicorn               |
| `WHISPER_MODEL`         | `small.en`              | nom du modèle Whisper (par ex. `small.en`, `turbo`)  |
| `WHISPER_LANGUAGE`      | `en`                    | langue de transcription par défaut                   |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | répertoire de cache des modèles (`/opt/models` dans Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` ou `auto`                              |
| `STT_BACKEND`           | `whisper`               | backend de transcription : `whisper` ou `parakeet`   |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | identifiant du modèle Parakeet                       |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | répertoire de cache des modèles Parakeet             |
| `DIARIZE_ENABLED`       | `false`                 | active `POST /api/diarize` (nécessite une image `DIARIZE=true`) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | identifiant du modèle de diarisation                 |
| `DIARIZE_POOL_SIZE`     | `1`                     | nombre d'instances de diarisation préchargées        |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | répertoire de cache des modèles de diarisation       |
| `DIARIZE_THRESHOLD`     | `0.5`                   | probabilité d'activité d'un locuteur comptée comme parole |
| `STT_WWW_PORT`          | `8080`                  | port http de l'interface web (compose)              |
| `STT_WWW_TLS_PORT`      | `8443`                  | port https de l'interface web (compose)             |
| `STT_URL`               | `http://localhost:5099` | client : URL de base du serveur                      |
| `STT_TOKEN`             | (vide)                  | client : jeton bearer envoyé au serveur              |

### Structure du projet

```text
speech-to-text/
├── stt_server.py        # Assemblage de l'application Flask, routes, point d'entrée
├── stt_client.py        # Client CLI qui envoie des fichiers au serveur
├── gu.py                # Configuration et hooks Gunicorn
├── libs/
│   ├── config.py        # toutes les variables d'environnement, lues une seule fois
│   ├── logs.py          # format de log partagé par l'application, uvicorn et les CLI
│   ├── errors.py        # réponses d'erreur JSON uniformes et handlers Flask
│   ├── auth.py          # authentification optionnelle par jeton statique
│   ├── audio.py         # conversion de l'envoi en WAV mono 16 kHz
│   ├── model_pool.py    # pools d'instances Whisper et de diarisation préchargées
│   ├── catalog.py       # ce que le serveur sait faire, pour GET /api/models
│   ├── align.py         # joint les segments de transcription aux tours de parole
│   ├── live.py          # le WebSocket /api/stream : protocole et sessions
│   ├── stream.py        # cœur de la transcription en direct : pauses, phrases, transcription par phrase
│   ├── stt.py           # wrapper Whisper
│   ├── parakeet.py      # wrapper NVIDIA Parakeet, le second transcripteur
│   ├── backends.py      # quel module transcrit, selon STT_BACKEND
│   └── diarize.py       # diarisation des locuteurs (qui a parlé et quand, sans texte)
├── Dockerfile           # Construction GPU (CUDA 13.0)
├── Dockerfile-cpu       # Construction CPU
├── Dockerfile-www       # Image de l'interface web (nginx)
├── nginx/               # Configuration de stt_www : interface statique, proxy /api/, TLS auto-signé
├── www/                 # Interface web : Vue 2 sans étape de build, bibliothèques embarquées
├── docs/                # Traductions du README
└── tests/               # Tests pytest, sans téléchargement de modèle ni GPU
```

### Développement

Les paquets système `ffmpeg` et `libsndfile1` doivent être présents. Installez les dépendances d'exécution et de développement :

```bash
pip install -e ".[dev]"
pre-commit install
```

Le Makefile enveloppe les tâches courantes :

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
make typecheck      # mypy
```

La suite de tests simule le backend Whisper, elle couvre donc la couche HTTP (request_id, catégories d'erreurs, sémantique du pool de modèles) et s'exécute en quelques secondes sans télécharger de modèle ni nécessiter de GPU.

### Licence

[MIT](../LICENSE)
