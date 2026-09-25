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
* **リアルタイム文字起こし。** WebSocket で音声をストリーミングすると、話すそばからフレーズごとに結果が返ってきます。ダイアライゼーションが有効なら、各フレーズに話者も割り当てられます。
* **Web UI 同梱。** ブラウザでファイルをアップロードして、テキストや誰が何を話したかを読めます。配信するのは、サーバーの隣で動く専用の nginx コンテナです。

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

#### 複数のモデル

`STT_MODELS` は起動時に複数の文字起こしモデルを読み込み、それぞれに専用のプールを持たせ、各リクエストが `model` でその中から 1 つを選べるようにします。エントリはカンマ区切りの `backend:model[@pool]` 形式です。

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # `model` のないリクエストが使うモデル。空の場合は最初のエントリ
```

選べるのは起動時に読み込まれたモデルだけです。リクエストがダウンロードや読み込みを引き起こすことはなく、読み込まれていないモデルは `400` で拒否されます。リストの各モデルはサーバーが動いている間ずっとメモリを使い、その量はおおよそ `ワーカー数 x (プール x モデルサイズ)` をリスト全体で合計したものに、ダイアライザーを加えたものです。GPU 上の `turbo@2,small@1,parakeet@1` はプロセスあたり約 12 + 2 + 3 = 17 GB です。gunicorn では各 sync ワーカーが一度に 1 つのリクエストしか処理しないため、各エントリは `@1` にして `GUNICORN_WORKERS` でスケールしてください。`@pool` のないエントリは `STT_POOL_SIZE` を使い、Docker の外ではこれが 8 なので、`@N` を明示してください。大きなモデルを複数読み込むと 1 つより時間がかかるため、起動中にコンテナが unhealthy と判定される場合は compose ファイルの healthcheck の `start_period` を延ばしてください。

`STT_MODELS` が空なら、これまでどおり `STT_BACKEND`、`WHISPER_MODEL`、`PARAKEET_MODEL` が単一のモデルを選び、サーバーは以前とまったく同じものを読み込みます。レスポンスにはフィールドが増えるだけです。設定されている場合、これらの変数は何を読み込むかを決めなくなります。Docker では `STT_MODELS` と `STT_DEFAULT_MODEL` を `.env` に書いてください。compose の `environment:` ブロックに書くと `.env` を上書きしてしまいます。Parakeet のエントリには引き続き `PARAKEET=true` でビルドしたイメージが必要です。未知のバックエンド、同じ重みの二重指定（`turbo` と `large-v3-turbo`）、リストにない `STT_DEFAULT_MODEL` があると、サーバーは起動を拒否します。ファイルパスで指定したモデルは `.pt` を除いたファイル名で公開されるため、パスがクライアントに届くことはありません。 `STT_DEFAULT_MODEL` では、このようなエントリをその名前でも、`STT_MODELS` に書かれたとおりのパスでも指定できます。その言語はファイル名が示すチェックポイントのものになり、`/models/large-v3.pt` は `large-v3` と同じ言語を扱います。同じ名前で提供されることになる 2 つのエントリ (`/a/model.pt` と `/b/model.pt`) や、バックエンド名で提供されることになるエントリ (`/models/parakeet.pt`) があると、サーバーは起動時に停止します。

### クイックスタート（Docker）

サーバーを動かす最も簡単な方法は Docker です。モデルファイルはホストの `./models` にキャッシュされるため、コンテナを再ビルドしても残ります。

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU ビルドにはホスト上に `nvidia-container-toolkit` が必要です。初回実行時に Whisper モデルが `./models` にダウンロードされます。

### Web UI

`docker compose up` は `stt_www` も起動します。これはブラウザ UI を配信し、`/api/` をサーバーへ中継する nginx コンテナなので、UI と API は同じアドレスを共有します。

| リスナー | デフォルトポート | 設定する変数       |
| -------- | ---------------- | ------------------ |
| http     | `8080`           | `STT_WWW_PORT`     |
| https    | `8443`           | `STT_WWW_TLS_PORT` |

`http://<host>:8080` を開きます。**TRANSCRIBE** には 2 つのソースがあります。**FILE** は音声ファイルをアップロードします。**DEVICE** は音声入力からリアルタイムで文字起こしします。入力には、マイクやヘッドセット、スピーカーやヘッドホンで再生されるものをすべて運ぶ Linux の `Monitor of ...` ソース、あるいはブラウザのタブで再生されるもの（OS が許す場合はシステム全体）を対象とする `Tab or screen audio` を使えます。どちらの場合も、結果はフォームの下にプレーンテキストとして表示されます。ダイアライゼーションが有効なら、フレーズごとに話者と時刻を付けたブロックとして表示され、話者ごとに色が分かれ、2 人が同時に話したフレーズには印が付きます。リアルタイムのフレーズは、話者が言葉を切ってから約 1 秒後に表示されます。結果はコピーすることも、TXT または JSON としてダウンロードすることもできます。複数のモデルを読み込んでいる場合（`STT_MODELS`）、モードと言語の横にあるモデル選択で、どちらのソースでも使うモデルを選べます。選択肢は `GET /api/models` から取得され、言語の一覧は選んだモデルに従います。**MODELS** は `GET /api/models` が報告する内容を表示します。`STT_TOKENS` が設定されている場合、UI は一度だけトークンを尋ね、ブラウザに保存します。

ブラウザは安全なページにしか音声デバイスを渡さないため、ネットワーク越しでは DEVICE は https リスナー経由で動作します（`http://localhost` でも動作します）。https リスナーは、コンテナが初回起動時に `./data/certs` に作成する自己署名証明書を使います。置き換えるには、本物の `stt.crt` と `stt.key` をそこに置いてください。UI にはビルド工程も CDN もありません。Vue 2 とそのライブラリは `www/vendor` に同梱されているため、インターネットに接続できないマシンでも動作します。

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

`GET /api/health` はプールのステータスを返します。最上位の `pool_size` と `available` はデフォルトモデル、つまり `model` のないリクエストが待つモデルを表し、`available` が 0 になった場合はそのインスタンスがすべて処理中であることを意味します。`models` は読み込まれた各モデルを id ごとに報告します。

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

`STT_TOKENS` が設定されている場合、`default_model` と `models` は有効なトークンを持つリクエストへの応答にのみ含まれます。`GET /api/models` と同様に、これらはサーバーの構成を示すからです。トークンのないヘルスチェックも引き続き `status`、`pool_size`、`available`、`diarize` を受け取ります。

`POST /api/stt` は `file` という名前の `multipart/form-data` フィールド、または生の `audio/*` ボディを受け付けます。任意の `model`（クエリ文字列またはフォームフィールド）で、読み込まれたモデルの 1 つを選べます。指定できるのは id、エイリアス（`large-v3-turbo`、`parakeet-tdt-0.6b-v3`）、`backend:model` 形式、またはバックエンド名だけで、バックエンド名はデフォルトモデルがそのバックエンドに属していればデフォルトモデルを、そうでなければそのバックエンドの最初のモデルを意味します。`model` がなければデフォルトモデルが応答します。任意の `language`（クエリ文字列またはフォームフィールド）は、そのリクエストに限りサーバーのデフォルトを上書きし、`auto` で自動検出します。成功するとテキスト、経過秒数、文字起こししたモデル、言語を返します。言語は Whisper が検出または使用したコード（英語専用モデルでは常に `en`）で、Parakeet は言語を報告しないため `null` です。

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

言語はコード（`ru`）でも英語名（`russian`）でも指定できます。モデルが知らない値は、文字起こしの途中で失敗させるのではなく `400` で拒否されます。各モデルが何を知っているかは `GET /api/models` が一覧にします。`language` をどれだけ厳密に確認するかは、モデルと、リクエストがモデルを指定したかどうかで決まります。

| モデル | 受け付ける `language` | `model` なしのリクエスト | `model` ありのリクエスト |
| --- | --- | --- | --- |
| 多言語 Whisper | リストにあるコードまたは英語名 | リスト外は `400 Unsupported language` | 同じ |
| 英語専用 Whisper（`.en`） | `en` と `auto` | ほかの既知のコードは英語として文字起こし | `400 Unsupported language` |
| Parakeet | なし（言語を自分で検出） | どの値も受け付けて無視 | リストにあるコード、それ以外は `400` |

Parakeet が受け付けるのはコードだけで、英語名は受け付けません。また、確信の持てない発話を知らせずに落とすことがあり、複数言語が混ざった録音では少数派の言語について何も返さない場合があります。

既知のチェックポイント名のどれにも一致しない Whisper のファイルパス（たとえば `/models/my-large-v3-finetune.pt` に置いたファインチューン）は、言語リストがその名前から推測されたものにすぎません。そのため `model` を指定しないリクエストは、これまでどおり既知のコードをそのまま渡します。モデルを指定したリクエストは、引き続き推測されたリストで検査されます。

この 2 つのオプションの `400` エラーは、`Invalid model`（どのバックエンドもその名前を知らない）、`Model not loaded`（実在するがこのサーバーが読み込んでいないモデル）、`Invalid language`（そもそも言語ではない）、`Unsupported language`（実在するが選んだモデルが受け付けない言語）です。4 つとも音声のデコード前に返されます。

`GET /api/models` はこのサーバーが備えているものを報告するため、クライアントは推測する必要がありません。読み込まれた各モデルが独自の行を持ち、何も読み込まれていない文字起こしバックエンド（`selectable: false`）とダイアライザーも同様です。各行はそれぞれの言語リストを持ちます。集合は実際に異なるため、統合したリストはどのモデルにとっても不正確になるからです。

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

`id` はリクエストが `model` として渡す値で、`default: true` を持つ行はちょうど 1 つです。その id が `default_model`、そのバックエンドが最上位の `default` です。`pool_size` と `available` はそのモデルのプールを表します。`status` は、モデルのインスタンスが空きでも処理中でも存在すれば `loaded`、重みはディスクにあるがまだ何も読み込まれていなければ `installed`、それ以外は `absent` です。設定済みだがインストールされていないバックエンドは `absent` とだけ返し、理由はログに出力されます。`accepts_language` は、そのバックエンドにとって `?language=` に意味があるかどうかを示します。ダイアライザーはどの言語のテキストも生成しないため、空のリストではなく `null` の言語を返します。

CLI クライアントは同じエンドポイントを読み取ります。

```bash
python3 stt_client.py --list
```

`POST /api/diarize` は **誰がいつ話したか** だけに答え、それ以外は返しません。話者番号付きの時間範囲を返すだけで、テキストは決して返しません。`DIARIZE=true` でビルドしたイメージ上で `DIARIZE_ENABLED` を設定しない限り無効で、その場合は `503` を返します。

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

これらの数値について 2 点あります。話者チャンネルごとに個別にスコアリングされるため、発話区間は重なることがあります。2 人が同時に話せば、同じ秒数を覆う 2 つの区間が生成されます。もう 1 点、ラベルはこの録音 1 件の中での位置であり、最初に話した順に並びます。話者の同一性を表すものではなく、同じ人物でも次のリクエストでは別の番号になります。話者に名前を付けるには登録（エンロールメント）の工程が必要ですが、このサービスにはありません。区別できる話者は最大 8 人です。

文字起こしのバックエンドは 2 つあります。**Whisper** がデフォルトで、`language` を受け付けます。**Parakeet**（`nvidia/parakeet-tdt-0.6b-v3`）は 25 のヨーロッパ言語に対応し、言語を自分で検出するため `language` 引数をまったく受け付けません。`GET /api/models` はこれを `accepts_language: false` として報告します。`PARAKEET=true` でビルドしたイメージが必要です。サーバー全体で使うなら `STT_BACKEND=parakeet` を指定し、Whisper と並べて使うなら `STT_MODELS` で読み込んでリクエストごとに `model` で選びます。リクエストが選べるのは起動時に読み込まれたモデルだけで、読み込まれた各モデルはすべてのワーカーで重みを保持するため、メモリはワーカー数にプールの合計を掛けたものになります。

どちらのバックエンドも重なり合う発話には対応していません。NVIDIA の重なり対応モデルは NeMo のチェックポイントとしてのみ提供されており、NeMo はこのプロジェクトの CUDA ビルドとは異なる PyTorch に固定されているため、ここではインストールすることができません。

`POST /api/transcript` は **誰が何を話したか** に答えます。同じ音声に対してダイアライゼーションと文字起こしを実行し、時間で突き合わせます。ダイアライゼーションが有効になっている必要があり、そうでなければ `503` を返します。`/api/stt` と同じ `model` と `language` を受け付け、文字起こししたモデルを `model` で返します。

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

`turns` はダイアライザーの生の出力で、`segments` は突き合わせた結果です。両者を分けてあるのは、話者の割り当てを信用しない呼び出し側でも、ダイアライザーが何を出力したのかを確認できるようにするためです。`text` は素の文字起こしで、同じファイルに対して `/api/stt` が返すものと同一です。どの発話区間にも覆われないフレーズは、最も近い話者に押し付けられるのではなく `"speaker": null` のままになります。

`overlap` は、そのフレーズの最中に別の人も話していたことを示します。NVIDIA は、従来の単一話者モデルをダイアライゼーションと組み合わせても、重なり合う発話のために作られたモデルと同等にはならないと明言しています。切り出した時間範囲には、そこに重なるすべての声が依然として含まれているため、そうしたフレーズは混ざり合ったり、別の話者の言葉を拾ってしまったりすることがあります。`overlap` が付いたセグメントは、文字起こしが最も信用できない箇所として扱ってください。

`/api/stream` は**リアルタイム文字起こし**のための WebSocket です。音声は録音されるそばから送られ、各フレーズは話者が言葉を切ってから約 1 秒後に返ってきます。JSON のテキストメッセージが制御を、バイナリメッセージが音声を運びます。

1. クライアントは `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}` を送ります。`type` 以外のフィールドはすべて省略可能です。`model` は `/api/stt` の `model` と同じように読み込み済みのモデルを 1 つ選び、言語はそのモデルに対して検証されます。省略するとデフォルトのモデルが使われ、言語はこれまでどおり言語であるかどうかだけが検査されます。そのため、デフォルトのモデルが知らないコードは、フレーズを文字起こしする時点で失敗します。`token` はブラウザが認証するための手段です。ブラウザは WebSocket にヘッダーを設定できないためです。それ以外のクライアントは、代わりにハンドシェイク時に `Authorization: Bearer <token>` を送っても構いません。
2. サーバーは `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}` と応答します。
3. クライアントは生の PCM（符号付き 16 ビット、リトルエンディアン、モノラル、16 kHz）を任意のサイズのバイナリメッセージとして送り、終わったら `{"type": "stop"}` を送ります。
4. サーバーはフレーズごとに `segment` を、約 1 秒ごとに `progress` を送り、閉じる前に `done` を送ります。

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

音声は別の場所から取ることもできます。開始メッセージに `"source": "url", "url": "https://..."` を含めると、クライアントは音声をまったく送りません。サーバーがそのアドレスのストリームを ffmpeg でソース自身のペースで読み込み、ストリームが終わるかクライアントが `stop` を送るまで続けます。インターネットラジオ、HLS、RTMP、RTSP、SRT が使えます。スキームは `http`、`https`、`rtmp`、`rtmps`、`rtsp`、`srt` のいずれかである必要があり、ffmpeg はネットワークプロトコルだけに制限されているため、URL やプレイリストを使ってローカルファイルを読ませることはできません。それでも、クライアントが選んだアドレス（サーバー自身のネットワーク上のアドレスも含む）をサーバーに取得させることに変わりはありません。他者が到達できるサーバーでは必ず `STT_TOKENS` を設定してください。

失敗は 1 つの `{"type": "error", "error": "<category>", "request_id": "..."}` として届き、その後に接続が閉じられます。カテゴリは HTTP のエラーカテゴリに加えて、`Invalid start message`、`Invalid audio frame`、`Invalid stream URL`、`Stream source failed` があります。

フレーズは 0.6 秒のポーズで区切られるか、15 秒を超えた場合は最も静かな箇所で区切られます。各フレーズはアップロードと同じプールから借りたモデルで個別に文字起こしされるため、プールが混んでいてもリアルタイムのフレーズは失敗せず、遅れるだけです。`diarize` を指定すると、ダイアライザーはストリーミングモードで動作し、チャンクからチャンクへ話者キャッシュを引き継ぐため、セッション全体を通じて同じ話者は同じ番号を保ちます。このソケットは、サーバーが uvicorn で動いている場合（`python3 stt_server.py`、Docker のデフォルト）にのみ存在します。Flask のデバッグサーバーと gunicorn の sync ワーカーは WebSocket を扱えません。

アップロードは `MAX_CONTENT_LENGTH_MB`（デフォルトで 10 MB）に制限されており、それより大きいボディは `413` を返します。

エラーは統一されています。`error` は一般的なカテゴリを伝え、`request_id` はレスポンスとサーバーログを関連付けます。完全な例外はサーバーログに記録されます。

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

`STT_TOKENS` が設定されている場合、`GET /api/health` を除くすべてのルートは `Authorization: Bearer <token>` を伴う必要があります。`GET /api/health` は開いたままなので、ヘルスチェックは引き続き機能します。

### CLI クライアント

`stt_client.py` は、サーバーの操作とテストのための小さなクライアントです。サーバーアドレスとトークンを `STT_URL` と `STT_TOKEN` から読み取ります。

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` と `--language`（`--model=NAME` の形でも可）は指定したときだけ送信され、指定しなければサーバーのデフォルトが適用されます。各結果行には、サーバーが使ったモデルと言語が表示されます。`--list` はデフォルトモデルと、モデルごとに状態、リクエストで選べるかどうか、プール、言語を 1 行ずつ表示します。

`--stream` は 1 つのファイルを話す速さで `/api/stream` に流し込み、フレーズが返ってくるたびに表示します。`--speakers` を付けると話者も割り当てます。

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### 環境変数

`.env` は `python-dotenv` を通じてサーバーとクライアントの両方で読み込まれます。

| 変数                     | デフォルト               | 用途                                                |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | サーバーのバインドアドレス                            |
| `STT_PORT`              | `5099`                  | サーバーのポート                                     |
| `STT_POOL_SIZE`         | `8`                     | モデルごとのインスタンス数。`@pool` のない `STT_MODELS` エントリのデフォルト |
| `STT_TOKENS`            | （空）                   | カンマ区切りの有効なトークン。空にすると認証を無効化     |
| `STT_DEBUG`             | `false`                 | Flask のデバッグモード                               |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | アップロードの最大サイズ（MB）。これを超えるボディは `413` を返す |
| `CORS_ORIGINS`          | `*`                     | 許可する CORS オリジン: `*` またはカンマ区切りのリスト   |
| `GUNICORN_WORKERS`      | `4`                     | ワーカープロセスの数（gunicorn のみ）                 |
| `LOG_LEVEL`             | `INFO`                  | ログレベル                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn のアクセスログを記録する                      |
| `WHISPER_MODEL`         | `small.en`              | Whisper モデル名（例: `small.en`、`turbo`）（`STT_MODELS` が空の場合） |
| `WHISPER_LANGUAGE`      | `en`                    | すべての Whisper モデルのデフォルト言語 |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | モデルキャッシュのディレクトリ（Docker では `/opt/models`） |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`、`cuda`、または `auto`                         |
| `STT_BACKEND`           | `whisper`               | 文字起こしのバックエンド: `whisper` または `parakeet`（`STT_MODELS` が空の場合） |
| `STT_MODELS`            | （空）                     | 複数モデルの同時利用: カンマ区切りの `backend:model[@pool]` |
| `STT_DEFAULT_MODEL`     | （空）                     | `model` のないリクエストのモデル。空なら `STT_MODELS` の最初のエントリ |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet のモデル ID                                  |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet モデルのキャッシュディレクトリ               |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` を有効化（`DIARIZE=true` イメージが必要） |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | 話者ダイアライゼーションのモデル ID                   |
| `DIARIZE_POOL_SIZE`     | `1`                     | 事前に読み込むダイアライザーインスタンスの数          |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | ダイアライゼーションモデルのキャッシュディレクトリ    |
| `DIARIZE_THRESHOLD`     | `0.5`                   | 発話とみなす話者アクティビティの確率                  |
| `STT_WWW_PORT`          | `8080`                  | Web UI の http ポート（compose）                    |
| `STT_WWW_TLS_PORT`      | `8443`                  | Web UI の https ポート（compose）                   |
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

### 開発

システムパッケージ `ffmpeg` と `libsndfile1` が存在している必要があります。ランタイムと開発用の依存関係をインストールします。

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

テストスイートは Whisper バックエンドをスタブ化するため、HTTP レイヤー（request_id、エラーカテゴリ、モデルプールのセマンティクス）をカバーし、モデルをダウンロードしたり GPU を必要としたりせず、数秒で実行されます。

### ライセンス

[MIT](../LICENSE)
