---
title: ThoxOS Web Edition
emoji: 🌐
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

# ThoxOS Web Edition

Local-first AI chat. THOX fleet by default (ThoxRoute · ThoxMini-3B · ThoxMythos-9B
via the public Space bridge), ThoxVisual Blocks, ThoxCanvas Studio, ThoxSpeech
voice (Whisper / ElevenLabs), ThoxSearch grounding, file/image upload, and
response export + artifact sharing via Vercel Blob.

All chat data stays in the browser (IndexedDB). The only server piece is
`POST /api/blob-upload`, which publishes a shared artifact via `@vercel/blob`
using the `BLOB_READ_WRITE_TOKEN` Space secret (never exposed to the client).
