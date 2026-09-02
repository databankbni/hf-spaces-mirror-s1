---
title: Türkçe PII Guard
emoji: 🛡️
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
license: apache-2.0
short_description: Türkçe metindeki kişisel verileri maskeler (50 etiket)
---

Model: [melikegks/turkish-pii-guard-0.8b](https://huggingface.co/melikegks/turkish-pii-guard-0.8b)

50 etiket · talimat koşullu maskeleme. Aynı metin farklı politikalarla farklı
maskelenir.

```
zor test (22)                22/22   %100
Çağrı benchmark (903)        0,922   şema-nötr
kendi validation (3.000)     %98,17  tam eşleşme · entity F1 %99,83
kör final holdout (1.600)    %75,81  tam eşleşme · entity F1 %98,15
```

CPU'da bir üretim ~15-30 sn sürer. Akıcı demo için Space donanımını
**T4 small** veya üstü yap.
