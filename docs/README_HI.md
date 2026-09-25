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

#### कई मॉडल

`STT_MODELS` स्टार्टअप पर कई ट्रांसक्रिप्शन मॉडल लोड करता है, हर एक का अपना पूल होता है, और हर अनुरोध `model` से उनमें से एक चुन सकता है। प्रविष्टियाँ अल्पविराम से अलग `backend:model[@pool]` रूप में होती हैं:

```bash
STT_MODELS=whisper:turbo@2,whisper:small.en@1,parakeet:nvidia/parakeet-tdt-0.6b-v3@1
STT_DEFAULT_MODEL=turbo    # बिना `model` वाले अनुरोध का मॉडल; खाली होने पर पहली प्रविष्टि
```

चुनाव केवल स्टार्टअप पर लोड किए गए मॉडलों में से होता है: कोई अनुरोध कभी डाउनलोड या लोडिंग शुरू नहीं करता, और जो मॉडल लोड नहीं है उसे `400` के साथ अस्वीकार किया जाता है। सूची का हर मॉडल सर्वर चलने तक मेमोरी लेता है, मोटे तौर पर पूरी सूची पर जोड़ा गया `वर्कर x (पूल x मॉडल का आकार)`, और साथ में डायराइज़र। GPU पर `turbo@2,small@1,parakeet@1` प्रति प्रोसेस लगभग 12 + 2 + 3 = 17 GB है। gunicorn में हर sync वर्कर एक समय में एक ही अनुरोध संभालता है, इसलिए हर प्रविष्टि को `@1` दें और `GUNICORN_WORKERS` से स्केल करें। बिना `@pool` वाली प्रविष्टि को `STT_POOL_SIZE` मिलता है, जो Docker के बाहर 8 है, इसलिए `@N` स्पष्ट रूप से लिखें। कई बड़े मॉडल लोड करने में एक से अधिक समय लगता है, इसलिए यदि स्टार्टअप के दौरान कंटेनर unhealthy चिह्नित हो जाए तो compose फ़ाइल में healthcheck का `start_period` बढ़ाएँ।

`STT_MODELS` खाली होने पर `STT_BACKEND`, `WHISPER_MODEL` और `PARAKEET_MODEL` पहले की तरह एकमात्र मॉडल चुनते हैं, और सर्वर ठीक वही लोड करता है जो पहले करता था; प्रतिक्रियाओं में केवल नए फ़ील्ड जुड़ते हैं। इसके सेट होने पर ये चर तय नहीं करते कि क्या लोड होगा। Docker में `STT_MODELS` और `STT_DEFAULT_MODEL` को `.env` में रखें, compose के `environment:` ब्लॉक में नहीं, जो `.env` को ओवरराइड करता है। Parakeet प्रविष्टि के लिए अब भी `PARAKEET=true` के साथ बनी इमेज चाहिए, और अज्ञात बैकएंड, दो बार सूचीबद्ध एक ही वेट (`turbo` और `large-v3-turbo`) या सूची में न मौजूद `STT_DEFAULT_MODEL` होने पर सर्वर शुरू होने से इनकार करता है। फ़ाइल पथ के रूप में दिया गया मॉडल `.pt` के बिना उसके फ़ाइल नाम से उपलब्ध कराया जाता है, ताकि पथ कभी किसी क्लाइंट तक न पहुँचे। `STT_DEFAULT_MODEL` ऐसी प्रविष्टि को उसी नाम से या `STT_MODELS` में ठीक जैसा लिखा है उसी पथ से बता सकता है, और उसकी भाषाएँ उस चेकपॉइंट की होती हैं जिसका नाम फ़ाइल नाम में है: `/models/large-v3.pt` वही जानता है जो `large-v3` जानता है। दो प्रविष्टियाँ जो एक ही नाम से परोसी जाएँगी (`/a/model.pt` और `/b/model.pt`), या कोई प्रविष्टि जो किसी बैकएंड के नाम से परोसी जाएगी (`/models/parakeet.pt`), स्टार्टअप पर सर्वर को रोक देती हैं।

### त्वरित प्रारंभ (Docker)

सर्वर चलाने का सबसे आसान तरीका Docker के साथ है। मॉडल फ़ाइलें होस्ट पर `./models` में कैश की जाती हैं, इसलिए वे कंटेनर के पुनर्निर्माण के बाद भी बनी रहती हैं।

```bash
git clone https://github.com/wachawo/speech-to-text.git
cd speech-to-text

docker compose up --build                              # GPU (CUDA 13.0)
docker compose -f docker-compose-cpu.yml up --build    # CPU only
```

GPU बिल्ड को होस्ट पर `nvidia-container-toolkit` की आवश्यकता होती है। पहली बार चलाने पर Whisper मॉडल `./models` में डाउनलोड हो जाता है।

### वेब UI

`docker compose up` साथ में `stt_www` भी शुरू करता है, एक nginx कंटेनर जो ब्राउज़र UI सर्व करता है और `/api/` को सर्वर तक आगे भेजता है, ताकि UI और API एक ही पते पर रहें।

| लिसनर | डिफ़ॉल्ट पोर्ट | किससे सेट करें         |
| ----- | ----------- | ------------------ |
| http  | `8080`      | `STT_WWW_PORT`     |
| https | `8443`      | `STT_WWW_TLS_PORT` |

`http://<host>:8080` खोलें। **TRANSCRIBE** के दो स्रोत हैं। **FILE** एक ऑडियो फ़ाइल अपलोड करता है। **DEVICE** किसी ऑडियो इनपुट से लाइव ट्रांसक्राइब करता है: माइक्रोफ़ोन या हेडसेट, Linux पर `Monitor of ...` स्रोत जो स्पीकर या हेडफ़ोन से बजने वाली हर चीज़ को लाता है, या `Tab or screen audio`, जो ब्राउज़र टैब में बज रही चीज़ के लिए है, या जहाँ OS अनुमति दे वहाँ पूरे सिस्टम के लिए। दोनों ही स्थितियों में परिणाम फ़ॉर्म के नीचे सादे टेक्स्ट के रूप में दिखता है या, डायराइज़ेशन सक्षम होने पर, हर वाक्यांश के लिए एक ब्लॉक के रूप में जिसमें उसका स्पीकर और समय होता है, हर स्पीकर अपने रंग में, और जिन वाक्यांशों में दो लोग एक साथ बोले वे चिह्नित होते हैं; लाइव वाक्यांश स्पीकर के रुकने के लगभग एक सेकंड बाद दिखता है। परिणाम को कॉपी किया जा सकता है या TXT अथवा JSON के रूप में डाउनलोड किया जा सकता है। कई मॉडल लोड होने पर (`STT_MODELS`), मोड और भाषा के पास एक मॉडल चयन दोनों स्रोतों के लिए मॉडल चुनता है, जो `GET /api/models` से भरा जाता है, और भाषा सूची चुने गए मॉडल के अनुसार बदलती है। **MODELS** वही दिखाता है जो `GET /api/models` बताता है। जब `STT_TOKENS` सेट होता है, तो UI एक बार टोकन माँगता है और उसे ब्राउज़र में रखता है।

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

`GET /api/health` पूलों की स्थिति लौटाता है। शीर्ष-स्तर के `pool_size` और `available` डिफ़ॉल्ट मॉडल का वर्णन करते हैं, यानी वह मॉडल जिसकी प्रतीक्षा बिना `model` वाला अनुरोध करता है; `available` का 0 तक गिरना मतलब उसका हर इंस्टेंस इस समय काम में है। `models` हर लोड किए गए मॉडल को उसके id से बताता है:

```json
{ "status": "ok", "pool_size": 2, "available": 1, "diarize": false, "default_model": "turbo",
  "models": { "turbo": { "backend": "whisper", "pool_size": 2, "available": 1 },
              "nvidia/parakeet-tdt-0.6b-v3": { "backend": "parakeet", "pool_size": 1, "available": 1 } } }
```

जब `STT_TOKENS` सेट होता है, तो `default_model` और `models` केवल वैध टोकन वाले अनुरोध के जवाब में शामिल होते हैं: `GET /api/models` की तरह ये सर्वर का कॉन्फ़िगरेशन बताते हैं। बिना टोकन वाला हेल्थचेक अब भी `status`, `pool_size`, `available` और `diarize` पाता है।

`POST /api/stt` या तो `file` नाम का `multipart/form-data` फ़ील्ड या कच्चा `audio/*` बॉडी स्वीकार करता है। वैकल्पिक `model` (क्वेरी स्ट्रिंग या फ़ॉर्म फ़ील्ड) लोड किए गए मॉडलों में से एक चुनता है: उसका id, कोई उपनाम (`large-v3-turbo`, `parakeet-tdt-0.6b-v3`), `backend:model` रूप, या केवल बैकएंड का नाम, जिसका अर्थ है डिफ़ॉल्ट मॉडल यदि वह उसी बैकएंड का है, अन्यथा उस बैकएंड का पहला मॉडल। `model` न होने पर डिफ़ॉल्ट मॉडल उत्तर देता है। वैकल्पिक `language` (क्वेरी स्ट्रिंग या फ़ॉर्म फ़ील्ड) उस अनुरोध के लिए सर्वर के डिफ़ॉल्ट को बदल देता है; `auto` अपने आप पहचान करता है। सफल होने पर यह टेक्स्ट, बीते हुए सेकंड, ट्रांसक्राइब करने वाला मॉडल और भाषा लौटाता है: वह कोड जो Whisper ने पहचाना या इस्तेमाल किया (केवल-अंग्रेज़ी मॉडल के लिए हमेशा `en`), या Parakeet के लिए `null`, जो भाषा नहीं बताता।

```bash
curl -X POST 'localhost:5099/api/stt?model=turbo&language=en' -F file=@speech.mp3
```

```json
{ "text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en" }
```

भाषा कोड (`ru`) के रूप में या उसके अंग्रेज़ी नाम (`russian`) के रूप में दी जा सकती है; जिसे मॉडल नहीं जानता उसे ट्रांसक्रिप्शन के बीच में विफल होने के बजाय `400` के साथ अस्वीकार किया जाता है। हर मॉडल क्या जानता है, यह `GET /api/models` बताता है। `language` की जाँच कितनी सख़्त है, यह मॉडल पर और इस पर निर्भर करता है कि अनुरोध ने मॉडल का नाम दिया या नहीं:

| मॉडल | कौन सा `language` लेता है | बिना `model` का अनुरोध | `model` वाला अनुरोध |
| --- | --- | --- | --- |
| बहुभाषी Whisper | उसकी सूची का कोड या अंग्रेज़ी नाम | सूची के बाहर `400 Unsupported language` | वही |
| केवल-अंग्रेज़ी Whisper (`.en`) | `en` और `auto` | कोई दूसरा ज्ञात कोड अंग्रेज़ी की तरह ट्रांसक्राइब होता है | `400 Unsupported language` |
| Parakeet | कोई नहीं, यह भाषा ख़ुद पहचानता है | कोई भी मान स्वीकार और अनदेखा | उसकी सूची का कोड, अन्यथा `400` |

Parakeet केवल कोड स्वीकार करता है, अंग्रेज़ी नाम नहीं, और जिस भाषण के बारे में वह अनिश्चित हो उसे बिना बताए छोड़ सकता है: कई भाषाओं वाली रिकॉर्डिंग में वह अल्पसंख्यक भाषा के लिए कुछ भी न लौटाए, ऐसा हो सकता है।

ऐसा Whisper फ़ाइल पाथ जिसका नाम किसी ज्ञात चेकपॉइंट से मेल नहीं खाता, जैसे `/models/my-large-v3-finetune.pt` पर रखा फ़ाइन-ट्यून, उसकी भाषा सूची केवल उस नाम से अनुमानित होती है। इसलिए `model` के बिना आया अनुरोध उसे पहले की तरह कोई भी ज्ञात कोड दे देता है; जो अनुरोध उसका नाम लेता है, उसे अब भी अनुमानित सूची से जाँचा जाता है।

इन दो विकल्पों की `400` त्रुटियाँ हैं `Invalid model` (कोई बैकएंड यह नाम नहीं जानता), `Model not loaded` (असली मॉडल जिसे इस सर्वर ने लोड नहीं किया), `Invalid language` (यह कोई भाषा ही नहीं) और `Unsupported language` (असली भाषा जिसे चुना गया मॉडल नहीं लेता)। चारों ऑडियो डिकोड होने से पहले लौटाई जाती हैं।

`GET /api/models` बताता है कि यह सर्वर क्या-क्या रखता है, ताकि क्लाइंट को अनुमान न लगाना पड़े। हर लोड किए गए मॉडल की अपनी पंक्ति होती है, और ऐसा ही हर उस ट्रांसक्राइबर का जिसका कोई मॉडल लोड नहीं (`selectable: false`) और डायराइज़र का भी। हर पंक्ति अपनी भाषा सूची लाती है, क्योंकि ये समूह सचमुच अलग हैं और मिलाई गई सूची अपने आप में हर मॉडल के लिए ग़लत होगी।

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

`id` वह है जो अनुरोध `model` के रूप में भेजता है, और ठीक एक पंक्ति में `default: true` होता है: उसका id `default_model` है और उसका बैकएंड शीर्ष-स्तर का `default` है। `pool_size` और `available` उस मॉडल के पूल का वर्णन करते हैं। `status` तब `loaded` होता है जब मॉडल के इंस्टेंस मौजूद हों, खाली हों या व्यस्त, `installed` तब जब वेट डिस्क पर हों पर अभी कुछ लोड न हुआ हो, और बाक़ी मामलों में `absent`। जो बैकएंड कॉन्फ़िगर है पर इंस्टॉल नहीं, वह केवल `absent` बताता है; कारण लॉग में जाता है। `accepts_language` बताता है कि उस बैकएंड के लिए `?language=` का कोई मतलब है या नहीं। डायराइज़र ख़ाली सूची के बजाय `null` भाषाएँ बताता है, क्योंकि वह किसी भी भाषा में टेक्स्ट नहीं बनाता।

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

दो ट्रांसक्रिप्शन बैकएंड उपलब्ध हैं। **Whisper** डिफ़ॉल्ट है और `language` स्वीकार करता है। **Parakeet** (`nvidia/parakeet-tdt-0.6b-v3`) 25 यूरोपीय भाषाएँ कवर करता है, भाषा ख़ुद पहचानता है और इसलिए कोई `language` तर्क स्वीकार ही नहीं करता, जिसे `GET /api/models` `accepts_language: false` के रूप में बताता है। इसके लिए `PARAKEET=true` के साथ बनी इमेज चाहिए। पूरे सर्वर के लिए इसे `STT_BACKEND=parakeet` से चुनें, या `STT_MODELS` के ज़रिए Whisper के साथ लोड करें और हर अनुरोध में `model` से चुनें। अनुरोध केवल स्टार्टअप पर लोड किए गए मॉडलों में से चुनता है, और हर लोड किया गया मॉडल हर वर्कर में अपने वेट रखता है, इसलिए मेमोरी वर्करों की संख्या गुणा पूलों का योग होती है।

कोई भी बैकएंड ओवरलैप-सजग (overlap-aware) नहीं है। NVIDIA का ओवरलैप-सजग मॉडल केवल एक NeMo चेकपॉइंट के रूप में आता है, और NeMo इस प्रोजेक्ट के CUDA बिल्ड से भिन्न PyTorch को पिन करता है, इसलिए यहाँ उसे इंस्टॉल नहीं किया जा सकता।

`POST /api/transcript` यह उत्तर देता है कि **किसने क्या कहा**: यह एक ही ऑडियो पर डायराइज़ेशन और ट्रांसक्रिप्शन दोनों चलाता है और उन्हें समय के आधार पर जोड़ता है। इसके लिए डायराइज़ेशन सक्षम होना चाहिए, अन्यथा यह `503` लौटाता है। यह `/api/stt` जैसे ही `model` और `language` स्वीकार करता है और ट्रांसक्राइब करने वाले मॉडल का नाम `model` में देता है।

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

`turns` डायराइज़र का कच्चा आउटपुट है और `segments` उन दोनों का जोड़ (join) है; इन्हें अलग-अलग रखा गया है ताकि जो कॉलर इस आरोपण (attribution) पर भरोसा न करे, वह फिर भी देख सके कि डायराइज़र ने क्या कहा। `text` सादा ट्रांसक्रिप्ट है, ठीक वही जो उसी फ़ाइल के लिए `/api/stt` लौटाता है। जिस वाक्यांश को कोई भी turn कवर नहीं करता, उसे निकटतम स्पीकर को सौंपने के बजाय वह `"speaker": null` रखता है।

`overlap` उस वाक्यांश को चिह्नित करता है जिसके दौरान कोई और भी बोल रहा था। NVIDIA स्पष्ट रूप से कहता है कि किसी पारंपरिक एकल-स्पीकर मॉडल को डायराइज़ेशन के साथ जोड़ना, ओवरलैपिंग वाक् के लिए बनाए गए मॉडल के समतुल्य नहीं है: निकाले गए समय-अंतराल में वे सभी आवाज़ें मौजूद रहती हैं जो उस पर ओवरलैप करती हैं, इसलिए ऐसे वाक्यांश आपस में मिल सकते हैं या ग़लत स्पीकर के शब्द चुन सकते हैं। `overlap` से चिह्नित सेगमेंट को उस जगह के रूप में लें जहाँ ट्रांसक्रिप्ट सबसे कम भरोसेमंद है।

`/api/stream` **लाइव ट्रांसक्रिप्शन** के लिए एक वेबसॉकेट है: ऑडियो रिकॉर्ड होते-होते भीतर जाता है, और हर वाक्यांश स्पीकर के रुकने के लगभग एक सेकंड बाद वापस आता है। JSON टेक्स्ट संदेश नियंत्रण ले जाते हैं, बाइनरी संदेश ऑडियो:

1. क्लाइंट `{"type": "start", "model": "turbo", "language": "ru", "diarize": true, "token": "<token>"}` भेजता है। `type` को छोड़कर हर फ़ील्ड वैकल्पिक है। `model` लोड किए गए मॉडलों में से एक को उसी तरह चुनता है जैसे `/api/stt` पर `model` करता है, और भाषा उसी मॉडल के विरुद्ध जाँची जाती है; इसके बिना डिफ़ॉल्ट मॉडल काम करता है और भाषा को पहले की तरह केवल इस बात के लिए जाँचा जाता है कि वह कोई भाषा है या नहीं, इसलिए डिफ़ॉल्ट मॉडल जिस कोड को नहीं जानता वह किसी वाक्यांश को ट्रांसक्राइब करते समय विफल होता है। `token` वह तरीका है जिससे ब्राउज़र प्रमाणीकरण करता है, क्योंकि वह वेबसॉकेट पर हेडर सेट नहीं कर सकता; अन्य क्लाइंट इसके बजाय हैंडशेक पर `Authorization: Bearer <token>` भेज सकते हैं।
2. सर्वर `{"type": "ready", "sample_rate": 16000, "backend": "whisper", "model": "turbo", "language": "ru", "diarize": true, "source": "client"}` के साथ उत्तर देता है।
3. क्लाइंट कच्चा PCM - signed 16-bit, little-endian, मोनो, 16 kHz - किसी भी आकार के बाइनरी संदेशों के रूप में भेजता है, और काम पूरा होने पर `{"type": "stop"}` भेजता है।
4. सर्वर हर वाक्यांश के लिए एक `segment`, लगभग हर सेकंड एक `progress`, और बंद करने से पहले `done` भेजता है:

```json
{ "type": "segment", "id": 3, "start": 6.88, "end": 8.2, "text": "This is the second speaker.", "speaker": 1, "overlap": false }
{ "type": "progress", "seconds": 12.3 }
{ "type": "done", "segments": 10, "seconds": 21.87, "elapsed": 22.08 }
```

ऑडियो कहीं और से भी आ सकता है। स्टार्ट संदेश में `"source": "url", "url": "https://..."` होने पर क्लाइंट कोई ऑडियो नहीं भेजता: सर्वर उस पते पर मौजूद स्ट्रीम को ffmpeg के ज़रिए, स्रोत की अपनी गति से, तब तक पढ़ता है जब तक वह समाप्त न हो जाए या क्लाइंट `stop` न भेज दे। इंटरनेट रेडियो, HLS, RTMP, RTSP और SRT काम करते हैं; स्कीम `http`, `https`, `rtmp`, `rtmps`, `rtsp` या `srt` होनी चाहिए, और ffmpeg को केवल नेटवर्क प्रोटोकॉल तक सीमित रखा गया है, इसलिए कोई URL या प्लेलिस्ट उससे कोई स्थानीय फ़ाइल नहीं पढ़वा सकती। फिर भी इससे सर्वर क्लाइंट द्वारा चुना गया पता प्राप्त करता है, जिसमें सर्वर के अपने नेटवर्क के पते भी शामिल हैं: जिस भी सर्वर तक दूसरे पहुँच सकते हैं, उस पर `STT_TOKENS` सेट करें।

विफलता एक अकेला `{"type": "error", "error": "<category>", "request_id": "..."}` होती है जिसके बाद कनेक्शन बंद हो जाता है; इसकी श्रेणियाँ HTTP त्रुटि श्रेणियाँ हैं, साथ में `Invalid start message`, `Invalid audio frame`, `Invalid stream URL` और `Stream source failed`।

एक वाक्यांश 0.6 सेकंड के विराम पर समाप्त होता है, या 15 सेकंड से लंबा हो जाने पर अपने सबसे शांत क्षण पर, और उसे अलग से ऐसे मॉडल से ट्रांसक्राइब किया जाता है जो उसी पूल से उधार लिया जाता है जिससे अपलोड के लिए लिया जाता है, इसलिए व्यस्त पूल लाइव वाक्यांशों को विफल करने के बजाय केवल विलंबित करता है। `diarize` के साथ, डायराइज़र अपने स्ट्रीमिंग मोड में चलता है और एक चंक से दूसरे चंक तक स्पीकर कैश बनाए रखता है, इसलिए पूरे सत्र में एक स्पीकर की संख्या वही रहती है। यह सॉकेट केवल तब मौजूद होता है जब सर्वर uvicorn के अंतर्गत चलता है (`python3 stt_server.py`, Docker का डिफ़ॉल्ट): Flask डिबग सर्वर और gunicorn के sync वर्कर वेबसॉकेट नहीं समझते।

अपलोड `MAX_CONTENT_LENGTH_MB` (डिफ़ॉल्ट रूप से 10 MB) तक सीमित हैं; बड़ा बॉडी `413` लौटाता है।

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
python3 stt_client.py --model small.en --language en speech.mp3
python3 stt_client.py --list
```

`--model` और `--language` (`--model=NAME` रूप में भी) केवल दिए जाने पर भेजे जाते हैं, अन्यथा सर्वर का डिफ़ॉल्ट लागू होता है; हर परिणाम पंक्ति सर्वर द्वारा इस्तेमाल किया गया मॉडल और भाषा दिखाती है। `--list` डिफ़ॉल्ट मॉडल और हर मॉडल के लिए एक पंक्ति छापता है, जिसमें उसकी स्थिति, क्या अनुरोध उसे चुन सकता है, उसका पूल और उसकी भाषाएँ होती हैं।

`--stream` एक फ़ाइल को बोलने की गति से `/api/stream` में चलाता है और हर वाक्यांश लौटते ही उसे प्रिंट करता है, स्पीकर आरोपण के लिए `--speakers` के साथ:

```bash
python3 stt_client.py --stream meeting.wav --speakers --model turbo --language ru
```

### पर्यावरण चर (Environment variables)

`.env` को सर्वर और क्लाइंट दोनों द्वारा `python-dotenv` के माध्यम से लोड किया जाता है।

| Variable                | Default                 | उद्देश्य                                             |
| ----------------------- | ----------------------- | --------------------------------------------------- |
| `STT_HOST`              | `0.0.0.0`               | सर्वर बाइंड पता                                      |
| `STT_PORT`              | `5099`                  | सर्वर पोर्ट                                          |
| `STT_POOL_SIZE`         | `8`                     | प्रति मॉडल इंस्टेंस; बिना `@pool` वाली `STT_MODELS` प्रविष्टि का डिफ़ॉल्ट |
| `STT_TOKENS`            | (खाली)                  | अल्पविराम से अलग किए गए मान्य टोकन; खाली होने पर auth निष्क्रिय |
| `STT_DEBUG`             | `false`                 | Flask डिबग मोड                                      |
| `MAX_CONTENT_LENGTH_MB` | `10`                    | MB में अधिकतम अपलोड आकार; बड़ा बॉडी `413` लौटाता है   |
| `CORS_ORIGINS`          | `*`                     | अनुमत CORS मूल: `*` या अल्पविराम से अलग की गई सूची    |
| `GUNICORN_WORKERS`      | `4`                     | वर्कर प्रक्रियाएँ (केवल gunicorn)                     |
| `LOG_LEVEL`             | `INFO`                  | लॉगिंग स्तर                                          |
| `LOG_ACCESS`            | `false`                 | uvicorn एक्सेस लाइनें लॉग करें                       |
| `WHISPER_MODEL`         | `small.en`              | Whisper मॉडल नाम (जैसे `small.en`, `turbo`) (जब `STT_MODELS` खाली हो) |
| `WHISPER_LANGUAGE`      | `en`                    | हर Whisper मॉडल की डिफ़ॉल्ट भाषा |
| `WHISPER_DOWNLOAD_ROOT` | `models`                | मॉडल कैश डायरेक्टरी (Docker में `/opt/models`)        |
| `COMPUTE_TYPE`          | `auto`                  | `cpu`, `cuda`, या `auto`                             |
| `STT_BACKEND`           | `whisper`               | ट्रांसक्रिप्शन बैकएंड: `whisper` या `parakeet` (जब `STT_MODELS` खाली हो) |
| `STT_MODELS`            | (खाली)                  | एक साथ कई मॉडल: अल्पविराम से अलग `backend:model[@pool]` |
| `STT_DEFAULT_MODEL`     | (खाली)                  | बिना `model` वाले अनुरोध का मॉडल; खाली होने पर `STT_MODELS` की पहली प्रविष्टि |
| `PARAKEET_MODEL`        | `nvidia/parakeet-tdt-0.6b-v3` | Parakeet मॉडल id                                    |
| `PARAKEET_DOWNLOAD_ROOT`| `models`                | Parakeet मॉडल कैश डायरेक्टरी                         |
| `DIARIZE_ENABLED`       | `false`                 | `POST /api/diarize` सक्षम करें (`DIARIZE=true` इमेज चाहिए) |
| `DIARIZE_MODEL`         | `nvidia/Nemotron-3-Diarization` | डायराइज़ेशन मॉडल id                                  |
| `DIARIZE_POOL_SIZE`     | `1`                     | पहले से लोड किए गए डायराइज़र इंस्टेंस                 |
| `DIARIZE_DOWNLOAD_ROOT` | `models`                | डायराइज़ेशन मॉडल कैश डायरेक्टरी                       |
| `DIARIZE_THRESHOLD`     | `0.5`                   | स्पीकर सक्रियता संभावना जिसे वाक् माना जाए             |
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
