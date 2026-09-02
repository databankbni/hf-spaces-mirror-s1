# Deploying to Hugging Face Spaces (free)

This app is configured to run as a **Docker Space** on Hugging Face — the free tier
(16 GB RAM, 2 CPU) is the only free host with enough memory to run the local embedding
model without code changes. Everything needed is already in the repo:

- `Dockerfile` — builds and runs the app with gunicorn on port 7860
- `.dockerignore` / `.gitignore` — keep the large `Books/` PDFs out of the deploy
- README frontmatter — tells HF this is a Docker Space

## Before you start

1. You must have already run `python src/ingest.py` **locally once**, so your Pinecone
   index is populated. The deployed app only *queries* Pinecone — it never needs the
   `Books/` PDFs or runs ingestion. (This is why we don't deploy the books.)
2. Have your `GROQ_API_KEY` and `PINECONE_API_KEY` ready.

## Step 1 — Create the Space

1. Go to https://huggingface.co and sign in (free account).
2. Click your avatar → **New Space**.
3. Set:
   - **Owner:** your username
   - **Space name:** e.g. `mahabharata-chatbot`
   - **SDK:** **Docker** → **Blank**
   - **Visibility:** Public (so you can link it on your resume)
4. Click **Create Space**.

## Step 2 — Add your API keys as secrets

In the new Space: **Settings → Variables and secrets → New secret**. Add two **secrets**
(not variables):

| Name | Value |
|------|-------|
| `GROQ_API_KEY` | your Groq key |
| `PINECONE_API_KEY` | your Pinecone key |

## Step 3 — Push your code to the Space

A Space is just a git repo. From your project folder:

```bash
# 1. Make sure the books are no longer tracked by git (they're now gitignored)
git rm -r --cached Books

# 2. Commit the deployment files
git add .
git commit -m "Add Docker deployment for Hugging Face Spaces"

# 3. Add the Space as a remote (replace USERNAME / SPACE_NAME)
git remote add space https://huggingface.co/spaces/USERNAME/SPACE_NAME

# 4. Push (use your HF username + an access token as the password)
git push space main
```

> **Access token:** when git asks for a password, paste a Hugging Face token from
> https://huggingface.co/settings/tokens (create one with **write** access).
>
> If your branch is called `master`, push with `git push space master:main`.

## Step 4 — Watch it build

On the Space page, open the **Logs** tab. Hugging Face will build the Docker image
(installing dependencies and pre-downloading the embedding model — this takes a few
minutes the first time). When it finishes, the **App** tab shows your live chatbot at:

```
https://USERNAME-SPACE_NAME.hf.space
```

That URL is what you put on your resume.

## Notes & gotchas

- **First build is slow** (PyTorch + model download). Later pushes are faster thanks to
  Docker layer caching.
- **Chat history is not permanent.** The free tier's disk is ephemeral, so conversations
  reset if the Space restarts or sleeps. That's fine for a demo; if you want durable
  history, point `src/db.py` at a free hosted Postgres (e.g. Neon) instead of SQLite.
- **Sleeping:** free Spaces pause after a period of inactivity and wake on the next visit
  (a short cold start). Normal for free hosting.
- **Updating the app:** just commit and `git push space main` again — it rebuilds.
- **Don't commit `.env`.** Keys live only in the Space secrets (Step 2).
