# Berean — Web UI

A Next.js (App Router, TypeScript, Tailwind) front end for the Bible verse
predictor. **Speak or type** part of a verse and it shows the closest
scriptures across **multiple translations** — pick one translation or search
them all, and compare a matched verse side-by-side across versions.

## Architecture

```
Browser ──record (MediaRecorder)──▶ Next.js route handler ──▶ FastAPI (Python)
  │                                   /app/api/predict             │
  └──────────────── JSON result ◀──────── proxy ◀──── Whisper + verse retrieval
```

- The **browser** records audio with the `MediaRecorder` API (webm/opus).
- The Next.js **route handler** (`app/api/predict/route.ts`) proxies the audio
  to the Python service. This keeps the browser talking only to the Next.js
  origin (no CORS) and keeps the backend URL server-side.
- The **Python FastAPI service** (`../verse_predictor/server.py`) runs Whisper
  speech-to-text + hybrid semantic/lexical retrieval over all translations,
  and returns verses grouped by reference.
- The **translation list is dynamic**: the dropdown is populated from
  `GET /api/versions`, and the text path (`app/api/search/route.ts`) forwards
  the chosen `version` to the model service. A typed query skips Whisper.

## Run it (two processes)

**1. Start the Python model service** (from `../verse_predictor`):

```bash
cd ../verse_predictor
source .venv/bin/activate
python download_versions.py    # once: fetch the translation texts
python build_index.py          # once: embed the corpus
uvicorn server:app --port 8000
```

**2. Start the web app** (from this `web/` folder):

```bash
npm install
npm run dev
```

Open http://localhost:3000 and click the mic. Your browser will ask for
microphone permission the first time.

## Config

`PYTHON_API_URL` (in `.env.local`) points the proxy at the Python service.
Defaults to `http://127.0.0.1:8000`.

## Notes

- Microphone capture requires a **secure context**: `localhost` works in dev;
  in production you must serve the site over **HTTPS**.
- First request after starting the Python server is slower while the Whisper
  and embedding models load into memory; subsequent requests are fast.
