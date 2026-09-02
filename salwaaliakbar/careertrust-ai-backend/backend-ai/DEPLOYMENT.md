# Deploying backend-ai to Render

## Render setup (native Python service — no Docker)
1. New → Web Service → pick this repo → **Environment: Python 3** (set "Root Directory" to `backend-ai` if the repo contains more than this service).
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Python version**: this repo pins `3.11.9` via `.python-version` — without it Render defaults to the latest Python (e.g. 3.14), and old pinned deps like `pillow==9.5.0` fail to build from source on anything newer than what they were released for. If Render still doesn't pick it up, set `PYTHON_VERSION=3.11.9` explicitly as an environment variable on the service.
4. Environment variables (Render dashboard → Environment):
   - `API_KEY` — long random string; the Node backend must send this same value as `AI_API_KEY`/`X-API-Key`.
   - `ALLOWED_ORIGINS` — your Vercel frontend URL, e.g. `https://your-app.vercel.app`. Add the Render backend URL too only if it calls this service directly from a browser context (server-to-server calls don't need CORS).
   - `DEV_BYPASS_FACE` — leave unset or `false`.
   - `HF_MODEL_REPO` — e.g. `salwaaliakbar/careertrust-sentiment-distilbert` (see "The sentiment model" below).
5. Render sets `$PORT` automatically; the Start Command above reads it.

A `Dockerfile` also exists in this folder as an alternative (e.g. for a Hugging Face Space) but isn't required for a plain Render Python web service — ignore it unless you switch Render's environment to Docker.

## Free-tier RAM warning
This service loads, at minimum: spaCy `en_core_web_lg` (~560MB on disk), a DistilBERT encoder, a MiniLM sentence-transformer, insightface's `buffalo_l` pack, and PyTorch itself. Loaded together in one process this is comfortably over Render's free instance limit (512MB RAM) — expect it to be OOM-killed on first request even though the build succeeds.

Two ways forward:
- **Try it anyway** — Render's free tier costs nothing to attempt; if it OOM-kills, you'll see it immediately in the logs.
- **Move this one service to a Hugging Face Space** (Docker SDK, free tier gives more RAM than Render's free instance) if it does OOM. The `Dockerfile` in this folder works there with minimal changes — HF Spaces expects the app to listen on port 7860 by default (still controlled by the `PORT` env var, so just set `PORT=7860` in the Space's settings).

## The sentiment model
`app/model_output_v3/` (the fine-tuned sentiment DistilBERT, ~254MB) is gitignored — too large for GitHub — so it isn't in the repo Render clones. Instead it's hosted on Hugging Face Hub and the app downloads it itself the first time the `/sentiment` endpoint is called (see `_download_from_hf` in `app/sentiment_analysis/routes.py`), as long as `HF_MODEL_REPO` is set.

One-time setup (only needs doing once, not per-deploy):
1. `pip install huggingface_hub && huggingface-cli login` (paste a token from https://huggingface.co/settings/tokens).
2. `python scripts/upload_model_to_hf.py <your-username>/careertrust-sentiment-distilbert` — creates the repo (public, free, no bandwidth cap) and uploads `best.pt` + tokenizer files.
3. Set `HF_MODEL_REPO=<your-username>/careertrust-sentiment-distilbert` — locally in `app/.env` (copy from `app/.env.example`), and on Render as a normal dashboard environment variable (step 4 above).

Notes:
- The download only happens if `app/model_output_v3/best.pt` isn't already on disk — on Render this means the **first** request to `/sentiment` after each new deploy will be slow (network download of ~254MB) rather than every request; subsequent requests reuse the already-downloaded file until the next deploy resets the instance's disk.
- If that first-request delay causes a timeout for the caller, hit the sentiment endpoint once yourself right after deploying to "warm" it before real traffic arrives.
