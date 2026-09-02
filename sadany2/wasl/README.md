---
title: Wasl Reader
emoji: 📗
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Wasl — Arabic reading fluency

Forced alignment against a known text. Not recognition: the reader has been asked
to say a specific line, so the task is finding where each character landed, which
a CTC alignment path solves exactly and cannot fake.

Per-character timings separate three productions that sound similar in a
transcript and are pedagogically very different:

| | signature |
|---|---|
| fluent | one connected run, no long silence before or inside |
| assembled | long silence, then the characters arrive together |
| spelled | silences *between* the characters of one word |

## Run locally

    pip install -r requirements.txt
    uvicorn app:app --reload --port 7860

## Deploy free on Hugging Face Spaces

1. Create a Space, SDK **Docker**, hardware **CPU basic (free)**
2. Push this directory to it
3. First boot downloads ~1.2GB of model weights; `/health` reports when warm

## API

    POST /align   audio=<file>  words="الولد في البيت"
    POST /choose  audio=<file>  candidates="كتاب كاتب مكتوب كتب"
