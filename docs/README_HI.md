## speech-to-text: एक स्वयं-होस्टेड Whisper ट्रांसक्रिप्शन सर्वर

[![CI](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml/badge.svg)](https://github.com/wachawo/speech-to-text/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/wachawo/speech-to-text/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

[English](https://github.com/wachawo/speech-to-text/blob/main/README.md) | [Español](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ES.md) | [Português](https://github.com/wachawo/speech-to-text/blob/main/docs/README_PT.md) | [Français](https://github.com/wachawo/speech-to-text/blob/main/docs/README_FR.md) | [Deutsch](https://github.com/wachawo/speech-to-text/blob/main/docs/README_DE.md) | [Italiano](https://github.com/wachawo/speech-to-text/blob/main/docs/README_IT.md) | [Русский](https://github.com/wachawo/speech-to-text/blob/main/docs/README_RU.md) | [中文](https://github.com/wachawo/speech-to-text/blob/main/docs/README_ZH.md) | [日本語](https://github.com/wachawo/speech-to-text/blob/main/docs/README_JA.md) | **[हिन्दी](https://github.com/wachawo/speech-to-text/blob/main/docs/README_HI.md)** | [한국어](https://github.com/wachawo/speech-to-text/blob/main/docs/README_KR.md)

`speech-to-text` [openai-whisper](https://github.com/openai/whisper) की मदद से ऑडियो को टेक्स्ट में बदलता है, जिसे एक छोटी HTTP सेवा में लपेटा गया है जिसे आप स्वयं चलाते हैं। आप एक ऑडियो फ़ाइल भेजते हैं और आपको ट्रांसक्रिप्शन वापस मिलता है। कोई बाहरी API नहीं, कोई प्रति-मिनट बिलिंग नहीं, और आपका ऑडियो कभी भी आपकी मशीन से बाहर नहीं जाता।

यह प्रोजेक्ट स्थानीय उपयोग, बैच ट्रांसक्रिप्शन, और नेटवर्क पर अपना खुद का STT सर्वर चलाने के लिए उपयुक्त है।

* **उपयोग के लिए तैयार एक HTTP सर्वर।** uvicorn द्वारा सर्व किया गया Flask स्टार्टअप पर Whisper को लोड करता है और आपके स्थानीय नेटवर्क की अन्य मशीनों से अनुरोधों का उत्तर देता है।
* **समवर्तीता (concurrency) के तहत सुरक्षित।** सर्वर पहले से लोड किए गए Whisper इंस्टेंस का एक पूल बनाए रखता है, इसलिए मॉडल को फिर से लोड किए बिना कई अनुरोध समानांतर रूप से ट्रांसक्राइब किए जाते हैं।
* **CPU या GPU, एक ही कोड।** बैकएंड का चयन पर्यावरण और आपके द्वारा बनाई गई Docker इमेज के आधार पर होता है। एक CUDA कार्ड इन्फरेंस को तेज़ करता है, लेकिन सब कुछ CPU पर भी चलता है।
* **एक CLI क्लाइंट शामिल है।** `stt_client.py` स्थानीय फ़ाइलों को सर्वर पर पोस्ट करता है और परिणाम प्रिंट करता है।

### मॉडल

Whisper कई मॉडल आकारों में आता है। बड़े मॉडल अधिक सटीक और धीमे होते हैं; छोटे मॉडल तेज़ और हल्के होते हैं।

| Model      | Parameters | VRAM    | Languages       | Good for                                      |
| ---------- | ---------- | ------- | --------------- | --------------------------------------------- |
| `tiny`     | 39M        | ~1 GB   | बहुभाषी          | कमज़ोर हार्डवेयर पर त्वरित ड्राफ़्ट              |
| `base`     | 74M        | ~1 GB   | बहुभाषी          | एक हल्का सामान्य-उद्देश्य डिफ़ॉल्ट              |
| `small`    | 244M       | ~2 GB   | बहुभाषी          | सटीकता / गति का अच्छा संतुलन                   |
| `medium`   | 769M       | ~5 GB   | बहुभाषी          | जब मेमोरी बचा सकें तो उच्च सटीकता               |
| `turbo`    | 809M       | ~6 GB   | बहुभाषी          | `large` के लगभग बराबर सटीकता, बहुत तेज़         |
| `large`    | 1550M      | ~10 GB  | बहुभाषी          | सर्वोत्तम गुणवत्ता, GPU की आवश्यकता             |

केवल-अंग्रेज़ी वेरिएंट (`tiny.en`, `base.en`, `small.en`, `medium.en`) अंग्रेज़ी ऑडियो पर थोड़े अधिक सटीक होते हैं। डिफ़ॉल्ट `turbo` है, जो GPU पर अंग्रेज़ी के लिए सबसे अच्छा सर्व-समावेशी विकल्प है।

### त्वरित प्रारंभ (Docker)

सर्वर चलाने का सबसे आसान तरीका Docker के साथ है। मॉडल फ़ाइलें होस्ट पर `./models` में कैश की जाती हैं, इसलिए वे कंटेनर के पुनर्निर्माण के बाद भी बनी रहती हैं।

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU बिल्ड को होस्ट पर `nvidia-container-toolkit` की आवश्यकता होती है। पहली बार चलाने पर Whisper मॉडल `./models` में डाउनलोड हो जाता है।

### HTTP API

सर्वर चालू होने के बाद, इसकी स्थिति जाँचें और ट्रांसक्रिप्शन के लिए एक ऑडियो फ़ाइल भेजें।

```bash
curl localhost:5099/api/health

curl -X POST localhost:5099/api/stt \
  -F file=@speech.mp3

curl -X POST 'localhost:5099/api/stt?language=ru' \
  -H 'Content-Type: audio/wav' \
  --data-binary @speech.wav
```

`GET /api/health` पूल की स्थिति लौटाता है। `available` का 0 तक गिरना यह दर्शाता है कि हर मॉडल इस समय उपयोग में है:

```json
{ "status": "ok", "pool_size": 4, "available": 3 }
```

`POST /api/stt` या तो `file` नामक एक `multipart/form-data` फ़ील्ड स्वीकार करता है, या एक कच्चा (raw) `audio/*` बॉडी। एक वैकल्पिक `language` (query string या form field) उस अनुरोध के लिए सर्वर डिफ़ॉल्ट को ओवरराइड करता है; `auto` स्वतः पहचान करता है। सफल होने पर यह टेक्स्ट और बीते हुए सेकंड लौटाता है:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

अपलोड `MAX_CONTENT_LENGTH_MB` (डिफ़ॉल्ट रूप से 10 MB) तक सीमित हैं; बड़ा बॉडी `413` लौटाता है।

त्रुटियाँ एकसमान होती हैं: `error` एक सामान्य श्रेणी रखता है और `request_id` प्रतिक्रिया को सर्वर लॉग से सहसंबंधित करता है, जहाँ पूरा अपवाद (exception) दर्ज होता है।

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

जब `STT_TOKENS` सेट होता है, तो हर `POST /api/stt` को `Authorization: Bearer <token>` ले जाना होता है; `GET /api/health` खुला रहता है ताकि हेल्थचेक काम करते रहें।

### CLI क्लाइंट

`stt_client.py` सर्वर के साथ काम करने और परीक्षण करने के लिए एक छोटा क्लाइंट है। यह सर्वर का पता और टोकन `STT_URL` और `STT_TOKEN` से पढ़ता है।

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

### पर्यावरण चर (Environment variables)

`.env` को सर्वर और क्लाइंट दोनों द्वारा `python-dotenv` के माध्यम से लोड किया जाता है।

| Variable                | Default                 | उद्देश्य                                             |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | सर्वर बाइंड पता                                      |
| `STT_PORT`              | `5099`                  | सर्वर पोर्ट                                          |
| `STT_POOL_SIZE`         | `8`                     | पहले से लोड किए गए Whisper इंस्टेंस की संख्या         |
| `STT_TOKENS`            | (खाली)                  | अल्पविराम से अलग किए गए मान्य टोकन; खाली होने पर auth निष्क्रिय |
| `STT_DEBUG`             | `false`                 | Flask डिबग मोड                                      |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | MB में अधिकतम अपलोड आकार; बड़ा बॉडी `413` लौटाता है   |
| `CORS_ORIGINS`          | `*`                     | अनुमत CORS मूल: `*` या अल्पविराम से अलग की गई सूची    |
| `GUNICORN_WORKERS`      | `4`                     | वर्कर प्रक्रियाएँ (केवल gunicorn)                     |
| `LOG_LEVEL`             | `INFO`                  | लॉगिंग स्तर                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn एक्सेस लाइनें लॉग करें                       |
| `WHISPER_MODEL`         | `turbo`                 | Whisper मॉडल नाम (जैसे `small.en`, `turbo`)          |
| `WHISPER_LANGUAGE`      | `en`                    | डिफ़ॉल्ट ट्रांसक्रिप्शन भाषा                          |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | मॉडल कैश डायरेक्टरी (Docker में `/opt/models`)        |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, या `auto`                             |
| `STT_URL`               | `http://localhost:5099` | क्लाइंट: सर्वर बेस URL                               |
| `STT_TOKEN`             | (खाली)                  | क्लाइंट: सर्वर को भेजा गया बियरर टोकन                 |

### प्रोजेक्ट संरचना

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

### विकास (Development)

सिस्टम पैकेज `ffmpeg` और `libsndfile1` मौजूद होने चाहिए। रनटाइम और डेव निर्भरताएँ इंस्टॉल करें:

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Makefile सामान्य कार्यों को लपेटता है:

```bash
make run            # foreground: python3 stt_server.py
make start          # background: PID -> .stt_server.pid, logs -> logs/stt_server.log
make stop           # stop the background server
make gunicorn       # run via gunicorn
make test           # pytest
make lint           # pre-commit (black + ruff)
```

टेस्ट सूट Whisper बैकएंड को स्टब कर देता है, इसलिए यह HTTP परत (request_id, error श्रेणियाँ, model pool semantics) को कवर करता है और बिना मॉडल डाउनलोड किए या GPU की आवश्यकता के कुछ ही सेकंड में चलता है।

### लाइसेंस

[MIT](../LICENSE)
