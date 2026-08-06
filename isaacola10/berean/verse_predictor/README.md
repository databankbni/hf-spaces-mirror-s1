# Bible Verse Predictor (voice → verse)

Speak (recite) part of a Bible verse and the tool tells you which verse it is —
returning the reference (e.g. `John 3:16`), the full KJV text, and a confidence
level.

## How it works

```
🎙 microphone ─▶ Whisper (speech-to-text) ─▶ transcript
                                                 │
              hybrid retrieval over every verse of every translation
              (semantic embeddings + lexical fuzzy match), grouped by verse
                                                 │
                          📖 closest verses, each with all translations
```

- **Speech-to-text:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (Whisper on the CTranslate2 backend), running locally — no API key, no
  internet after the model downloads.
- **Verse matching:** every verse of every translation is embedded once with
  `all-MiniLM-L6-v2` (sentence-transformers). At query time the transcript is
  embedded and compared by cosine similarity, then the top candidates are
  re-ranked with a lexical fuzzy score (`rapidfuzz`). Matches are **grouped by
  verse reference**, so the same verse quoted across translations collapses
  into one hit, with every translation of that verse attached.

This is **retrieval**, not a classifier trained from scratch — the right tool
for picking 1 verse out of ~124k. No training step, no labelled data needed.

## Translations

The corpus is **dynamic**: every `*.json` file in `data/versions/` is loaded
automatically. Bundled (all public domain): **KJV, ASV, YLT, BBE**.

```bash
python download_versions.py   # fetches the translations into data/versions/
```

Add more public-domain codes to `VERSIONS` in `download_versions.py`, re-run
it, then rebuild the index. Modern translations (NIV, ESV, NKJV, Amplified,
GNT, …) are copyrighted and cannot be bundled.

## Setup

```bash
cd verse_predictor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python download_versions.py   # download the translation texts
python build_index.py         # embed the whole corpus once (cached to data/*.npy)
```

## Use

```bash
# Record from the mic (press Enter to stop), then identify the verse:
python predict.py

# Or record a fixed duration:
python predict.py --seconds 6

# Test without a mic — match typed text:
python predict.py --text "for god so loved the world that he gave his only son"

# Transcribe an existing audio file (needs ffmpeg for mp3):
python predict.py --file recording.wav
```

Example output:

```
Heard: "for god so loved the world that he gave his only begotten son"
============================================================
  📖  John 3:16   [high confidence]
  For God so loved the world, that he gave his only begotten Son...
============================================================
```

## Files

| File | Role |
|------|------|
| `corpus.py` | Load + clean the KJV JSON into a flat verse list |
| `build_index.py` | Embed all verses once, cache vectors to `data/` |
| `matcher.py` | Hybrid semantic + lexical retrieval |
| `transcribe.py` | Whisper wrapper (mic array or audio file) |
| `record.py` | Microphone capture (16 kHz mono) |
| `predict.py` | CLI that ties it all together |

## Tuning

- **Accuracy vs speed (ASR):** `--model small.en` is more accurate than the
  default `base.en`; `tiny.en` is faster.
- **Match blend:** adjust `SEMANTIC_WEIGHT` / `LEXICAL_WEIGHT` in `matcher.py`.
- **Translations:** see the [Translations](#translations) section — add a JSON
  to `data/versions/` and rebuild.

## Web API + UI

`server.py` exposes the same pipeline over HTTP for the Next.js front end in
[`../web`](../web):

```bash
uvicorn server:app --port 8000
```

Endpoints (all return verses grouped by reference with every translation
attached):

| Method | Path            | Body / params                        |
|--------|-----------------|--------------------------------------|
| GET    | `/api/versions` | —  (lists available translations)    |
| POST   | `/api/predict`  | multipart `audio`, `?version=`       |
| POST   | `/api/search`   | JSON `{text, version, top_k}`        |

`version` defaults to `all`; pass a code (e.g. `KJV`) to search one
translation. See `../web/README.md` to run the UI.
