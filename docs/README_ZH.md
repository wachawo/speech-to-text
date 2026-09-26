## speech-to-text: 自托管的 Whisper 转录服务器

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | **[中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md)** | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | [हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md) | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` 使用 [openai-whisper](https://github.com/openai/whisper) 将音频转换为文本，并封装在一个由你自己运行的小型 HTTP 服务中。你发送一个音频文件，就能得到转录结果。没有外部 API，没有按分钟计费，你的音频也绝不会离开你的机器。

本项目适用于本地使用、批量转录，以及在网络上运行你自己的 STT 服务器。

* **开箱即用的 HTTP 服务器。** 由 uvicorn 提供服务的 Flask 在启动时加载 Whisper，并响应本地网络中其他机器的请求。
* **并发安全。** 服务器维护一个预加载的 Whisper 实例池，因此可以并行转录多个请求而无需重新加载模型。
* **CPU 或 GPU，代码相同。** 后端由环境以及你构建的 Docker 镜像决定。CUDA 显卡能加速推理，但一切也都能在 CPU 上运行。
* **附带命令行客户端。** `stt_client.py` 将本地文件提交到服务器并打印结果。
* **实时转录。** 通过 WebSocket 流式发送音频，边说边逐句取回转录结果；启用说话人分离时，每个语句都会归属到一个说话人。
* **附带 Web 界面。** 在浏览器中上传文件，即可阅读文本，或查看谁说了什么；界面由服务器旁边一个独立的 nginx 容器提供。

### 模型

Whisper 提供多种模型尺寸。更大的模型更准确但更慢；更小的模型快速且轻量。

| 模型       | 参数量     | 显存    | 语言            | 适用场景                                      |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | 多语言          | 弱硬件上的快速草稿                            |
| `base`     | 74M        | ~1 GB   | 多语言          | 轻量的通用默认选项                            |
| `small`    | 244M       | ~2 GB   | 多语言          | 准确度与速度的良好平衡                        |
| `medium`   | 769M       | ~5 GB   | 多语言          | 在内存允许时获得更高准确度                    |
| `turbo`    | 809M       | ~6 GB   | 多语言          | 接近 `large` 的准确度，速度快得多             |
| `large`    | 1550M      | ~10 GB  | 多语言          | 最佳质量，需要 GPU                            |

仅英语的变体（`tiny.en`、`base.en`、`small.en`、`medium.en`）在英语音频上略微更准确。默认值是 `turbo`，它是 GPU 上英语转录的最佳综合选择。

### 快速开始（Docker）

运行服务器最简单的方式是使用 Docker。模型文件缓存在主机的 `./models` 中，因此在容器重建后仍会保留。

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU 构建需要主机上安装 `nvidia-container-toolkit`。首次运行会将 Whisper 模型下载到 `./models`。在服务器上运行（更新、回滚、证书、依赖）的说明见 [docs/DEPLOY.md](DEPLOY.md)。

### Web 界面

`docker compose up` 还会启动 `stt_www`，这是一个 nginx 容器，负责提供浏览器界面并将 `/api/` 转发给服务器，因此界面和 API 共用同一个地址。

| 监听  | 默认端口 | 设置变量           |
| ----- | -------- | ------------------ |
| http  | `8080`   | `STT_WWW_PORT`     |
| https | `8443`   | `STT_WWW_TLS_PORT` |

打开 `http://<host>:8080`。**TRANSCRIBE** 有三种来源。**FILE** 上传一个音频文件。**DEVICE** 从音频输入实时转录：可以是麦克风或耳麦；Linux 上的 `Monitor of ...` 音源，它承载通过扬声器或耳机播放的一切声音；或者在 Chromium 系浏览器中使用 `Tab or screen audio`，用于浏览器标签页中播放的声音，在操作系统允许的情况下也可以是整个系统的声音。**STREAM** 接受一个流或远程文件的地址（网络电台、HLS、RTMP、RTSP、SRT），由服务器自行读取。无论哪种方式，结果都会显示在表单下方：要么是纯文本，要么在启用说话人分离时按语句分块显示，每块带有说话人和时间，每个说话人使用各自的颜色，两人同时说话的语句会被标记出来；实时语句会在说话人停顿约一秒后出现。结果可以复制，也可以下载为 TXT 或 JSON；在你查看其他页面时，每种来源都会保留其最近一次的结果。FILE 还有一个 **Turns** 模式，即单独调用 `POST /api/diarize`：以时间线的形式画出谁在什么时候说话，每个说话人一条轨道，并标出两人同时说话的片段。**MODELS** 显示 `GET /api/models` 报告的内容。设置了 `STT_TOKENS` 时，界面只会询问一次令牌，并将其保存在浏览器中。

浏览器只会把音频设备交给安全页面，因此通过网络访问时，DEVICE 需要经由 https 监听端口使用（在 `http://localhost` 上也可以）。https 监听端口使用自签名证书，由容器在首次启动时创建于 `./data/certs`；把真正的 `stt.crt` 和 `stt.key` 放到那里即可替换它。界面没有构建步骤，也不依赖 CDN：Vue 2 及其依赖库已随项目放在 `www/vendor` 下，因此在无法访问互联网的机器上也能工作。

### HTTP API

服务器启动后，检查其状态并发送音频文件进行转录。

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` 返回池状态。`available` 降为 0 意味着每个模型当前都在使用中：

```json
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`POST /api/stt` 接受名为 `file` 的 `multipart/form-data` 字段，或一个原始的 `audio/*` 请求体。可选的 `language`（查询字符串或表单字段）会针对该请求覆盖服务器默认值；`auto` 表示自动检测。成功时返回文本和耗费的秒数：

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

语言可以用代码（`ru`）或其英文名称（`russian`）给出；模型不认识的值会以 `400` 拒绝，而不是在转写中途失败。`GET /api/models` 会列出它认识的语言。 这仅适用于接受语言参数的后端（`accepts_language: true`）。Parakeet 会自行检测语言并忽略该值，而且可能在不作任何提示的情况下丢弃它不确定的语音：在多语言录音中，它可能对少数语言完全不返回任何内容。

`GET /api/models` 会报告本服务器所具备的能力，因此客户端无需猜测。每个后端都带有自己的语言列表，因为这些集合确实存在差异，而一个合并后的列表对任何单独的后端来说都是错误的。

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

当有实例在池中等待时，`status` 为 `loaded`；当权重已在磁盘上但尚未加载任何实例时为 `installed`；其余情况为 `absent`。已配置但未安装的后端只会返回 `absent`，不作其他说明；原因记录在日志中。`accepts_language` 说明 `?language=` 对该后端是否有任何意义。说话人分离器报告的 `languages` 为 `null` 而非空列表，因为它不产生任何语言的文本。

命令行客户端读取的是同一个接口：

```bash
python3 stt_client.py --list
```

`POST /api/diarize` 回答的是**谁在什么时候说话**，仅此而已：它返回带说话人编号的时间区间，而绝不返回文本。除非在以 `DIARIZE=true` 构建的镜像上设置了 `DIARIZE_ENABLED`，否则该接口处于关闭状态，并返回 `503`。

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

关于这些数字有两点说明。时间区间可能重叠，因为每个说话人通道都是单独评分的，所以两个人同时说话会产生覆盖相同秒数的两个区间。而这些编号只是这一次录音中的位置，按谁先开口排序：它们不是身份标识，同一个人在下一次请求中会得到不同的编号。要给说话人命名，需要一个本服务所不具备的声纹注册步骤。最多可区分八个说话人。

有两种转录后端可供选择。**Whisper** 是默认后端，接受 `language` 参数。**Parakeet**（`nvidia/parakeet-tdt-0.6b-v3`）覆盖 25 种欧洲语言，它自行检测语言，因此完全不接受 `language` 参数，`GET /api/models` 会把这一点报告为 `accepts_language: false`。要选用它，需要在以 `PARAKEET=true` 构建的镜像上设置 `STT_BACKEND=parakeet`；这是部署时的选择，而不是逐请求的选择，因为多一个常驻模型就意味着每个工作进程中都要多出一套权重。

两个后端都不支持重叠语音。NVIDIA 支持重叠语音的模型只以 NeMo checkpoint 的形式发布，而 NeMo 锁定的 PyTorch 版本与本项目的 CUDA 构建不同，因此无法在这里安装。

`POST /api/transcript` 回答的是**谁说了什么**：它对同一段音频同时运行说话人分离和转录，并按时间将二者连接起来。它需要启用说话人分离，否则返回 `503`。

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

`turns` 是说话人分离器的原始输出，`segments` 是二者连接后的结果，它们被分开保留，以便不信任这种归属的调用方仍能看到说话人分离器给出的结论。`text` 是纯转录文本，与 `/api/stt` 对同一文件返回的内容完全相同。没有任何一个 turn 覆盖到的语句会保持 `"speaker": null`，而不会被交给最接近的那一个。

`overlap` 标记的是在该语句期间还有其他人同时在说话。NVIDIA 明确指出，将传统的单说话人模型与说话人分离配合使用，并不等同于一个为重叠语音而构建的模型：被截取出来的时间区间里仍然包含所有与之重叠的声音，因此这些语句可能会混在一起，或者选中错误说话人的话语。把标记了 `overlap` 的片段视为转录结果最不可信的地方。

`/api/stream` 是一个用于**实时转录**的 WebSocket：音频边录制边送入，每个语句会在说话人停顿约一秒后返回。JSON 文本消息承载控制信息，二进制消息承载音频：

1. 客户端发送 `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}`。除 `type` 外的所有字段都是可选的。`token` 是浏览器进行身份验证的方式，因为浏览器无法在 WebSocket 上设置请求头；其他客户端也可以改为在握手时发送 `Authorization: Bearer <token>`。
2. 服务器回应 `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}`。
3. 客户端以任意大小的二进制消息发送原始 PCM（有符号 16 位、小端序、单声道、16 kHz），完成后发送 `{"type": "stop"}`。
4. 服务器为每个语句发送一条 `segment`，大约每秒发送一次 `progress`；如果会话一度落后超过两分钟，还会发送 `skipped`，其中给出被丢弃音频的秒数；并在关闭前发送 `done`：

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

音频也可以来自别处。在开始消息中加入 `"source": "url", "url": "https://..."` 后，客户端完全不发送音频：服务器通过 ffmpeg 读取该地址上的流，直到流结束或客户端发送 `stop`。网络电台、HLS、RTMP、RTSP 和 SRT 都可以使用；协议方案必须是 `http`、`https`、`rtmp`、`rtmps`、`rtsp` 或 `srt`。实时音源已经积压的部分会被一次性读取，其余部分则按音源自身的节奏读取，因此远程文件会像广播一样到达。

由于这会让服务器去访问由客户端选定的地址，因此它受到了限制。ffmpeg 只能使用网络协议，因此 URL 和播放列表都无法让它读取本地文件，也没有任何办法让它进入监听状态：SRT 的 `listener` 和 `rendezvous` 模式以及任何 `listen` 参数都会被拒绝。其他站点上的页面无法启动 URL 音源（`Forbidden`）：浏览器不会对 WebSocket 应用 CORS，因此该套接字会检查页面的来源（origin）是否为本主机，或是否列在 `CORS_ORIGINS` 中。最多同时运行四个 URL 音源（超出时返回 `Service Unavailable`），日志记录每个地址时会去掉其中的凭据和查询字符串。它仍然可以访问服务器自身所在网络中的主机，这对摄像头来说正是用途所在，也是在他人可以访问到的服务器上设置 `STT_TOKENS` 的原因。

失败时会发送一条 `{"type": "error", "error": "<category>", "request_id": "..."}`，随后关闭连接；错误类别与 HTTP 接口相同，另外还有 `Invalid start message`、`Invalid audio frame`、`Invalid stream URL`、`Stream source failed` 和 `Forbidden`。

一个语句在出现 0.6 秒的停顿时结束，或在说话人分离器听到一个说话人把话交给另一个说话人时结束（需启用 `diarize`，因为互相应答的人之间的停顿往往不到 0.6 秒），或者在持续超过 15 秒后于其最安静的时刻切分；每个语句单独转录，所用模型从与上传请求相同的池中借用，因此池繁忙时实时语句只会被延迟，而不会失败。启用 `diarize` 时，说话人分离器以流式模式运行，并在各个音频块之间延续说话人缓存，因此同一说话人在整个会话中保持同一个编号。只有当服务器在 uvicorn 下运行时（`python3 stt_server.py`，即 Docker 的默认方式）才存在该套接字：Flask 调试服务器和 gunicorn 的 sync 工作进程都不支持 WebSocket。

**只返回真正说出的文本。** 在没有语音的地方，比如提示音、音乐、噪声、回铃音，甚至数字静音，Whisper 会用它学习过的带字幕视频的片尾署名来作答（一条俄语署名"字幕制作：DimaTorzok"、"未完待续..."、"感谢观看。"），而且十分笃定：在测试语料上，即便是静音，它自己的 `no_speech_prob` 也是 0.00。因此，每个接口都会用语音检测器 Silero VAD 扫描音频，丢弃大部分落在检测到的语音之外的转录片段，以及任何整段都是字幕署名行的片段。在一个由九段无语音录音组成的语料上，这一做法去除了所有此类行，同时保留了语音录音中的每一个语句。没有任何人说话的录音现在会得到空文本。在实时流中，未检测到语音的语句甚至不会被送入模型。检测器在 CPU 上运行，每三分钟音频大约增加一秒。`SPEECH_GATE=false` 可恢复旧的行为。

上传大小上限为 `MAX_CONTENT_LENGTH_MB`（直接运行服务器时为 10 MB，Docker 部署中为 100 MB）；更大的请求体返回 `413`。

错误格式统一：`error` 携带一个通用类别，`request_id` 将响应与服务器日志关联起来，完整的异常信息记录在日志中。

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

当设置了 `STT_TOKENS` 时，除 `GET /api/health` 之外的每个路由都必须携带 `Authorization: Bearer <token>`；该接口保持开放，以便健康检查能正常工作。

### 命令行客户端

`stt_client.py` 是一个用于操作和测试服务器的小型客户端。它从 `STT_URL` 和 `STT_TOKEN` 读取服务器地址和令牌。

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

`--stream` 会以正常语速把一个文件播放到 `/api/stream`，并在每个语句返回时将其打印出来；加上 `--speakers` 可标注说话人：

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
```

### 环境变量

`.env` 由服务器和客户端通过 `python-dotenv` 共同加载。

| 变量                    | 默认值                  | 用途                                               |
| ----------------------- | ----------------------- | -------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | 服务器绑定地址                                     |
| `STT_PORT`              | `5099`                  | 服务器端口                                         |
| `STT_POOL_SIZE`         | `8`                     | 预加载的 Whisper 实例数量                          |
| `STT_TOKENS`            | （空）                  | 逗号分隔的有效令牌；为空则禁用鉴权                 |
| `STT_DEBUG`             | `false`                 | Flask 调试模式                                     |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | 最大上传大小（MB）；更大的请求体返回 `413`         |
| `CORS_ORIGINS`          | `*`                     | 允许的 CORS 来源：`*` 或逗号分隔的列表             |
| `GUNICORN_WORKERS`      | `4`                     | 工作进程数量（仅 gunicorn）                        |
| `LOG_LEVEL`             | `INFO`                  | 日志级别                                           |
| `LOG_ACCESS`            | `false`                 | 记录 uvicorn 访问日志行                            |
| `WHISPER_MODEL`         | `small.en`              | Whisper 模型名称（例如 `small.en`、`turbo`）       |
| `WHISPER_LANGUAGE`      | `en`                    | 默认转录语言                                       |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | 模型缓存目录（Docker 中为 `/opt/models`）          |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`、`cuda` 或 `auto`                            |
| `STT_BACKEND`           | `whisper`               | 转录后端：`whisper` 或 `parakeet`                  |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet 模型 id                                   |
| `PARAKEET_DOWNLOAD_ROOT` | `models`                | Parakeet 模型缓存目录                              |
| `DIARIZE_ENABLED`       | `false`                 | 启用 `POST /api/diarize`（需 `DIARIZE=true` 镜像） |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | 说话人分离模型 id                                  |
| `DIARIZE_POOL_SIZE`     | `1`                     | 预加载的说话人分离实例数量                         |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | 说话人分离模型缓存目录                             |
| `DIARIZE_THRESHOLD`     | `0.5`                   | 判定为语音的说话人活动概率                         |
| `SPEECH_GATE`           | `true`                  | 丢弃无人说出的转录文本（语音检测器）                |
| `STT_UID`, `STT_GID`    | （镜像中的 `stt`，1001） | 拥有 `models/`、`logs/`、`recs/` 的主机用户（Docker） |
| `HF_HUB_OFFLINE`        | `0`                     | 模型缓存完成后设为 `1`：启动时不再请求 hub          |
| `STT_WWW_PORT`          | `8080`                  | Web 界面的 http 端口（compose）                     |
| `STT_WWW_TLS_PORT`      | `8443`                  | Web 界面的 https 端口（compose）                    |
| `STT_URL`               | `http://localhost:5099` | 客户端：服务器基础 URL                             |
| `STT_TOKEN`             | （空）                  | 客户端：发送给服务器的 bearer 令牌                 |

### 项目结构

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
├── constraints.txt      # every dependency version the tested image resolved
├── docs/                # DEPLOY.md and the README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### 开发

系统软件包 `ffmpeg` 和 `libsndfile1` 必须存在。安装运行时和开发依赖：

```bash
pip install -e ".[dev]"
pre-commit install
```

Makefile 封装了常见任务：

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
make typecheck      # mypy
```

测试套件对 Whisper 后端进行了打桩，因此它覆盖了 HTTP 层（request_id、错误类别、模型池语义），并能在数秒内运行完成，无需下载模型或使用 GPU。

### 许可证

[MIT](../LICENSE)
