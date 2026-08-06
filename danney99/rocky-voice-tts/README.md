---
title: Rocky Voice TTS
emoji: 🪨
colorFrom: blue
colorTo: gray
sdk: gradio
app_file: app.py
pinned: false
short_description: Piper (en_US-lessac-low) TTS voice for Reachy Mini.
tags:
  - reachy-mini-tool
  - mcp
  - tts
---

# Rocky Voice TTS

Text-to-speech in the Rocky (Project Hail Mary) human voice using Piper `en_US-lessac-low`.
API: `POST /gradio_api/call/tts_b64` with `{"data": ["your text"]}` returns an event id; `GET /gradio_api/call/tts_b64/<event_id>` streams the result: `{sample_rate, audio_b64}` (base64 WAV, int16 mono 16 kHz). Used by the Reachy Mini Rocky app.

<!-- build-kick 2026-07-15 -->
