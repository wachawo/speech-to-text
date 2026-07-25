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

GPU 构建需要主机上安装 `nvidia-container-toolkit`。首次运行会将 Whisper 模型下载到 `./models`。

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
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` 接受名为 `file` 的 `multipart/form-data` 字段，或一个原始的 `audio/*` 请求体。可选的 `language`（查询字符串或表单字段）会针对该请求覆盖服务器默认值；`auto` 表示自动检测。成功时返回文本和耗费的秒数：

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

上传大小上限为 `MAX_CONTENT_LENGTH_MB`（默认 10 MB）；更大的请求体返回 `413`。

错误格式统一：`error` 携带一个通用类别，`request_id` 将响应与服务器日志关联起来，完整的异常信息记录在日志中。

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

当设置了 `STT_TOKENS` 时，每个 `POST /api/stt` 都必须携带 `Authorization: Bearer <token>`；`GET /api/health` 保持开放，以便健康检查能正常工作。

### 命令行客户端

`stt_client.py` 是一个用于操作和测试服务器的小型客户端。它从 `STT_URL` 和 `STT_TOKEN` 读取服务器地址和令牌。

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
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
| `WHISPER_MODEL`         | `turbo`                 | Whisper 模型名称（例如 `small.en`、`turbo`）       |
| `WHISPER_LANGUAGE`      | `en`                    | 默认转录语言                                       |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | 模型缓存目录（Docker 中为 `/opt/models`）          |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`、`cuda` 或 `auto`                            |
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
│   ├── model_pool.py    # pool of pre-loaded Whisper instances
│   └── stt.py           # Whisper wrapper
├── Dockerfile           # GPU build (CUDA 13.0)
├── Dockerfile-cpu       # CPU build
├── docs/                # README translations
└── tests/               # pytest tests, no model downloads and no GPU
```

### 开发

系统软件包 `ffmpeg` 和 `libsndfile1` 必须存在。安装运行时和开发依赖：

```bash
pip install -r requirements-dev.txt
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
```

测试套件对 Whisper 后端进行了打桩，因此它覆盖了 HTTP 层（request_id、错误类别、模型池语义），并能在数秒内运行完成，无需下载模型或使用 GPU。

### 许可证

[MIT](../LICENSE)
