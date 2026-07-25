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
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` accepte un champ `multipart/form-data` nommé `file`, ou un corps brut `audio/*`. Un paramètre optionnel `language` (chaîne de requête ou champ de formulaire) remplace la valeur par défaut du serveur pour cette requête ; `auto` détecte automatiquement. En cas de succès, il renvoie le texte et les secondes écoulées :

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

Les envois sont limités à `MAX_CONTENT_LENGTH_MB` (10 Mo par défaut) ; un corps plus grand renvoie `413`.

Les erreurs sont uniformes : `error` porte une catégorie générique et `request_id` met en corrélation la réponse avec le journal du serveur, où l'exception complète est enregistrée.

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

Lorsque `STT_TOKENS` est défini, chaque `POST /api/stt` doit comporter `Authorization: Bearer <token>` ; `GET /api/health` reste ouvert afin que les contrôles de santé continuent de fonctionner.

### Client en ligne de commande

`stt_client.py` est un petit client pour travailler avec le serveur et le tester. Il lit l'adresse du serveur et le jeton depuis `STT_URL` et `STT_TOKEN`.

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
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
| `WHISPER_MODEL`         | `turbo`                 | nom du modèle Whisper (par ex. `small.en`, `turbo`)  |
| `WHISPER_LANGUAGE`      | `en`                    | langue de transcription par défaut                   |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | répertoire de cache des modèles (`/opt/models` dans Docker) |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda` ou `auto`                              |
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
│   ├── model_pool.py    # pool d'instances Whisper préchargées
│   └── stt.py           # wrapper Whisper
├── Dockerfile           # Construction GPU (CUDA 13.0)
├── Dockerfile-cpu       # Construction CPU
├── docs/                # Traductions du README
└── tests/               # Tests pytest, sans téléchargement de modèle ni GPU
```

### Développement

Les paquets système `ffmpeg` et `libsndfile1` doivent être présents. Installez les dépendances d'exécution et de développement :

```bash
pip install -r requirements-dev.txt
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
```

La suite de tests simule le backend Whisper, elle couvre donc la couche HTTP (request_id, catégories d'erreurs, sémantique du pool de modèles) et s'exécute en quelques secondes sans télécharger de modèle ni nécessiter de GPU.

### Licence

[MIT](../LICENSE)
