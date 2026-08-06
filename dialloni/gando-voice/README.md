---
title: Gando Voice
emoji: 🎙️
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-4.0
---

# Gando Voice — Pulaar TTS + ASR

Internal voice engine for [Gando AI](https://gando-ai.up.railway.app). Wraps Meta MMS
(`facebook/mms-tts-ful`, `facebook/mms-1b-all` with the Fula adapter) behind two endpoints:

- `POST /tts` `{text, rate}` → wav — Pulaar speech from Latin text
- `POST /asr` `{audio (base64), mime}` → `{text}` — Latin Pulaar transcription

MMS models are CC-BY-NC 4.0 — research/beta use.
