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
* **लाइव ट्रांसक्रिप्शन।** वेबसॉकेट पर ऑडियो स्ट्रीम करें और हर वाक्यांश बोले जाते ही वापस पाएँ; डायराइज़ेशन चालू होने पर उसे किसी स्पीकर को सौंपा जाता है।
* **एक वेब UI शामिल है।** ब्राउज़र में फ़ाइल अपलोड करें और टेक्स्ट पढ़ें, या देखें कि किसने क्या कहा; इसे सर्वर के बगल में चलने वाला इसका अपना nginx कंटेनर सर्व करता है।

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

GPU बिल्ड को होस्ट पर `nvidia-container-toolkit` की आवश्यकता होती है। पहली बार चलाने पर Whisper मॉडल `./models` में डाउनलोड हो जाता है। सर्वर पर इसे चलाना - अपडेट, रोलबैक, प्रमाणपत्र, निर्भरताएँ - [docs/DEPLOY.md](DEPLOY.md) में बताया गया है।

### वेब UI

`docker compose up` साथ में `stt_www` भी शुरू करता है, एक nginx कंटेनर जो ब्राउज़र UI सर्व करता है और `/api/` को सर्वर तक आगे भेजता है, ताकि UI और API एक ही पते पर रहें।

| लिसनर | डिफ़ॉल्ट पोर्ट | किससे सेट करें         |
| ----- | ----------- | ------------------ |
| http  | `8080`      | `STT_WWW_PORT`     |
| https | `8443`      | `STT_WWW_TLS_PORT` |

`http://<host>:8080` खोलें। **TRANSCRIBE** के तीन स्रोत हैं। **FILE** एक ऑडियो फ़ाइल अपलोड करता है। **DEVICE** किसी ऑडियो इनपुट से लाइव ट्रांसक्राइब करता है: माइक्रोफ़ोन या हेडसेट, Linux पर `Monitor of ...` स्रोत जो स्पीकर या हेडफ़ोन से बजने वाली हर चीज़ को लाता है, या, Chromium ब्राउज़रों में, `Tab or screen audio`, जो ब्राउज़र टैब में बज रही चीज़ के लिए है, या जहाँ OS अनुमति दे वहाँ पूरे सिस्टम के लिए। **STREAM** किसी स्ट्रीम या रिमोट फ़ाइल का पता लेता है - इंटरनेट रेडियो, HLS, RTMP, RTSP, SRT - और सर्वर उसे खुद पढ़ता है। हर स्थिति में परिणाम फ़ॉर्म के नीचे सादे टेक्स्ट के रूप में दिखता है या, डायराइज़ेशन सक्षम होने पर, हर वाक्यांश के लिए एक ब्लॉक के रूप में जिसमें उसका स्पीकर और समय होता है, हर स्पीकर अपने रंग में, और जिन वाक्यांशों में दो लोग एक साथ बोले वे चिह्नित होते हैं; लाइव वाक्यांश स्पीकर के रुकने के लगभग एक सेकंड बाद दिखता है। परिणाम को कॉपी किया जा सकता है या TXT अथवा JSON के रूप में डाउनलोड किया जा सकता है, और जब आप कोई दूसरी स्क्रीन देखते हैं तब भी हर स्रोत अपना पिछला परिणाम बनाए रखता है। FILE में एक **Turns** मोड भी है, यानी अकेला `POST /api/diarize`: कौन कब बोला, इसे हर स्पीकर के लिए एक लेन वाली टाइमलाइन के रूप में दिखाया जाता है और जिन हिस्सों में दो लोग एक साथ बोलते हैं वे चिह्नित होते हैं। **MODELS** वही दिखाता है जो `GET /api/models` बताता है। जब `STT_TOKENS` सेट होता है, तो UI एक बार टोकन माँगता है और उसे ब्राउज़र में रखता है।

ब्राउज़र ऑडियो डिवाइस केवल सुरक्षित पेज को देते हैं, इसलिए नेटवर्क पर DEVICE https लिसनर के माध्यम से काम करता है (और `http://localhost` पर भी)। https लिसनर एक स्व-हस्ताक्षरित (self-signed) प्रमाणपत्र का उपयोग करता है जिसे कंटेनर पहली बार शुरू होने पर `./data/certs` में बनाता है; उसे बदलने के लिए वहाँ असली `stt.crt` और `stt.key` रख दें। UI में न कोई बिल्ड चरण है और न कोई CDN: Vue 2 और उसकी लाइब्रेरियाँ `www/vendor` में साथ रखी गई हैं, इसलिए यह इंटरनेट तक पहुँच न रखने वाली मशीन पर भी काम करता है।

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
{ "status": "ok", "pool_size": 4, "available": 3, "diarize": false }
```

`GET /api/health?deep=1` इसके अलावा हर लोड किए गए मॉडल से एक सेकंड का सन्नाटा गुज़ारता है और हर मॉडल को `ok`, `busy` (पाँच सेकंड के भीतर कोई इंस्टेंस खाली नहीं हुआ) या `failed` के रूप में बताता है, और अगर कोई विफल हुआ तो `503` लौटाता है। इसमें GPU का काम लगता है, इसलिए जब तक `STT_TOKENS` सेट है, इसके लिए टोकन चाहिए; सामान्य जाँच कंटेनर हेल्थचेक के लिए खुली रहती है।

`GET /metrics` Prometheus मेट्रिक्स देता है: रूट और स्टेटस के अनुसार अनुरोध, उनकी अवधि, श्रेणी के अनुसार त्रुटि प्रतिक्रियाएँ, पूल के आकार और खाली इंस्टेंस, चल रहे और शुरू हुए लाइव सत्र, वॉइस डिटेक्टर द्वारा हटाए गए सेगमेंट, और पीछे रह गए सत्र द्वारा छोड़ा गया लाइव ऑडियो। हेल्थ की तरह इसे भी टोकन नहीं चाहिए, और `stt_www` इसे प्रॉक्सी नहीं करता: `STT_PORT` को सीधे स्क्रैप करें। gunicorn के अंतर्गत हर वर्कर अपनी गिनती अलग रखता है।

`POST /api/stt` या तो `file` नामक एक `multipart/form-data` फ़ील्ड स्वीकार करता है, या एक कच्चा (raw) `audio/*` बॉडी। एक वैकल्पिक `language` (query string या form field) उस अनुरोध के लिए सर्वर डिफ़ॉल्ट को ओवरराइड करता है; `auto` स्वतः पहचान करता है। सफल होने पर यह टेक्स्ट और बीते हुए सेकंड लौटाता है:

```json
{ "text": "transcribed text", "elapsed": 1.23 }
```

भाषा कोड (`ru`) के रूप में या उसके अंग्रेज़ी नाम (`russian`) से दी जा सकती है; जो मॉडल नहीं जानता उसे ट्रांसक्रिप्शन के बीच में विफल होने के बजाय `400` के साथ अस्वीकार किया जाता है। `GET /api/models` बताता है कि वह क्या जानता है। यह केवल उन बैकएंड पर लागू होता है जो भाषा स्वीकार करते हैं (`accepts_language: true`)। Parakeet भाषा खुद पहचानता है और मान को अनदेखा करता है, और जिस भाषण के बारे में वह अनिश्चित हो उसे बिना बताए छोड़ सकता है: बहुभाषी रिकॉर्डिंग में वह अल्पसंख्यक भाषा के लिए कुछ भी नहीं लौटा सकता।

`GET /api/models` बताता है कि यह सर्वर क्या-क्या रखता है, ताकि किसी क्लाइंट को अनुमान न लगाना पड़े। हर बैकएंड अपनी अलग भाषा-सूची लाता है, क्योंकि ये समूह वास्तव में एक-दूसरे से भिन्न हैं और एक मिली-जुली सूची अलग-अलग हर बैकएंड के लिए ग़लत होती।

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

`status` तब `loaded` होता है जब कोई इंस्टेंस पूल में प्रतीक्षा कर रहा हो, `installed` तब जब वेट्स डिस्क पर मौजूद हों लेकिन अभी कुछ लोड न हुआ हो, और अन्यथा `absent`। ऐसा बैकएंड जो कॉन्फ़िगर है पर इंस्टॉल नहीं, केवल `absent` कहता है और उससे अधिक कुछ नहीं; कारण लॉग में जाता है। `accepts_language` बताता है कि उस बैकएंड के लिए `?language=` का कोई अर्थ है या नहीं। डायराइज़र खाली सूची के बजाय `null` भाषाएँ लौटाता है, क्योंकि वह किसी भी भाषा में टेक्स्ट नहीं बनाता।

CLI क्लाइंट भी यही एंडपॉइंट पढ़ता है:

```bash
python3 stt_client.py --list
```

`POST /api/diarize` केवल यह उत्तर देता है कि **कौन कब बोला**, और कुछ नहीं: यह स्पीकर संख्या के साथ समय-अंतराल लौटाता है, कभी टेक्स्ट नहीं। यह तब तक बंद रहता है जब तक `DIARIZE=true` के साथ बनाई गई इमेज पर `DIARIZE_ENABLED` सेट न हो; अन्यथा यह `503` लौटाता है।

```bash
curl -X POST localhost:5099/api/diarize -F file=@meeting.wav
```

```json
{ "segments": [ { "speaker": 0, "start": 0.51, "end": 12.62 },
                { "speaker": 1, "start": 12.20, "end": 19.04 } ], "speakers": 2, "elapsed": 1.23 }
```

इन संख्याओं के बारे में दो बातें। अंतराल एक-दूसरे पर ओवरलैप कर सकते हैं, क्योंकि हर स्पीकर चैनल का मूल्यांकन अलग से होता है, इसलिए एक साथ बोलते दो लोग समान सेकंडों को कवर करने वाले दो अंतराल बनाते हैं। और लेबल केवल इसी एक रिकॉर्डिंग में स्थितियाँ हैं, इस क्रम में कि कौन पहले बोला: वे पहचान नहीं हैं, और अगले अनुरोध में उसी व्यक्ति को अलग संख्या मिलती है। किसी स्पीकर का नाम बताने के लिए एक एनरोलमेंट चरण चाहिए, जो इस सेवा में नहीं है। अधिकतम आठ स्पीकर अलग-अलग पहचाने जाते हैं।

दो ट्रांसक्रिप्शन बैकएंड उपलब्ध हैं। **Whisper** डिफ़ॉल्ट है और `language` स्वीकार करता है। **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) 25 यूरोपीय भाषाओं को कवर करता है, भाषा स्वयं पहचान लेता है और इसलिए कोई `language` तर्क लेता ही नहीं, जिसे `GET /api/models` `accepts_language: false` के रूप में बताता है। इसे `PARAKEET=true` के साथ बनाई गई इमेज पर `STT_BACKEND=parakeet` से चुनें; यह डिप्लॉय-समय का चयन है, प्रति-अनुरोध का नहीं, क्योंकि दूसरा स्थायी रूप से लोड मॉडल हर वर्कर में वेट्स का दूसरा सेट होगा।

कोई भी बैकएंड ओवरलैप-सजग (overlap-aware) नहीं है। NVIDIA का ओवरलैप-सजग मॉडल केवल एक NeMo चेकपॉइंट के रूप में आता है, और NeMo इस प्रोजेक्ट के CUDA बिल्ड से भिन्न PyTorch को पिन करता है, इसलिए यहाँ उसे इंस्टॉल नहीं किया जा सकता।

`POST /api/transcript` यह उत्तर देता है कि **किसने क्या कहा**: यह एक ही ऑडियो पर डायराइज़ेशन और ट्रांसक्रिप्शन दोनों चलाता है और उन्हें समय के आधार पर जोड़ता है। इसके लिए डायराइज़ेशन सक्षम होना चाहिए, अन्यथा यह `503` लौटाता है।

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

`turns` डायराइज़र का कच्चा आउटपुट है और `segments` उन दोनों का जोड़ (join) है; इन्हें अलग-अलग रखा गया है ताकि जो कॉलर इस आरोपण (attribution) पर भरोसा न करे, वह फिर भी देख सके कि डायराइज़र ने क्या कहा। `text` सादा ट्रांसक्रिप्ट है, ठीक वही जो उसी फ़ाइल के लिए `/api/stt` लौटाता है। जिस वाक्यांश को कोई भी turn कवर नहीं करता, उसे निकटतम स्पीकर को सौंपने के बजाय वह `"speaker": null` रखता है।

`overlap` उस वाक्यांश को चिह्नित करता है जिसके दौरान कोई और भी बोल रहा था। NVIDIA स्पष्ट रूप से कहता है कि किसी पारंपरिक एकल-स्पीकर मॉडल को डायराइज़ेशन के साथ जोड़ना, ओवरलैपिंग वाक् के लिए बनाए गए मॉडल के समतुल्य नहीं है: निकाले गए समय-अंतराल में वे सभी आवाज़ें मौजूद रहती हैं जो उस पर ओवरलैप करती हैं, इसलिए ऐसे वाक्यांश आपस में मिल सकते हैं या ग़लत स्पीकर के शब्द चुन सकते हैं। `overlap` से चिह्नित सेगमेंट को उस जगह के रूप में लें जहाँ ट्रांसक्रिप्ट सबसे कम भरोसेमंद है।

`/api/stream` **लाइव ट्रांसक्रिप्शन** के लिए एक वेबसॉकेट है: ऑडियो रिकॉर्ड होते-होते भीतर जाता है, और हर वाक्यांश स्पीकर के रुकने के लगभग एक सेकंड बाद वापस आता है। JSON टेक्स्ट संदेश नियंत्रण ले जाते हैं, बाइनरी संदेश ऑडियो:

1. क्लाइंट `{"type": "start", "language": "ru", "diarize": true, "token": "<token>"}` भेजता है। `type` को छोड़कर हर फ़ील्ड वैकल्पिक है। `token` वह तरीका है जिससे ब्राउज़र प्रमाणीकरण करता है, क्योंकि वह वेबसॉकेट पर हेडर सेट नहीं कर सकता; अन्य क्लाइंट इसके बजाय हैंडशेक पर `Authorization: Bearer <token>` भेज सकते हैं।
2. सर्वर `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "language": "ru", "diarize": true, "source": "client"}` के साथ उत्तर देता है।
3. क्लाइंट कच्चा PCM - signed 16-bit, little-endian, मोनो, 16 kHz - किसी भी आकार के बाइनरी संदेशों के रूप में भेजता है, और काम पूरा होने पर `{"type": "stop"}` भेजता है।
4. सर्वर हर वाक्यांश के लिए एक `segment`, लगभग हर सेकंड एक `progress`, सत्र के कभी दो मिनट से अधिक पीछे रह जाने पर छोड़े गए ऑडियो के सेकंड के साथ `skipped`, और बंद करने से पहले `done` भेजता है:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

ऑडियो कहीं और से भी आ सकता है। स्टार्ट संदेश में `"source": "url", "url": "https://..."` होने पर क्लाइंट कोई ऑडियो नहीं भेजता: सर्वर उस पते पर मौजूद स्ट्रीम को ffmpeg के ज़रिए तब तक पढ़ता है जब तक वह समाप्त न हो जाए या क्लाइंट `stop` न भेज दे। इंटरनेट रेडियो, HLS, RTMP, RTSP और SRT काम करते हैं; स्कीम `http`, `https`, `rtmp`, `rtmps`, `rtsp` या `srt` होनी चाहिए। किसी लाइव स्रोत में जो पहले से जमा है उसे एक साथ ले लिया जाता है और बाकी को स्रोत की अपनी गति से, इसलिए रिमोट फ़ाइल भी वैसे ही आती है जैसे कोई प्रसारण आता।

क्योंकि इससे सर्वर क्लाइंट द्वारा चुना गया पता प्राप्त करता है, इसलिए इसे सीमाओं में बाँधा गया है। ffmpeg केवल नेटवर्क प्रोटोकॉल का उपयोग कर सकता है, इसलिए न कोई URL और न कोई प्लेलिस्ट उससे कोई स्थानीय फ़ाइल पढ़वा सकती है, और कोई भी चीज़ उसे कनेक्शन सुनने की स्थिति में नहीं ला सकती: SRT के `listener` और `rendezvous` मोड और कोई भी `listen` पैरामीटर अस्वीकार कर दिए जाते हैं। किसी दूसरी साइट का पेज इसे शुरू नहीं कर सकता (`Forbidden`): ब्राउज़र वेबसॉकेट पर CORS लागू नहीं करते, इसलिए सॉकेट जाँचता है कि पेज का origin यही होस्ट है, या `CORS_ORIGINS` में सूचीबद्ध है। एक साथ अधिकतम चार URL स्रोत चलते हैं (उससे अधिक पर `Service Unavailable`), और लॉग हर पते को उसके क्रेडेंशियल और query के बिना दर्ज करता है। यह फिर भी सर्वर के अपने नेटवर्क के होस्ट तक पहुँच सकता है, जो कैमरे के लिए ठीक यही उद्देश्य है और यही कारण है कि जिस सर्वर तक दूसरे पहुँच सकते हैं उस पर `STT_TOKENS` सेट किया जाए।

विफलता एक अकेला `{"type": "error", "error": "<category>", "request_id": "..."}` होती है जिसके बाद कनेक्शन बंद हो जाता है; इसकी श्रेणियाँ HTTP त्रुटि श्रेणियाँ हैं, साथ में `Invalid start message`, `Invalid audio frame`, `Invalid stream URL`, `Stream source failed` और `Forbidden`।

एक वाक्यांश 0.6 सेकंड के विराम पर समाप्त होता है, वहाँ जहाँ डायराइज़र सुनता है कि एक स्पीकर ने बात दूसरे को सौंप दी (`diarize` के साथ, क्योंकि एक-दूसरे को जवाब देते लोग अक्सर 0.6 सेकंड से कम का अंतर छोड़ते हैं), या 15 सेकंड से लंबा हो जाने पर अपने सबसे शांत क्षण पर, और उसे अलग से ऐसे मॉडल से ट्रांसक्राइब किया जाता है जो उसी पूल से उधार लिया जाता है जिससे अपलोड के लिए लिया जाता है, इसलिए व्यस्त पूल लाइव वाक्यांशों को विफल करने के बजाय केवल विलंबित करता है। `diarize` के साथ, डायराइज़र अपने स्ट्रीमिंग मोड में चलता है और एक चंक से दूसरे चंक तक स्पीकर कैश बनाए रखता है, इसलिए पूरे सत्र में एक स्पीकर की संख्या वही रहती है। यह सॉकेट तब मौजूद होता है जब सर्वर uvicorn के अंतर्गत चलता है - `python3 stt_server.py`, Docker का डिफ़ॉल्ट, या `GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker` के साथ `stt_server:asgi_app` सर्व करता gunicorn - और Flask डिबग सर्वर या gunicorn के डिफ़ॉल्ट sync वर्कर के अंतर्गत नहीं, जो वेबसॉकेट नहीं समझते।

**केवल बोला गया टेक्स्ट लौटाया जाता है।** जहाँ कोई वाक् नहीं है - कोई टोन, संगीत, शोर, रिंगबैक, यहाँ तक कि डिजिटल सन्नाटा - वहाँ Whisper उन सबटाइटल वाले वीडियो के क्रेडिट्स से उत्तर देता है जिनसे उसने सीखा है (एक रूसी "सबटाइटल: DimaTorzok" क्रेडिट, "जारी रहेगा...", "देखने के लिए धन्यवाद।"), और वह भी पूरे विश्वास के साथ: परीक्षण कॉर्पस पर उसका अपना `no_speech_prob` सन्नाटे पर भी 0.00 था। इसलिए हर एंडपॉइंट ऑडियो पर एक वॉइस डिटेक्टर, Silero VAD, चलाता है और ऐसे ट्रांसक्राइब किए गए सेगमेंट को हटा देता है जो ज़्यादातर पहचानी गई वाक् से बाहर पड़ता है, साथ ही हर उस सेगमेंट को भी जो पूरी तरह सबटाइटल क्रेडिट की एक पंक्ति है। बिना वाक् वाली नौ रिकॉर्डिंग के कॉर्पस पर इसने ऐसी हर पंक्ति हटा दी, जबकि वाक् वाली रिकॉर्डिंग का हर वाक्यांश बना रहा। जिस रिकॉर्डिंग में कुछ भी बोला नहीं गया, वह अब खाली टेक्स्ट देती है। लाइव स्ट्रीम में बिना पहचानी गई वाक् वाला वाक्यांश मॉडल को भेजा तक नहीं जाता। डिटेक्टर CPU पर चलता है और हर तीन मिनट के ऑडियो पर लगभग एक सेकंड जोड़ता है। `SPEECH_GATE=false` पुराना व्यवहार वापस ले आता है।

अपलोड `MAX_CONTENT_LENGTH_MB` (सीधे चलाए गए सर्वर के लिए 10 MB, Docker सेटअप में 100 MB) तक सीमित हैं; बड़ा बॉडी `413` लौटाता है।

त्रुटियाँ एकसमान होती हैं: `error` एक सामान्य श्रेणी रखता है और `request_id` प्रतिक्रिया को सर्वर लॉग से सहसंबंधित करता है, जहाँ पूरा अपवाद (exception) दर्ज होता है।

```json
{ "error": "Invalid audio data", "request_id": "a1b2c3d4e5f6" }
```

जब `STT_TOKENS` सेट होता है, तो `GET /api/health` को छोड़कर हर रूट को `Authorization: Bearer <token>` ले जाना होता है; हेल्थचेक काम करते रहें, इसलिए वही एक रूट खुला रहता है।

### CLI क्लाइंट

`stt_client.py` सर्वर के साथ काम करने और परीक्षण करने के लिए एक छोटा क्लाइंट है। यह सर्वर का पता और टोकन `STT_URL` और `STT_TOKEN` से पढ़ता है।

```bash
python3 stt_client.py speech.mp3
python3 stt_client.py file1.wav file2.mp3 file3.ogg
```

`--stream` एक फ़ाइल को बोलने की गति से `/api/stream` में चलाता है और हर वाक्यांश लौटते ही उसे प्रिंट करता है, स्पीकर आरोपण के लिए `--speakers` के साथ:

```bash
python3 stt_client.py --stream meeting.wav --speakers --language ru
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
| `GUNICORN_WORKER_CLASS` | `sync`                  | `uvicorn_worker.UvicornWorker` `/api/stream` जोड़ता है (केवल gunicorn) |
| `LOG_LEVEL`             | `INFO`                  | लॉगिंग स्तर                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn एक्सेस लाइनें लॉग करें                       |
| `WHISPER_MODEL`         | `small.en`              | Whisper मॉडल नाम (जैसे `small.en`, `turbo`)          |
| `WHISPER_LANGUAGE`      | `en`                    | डिफ़ॉल्ट ट्रांसक्रिप्शन भाषा                          |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | मॉडल कैश डायरेक्टरी (Docker में `/opt/models`)        |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, या `auto`                             |
| `STT_BACKEND`           | `whisper`               | ट्रांसक्रिप्शन बैकएंड: `whisper` या `parakeet`         |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet मॉडल id                                    |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet मॉडल कैश डायरेक्टरी                         |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` सक्षम करें (`DIARIZE=true` इमेज चाहिए) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | डायराइज़ेशन मॉडल id                                  |
| `DIARIZE_POOL_SIZE`     | `1`                     | पहले से लोड किए गए डायराइज़र इंस्टेंस                 |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | डायराइज़ेशन मॉडल कैश डायरेक्टरी                       |
| `DIARIZE_THRESHOLD`     | `0.5`                   | स्पीकर सक्रियता संभावना जिसे वाक् माना जाए             |
| `SPEECH_GATE`           | `true`                  | वह ट्रांसक्राइब किया टेक्स्ट हटाएँ जिसे किसी ने नहीं बोला (वॉइस डिटेक्टर) |
| `STT_UID`, `STT_GID`    | (इमेज का `stt`, 1001)    | `models/`, `logs/`, `recs/` का स्वामी होस्ट उपयोगकर्ता (Docker) |
| `HF_HUB_OFFLINE`        | `0`                     | मॉडल कैश हो जाने पर `1`: स्टार्ट पर hub अनुरोध नहीं       |
| `STT_WWW_PORT`          | `8080`                  | वेब UI का http पोर्ट (compose)                        |
| `STT_WWW_TLS_PORT`      | `8443`                  | वेब UI का https पोर्ट (compose)                       |
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
│   ├── model_pool.py    # pools of pre-loaded Whisper and diarizer instances
│   ├── catalog.py       # what the server can do, for GET /api/models
│   ├── align.py         # joins transcription segments to speaker turns
│   ├── live.py          # the /api/stream websocket: protocol and sessions
│   ├── stream.py        # live transcription core: pauses, phrases, per-phrase transcription
│   ├── url_source.py    # URL sources for /api/stream: vetting the address, running ffmpeg
│   ├── speech_gate.py   # voice detector that drops text nobody spoke
│   ├── metrics.py       # Prometheus metrics for GET /metrics
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

### विकास (Development)

सिस्टम पैकेज `ffmpeg` और `libsndfile1` मौजूद होने चाहिए। रनटाइम और डेव निर्भरताएँ इंस्टॉल करें:

```bash
pip install -e ".[dev]"
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
make typecheck      # mypy
```

टेस्ट सूट Whisper बैकएंड को स्टब कर देता है, इसलिए यह HTTP परत (request_id, error श्रेणियाँ, model pool semantics) को कवर करता है और बिना मॉडल डाउनलोड किए या GPU की आवश्यकता के कुछ ही सेकंड में चलता है।

### लाइसेंस

[MIT](../LICENSE)
