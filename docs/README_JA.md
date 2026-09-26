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

`http://<host>:8080` を開きます。**TRANSCRIBE** には 3 つのソースがあります。**FILE** は音声ファイルをアップロードします。**DEVICE** は音声入力からリアルタイムで文字起こしします。入力には、マイクやヘッドセット、スピーカーやヘッドホンで再生されるものをすべて運ぶ Linux の `Monitor of ...` ソース、あるいは Chromium 系ブラウザでは、ブラウザのタブで再生されるもの（OS が許す場合はシステム全体）を対象とする `Tab or screen audio` を使えます。**STREAM** はストリームまたはリモートファイルのアドレス（インターネットラジオ、HLS、RTMP、RTSP、SRT）を受け取り、サーバー自身がそれを読み込みます。いずれの場合も、結果はフォームの下にプレーンテキストとして表示されます。ダイアライゼーションが有効なら、フレーズごとに話者と時刻を付けたブロックとして表示され、話者ごとに色が分かれ、2 人が同時に話したフレーズには印が付きます。リアルタイムのフレーズは、話者が言葉を切ってから約 1 秒後に表示されます。結果はコピーすることも、TXT または JSON としてダウンロードすることもできます。**MODELS** は `GET /api/models` が報告する内容を表示します。`STT_TOKENS` が設定されている場合、UI は一度だけトークンを尋ね、ブラウザに保存します。

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

`GET /api/health` はプールのステータスを返します。`available` が 0 になった場合は、すべてのモデルが現在使用中であることを意味します。

```json
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`POST /api/stt` は `file` という名前の `multipart/form-data` フィールド、または生の `audio/*` ボディを受け付けます。オプションの `language`（クエリ文字列またはフォームフィールド）は、そのリクエストに限ってサーバーのデフォルトを上書きします。`auto` は自動検出します。成功すると、テキストと経過秒数を返します。

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

言語はコード（`ru`）でも英語名（`russian`）でも指定できます。モデルが知らない値は、文字起こしの途中で失敗するのではなく `400` で拒否されます。`GET /api/models` が認識できる言語を列挙します。 これは言語を受け付けるバックエンド（`accepts_language: true`）にのみ当てはまります。Parakeet は言語を自動で判定して値を無視し、確信の持てない音声を何も知らせずに落とすことがあります。複数言語の録音では、少数派の言語について何も返さないことがあります。

`GET /api/models` はこのサーバーが備えているものを報告するため、クライアントが推測する必要はありません。バックエンドごとに独自の言語リストを返します。対応する言語の集合は実際に食い違っており、統合したリストではどのバックエンドにとっても正しくないからです。

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

`status` は、インスタンスがプールで待機している場合は `loaded`、重みがディスク上にあるもののまだ何も読み込まれていない場合は `installed`、それ以外は `absent` になります。設定されているがインストールされていないバックエンドは `absent` とだけ伝え、理由はログに記録されます。`accepts_language` は、そのバックエンドにとって `?language=` に意味があるかどうかを示します。ダイアライザーはどの言語のテキストも生成しないため、言語は空のリストではなく `null` を報告します。

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

文字起こしのバックエンドは 2 つあります。**Whisper** がデフォルトで、`language` を受け付けます。**Parakeet**（`nvidia/parakeet-tdt-0.6b-v3`）はヨーロッパの 25 言語に対応し、言語を自分で検出するため `language` 引数をまったく取りません。これは `GET /api/models` が `accepts_language: false` として報告します。`PARAKEET=true` でビルドしたイメージ上で `STT_BACKEND=parakeet` を指定して選択します。これはデプロイ時の選択であり、リクエストごとの選択ではありません。常駐モデルがもう 1 つ増えれば、すべてのワーカーで重みがもう一式必要になるからです。

どちらのバックエンドも重なり合う発話には対応していません。NVIDIA の重なり対応モデルは NeMo のチェックポイントとしてのみ提供されており、NeMo はこのプロジェクトの CUDA ビルドとは異なる PyTorch に固定されているため、ここではインストールすることができません。

`POST /api/transcript` は **誰が何を話したか** に答えます。同じ音声に対してダイアライゼーションと文字起こしを実行し、時間で突き合わせます。ダイアライゼーションが有効になっている必要があり、そうでなければ `503` を返します。

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

`turns` はダイアライザーの生の出力で、`segments` は突き合わせた結果です。両者を分けてあるのは、話者の割り当てを信用しない呼び出し側でも、ダイアライザーが何を出力したのかを確認できるようにするためです。`text` は素の文字起こしで、同じファイルに対して `/api/stt` が返すものと同一です。どの発話区間にも覆われないフレーズは、最も近い話者に押し付けられるのではなく `"speaker": null` のままになります。

`overlap` は、そのフレーズの最中に別の人も話していたことを示します。NVIDIA は、従来の単一話者モデルをダイアライゼーションと組み合わせても、重なり合う発話のために作られたモデルと同等にはならないと明言しています。切り出した時間範囲には、そこに重なるすべての声が依然として含まれているため、そうしたフレーズは混ざり合ったり、別の話者の言葉を拾ってしまったりすることがあります。`overlap` が付いたセグメントは、文字起こしが最も信用できない箇所として扱ってください。

`/api/stream` は**リアルタイム文字起こし**のための WebSocket です。音声は録音されるそばから送られ、各フレーズは話者が言葉を切ってから約 1 秒後に返ってきます。JSON のテキストメッセージが制御を、バイナリメッセージが音声を運びます。

1. クライアントは `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}` を送ります。`type` 以外のフィールドはすべて省略可能です。`token` はブラウザが認証するための手段です。ブラウザは WebSocket にヘッダーを設定できないためです。それ以外のクライアントは、代わりにハンドシェイク時に `Authorization: Bearer <token>` を送っても構いません。
2. サーバーは `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}` と応答します。
3. クライアントは生の PCM（符号付き 16 ビット、リトルエンディアン、モノラル、16 kHz）を任意のサイズのバイナリメッセージとして送り、終わったら `{"type": "stop"}` を送ります。
4. サーバーはフレーズごとに `segment` を、約 1 秒ごとに `progress` を送り、閉じる前に `done` を送ります。

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

音声は別の場所から取ることもできます。開始メッセージに `"source": "url", "url": "https://..."` を含めると、クライアントは音声をまったく送りません。サーバーがそのアドレスのストリームを ffmpeg で読み込み、ストリームが終わるかクライアントが `stop` を送るまで続けます。インターネットラジオ、HLS、RTMP、RTSP、SRT が使えます。スキームは `http`、`https`、`rtmp`、`rtmps`、`rtsp`、`srt` のいずれかである必要があります。ライブソースにすでに溜まっている分は一度に取り込み、残りはソース自身のペースで読み込むため、リモートファイルも放送と同じように届きます。

これはクライアントが選んだアドレスをサーバーに取得させる仕組みなので、制限が設けられています。ffmpeg はネットワークプロトコルしか使えないため、URL でもプレイリストでもローカルファイルを読ませることはできず、接続を待ち受けさせることも一切できません。SRT の `listener` モードと `rendezvous` モード、および `listen` パラメーターはすべて拒否されます。別のサイトのページからは開始できません（`Forbidden`）。ブラウザは WebSocket に CORS を適用しないため、ソケット側でページのオリジンがこのホストであるか、`CORS_ORIGINS` に列挙されているかを確認します。同時に動かせる URL ソースは最大 4 つで（それを超えると `Service Unavailable`）、ログには各アドレスが認証情報とクエリを除いた形で記録されます。サーバー自身のネットワーク上のホストには引き続き到達できます。カメラを使う場合はまさにそれが目的であり、他者が到達できるサーバーで `STT_TOKENS` を設定すべき理由でもあります。

失敗は 1 つの `{"type": "error", "error": "<category>", "request_id": "..."}` として届き、その後に接続が閉じられます。カテゴリは HTTP のエラーカテゴリに加えて、`Invalid start message`、`Invalid audio frame`、`Invalid stream URL`、`Stream source failed`、`Forbidden` があります。

フレーズは 0.6 秒のポーズで区切られるか、ダイアライザーがある話者から別の話者への交代を聞き取った箇所で区切られるか（`diarize` 指定時。互いに応答し合う人どうしの間は 0.6 秒に満たないことが多いため）、15 秒を超えた場合は最も静かな箇所で区切られます。各フレーズはアップロードと同じプールから借りたモデルで個別に文字起こしされるため、プールが混んでいてもリアルタイムのフレーズは失敗せず、遅れるだけです。`diarize` を指定すると、ダイアライザーはストリーミングモードで動作し、チャンクからチャンクへ話者キャッシュを引き継ぐため、セッション全体を通じて同じ話者は同じ番号を保ちます。このソケットは、サーバーが uvicorn で動いている場合（`python3 stt_server.py`、Docker のデフォルト）にのみ存在します。Flask のデバッグサーバーと gunicorn の sync ワーカーは WebSocket を扱えません。

**返されるのは実際に話されたテキストだけです。** 発話がない箇所（トーン、音楽、ノイズ、呼び出し音、さらにはデジタル無音）では、Whisper は学習元となった字幕付き動画のクレジットで答えてしまいます（ロシア語の "字幕制作: DimaTorzok" というクレジット、"つづく..."、"ご視聴ありがとうございました。"）。しかも完全な自信を持ってそうします。テストコーパスでは、無音に対してさえ Whisper 自身の `no_speech_prob` は 0.00 でした。そのため、すべてのエンドポイントは音声に対して音声検出器 Silero VAD を実行し、検出された発話の外側に大部分がある文字起こしセグメントと、字幕クレジットの 1 行そのものであるセグメントを取り除きます。発話を含まない 9 件の録音からなるコーパスでは、これによりそうした行がすべて取り除かれ、発話を含む録音のフレーズは 1 つも失われませんでした。何も話されていない録音は、今では空のテキストになります。ライブストリームでは、発話が検出されなかったフレーズはモデルに送られることすらありません。検出器は CPU 上で動作し、音声 3 分あたり約 1 秒の処理時間が加わります。`SPEECH_GATE=false` で以前の動作に戻せます。

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
```

`--stream` は 1 つのファイルを話す速さで `/api/stream` に流し込み、フレーズが返ってくるたびに表示します。`--speakers` を付けると話者も割り当てます。

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `WHISPER_MODEL`         | `small.en`              | Whisper モデル名（例: `small.en`、`turbo`）          |
| `WHISPER_LANGUAGE`      | `en`                    | デフォルトの文字起こし言語                            |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | モデルキャッシュのディレクトリ（Docker では `/opt/models`） |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`、`cuda`、または `auto`                         |
| `STT_BACKEND`           | `whisper`               | 文字起こしのバックエンド: `whisper` または `parakeet` |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet のモデル ID                                  |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet モデルのキャッシュディレクトリ               |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` を有効化（`DIARIZE=true` イメージが必要） |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | 話者ダイアライゼーションのモデル ID                   |
| `DIARIZE_POOL_SIZE`     | `1`                     | 事前に読み込むダイアライザーインスタンスの数          |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | ダイアライゼーションモデルのキャッシュディレクトリ    |
| `DIARIZE_THRESHOLD`     | `0.5`                   | 発話とみなす話者アクティビティの確率                  |
| `SPEECH_GATE`           | `true`                  | 誰も話していない文字起こしテキストを除去（音声検出器） |
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
│   ├── model_pool.py    # pools of pre-loaded Whisper and diarizer instances
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── align.py         # joins transcription segments to speaker turns
│   ├── live.py          # the /api/stream websocket: protocol and sessions
│   ├── stream.py        # live transcription core: pauses, phrases, per-phrase transcription
│   ├── url_source.py    # URL sources for /api/stream: vetting the address, running ffmpeg
│   ├── speech_gate.py   # voice detector that drops text nobody spoke
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
