## speech-to-text: セルフホスト型 Whisper 文字起こしサーバー

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | **[日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md)** | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` は [openai-whisper](https://github.com/openai/whisper) を使って音声をテキストに変換し、自分で運用できる小さな HTTP サービスとしてラップしたものです。音声ファイルを送ると、文字起こし結果が返ってきます。外部 API もなく、分単位の課金もなく、音声があなたのマシンの外に出ることもありません。

このプロジェクトは、ローカルでの利用、バッチ文字起こし、ネットワーク上で自前の STT サーバーを動かす用途に適しています。

* **すぐに使える HTTP サーバー。** uvicorn で動作する Flask が起動時に Whisper を読み込み、ローカルネットワーク上の他のマシンからのリクエストに応答します。
* **並行処理でも安全。** サーバーは事前に読み込んだ Whisper インスタンスのプールを保持するため、モデルを再読み込みすることなく複数のリクエストを並列で文字起こしできます。
* **CPU でも GPU でも、同じコード。** バックエンドは環境変数と、どの Docker イメージをビルドするかによって選択されます。CUDA カードがあれば推論が高速になりますが、すべて CPU 上でも動作します。
* **CLI クライアント同梱。** `stt_client.py` はローカルファイルをサーバーに POST し、結果を表示します。

### モデル

Whisper にはいくつかのモデルサイズがあります。大きいモデルほど精度が高く処理が遅く、小さいモデルは高速で軽量です。

| モデル      | パラメータ数 | VRAM    | 言語             | 適した用途                                       |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | 多言語           | 非力なハードウェアでの素早い下書き                  |
| `base`     | 74M        | ~1 GB   | 多言語           | 軽量な汎用デフォルト                              |
| `small`    | 244M       | ~2 GB   | 多言語           | 精度と速度の良いバランス                          |
| `medium`   | 769M       | ~5 GB   | 多言語           | メモリに余裕があるときの高精度                      |
| `turbo`    | 809M       | ~6 GB   | 多言語           | `large` に近い精度で、はるかに高速                 |
| `large`    | 1550M      | ~10 GB  | 多言語           | 最高品質、GPU が必要                             |

英語専用のバリアント（`tiny.en`、`base.en`、`small.en`、`medium.en`）は、英語音声でわずかに精度が高くなります。デフォルトは `turbo` で、GPU 上での英語処理に最適な万能の選択肢です。

### クイックスタート（Docker）

サーバーを動かす最も簡単な方法は Docker です。モデルファイルはホストの `./models` にキャッシュされるため、コンテナを再ビルドしても残ります。

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU ビルドにはホスト上に `nvidia-container-toolkit` が必要です。初回実行時に Whisper モデルが `./models` にダウンロードされます。

### HTTP API

サーバーが起動したら、ステータスを確認し、文字起こし用の音声ファイルを送信します。

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` はプールのステータスを返します。`available` が 0 になった場合は、すべてのモデルが現在使用中であることを意味します。

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` は `file` という名前の `multipart/form-data` フィールド、または生の `audio/*` ボディを受け付けます。オプションの `language`（クエリ文字列またはフォームフィールド）は、そのリクエストに限ってサーバーのデフォルトを上書きします。`auto` は自動検出します。成功すると、テキストと経過秒数を返します。

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

アップロードは `MAX_CONTENT_LENGTH_MB`（デフォルトで 10 MB）に制限されており、それより大きいボディは `413` を返します。

エラーは統一されています。`error` は一般的なカテゴリを伝え、`request_id` はレスポンスとサーバーログを関連付けます。完全な例外はサーバーログに記録されます。

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

`STT_TOKENS` が設定されている場合、すべての `POST /api/stt` は `Authorization: Bearer <token>` を伴う必要があります。`GET /api/health` は開いたままなので、ヘルスチェックは引き続き機能します。

### CLI クライアント

`stt_client.py` は、サーバーの操作とテストのための小さなクライアントです。サーバーアドレスとトークンを `STT_URL` と `STT_TOKEN` から読み取ります。

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### 環境変数

`.env` は `python-dotenv` を通じてサーバーとクライアントの両方で読み込まれます。

| 変数                     | デフォルト               | 用途                                                |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | サーバーのバインドアドレス                            |
| `STT_PORT`              | `5099`                  | サーバーのポート                                     |
| `STT_POOL_SIZE`         | `8`                     | 事前に読み込む Whisper インスタンスの数               |
| `STT_TOKENS`            | （空）                   | カンマ区切りの有効なトークン。空にすると認証を無効化     |
| `STT_DEBUG`             | `false`                 | Flask のデバッグモード                               |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | アップロードの最大サイズ（MB）。これを超えるボディは `413` を返す |
| `CORS_ORIGINS`          | `*`                     | 許可する CORS オリジン: `*` またはカンマ区切りのリスト   |
| `GUNICORN_WORKERS`      | `4`                     | ワーカープロセスの数（gunicorn のみ）                 |
| `LOG_LEVEL`             | `INFO`                  | ログレベル                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn のアクセスログを記録する                      |
| `WHISPER_MODEL`         | `turbo`                 | Whisper モデル名（例: `small.en`、`turbo`）          |
| `WHISPER_LANGUAGE`      | `en`                    | デフォルトの文字起こし言語                            |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | モデルキャッシュのディレクトリ（Docker では `/opt/models`） |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`、`cuda`、または `auto`                         |
| `STT_URL`               | `http://localhost:5099` | クライアント: サーバーのベース URL                    |
| `STT_TOKEN`             | （空）                   | クライアント: サーバーに送るベアラートークン           |

### プロジェクト構成

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

### 開発

システムパッケージ `ffmpeg` と `libsndfile1` が存在している必要があります。ランタイムと開発用の依存関係をインストールします。

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Makefile が共通のタスクをまとめています。

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

テストスイートは Whisper バックエンドをスタブ化するため、HTTP レイヤー（request_id、エラーカテゴリ、モデルプールのセマンティクス）をカバーし、モデルをダウンロードしたり GPU を必要としたりせず、数秒で実行されます。

### ライセンス

[MIT](../LICENSE)
