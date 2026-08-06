# Deploying this fork to Hugging Face Spaces

The repo is already HF-ready: `README.md` carries the Space front-matter
(`sdk: docker`, `app_port: 3000`) and the `Dockerfile` is a standalone
Next.js multi-stage build that listens on port 3000 as non-root — exactly
what Docker Spaces expect. HF builds the image on its own servers, so you
don't need Docker locally to deploy (it's still useful for pre-testing:
`docker compose up -d`).

## 1. Create the Space

1. Sign in at https://huggingface.co (account: create one if needed).
2. New Space → https://huggingface.co/new-space
   - **Space SDK: Docker** (blank template) — not Gradio/Streamlit.
   - Name it (e.g. `osiris-ai-manu`), pick public or private.
   - Hardware: the free **CPU basic (2 vCPU / 16GB)** tier runs this fine.

## 2. Push the code

HF Spaces are git repos. Add the Space as a second remote and push `main`:

```bash
git remote add hf https://huggingface.co/spaces/<your-username>/osiris-ai-manu
git push hf main
```

Authentication: username = your HF username, password = an **access token
with write scope** (create at https://huggingface.co/settings/tokens —
"Write" token type). Git will prompt; or embed it once:

```bash
git remote set-url hf https://<username>:<hf_token>@huggingface.co/spaces/<username>/osiris-ai-manu
```

(Don't commit that URL anywhere — it contains the token.)

If HF rejects the push because the Space was created with its own initial
commit, force the first push: `git push -f hf main`.

## 3. Watch the build

The Space page → **Logs** tab shows the Docker build. First build takes
several minutes (npm ci + next build). When it flips to "Running", the app
is live at `https://<username>-osiris-ai-manu.hf.space`.

## 4. Set secrets (Settings → Variables and secrets)

All optional — the app runs keyless. Add as **secrets** (not variables):

| Secret | Enables |
|---|---|
| `FRED_API_KEY` | official FRED API for `/api/macro` Fed-rate series |
| `EIA_API_KEY` | `/api/utilities` (US power demand, gas storage) |
| `OPENROUTER_API_KEY` | future AI evaluation layer |
| `FIRMS_API_KEY`, `N2YO_API_KEY`, `AIS_API_KEY`, `OPENSKY_CLIENT_ID/SECRET` | higher rate limits on upstream feeds |

Secrets are injected as environment variables at runtime; a restart of the
Space applies them.

## 5. Smoke test the live Space

- Globe loads, layer panel opens (press `L`).
- RESOURCE → Mining Companies / Memory RAM Fabs toggles plot pins;
  clicking a pin shows the company panel.
- `https://…hf.space/api/mining/companies` returns JSON (76 companies).
- `https://…hf.space/api/macro` returns VIX/yields (needs outbound net —
  works on HF).
- If anything fails, the Logs tab is the first stop; missing/typo'd
  secrets are the usual culprit.

## Notes / gotchas

- **Keep the front-matter block at the very top of README.md** — HF parses
  it for the Space config; GitHub just renders it as a small table.
- HF Space storage is **ephemeral**: anything written to disk vanishes on
  restart. This app doesn't persist to disk, so that's fine.
- Pushing to GitHub does NOT auto-deploy the Space. Either push to both
  remotes (`git push origin main && git push hf main`) or set up a GitHub
  Action later to mirror pushes.
- File-size limit on HF git is 10MB without LFS; this repo's largest
  tracked file is well under that.
