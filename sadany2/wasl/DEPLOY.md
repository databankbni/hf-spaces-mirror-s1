# Deploying free on Hugging Face Spaces

1. Sign in at huggingface.co → **New Space**
   - SDK: **Docker**
   - Hardware: **CPU basic** (free: 2 vCPU, 16GB RAM)
2. Push this directory:

       git init && git add . && git commit -m "wasl alignment service"
       git remote add origin https://huggingface.co/spaces/sadany2/wasl
       git push origin main

3. First boot pulls ~1.2GB of model weights and takes several minutes.
   Watch the build log; `GET /health` returns `{"ok": true}` once warm.
4. Open the Space URL. The page and the API share an origin, so the reader
   just works — no CORS, and none of the artifact CSP restrictions.

## What to watch in the pilot

- **`compute_seconds` vs `audio_seconds`** in the /align response. Above ~1.0×
  real time on free CPU, the wait will feel bad on a phone and you want either
  paid hardware or a smaller model.
- **Cold starts.** Free Spaces sleep. The first read after idle pays the wake-up.
- **`mean_score`.** Consistently low means the acoustic model is struggling with
  your readers, not that they read badly. That is the signal to try a different
  Arabic CTC checkpoint.

## Swapping the model

`MODEL_ID` in `align.py`. Anything with a `Wav2Vec2ForCTC` head and an Arabic
character vocabulary will drop in — the alignment and classification code does
not care which checkpoint produced the emissions.
